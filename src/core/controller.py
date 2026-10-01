import asyncio
import logging
import os
import time
from typing import Optional

from kubernetes_asyncio import client
from kubernetes_asyncio import config as k8s_config

from managers import (
    build_validation_config,
    cleanup_validation_config,
    commit_candidate_config,
    load_site_infos,
    render_config,
    write_candidate_config,
)
from models import NginxConfigError, NginxReloadError
from settings import (
    NGINX_CONF_PATH,
    RELOAD_DEBOUNCE_SECONDS,
    RELOAD_MAX_WAIT_SECONDS,
    SITE_LOOKUP_RETRY_SECONDS,
    SITE_LOOKUP_RETRY_TIMEOUT_SECONDS,
)

from . import metrics
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
        # Guarantees sync() calls never actually overlap - see
        # _debounced_sync for why this can't-happen-in-theory case is real.
        self._sync_lock = asyncio.Lock()
        self._burst_started_at: Optional[float] = None
        self.debounce_seconds = RELOAD_DEBOUNCE_SECONDS
        self.max_wait_seconds = RELOAD_MAX_WAIT_SECONDS
        # site_name -> monotonic time it was first seen skipped for a
        # not-yet-resolvable dependency (see sync()).
        self._pending_lookups: dict[str, float] = {}
        self._retry_task: Optional[asyncio.Task] = None
        # None until the first sync commits a config - distinguishes the
        # initial "here's what got configured" log from later diffs.
        self._last_synced_names: Optional[set] = None

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
        """Run one sync (see _sync), recording its outcome in the metrics."""
        try:
            with metrics.sync_duration.time():
                await self._sync()
        except Exception:
            metrics.record_error("error")
            raise
        finally:
            metrics.last_sync.set_to_current_time()
            metrics.nginx_up.set(1 if self.nginx.is_running() else 0)

    async def _sync(self) -> None:
        """Re-read every WordpressSite in the namespace from the Kubernetes
        API, rebuild the full nginx config from scratch, and reload nginx
        only if the result is both different and valid. The candidate is
        validated with `nginx -t` through a throwaway main config (see
        build_validation_config) without touching anything under nginx's
        config directory; only once proven valid is it renamed over the
        live config - the single step that modifies it."""
        sites, skipped = await load_site_infos(self.core_api, self.custom_api, self.namespace)
        lookup_activity_logged = self._track_pending_lookups(skipped, resolved_names={s.name for s in sites})
        metrics.sites.labels("configured").set(len(sites))
        metrics.sites.labels("pending").set(len(skipped))
        content = render_config(sites)
        previous_content = self._read_current_config()

        if content == previous_content:
            # Skip this if _track_pending_lookups already explained why
            # nothing changed this cycle (a site started/stopped waiting) -
            # restating "no change" right under that is pure noise.
            if not lookup_activity_logged:
                logger.info(f"No configuration change for {len(sites)} WordpressSite(s)")
            metrics.syncs.labels("unchanged").inc()
            # What is on disk already passed validation, so any earlier
            # rejected candidate is moot now.
            metrics.config_valid.set(1)
            return

        current_names = {f"{s.namespace}/{s.name}" for s in sites}
        if self._last_synced_names is None:
            logger.info(f"Initial configuration: {len(sites)} WordpressSite(s)")
        else:
            added = sorted(current_names - self._last_synced_names)
            removed = sorted(self._last_synced_names - current_names)
            parts = []
            if added:
                parts.append(f"+{len(added)} ({', '.join(added)})")
            if removed:
                parts.append(f"-{len(removed)} ({', '.join(removed)})")
            logger.info(f"Configuration changed for {len(sites)} WordpressSite(s): {'; '.join(parts) or 'content updated'}")
        self._last_synced_names = current_names

        candidate_path = write_candidate_config(content, self.conf_path)
        validation_path = None
        try:
            validation_path = build_validation_config(candidate_path, self.conf_path)
            await self.nginx.validate(validation_path)
        except (NginxConfigError, RuntimeError, OSError) as e:
            os.unlink(candidate_path)
            metrics.config_valid.set(0)
            metrics.record_error("invalid")
            logger.error(f"Generated nginx config is invalid, keeping previous config: {e}")
            logger.debug(f"Rejected nginx config:\n{content}")
            return
        finally:
            if validation_path is not None:
                cleanup_validation_config(validation_path)

        commit_candidate_config(candidate_path, self.conf_path)
        metrics.config_valid.set(1)
        metrics.last_change.set_to_current_time()

        if not self.nginx.is_running():
            self.nginx.start()
            metrics.syncs.labels("applied").inc()
            metrics.last_success.set_to_current_time()
            metrics.last_reload.set_to_current_time()
            logger.info(f"nginx started with config for {len(sites)} WordpressSite(s)")
            return

        try:
            await self.nginx.reload()
        except NginxReloadError as e:
            metrics.record_error("reload_failed")
            logger.error(f"Failed to reload nginx: {e}")
            return

        metrics.syncs.labels("applied").inc()
        metrics.last_success.set_to_current_time()
        metrics.last_reload.set_to_current_time()
        logger.info(f"nginx reloaded for {len(sites)} WordpressSite(s)")

    def _track_pending_lookups(self, skipped: dict[str, str], resolved_names: set[str]) -> bool:
        """Update retry bookkeeping for sites skipped this sync because a
        dependency (e.g. wp-operator's Database/User/Secret) isn't ready
        yet, and (re)schedule a retry while any are still within their
        timeout - see SITE_LOOKUP_RETRY_SECONDS/_TIMEOUT_SECONDS. Logs once
        when a site starts/stops waiting, not on every retry in between -
        site_repository.load_site_infos only logs the reason at DEBUG.
        Returns whether anything was logged, so sync() can skip its own
        "no configuration change" line when this already explained why.

        A site leaving `skipped` isn't necessarily resolved: it may instead
        have been deleted (or be stuck Terminating behind some other
        finalizer while wp-operator tears its DB down first) while still
        waiting - `resolved_names` (from THIS sync's successfully resolved
        sites) is what actually distinguishes the two, so a deleted site
        isn't misreported as "resolved"."""
        now = time.monotonic()
        logged = False

        for site_name in list(self._pending_lookups):
            if site_name in skipped:
                continue  # still waiting, nothing changed
            waited = now - self._pending_lookups.pop(site_name)
            logged = True
            if site_name in resolved_names:
                logger.info(f"WordpressSite {self.namespace}/{site_name} is now resolved (waited {waited:.0f}s)")
            else:
                logger.info(f"WordpressSite {self.namespace}/{site_name} was removed while waiting (waited {waited:.0f}s)")

        for site_name, reason in skipped.items():
            if site_name not in self._pending_lookups:
                self._pending_lookups[site_name] = now
                logged = True
                logger.info(
                    f"WordpressSite {self.namespace}/{site_name} not ready yet ({reason}), "
                    f"retrying in {SITE_LOOKUP_RETRY_SECONDS:.0f}s"
                )

        still_waiting = False
        for site_name, first_skipped_at in list(self._pending_lookups.items()):
            if now - first_skipped_at > SITE_LOOKUP_RETRY_TIMEOUT_SECONDS:
                logged = True
                logger.error(
                    f"Giving up on WordpressSite {self.namespace}/{site_name}: "
                    f"still unresolved after {SITE_LOOKUP_RETRY_TIMEOUT_SECONDS:.0f}s ({skipped[site_name]})"
                )
                del self._pending_lookups[site_name]
            else:
                still_waiting = True

        if self._retry_task is not None:
            self._retry_task.cancel()
        self._retry_task = asyncio.create_task(self._retry_pending_lookups()) if still_waiting else None
        return logged

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
        # nginx) by a trailing event cancelling this task. The lock must be
        # acquired *inside* the shielded coroutine, not around it: shield
        # only protects what's inside it from cancellation, and cancelling
        # this task would otherwise unwind straight through an outer `async
        # with self._sync_lock` and release it while the shielded sync it
        # was guarding is still actually running - letting a freshly
        # scheduled sync start concurrently with the "cancelled" one instead
        # of queueing behind it.
        await asyncio.shield(self._locked_sync())

    async def _locked_sync(self) -> None:
        async with self._sync_lock:
            await self.sync()

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
