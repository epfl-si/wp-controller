# nginx comes from nginx.org, not from Debian, so it can be newer than the
# release's 1.26.3. The Lua module (used for the Prometheus metrics, see
# src/templates/lua/) is not packaged there and Debian's is tied to its own
# nginx build, so it is compiled here against exactly the nginx version
# installed below: a dynamic module only loads into the nginx it was built
# for. Bump NGINX_VERSION and these together; see
# https://github.com/epfl-si/wp-controller/issues/1
ARG NGINX_VERSION=1.30.5
# lua-resty-core must match lua-nginx-module (the module refuses to start
# otherwise): v0.10.28 goes with lua-resty-core v0.1.31, the pair Debian ships.
ARG LUA_NGINX_MODULE_VERSION=v0.10.28
ARG LUA_RESTY_CORE_VERSION=v0.1.31
ARG LUA_RESTY_LRUCACHE_VERSION=v0.15
ARG NGX_DEVEL_KIT_VERSION=v0.3.4

FROM debian:trixie-slim AS lua-build
ARG NGINX_VERSION
ARG LUA_NGINX_MODULE_VERSION
ARG LUA_RESTY_CORE_VERSION
ARG LUA_RESTY_LRUCACHE_VERSION
ARG NGX_DEVEL_KIT_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl ca-certificates \
    libpcre2-dev zlib1g-dev libssl-dev libluajit-5.1-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN set -ex; \
    curl -fsSL "https://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz" | tar xz; \
    git clone --depth 1 --branch "${NGX_DEVEL_KIT_VERSION}" https://github.com/vision5/ngx_devel_kit.git; \
    git clone --depth 1 --branch "${LUA_NGINX_MODULE_VERSION}" https://github.com/openresty/lua-nginx-module.git; \
    cd "nginx-${NGINX_VERSION}"; \
    export LUAJIT_LIB="/usr/lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH)" LUAJIT_INC=/usr/include/luajit-2.1; \
    ./configure --with-compat \
        --add-dynamic-module=../ngx_devel_kit \
        --add-dynamic-module=../lua-nginx-module; \
    make -j"$(nproc)" modules; \
    mkdir -p /out/modules; \
    cp objs/ndk_http_module.so objs/ngx_http_lua_module.so /out/modules/
# The Lua side of the module, installed where it looks by default
# (/usr/local/share/lua/5.1).
RUN set -ex; \
    git clone --depth 1 --branch "${LUA_RESTY_CORE_VERSION}" https://github.com/openresty/lua-resty-core.git; \
    git clone --depth 1 --branch "${LUA_RESTY_LRUCACHE_VERSION}" https://github.com/openresty/lua-resty-lrucache.git; \
    mkdir -p /out/lua/resty; \
    cp -r lua-resty-core/lib/resty/* lua-resty-lrucache/lib/resty/* /out/lua/resty/

FROM python:3.13-trixie
ARG NGINX_VERSION
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    curl \
    gnupg \
    libluajit-5.1-2 \
    && curl -fsSL https://nginx.org/keys/nginx_signing.key | gpg --dearmor -o /usr/share/keyrings/nginx.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/nginx.gpg] http://nginx.org/packages/debian trixie nginx" > /etc/apt/sources.list.d/nginx.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends "nginx=${NGINX_VERSION}-1~trixie" \
    && rm -f /etc/nginx/conf.d/default.conf \
    && rm -rf /var/lib/apt/lists/*
COPY --from=lua-build /out/modules/ /usr/lib/nginx/modules/
COPY --from=lua-build /out/lua/ /usr/local/share/lua/5.1/

COPY . .
RUN pip install --no-cache-dir -r requirements.txt
RUN set -ex; mkdir -p /etc/nginx/snippets /etc/nginx/lua; \
    cp src/templates/fastcgi.conf /etc/nginx/snippets/fastcgi.conf; \   
    cp src/templates/generic.conf /etc/nginx/conf.d/generic.conf; \
    cp src/templates/lua/*.lua /etc/nginx/lua/; \   
    sed -i 's|^pid .*;|pid /tmp/nginx/nginx.pid;|; /^user /d' /etc/nginx/nginx.conf; \
    printf 'load_module modules/ndk_http_module.so;\nload_module modules/ngx_http_lua_module.so;\n' | cat - /etc/nginx/nginx.conf > /tmp/nginx.conf; \
    cat /tmp/nginx.conf > /etc/nginx/nginx.conf; rm /tmp/nginx.conf

# The WordPress codebase: served directly for static assets
# (wp-includes/wp-admin/wp-content plugins/themes) and PHP error pages,
# same as wordpress-nginx.
COPY --from=quay-its.epfl.ch/svc0041/wp-base:rc /wp /wp

# nginx listens on :8000 (see src/templates/wordpress.conf.j2), not :80,
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
    && mkdir -p /etc/nginx/errors /tmp/nginx/client_body /tmp/nginx/proxy /tmp/nginx/fastcgi /tmp/nginx/uwsgi /tmp/nginx/scgi \
    && chown -R wp-controller:0 /etc/nginx/conf.d /etc/nginx/snippets /etc/nginx/errors /tmp/nginx /var/log/nginx /run \
    && chmod -R g+rwX /etc/nginx/conf.d /etc/nginx/snippets /etc/nginx/errors /tmp/nginx /var/log/nginx /run
# So `pip install --user` (used for dev-only extras, see docker-compose.dev.yml)
# has a real home to write to, and its console scripts are on PATH.
ENV PATH="/home/wp-controller/.local/bin:${PATH}"
USER wp-controller

CMD ["sh", "-c", "kopf run main.py --namespace=${WATCH_NAMESPACE}"]
