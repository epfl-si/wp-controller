import logging

import kopf

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
from core import controller

logger = logging.getLogger(__name__)


@kopf.on.event(WORDPRESS_GROUP, WORDPRESS_VERSION, WORDPRESS_PLURAL)
async def on_wordpresssite_change(name: str, namespace: str, **_):
    # Debounced: with many sites changing close together (e.g. the burst of
    # `resume` events on startup), only the last one actually triggers a
    # sync a moment later - see WordPressNginxController.request_sync.
    logger.debug(f"WordpressSite {namespace}/{name} changed, requesting a sync")
    await controller.request_sync()


def _is_site_dependency(prefix: str):
    """kopf `when=` filter: only react to the objects wp-operator provisions
    for a WordpressSite (matched by well-known name, same as
    site_repository.resolve_db_credentials), not every Secret in the
    namespace."""
    return lambda name, **_: bool(name) and name.startswith(prefix)


# The DB credentials baked into the nginx config come from these three, so
# any change (e.g. a rotated password Secret, a Database/User appearing or
# being deleted) must trigger a re-sync - the sync itself is a no-op when the
# rendered config comes out identical. These are plain events: no finalizer
# or annotation is ever written to these objects, hence read-only RBAC.
@kopf.on.event(MARIADB_GROUP, MARIADB_VERSION, "databases", when=_is_site_dependency(DATABASE_PREFIX))
async def on_database_change(name: str, namespace: str, **_):
    logger.debug(f"Database {namespace}/{name} changed, requesting a sync")
    await controller.request_sync()


@kopf.on.event(MARIADB_GROUP, MARIADB_VERSION, "users", when=_is_site_dependency(USER_PREFIX))
async def on_user_change(name: str, namespace: str, **_):
    logger.debug(f"User {namespace}/{name} changed, requesting a sync")
    await controller.request_sync()


@kopf.on.event("", "v1", "secrets", when=_is_site_dependency(PASSWORD_SECRET_PREFIX))
async def on_secret_change(name: str, namespace: str, **_):
    logger.debug(f"Secret {namespace}/{name} changed, requesting a sync")
    await controller.request_sync()
