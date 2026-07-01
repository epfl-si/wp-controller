#!/usr/bin/env python3

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import kopf  # noqa: E402

from constants import DEFAULT_RELOAD_DEBOUNCE_SECONDS  # noqa: E402
from core import WordPressNginxController  # noqa: E402
from handlers import on_wordpresssite_change  # noqa: E402,F401 (registers the kopf handler)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@kopf.on.startup()
async def on_startup(settings: kopf.OperatorSettings, memo: kopf.Memo, **_):
    settings.posting.level = logging.INFO
    settings.batching.batch_window = float(os.environ.get("RELOAD_DEBOUNCE_SECONDS", DEFAULT_RELOAD_DEBOUNCE_SECONDS))

    memo.controller = WordPressNginxController()
    await memo.controller.connect()
    await memo.controller.sync()
    memo.watchdog_task = asyncio.create_task(memo.controller.nginx.watchdog())

    logger.info(f"wp-controller started, watching namespace {memo.controller.namespace}")


@kopf.on.cleanup()
async def on_cleanup(memo: kopf.Memo, **_):
    memo.watchdog_task.cancel()
    await memo.controller.nginx.stop()

    logger.info("wp-controller stopped")


def main():
    kopf.run(namespaces=[os.environ["WATCH_NAMESPACE"]])


if __name__ == "__main__":
    main()
