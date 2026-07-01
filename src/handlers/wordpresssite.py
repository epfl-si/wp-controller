import logging

import kopf

from constants import WORDPRESS_GROUP, WORDPRESS_PLURAL, WORDPRESS_VERSION

logger = logging.getLogger(__name__)


@kopf.on.create(WORDPRESS_GROUP, WORDPRESS_VERSION, WORDPRESS_PLURAL)
@kopf.on.update(WORDPRESS_GROUP, WORDPRESS_VERSION, WORDPRESS_PLURAL)
@kopf.on.delete(WORDPRESS_GROUP, WORDPRESS_VERSION, WORDPRESS_PLURAL)
@kopf.on.resume(WORDPRESS_GROUP, WORDPRESS_VERSION, WORDPRESS_PLURAL)
async def on_wordpresssite_change(name: str, namespace: str, **_):
    import main  # deferred: main.py owns the controller instance, and

    # imports this module in turn - importing it at module level here
    # would be circular.

    logger.info(f"WordpressSite {namespace}/{name} changed, resyncing nginx config")
    await main.controller.sync()
