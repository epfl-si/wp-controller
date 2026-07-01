import logging

import kopf

from constants import WORDPRESS_GROUP, WORDPRESS_PLURAL, WORDPRESS_VERSION

logger = logging.getLogger(__name__)


@kopf.on.create(WORDPRESS_GROUP, WORDPRESS_VERSION, WORDPRESS_PLURAL)
@kopf.on.update(WORDPRESS_GROUP, WORDPRESS_VERSION, WORDPRESS_PLURAL)
@kopf.on.delete(WORDPRESS_GROUP, WORDPRESS_VERSION, WORDPRESS_PLURAL)
@kopf.on.resume(WORDPRESS_GROUP, WORDPRESS_VERSION, WORDPRESS_PLURAL)
async def on_wordpresssite_change(name: str, namespace: str, memo: kopf.Memo, **_):
    logger.info(f"WordpressSite {namespace}/{name} changed, resyncing nginx config")
    await memo.controller.sync()
