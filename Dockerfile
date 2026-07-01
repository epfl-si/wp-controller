FROM python:3.13-bullseye
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["kopf", "run", "main.py"]
