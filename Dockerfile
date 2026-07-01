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
CMD ["kopf", "run", "main.py"]
