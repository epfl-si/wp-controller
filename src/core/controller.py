import asyncio
import logging
import os
import time
from typing import Optional

from kubernetes_asyncio import client
from kubernetes_asyncio import config as k8s_config

from managers import load_site_infos, render_config, write_config_atomic
from models import NginxConfigError, NginxReloadError
from settings import NGINX_CONF_PATH, RELOAD_DEBOUNCE_SECONDS, RELOAD_MAX_WAIT_SECONDS

from .nginx import NginxProcess

logger = logging.getLogger(__name__)


class WordPressNginxController:
    """Ties together the Kubernetes client, the WordpressSite lookups and
    the nginx process for a single watched namespace."""

    def __init__(self):
        self.namespace = os.environ["WATCH_NAMESPACE"]
        self.conf_path = NGINX_CONF_PATH
        self.nginx = NginxProcess()
        self.core_api = None
        self.custom_api = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._sync_task: Optional[asyncio.Task] = None
        self._burst_started_at: Optional[float] = None
        self.debounce_seconds = RELOAD_DEBOUNCE_SECONDS
        self.max_wait_seconds = RELOAD_MAX_WAIT_SECONDS

    async def connect(self) -> None:
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            await k8s_config.load_kube_config()

        api_client = client.ApiClient()
        self.core_api = client.CoreV1Api(api_client)
        self.custom_api = client.CustomObjectsApi(api_client)

    def start_watchdog(self) -> None:
        self._watchdog_task = asyncio.create_task(self.nginx.watchdog())

    async def stop_watchdog(self) -> None:
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()

    def _read_current_config(self):
        if not os.path.exists(self.conf_path):
            return None
        with open(self.conf_path) as f:
            return f.read()

    async def sync(self) -> None:
        """Re-read every WordpressSite in the namespace from the Kubernetes
        API, rebuild the full nginx config from scratch, and reload nginx
        only if the result is both different and valid."""
        sites = await load_site_infos(self.core_api, self.custom_api, self.namespace)
        content = render_config(sites)
        previous_content = self._read_current_config()

        if content == previous_content:
            logger.info(f"No configuration change for {len(sites)} WordpressSite(s)")
            return

        write_config_atomic(content, self.conf_path)

        try:
            await self.nginx.validate()
        except NginxConfigError as e:
            logger.error(f"Generated nginx config is invalid, keeping previous config: {e}")
            if previous_content is not None:
                write_config_atomic(previous_content, self.conf_path)
            return

        if not self.nginx.is_running():
            self.nginx.start()
            logger.info(f"nginx started with config for {len(sites)} WordpressSite(s)")
            return

        try:
            await self.nginx.reload()
        except NginxReloadError as e:
            logger.error(f"Failed to reload nginx: {e}")
            return

        logger.info(f"nginx reloaded for {len(sites)} WordpressSite(s)")

    async def request_sync(self) -> None:
        """Coalesce sync requests from many WordpressSite events arriving
        close together (e.g. the flood of `resume` events on startup, or a
        batch of Ingress-like changes) into a single sync: each call cancels
        any not-yet-started pending sync and reschedules it `debounce_seconds`
        from now - capped so it fires at most `max_wait_seconds` after the
        first request of the current burst. Without that cap, a steady
        stream of events arriving faster than `debounce_seconds` apart would
        keep pushing the sync back forever and the state would never
        actually get regenerated."""
        now = time.monotonic()
        if self._burst_started_at is None:
            self._burst_started_at = now
        delay = min(self.debounce_seconds, max(self.max_wait_seconds - (now - self._burst_started_at), 0))

        if self._sync_task is not None:
            self._sync_task.cancel()
        self._sync_task = asyncio.create_task(self._debounced_sync(delay))

    async def _debounced_sync(self, delay: float) -> None:
        await asyncio.sleep(delay)
        self._burst_started_at = None
        # Shielded so a sync that's already under way can't be aborted
        # mid-step (e.g. after writing the config but before reloading
        # nginx) by a trailing event cancelling this task.
        await asyncio.shield(self.sync())

    def cancel_pending_sync(self) -> None:
        if self._sync_task is not None:
            self._sync_task.cancel()


# A single instance for the whole process: unlike the stateless Kubernetes
# API clients, it owns the long-lived nginx subprocess, so it must survive
# across handler calls instead of being recreated on every one.
#
# It lives here (not in main.py) because main.py is executed as
# `__main__` when kopf runs it - a later `import main` from elsewhere
# would load the file a second time under a different module name,
# creating a second, disconnected instance. `core.controller` is always
# imported the normal way, so there is only ever one.
controller = WordPressNginxController()
