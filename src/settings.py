import os

WORDPRESS_GROUP = "wordpress.epfl.ch"
WORDPRESS_VERSION = "v2"
WORDPRESS_PLURAL = "wordpresssites"

MARIADB_GROUP = "k8s.mariadb.com"
MARIADB_VERSION = "v1alpha1"

# Naming convention used by wp-operator when it provisions a WordpressSite's
# database (see wp-operator's wp_operator.py `self.prefix`).
DATABASE_PREFIX = "wp-db-"
USER_PREFIX = "wp-db-user-"
PASSWORD_SECRET_PREFIX = "wp-db-password-"

NGINX_BINARY = "nginx"
NGINX_MAIN_CONF_PATH = "/etc/nginx/nginx.conf"
# Must live outside conf.d/: nginx auto-includes every *.conf file there
# directly inside http{}, but this file is a snippet of bare `location`
# blocks only valid when nested inside a site's own `location {}`.
FASTCGI_INCLUDE_PATH = "/etc/nginx/snippets/fastcgi.conf"

# Where the wordpress-data PVC (uploads) is mounted, and where the
# WordPress codebase itself is baked in from wp-base - same paths as
# wordpress-nginx (see manifests/deployment.yaml and the Dockerfile).
UPLOADS_ROOT = "/wp-data"
WORDPRESS_CODE_ROOT = "/wp"

# Static WordPress assets served directly from disk instead of through PHP,
# matching wordpress-nginx's nginx.tmpl.
STATIC_ASSET_WHITELIST_RE = r"(wp-bom[.]yaml|(wp-includes|wp-admin|wp-content/(plugins|mu-plugins|themes))/)"

# Below: resolved once here (default, overridable via ENV) instead of each
# caller doing its own os.environ.get(...). WATCH_NAMESPACE has no default -
# it stays a direct os.environ[...] read at the two call sites that need it
# (main.py, core/controller.py), so importing settings.py for any of the
# constants above never requires it to be set (e.g. in unit tests).
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
NGINX_CONF_PATH = os.environ.get("NGINX_CONF_PATH", "/etc/nginx/conf.d/wordpress.conf")
RELOAD_DEBOUNCE_SECONDS = float(os.environ.get("RELOAD_DEBOUNCE_SECONDS", 2.0))
# Upper bound on how long a steady stream of events (each one resetting the
# debounce) can postpone a sync - see WordPressNginxController.request_sync.
RELOAD_MAX_WAIT_SECONDS = float(os.environ.get("RELOAD_MAX_WAIT_SECONDS", 30.0))
# A WordpressSite can exist before wp-operator has finished provisioning its
# Database/User/Secret trio (see managers.site_repository.resolve_db_credentials).
# Rather than skip it forever until some unrelated event happens to trigger
# another sync, keep retrying on this interval until it resolves or the
# timeout below is reached - see WordPressNginxController.sync.
SITE_LOOKUP_RETRY_SECONDS = float(os.environ.get("SITE_LOOKUP_RETRY_SECONDS", 10.0))
SITE_LOOKUP_RETRY_TIMEOUT_SECONDS = float(os.environ.get("SITE_LOOKUP_RETRY_TIMEOUT_SECONDS", 120.0))
# wp-controller's own Prometheus metrics (see core/metrics.py); 9145 is
# taken by nginx's request metrics.
METRICS_PORT = int(os.environ.get("METRICS_PORT", 9190))
# Where the last rejected nginx config (and nginx's verbose output for it) is
# kept for debugging - see WordPressNginxController._keep_rejected_config.
# Not under conf.d/: it holds the sites' DB passwords and shouldn't sit next
# to the config nginx loads. Created and made writable in the Dockerfile.
REJECTED_CONFIG_DIR = os.environ.get("REJECTED_CONFIG_DIR", "/etc/nginx/errors")
# How many rejected configs to keep there; older ones are deleted.
REJECTED_CONFIG_KEEP = int(os.environ.get("REJECTED_CONFIG_KEEP", 5))
# Testing aid: while LOG_LEVEL is DEBUG, a WordpressSite bearing this
# annotation (whatever its value) makes wp-controller append a deliberately
# invalid directive to the generated config, so `nginx -t` rejects it and the
# whole failure path (rejected-config file, wp_controller_config_valid=0,
# error log) can be exercised on demand, on a running pod: add or remove the
# annotation. Safe by construction - a rejected candidate never replaces the
# live config - and ignored outside of DEBUG.
FORCE_INVALID_CONFIG_ANNOTATION = "wp-controller.epfl.ch/force-invalid-config"
