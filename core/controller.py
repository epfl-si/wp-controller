import logging
import os

from kubernetes_asyncio import client
from kubernetes_asyncio import config as k8s_config

from .nginx import NginxProcess

logger = logging.getLogger(__name__)


class WordPressNginxController:
    """Ties together the Kubernetes client, the WordpressSite lookups and
    the nginx process for a single watched namespace."""

    def __init__(self):
        self.namespace = os.environ["WATCH_NAMESPACE"]
        self.conf_path = os.environ.get("NGINX_CONF_PATH", "/etc/nginx/conf.d/wordpress.conf")
        self.nginx = NginxProcess()
        self.core_api = None
        self.custom_api = None

    async def connect(self) -> None:
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            await k8s_config.load_kube_config()

        api_client = client.ApiClient()
        self.core_api = client.CoreV1Api(api_client)
        self.custom_api = client.CustomObjectsApi(api_client)
