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
RUN cp src/templates/wordpress_fastcgi.conf /etc/nginx/conf.d/wordpress_fastcgi.conf

# nginx needs to bind :80 without running as root, and to write its pid,
# logs and the config we generate at runtime. Binding :80 as this user
# still requires the NET_BIND_SERVICE capability, granted by the Pod's
# securityContext (see manifests/deployment.yaml).
RUN groupadd -r wp-controller && useradd -r -g wp-controller wp-controller \
    && mkdir -p /var/lib/nginx/body /var/lib/nginx/proxy \
    && chown -R wp-controller:wp-controller /etc/nginx/conf.d /var/lib/nginx /var/log/nginx /run
USER wp-controller

CMD ["sh", "-c", "kopf run main.py --namespace=${WATCH_NAMESPACE}"]
