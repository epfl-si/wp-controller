import asyncio
import base64
import logging
from typing import Dict, List

from kubernetes_asyncio.client import CoreV1Api, CustomObjectsApi, V1Secret

from models import DbCredentials, WordpressSiteInfo, WordpressSiteLookupError
from settings import (
    MARIADB_GROUP,
    MARIADB_VERSION,
    WORDPRESS_GROUP,
    WORDPRESS_KIND,
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


def owned_by_site(owner_references, site_uid: str) -> bool:
    """Whether one of these ownerReferences (dicts for custom objects,
    V1OwnerReference models for core ones) points to the WordpressSite with
    this uid. The uid, not the name, so a deleted-and-recreated site never
    inherits its predecessor's leftovers."""
    for ref in owner_references or []:
        uid = ref.get("uid") if isinstance(ref, dict) else ref.uid
        kind = ref.get("kind") if isinstance(ref, dict) else ref.kind
        if kind == WORDPRESS_KIND and uid == site_uid:
            return True
    return False


async def load_db_credentials_index(core_api: CoreV1Api, custom_api: CustomObjectsApi, namespace: str):
    """List every MariaDB Database, MariaDB User and Secret in the namespace
    once, instead of resolving each WordpressSite's children with separate
    `get` calls (N+1: several round trips per site instead of 3 total)."""
    databases, users, secrets = await asyncio.gather(
        custom_api.list_namespaced_custom_object(group=MARIADB_GROUP, version=MARIADB_VERSION, namespace=namespace, plural="databases"),
        custom_api.list_namespaced_custom_object(group=MARIADB_GROUP, version=MARIADB_VERSION, namespace=namespace, plural="users"),
        core_api.list_namespaced_secret(namespace=namespace),
    )
    return databases.get("items", []), users.get("items", []), secrets.items


def _only_child(kind: str, children: list, namespace: str, site_name: str):
    if not children:
        raise WordpressSiteLookupError(
            f"Could not resolve database credentials for WordpressSite {namespace}/{site_name}: no {kind} owned by it"
        )
    if len(children) > 1:
        names = ", ".join(sorted(c["metadata"]["name"] for c in children))
        raise WordpressSiteLookupError(
            f"Could not resolve database credentials for WordpressSite {namespace}/{site_name}: "
            f"{len(children)} {kind} objects owned by it ({names}), expected exactly one"
        )
    return children[0]


def resolve_db_credentials(
    raw_site: dict,
    databases: List[dict],
    users: List[dict],
    secrets: List[V1Secret],
) -> DbCredentials:
    """Resolve the MariaDB Database, User and password Secret that
    wp-operator provisions for a WordpressSite, from the lists built by
    load_db_credentials_index: the Database and User are the ones whose
    ownerReferences point to this site, and the Secret is the one the User's
    own `passwordSecretKeyRef` names - provided the site owns it too, so a
    User can never be used to read some other Secret of the namespace."""
    metadata = raw_site.get("metadata", {})
    site_name, namespace, site_uid = metadata.get("name"), metadata.get("namespace"), metadata.get("uid")
    if not site_uid:
        raise WordpressSiteLookupError(f"WordpressSite {namespace}/{site_name} has no uid")

    database = _only_child("Database", [d for d in databases if owned_by_site(d["metadata"].get("ownerReferences"), site_uid)], namespace, site_name)
    user = _only_child("User", [u for u in users if owned_by_site(u["metadata"].get("ownerReferences"), site_uid)], namespace, site_name)

    password_ref = user.get("spec", {}).get("passwordSecretKeyRef", {})
    secret_name, secret_key = password_ref.get("name"), password_ref.get("key", "password")
    secret = next(
        (s for s in secrets if s.metadata.name == secret_name and owned_by_site(s.metadata.owner_references, site_uid)),
        None,
    )
    if secret is None or secret_key not in (secret.data or {}):
        raise WordpressSiteLookupError(
            f"Could not resolve database credentials for WordpressSite {namespace}/{site_name}: "
            f"password Secret {secret_name!r} (key {secret_key!r}) of User {user['metadata']['name']} "
            f"not found, or not owned by the site"
        )

    db_spec = database.get("spec", {})
    user_spec = user.get("spec", {})

    return DbCredentials(
        host=db_spec.get("mariaDbRef", {}).get("name", ""),
        name=db_spec.get("name") or database["metadata"]["name"],
        user=user_spec.get("name") or user["metadata"]["name"],
        password=base64.b64decode(secret.data[secret_key]).decode("utf-8"),
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
    databases, users, secrets = await load_db_credentials_index(core_api, custom_api, namespace)

    sites = []
    skipped = {}
    for raw_site in raw_sites:
        site_name = raw_site.get("metadata", {}).get("name", "<unknown>")
        try:
            db = resolve_db_credentials(raw_site, databases, users, secrets)
            sites.append(build_site_info(raw_site, db))
        except (WordpressSiteLookupError, ValueError, KeyError) as e:
            logger.debug(f"Skipping WordpressSite {namespace}/{site_name}: {e}")
            skipped[site_name] = str(e)
    return sites, skipped
