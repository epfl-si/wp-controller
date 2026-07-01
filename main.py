#!/usr/bin/env python3

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import kopf  # noqa: E402

from constants import DEFAULT_RELOAD_DEBOUNCE_SECONDS  # noqa: E402
from core import WordPressNginxController  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# A single instance for the whole process: unlike the stateless Kubernetes
# API clients, it owns the long-lived nginx subprocess, so it must survive
# across handler calls instead of being recreated on every one. Handlers
# reach it with a deferred `import main` (see handlers/wordpresssite.py) to
# avoid a circular import at module-load time.
controller = WordPressNginxController()

from handlers import on_wordpresssite_change  # noqa: E402,F401 (registers the kopf handler)


@kopf.on.startup()
async def on_startup(settings: kopf.OperatorSettings, **_):
    settings.posting.level = logging.INFO
    settings.batching.batch_window = float(os.environ.get("RELOAD_DEBOUNCE_SECONDS", DEFAULT_RELOAD_DEBOUNCE_SECONDS))

    await controller.connect()
    await controller.sync()
    controller.start_watchdog()

    logger.info(f"wp-controller started, watching namespace {controller.namespace}")


@kopf.on.cleanup()
async def on_cleanup(**_):
    await controller.stop_watchdog()
    await controller.nginx.stop()

    logger.info("wp-controller stopped")


def main():
    kopf.run(namespaces=[os.environ["WATCH_NAMESPACE"]])


if __name__ == "__main__":
    main()
