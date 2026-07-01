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

DEFAULT_NGINX_CONF_PATH = "/etc/nginx/conf.d/wordpress.conf"
DEFAULT_RELOAD_DEBOUNCE_SECONDS = 2.0
