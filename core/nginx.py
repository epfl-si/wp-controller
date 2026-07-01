import asyncio
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

NGINX_BINARY = "nginx"


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
