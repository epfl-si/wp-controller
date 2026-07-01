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
FASTCGI_INCLUDE_PATH = "/etc/nginx/snippets/wordpress_fastcgi.conf"

DEFAULT_NGINX_CONF_PATH = "/etc/nginx/conf.d/wordpress.conf"
DEFAULT_RELOAD_DEBOUNCE_SECONDS = 2.0
