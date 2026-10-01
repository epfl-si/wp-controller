import logging

import kopf

from settings import (
    MARIADB_GROUP,
    MARIADB_VERSION,
    WORDPRESS_GROUP,
    WORDPRESS_KIND,
    WORDPRESS_PLURAL,
    WORDPRESS_VERSION,
)
from core import controller

logger = logging.getLogger(__name__)


@kopf.on.event(WORDPRESS_GROUP, WORDPRESS_VERSION, WORDPRESS_PLURAL)
async def on_wordpresssite_change(name: str, namespace: str, **_):
    # Debounced: with many sites changing close together (e.g. the burst of
    # `resume` events on startup), only the last one actually triggers a
    # sync a moment later - see WordPressNginxController.request_sync.
    logger.debug(f"WordpressSite {namespace}/{name} changed, requesting a sync")
    await controller.request_sync()


def _is_site_child(meta, **_) -> bool:
    """kopf `when=` filter: only react to objects owned by a WordpressSite
    (what wp-operator provisions for it), not every Secret in the
    namespace. Matched on the ownerReferences, like
    site_repository.resolve_db_credentials - never on names."""
    return any(ref.get("kind") == WORDPRESS_KIND for ref in meta.get("ownerReferences") or [])


# The DB credentials baked into the nginx config come from these three, so
# any change (e.g. a rotated password Secret, a Database/User appearing or
# being deleted) must trigger a re-sync - the sync itself is a no-op when the
# rendered config comes out identical. These are plain events: no finalizer
# or annotation is ever written to these objects, hence read-only RBAC.
@kopf.on.event(MARIADB_GROUP, MARIADB_VERSION, "databases", when=_is_site_child)
async def on_database_change(name: str, namespace: str, **_):
    logger.debug(f"Database {namespace}/{name} changed, requesting a sync")
    await controller.request_sync()


@kopf.on.event(MARIADB_GROUP, MARIADB_VERSION, "users", when=_is_site_child)
async def on_user_change(name: str, namespace: str, **_):
    logger.debug(f"User {namespace}/{name} changed, requesting a sync")
    await controller.request_sync()


@kopf.on.event("", "v1", "secrets", when=_is_site_child)
async def on_secret_change(name: str, namespace: str, **_):
    logger.debug(f"Secret {namespace}/{name} changed, requesting a sync")
    await controller.request_sync()
