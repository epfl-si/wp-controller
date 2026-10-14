import asyncio
import logging
import os
import subprocess
from typing import Optional

from settings import NGINX_BINARY
from models import NginxConfigError, NginxReloadError

logger = logging.getLogger(__name__)


class NginxProcess:
    """Owns the nginx subprocess lifecycle. nginx always runs in the
    foreground (`daemon off;`) as a direct child of this process - no
    sidecar, no shared volume."""

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.is_running():
            return
        logger.info("Starting nginx")
        self._process = subprocess.Popen([NGINX_BINARY, "-g", "daemon off;"])

    async def stop(self, timeout: float = 10.0) -> None:
        if not self.is_running():
            return
        logger.info("Stopping nginx")
        self._process.terminate()
        try:
            await asyncio.to_thread(self._process.wait, timeout)
        except subprocess.TimeoutExpired:
            logger.warning("nginx did not stop in time, killing it")
            self._process.kill()
            await asyncio.to_thread(self._process.wait)

    async def validate(self, config_path: Optional[str] = None) -> None:
        """Run `nginx -t` against `config_path` (or nginx's default config
        if not given). Raises NginxConfigError (with nginx's own
        diagnostic) if it is invalid."""
        args = [NGINX_BINARY, "-t"] if config_path is None else [NGINX_BINARY, "-t", "-c", config_path]
        result = await asyncio.to_thread(subprocess.run, args, capture_output=True, text=True)
        if result.returncode != 0:
            # Keep the command and exit code: nginx's stderr alone doesn't
            # say which config file it was actually testing.
            output = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part.strip())
            # nginx -t has no verbose flag: the closest thing is a debug
            # error_log. Only run it once the test already failed (it is
            # very noisy). Not logged: it can contain the config's secrets,
            # so it is handed to the caller on the exception instead.
            verbose = await asyncio.to_thread(
                subprocess.run, [*args, "-g", "error_log stderr debug;"], capture_output=True, text=True
            )
            raise NginxConfigError(
                f"`{' '.join(args)}` exited with {result.returncode}:\n{output}",
                verbose_output=verbose.stderr.strip(),
            )

    async def reload(self) -> None:
        """Ask the running nginx master process to reload its config
        (re-reads /var/run/nginx.pid under the hood)."""
        result = await asyncio.to_thread(
            subprocess.run, [NGINX_BINARY, "-s", "reload"], capture_output=True, text=True
        )
        if result.returncode != 0:
            raise NginxReloadError(result.stderr.strip())

    async def watchdog(self, poll_interval: float = 3.0) -> None:
        """Run forever: if nginx dies unexpectedly, exit immediately rather
        than restarting it in-process. Kubernetes' pod restartPolicy is what
        actually recovers from that (see the livenessProbe on /livez in
        manifests/deployment.yaml, which nginx itself serves) - restarting
        the whole process gets a clean re-sync for free instead of adding
        our own process-supervision logic."""
        while True:
            await asyncio.sleep(poll_interval)
            if not self.is_running():
                logger.error("nginx is not running, exiting")
                os._exit(1)
