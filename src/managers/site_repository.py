import asyncio
import base64
import logging
from typing import Dict, List

from kubernetes_asyncio.client import CoreV1Api, CustomObjectsApi, V1Secret

from models import DbCredentials, WordpressSiteInfo, WordpressSiteLookupError
from settings import (
    DATABASE_PREFIX,
    MARIADB_GROUP,
    MARIADB_VERSION,
    PASSWORD_SECRET_PREFIX,
    USER_PREFIX,
    WORDPRESS_GROUP,
    WORDPRESS_PLURAL,
    WORDPRESS_VERSION,
)

from .site_builder import build_site_info

logger = logging.getLogger(__name__)


async def list_wordpress_sites(custom_api: CustomObjectsApi, namespace: str) -> List[dict]:
    response = await custom_api.list_namespaced_custom_object(
        group=WORDPRESS_GROUP, version=WORDPRESS_VERSION, namespace=namespace, plural=WORDPRESS_PLURAL
    )
    return response.get("items", [])


async def load_db_credentials_index(core_api: CoreV1Api, custom_api: CustomObjectsApi, namespace: str):
    """List every MariaDB Database, MariaDB User and Secret in the namespace
    once, instead of resolving each WordpressSite's trio with 3 separate
    `get` calls (N+1: 3 round trips per site instead of 3 total)."""
    databases, users, secrets = await asyncio.gather(
        custom_api.list_namespaced_custom_object(group=MARIADB_GROUP, version=MARIADB_VERSION, namespace=namespace, plural="databases"),
        custom_api.list_namespaced_custom_object(group=MARIADB_GROUP, version=MARIADB_VERSION, namespace=namespace, plural="users"),
        core_api.list_namespaced_secret(namespace=namespace),
    )
    databases_by_name = {d["metadata"]["name"]: d for d in databases.get("items", [])}
    users_by_name = {u["metadata"]["name"]: u for u in users.get("items", [])}
    secrets_by_name: Dict[str, V1Secret] = {s.metadata.name: s for s in secrets.items}
    return databases_by_name, users_by_name, secrets_by_name


def resolve_db_credentials(
    namespace: str,
    site_name: str,
    databases_by_name: Dict[str, dict],
    users_by_name: Dict[str, dict],
    secrets_by_name: Dict[str, V1Secret],
) -> DbCredentials:
    """Resolve the MariaDB Database/User/Secret trio that wp-operator
    provisions for a WordpressSite, by their well-known deterministic names,
    from the indexes built by load_db_credentials_index."""
    database = databases_by_name.get(f"{DATABASE_PREFIX}{site_name}")
    user = users_by_name.get(f"{USER_PREFIX}{site_name}")
    secret = secrets_by_name.get(f"{PASSWORD_SECRET_PREFIX}{site_name}")
    if database is None or user is None or secret is None:
        raise WordpressSiteLookupError(
            f"Could not resolve database credentials for WordpressSite {namespace}/{site_name}: "
            f"Database/User/Secret not found"
        )

    db_spec = database.get("spec", {})
    user_spec = user.get("spec", {})

    return DbCredentials(
        host=db_spec.get("mariaDbRef", {}).get("name", ""),
        name=db_spec.get("name") or database["metadata"]["name"],
        user=user_spec.get("name") or user["metadata"]["name"],
        password=base64.b64decode(secret.data["password"]).decode("utf-8"),
    )


async def load_site_infos(
    core_api: CoreV1Api, custom_api: CustomObjectsApi, namespace: str
) -> tuple[List[WordpressSiteInfo], Dict[str, str]]:
    """List every WordpressSite in the namespace and resolve it into a
    WordpressSiteInfo. A single misconfigured or not-yet-provisioned site is
    skipped rather than aborting the whole sync (see 6.5: a bad site must
    never take the rest of the namespace down with it). Returns the skipped
    sites' names and error messages alongside, so WordPressNginxController.
    sync can retry them once their dependencies (e.g. wp-operator's
    Database/User/Secret) show up, and narrate that wait once per site
    instead of logging the same skip on every retry."""
    raw_sites = await list_wordpress_sites(custom_api, namespace)
    databases_by_name, users_by_name, secrets_by_name = await load_db_credentials_index(core_api, custom_api, namespace)

    sites = []
    skipped = {}
    for raw_site in raw_sites:
        site_name = raw_site.get("metadata", {}).get("name", "<unknown>")
        try:
            db = resolve_db_credentials(namespace, site_name, databases_by_name, users_by_name, secrets_by_name)
            sites.append(build_site_info(raw_site, db))
        except (WordpressSiteLookupError, ValueError, KeyError) as e:
            logger.debug(f"Skipping WordpressSite {namespace}/{site_name}: {e}")
            skipped[site_name] = str(e)
    return sites, skipped
