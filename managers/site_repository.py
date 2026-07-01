import base64
import logging
from typing import List

from kubernetes_asyncio.client import CoreV1Api, CustomObjectsApi
from kubernetes_asyncio.client.exceptions import ApiException

from models import DbCredentials, WordpressSiteLookupError

logger = logging.getLogger(__name__)

WORDPRESS_GROUP = "wordpress.epfl.ch"
WORDPRESS_VERSION = "v2"
WORDPRESS_PLURAL = "wordpresssites"

MARIADB_GROUP = "k8s.mariadb.com"
MARIADB_VERSION = "v1alpha1"

# Matches the `self.prefix` naming convention used by wp-operator when it
# provisions a WordpressSite's database (see wp-operator's wp_operator.py).
DATABASE_PREFIX = "wp-db-"
USER_PREFIX = "wp-db-user-"
PASSWORD_SECRET_PREFIX = "wp-db-password-"


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
