FROM quay-its.epfl.ch/svc0041/wp-base:rc AS wp-base

FROM python:3.13-bullseye
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    nginx \
    && rm -f /etc/nginx/sites-enabled/default \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /etc/nginx/snippets \
    && cp src/templates/fastcgi.conf /etc/nginx/snippets/fastcgi.conf \
    && cp src/templates/generic.conf /etc/nginx/conf.d/generic.conf \
    && sed -i 's|^pid .*;|pid /tmp/nginx/nginx.pid;|' /etc/nginx/nginx.conf

# The WordPress codebase: served directly for static assets
# (wp-includes/wp-admin/wp-content plugins/themes) and PHP error pages,
# same as wordpress-nginx.
COPY --from=wp-base /wp /wp

# nginx needs to bind :80 without running as root, and to write its pid,
# logs and the config we generate at runtime. Binding :80 as this user
# still requires the NET_BIND_SERVICE capability, granted by the Pod's
# securityContext (see manifests/deployment.yaml).
RUN groupadd -r wp-controller && useradd -r -m -g wp-controller wp-controller \
    && mkdir -p /tmp/nginx/client_body /tmp/nginx/proxy /tmp/nginx/fastcgi /tmp/nginx/uwsgi /tmp/nginx/scgi \
    && chown -R wp-controller:wp-controller /etc/nginx/conf.d /etc/nginx/snippets /tmp/nginx /var/log/nginx /run
# So `pip install --user` (used for dev-only extras, see docker-compose.dev.yml)
# has a real home to write to, and its console scripts are on PATH.
ENV PATH="/home/wp-controller/.local/bin:${PATH}"
USER wp-controller

CMD ["sh", "-c", "kopf run main.py --namespace=${WATCH_NAMESPACE}"]
