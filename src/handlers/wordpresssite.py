import logging

import kopf

from settings import WORDPRESS_GROUP, WORDPRESS_PLURAL, WORDPRESS_VERSION
from core import controller

logger = logging.getLogger(__name__)


@kopf.on.create(WORDPRESS_GROUP, WORDPRESS_VERSION, WORDPRESS_PLURAL)
@kopf.on.update(WORDPRESS_GROUP, WORDPRESS_VERSION, WORDPRESS_PLURAL)
@kopf.on.delete(WORDPRESS_GROUP, WORDPRESS_VERSION, WORDPRESS_PLURAL)
@kopf.on.resume(WORDPRESS_GROUP, WORDPRESS_VERSION, WORDPRESS_PLURAL)
async def on_wordpresssite_change(name: str, namespace: str, **_):
    # Debounced: with many sites changing close together (e.g. the burst of
    # `resume` events on startup), only the last one actually triggers a
    # sync a moment later - see WordPressNginxController.request_sync.
    logger.debug(f"WordpressSite {namespace}/{name} changed, requesting a sync")
    await controller.request_sync()
