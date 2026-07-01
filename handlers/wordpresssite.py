import asyncio
import logging
import os

import kopf

from core import WordPressNginxController

logger = logging.getLogger(__name__)

_controller: WordPressNginxController = None
_watchdog_task: asyncio.Task = None


@kopf.on.startup()
async def on_startup(settings: kopf.OperatorSettings, **_):
    global _controller, _watchdog_task

    settings.posting.level = logging.INFO
    settings.batching.batch_window = float(os.environ.get("RELOAD_DEBOUNCE_SECONDS", "2"))

    _controller = WordPressNginxController()
    await _controller.connect()
    await _controller.sync()
    _watchdog_task = asyncio.create_task(_controller.nginx.watchdog())

    logger.info(f"wp-controller started, watching namespace {_controller.namespace}")


@kopf.on.cleanup()
async def on_cleanup(**_):
    if _watchdog_task is not None:
        _watchdog_task.cancel()
    if _controller is not None:
        await _controller.nginx.stop()

    logger.info("wp-controller stopped")
