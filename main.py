#!/usr/bin/env python3

import logging
import os

import kopf

from handlers import (
    validate,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_):
    settings.posting.level = logging.INFO

    logger.info("WP Controller started")


def main():
    logger.info("Starting WP Controller")
    kopf.run()


if __name__ == "__main__":
    main()
