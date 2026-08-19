FROM quay-its.epfl.ch/svc0041/wp-base:rc AS wp-base

FROM python:3.13-trixie
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    nginx \
    libnginx-mod-http-lua \
    && rm -f /etc/nginx/sites-enabled/default \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /etc/nginx/snippets /etc/nginx/lua \
    && cp src/templates/fastcgi.conf /etc/nginx/snippets/fastcgi.conf \
    && cp src/templates/generic.conf /etc/nginx/conf.d/generic.conf \
    && cp src/templates/lua/*.lua /etc/nginx/lua/ \
    && sed -i 's|^pid .*;|pid /tmp/nginx/nginx.pid;|; /^user /d' /etc/nginx/nginx.conf

# The WordPress codebase: served directly for static assets
# (wp-includes/wp-admin/wp-content plugins/themes) and PHP error pages,
# same as wordpress-nginx.
COPY --from=wp-base /wp /wp

# nginx listens on :8080 (see src/templates/wordpress.conf.j2), not :80,
# so it can bind without any capability or root privileges - a capability
# grant is unreliable across clusters (SCC policy, CRI-O ambient-capability
# support). It still needs to write its pid, logs and the config we
# generate at runtime.
#
# Group is set to root (GID 0) and made read/write/execute, not just
# wp-controller's own group: on OpenShift the container actually runs as
# an arbitrary, unpredictable UID assigned by the namespace's SCC - the
# image's USER/UID is ignored - and the only thing OpenShift guarantees
# about that UID is that it belongs to GID 0.
RUN groupadd -r wp-controller && useradd -r -m -g wp-controller wp-controller \
    && mkdir -p /tmp/nginx/client_body /tmp/nginx/proxy /tmp/nginx/fastcgi /tmp/nginx/uwsgi /tmp/nginx/scgi \
    && chown -R wp-controller:0 /etc/nginx/conf.d /etc/nginx/snippets /tmp/nginx /var/log/nginx /run \
    && chmod -R g+rwX /etc/nginx/conf.d /etc/nginx/snippets /tmp/nginx /var/log/nginx /run
# So `pip install --user` (used for dev-only extras, see docker-compose.dev.yml)
# has a real home to write to, and its console scripts are on PATH.
ENV PATH="/home/wp-controller/.local/bin:${PATH}"
USER wp-controller

CMD ["sh", "-c", "kopf run main.py --namespace=${WATCH_NAMESPACE}"]
