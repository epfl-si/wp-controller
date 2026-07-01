#!/usr/bin/env python3

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import kopf  # noqa: E402

from constants import DEFAULT_RELOAD_DEBOUNCE_SECONDS  # noqa: E402
from core import controller  # noqa: E402
from handlers import on_wordpresssite_change  # noqa: E402,F401 (registers the kopf handler)

# Only takes effect for `python main.py` (local dev): the `kopf run`
# CLI used in the container reconfigures logging itself on startup,
# overriding this - see the kopf.objects level tweak in on_startup below.
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@kopf.on.startup()
async def on_startup(settings: kopf.OperatorSettings, **_):
    settings.posting.level = logging.INFO
    settings.batching.batch_window = float(os.environ.get("RELOAD_DEBOUNCE_SECONDS", DEFAULT_RELOAD_DEBOUNCE_SECONDS))
    # This is a namespaced-only operator: it must not need cluster-scoped
    # RBAC to list CustomResourceDefinitions or Namespaces
    settings.scanning.disabled = True

    # kopf's own per-object "Handler succeeded"/"Updating is processed"
    # lines at INFO drown out our own logs once there are many
    # WordpressSites; keep only our application logs at that level.
    logging.getLogger("kopf.objects").setLevel(logging.WARNING)

    await controller.connect()
    await controller.sync()
    controller.start_watchdog()

    logger.info(f"wp-controller started, watching namespace {controller.namespace}")


@kopf.on.cleanup()
async def on_cleanup(**_):
    controller.cancel_pending_sync()
    await controller.stop_watchdog()
    await controller.nginx.stop()

    logger.info("wp-controller stopped")


def main():
    kopf.run(namespaces=[os.environ["WATCH_NAMESPACE"]])


if __name__ == "__main__":
    main()
