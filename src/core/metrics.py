"""Prometheus metrics about wp-controller itself (nginx's own request
metrics are exposed separately, by Lua, on :9145 - see templates/
generic.conf). Served on their own port, METRICS_PORT.

The one to alert on is `wp_controller_config_valid == 0`: the last generated
nginx config was rejected by `nginx -t` and nginx keeps running the previous
one, so sites are going stale."""

import time

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from settings import METRICS_PORT

_started_at = time.time()

start_time = Gauge("wp_controller_start_time_seconds", "Unix time wp-controller started")
start_time.set(_started_at)
uptime = Gauge("wp_controller_uptime_seconds", "Seconds since wp-controller started")
uptime.set_function(lambda: time.time() - _started_at)

# 1 if the last candidate config passed `nginx -t`, 0 if it was rejected
# (nginx then keeps the previous config). Unset until the first sync.
config_valid = Gauge("wp_controller_config_valid", "1 if the last generated nginx config was valid, 0 if rejected")
nginx_up = Gauge("wp_controller_nginx_up", "1 if the nginx process is running")

sites = Gauge("wp_controller_sites", "WordpressSites by state (configured, pending)", ["state"])

syncs = Counter(
    "wp_controller_syncs_total",
    "Sync runs by outcome (unchanged, applied, invalid, reload_failed, error)",
    ["result"],
)
sync_duration = Histogram("wp_controller_sync_duration_seconds", "Duration of a sync run")

last_sync = Gauge("wp_controller_last_sync_timestamp_seconds", "Unix time the last sync finished, whatever its outcome")
last_success = Gauge(
    "wp_controller_last_successful_sync_timestamp_seconds", "Unix time of the last sync that ended with a valid, applied config"
)
last_change = Gauge("wp_controller_last_config_change_timestamp_seconds", "Unix time the nginx config last actually changed")
last_reload = Gauge("wp_controller_last_reload_timestamp_seconds", "Unix time nginx was last started or reloaded successfully")
last_error = Gauge("wp_controller_last_error_timestamp_seconds", "Unix time of the last invalid config, reload failure or sync error")


def record_error(result: str) -> None:
    syncs.labels(result).inc()
    last_error.set_to_current_time()


def start_server() -> None:
    start_http_server(METRICS_PORT)
