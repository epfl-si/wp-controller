#!/usr/bin/env python3

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import kopf  # noqa: E402

from core import controller  # noqa: E402
from core import metrics  # noqa: E402
from handlers import (  # noqa: E402,F401 (registers the kopf handlers)
    on_database_change,
    on_secret_change,
    on_user_change,
    on_wordpresssite_change,
)
from settings import LOG_LEVEL  # noqa: E402

logger = logging.getLogger(__name__)

@kopf.on.startup()
async def on_startup(settings: kopf.OperatorSettings, **_):
    # kopf configures logging itself before running this activity, so this
    # is what actually has the final say (see the kopf.objects override
    # right below, which relies on the same ordering).
    logging.getLogger().setLevel(LOG_LEVEL)

    settings.posting.level = logging.INFO
    # This is a namespaced-only operator: it must not need cluster-scoped
    # RBAC to list CustomResourceDefinitions or Namespaces
    settings.scanning.disabled = True
    # Scope the finalizer to this operator instead of kopf's default
    # `kopf.zalando.org/KopfFinalizerMarker`, shared by every kopf-based
    # operator with no override - e.g. wp-operator, which also runs
    # against this namespace.
    settings.persistence.finalizer = "wordpress.epfl.ch/wp-controller"

    # kopf's own per-object "Handler succeeded"/"Updating is processed"
    # lines at INFO drown out our own logs once there are many
    # WordpressSites; keep only our application logs at that level.
    logging.getLogger("kopf.objects").setLevel(logging.WARNING)

    metrics.start_server()
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
