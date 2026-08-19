import asyncio
import logging
import os
import time
from typing import Optional

from kubernetes_asyncio import client
from kubernetes_asyncio import config as k8s_config

from managers import commit_candidate_config, load_site_infos, render_config, write_candidate_config
from models import NginxConfigError, NginxReloadError
from settings import (
    NGINX_CONF_PATH,
    RELOAD_DEBOUNCE_SECONDS,
    RELOAD_MAX_WAIT_SECONDS,
    SITE_LOOKUP_RETRY_SECONDS,
    SITE_LOOKUP_RETRY_TIMEOUT_SECONDS,
)

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
        # site_name -> monotonic time it was first seen skipped for a
        # not-yet-resolvable dependency (see sync()).
        self._pending_lookups: dict[str, float] = {}
        self._retry_task: Optional[asyncio.Task] = None

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
        only if the result is both different and valid. The candidate is
        validated with `nginx -t` next to the current config before it is
        ever moved into self.conf_path - the live config is never
        overwritten with something unverified."""
        sites, skipped = await load_site_infos(self.core_api, self.custom_api, self.namespace)
        self._track_pending_lookups(skipped)
        content = render_config(sites)
        previous_content = self._read_current_config()

        if content == previous_content:
            logger.info(f"No configuration change for {len(sites)} WordpressSite(s)")
            return

        candidate_path = write_candidate_config(content, self.conf_path)

        try:
            await self.nginx.validate()
        except NginxConfigError as e:
            os.unlink(candidate_path)
            logger.error(f"Generated nginx config is invalid, keeping previous config: {e}")
            return

        commit_candidate_config(candidate_path, self.conf_path)

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

    def _track_pending_lookups(self, skipped: list[str]) -> None:
        """Update retry bookkeeping for sites skipped this sync because a
        dependency (e.g. wp-operator's Database/User/Secret) isn't ready
        yet, and (re)schedule a retry while any are still within their
        timeout - see SITE_LOOKUP_RETRY_SECONDS/_TIMEOUT_SECONDS."""
        now = time.monotonic()
        skipped_set = set(skipped)

        # Drop sites that resolved (or disappeared) since the last sync.
        for site_name in list(self._pending_lookups):
            if site_name not in skipped_set:
                del self._pending_lookups[site_name]

        for site_name in skipped_set:
            self._pending_lookups.setdefault(site_name, now)

        still_waiting = False
        for site_name, first_skipped_at in list(self._pending_lookups.items()):
            if now - first_skipped_at > SITE_LOOKUP_RETRY_TIMEOUT_SECONDS:
                logger.error(
                    f"Giving up on WordpressSite {self.namespace}/{site_name}: "
                    f"still unresolved after {SITE_LOOKUP_RETRY_TIMEOUT_SECONDS:.0f}s"
                )
                del self._pending_lookups[site_name]
            else:
                still_waiting = True

        if self._retry_task is not None:
            self._retry_task.cancel()
        self._retry_task = asyncio.create_task(self._retry_pending_lookups()) if still_waiting else None

    async def _retry_pending_lookups(self) -> None:
        await asyncio.sleep(SITE_LOOKUP_RETRY_SECONDS)
        await self.request_sync()

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
        if self._retry_task is not None:
            self._retry_task.cancel()


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
