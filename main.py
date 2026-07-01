#!/usr/bin/env python3

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import kopf  # noqa: E402

from handlers import on_cleanup, on_startup, on_wordpresssite_change  # noqa: E402,F401 (registers kopf handlers)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main():
    kopf.run(namespaces=[os.environ["WATCH_NAMESPACE"]])


if __name__ == "__main__":
    main()
