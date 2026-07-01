import base64
import logging
from typing import List

from kubernetes_asyncio.client import CoreV1Api, CustomObjectsApi
from kubernetes_asyncio.client.exceptions import ApiException

from constants import (
    DATABASE_PREFIX,
    MARIADB_GROUP,
    MARIADB_VERSION,
    PASSWORD_SECRET_PREFIX,
    USER_PREFIX,
    WORDPRESS_GROUP,
    WORDPRESS_PLURAL,
    WORDPRESS_VERSION,
)
from models import DbCredentials, WordpressSiteInfo, WordpressSiteLookupError

from .site_builder import build_site_info

logger = logging.getLogger(__name__)


async def list_wordpress_sites(custom_api: CustomObjectsApi, namespace: str) -> List[dict]:
    response = await custom_api.list_namespaced_custom_object(
        group=WORDPRESS_GROUP, version=WORDPRESS_VERSION, namespace=namespace, plural=WORDPRESS_PLURAL
    )
    return response.get("items", [])


async def get_db_credentials(
    core_api: CoreV1Api, custom_api: CustomObjectsApi, namespace: str, site_name: str
) -> DbCredentials:
    """Resolve the MariaDB Database/User/Secret trio that wp-operator
    provisions for a WordpressSite, by their well-known deterministic names."""
    try:
        database = await custom_api.get_namespaced_custom_object(
            group=MARIADB_GROUP,
            version=MARIADB_VERSION,
            namespace=namespace,
            plural="databases",
            name=f"{DATABASE_PREFIX}{site_name}",
        )
        user = await custom_api.get_namespaced_custom_object(
            group=MARIADB_GROUP,
            version=MARIADB_VERSION,
            namespace=namespace,
            plural="users",
            name=f"{USER_PREFIX}{site_name}",
        )
        secret = await core_api.read_namespaced_secret(
            name=f"{PASSWORD_SECRET_PREFIX}{site_name}", namespace=namespace
        )
    except ApiException as e:
        raise WordpressSiteLookupError(
            f"Could not resolve database credentials for WordpressSite {namespace}/{site_name}: {e}"
        ) from e

    db_spec = database.get("spec", {})
    user_spec = user.get("spec", {})

    return DbCredentials(
        host=db_spec.get("mariaDbRef", {}).get("name", ""),
        name=db_spec.get("name") or database["metadata"]["name"],
        user=user_spec.get("name") or user["metadata"]["name"],
        password=base64.b64decode(secret.data["password"]).decode("utf-8"),
    )


async def load_site_infos(core_api: CoreV1Api, custom_api: CustomObjectsApi, namespace: str) -> List[WordpressSiteInfo]:
    """List every WordpressSite in the namespace and resolve it into a
    WordpressSiteInfo. A single misconfigured or not-yet-provisioned site is
    logged and skipped rather than aborting the whole sync (see 6.5: a bad
    site must never take the rest of the namespace down with it)."""
    sites = []
    for raw_site in await list_wordpress_sites(custom_api, namespace):
        site_name = raw_site.get("metadata", {}).get("name", "<unknown>")
        try:
            db = await get_db_credentials(core_api, custom_api, namespace, site_name)
            sites.append(build_site_info(raw_site, db))
        except (WordpressSiteLookupError, ValueError, KeyError) as e:
            logger.warning(f"Skipping WordpressSite {namespace}/{site_name}: {e}")
    return sites
