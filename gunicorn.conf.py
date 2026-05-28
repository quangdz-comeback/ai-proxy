"""Gunicorn configuration for OpenGateway AI Proxy.

Single-worker with threads to keep SQLite access serialized while still
allowing concurrent in-flight upstream streaming requests.
"""

# Network
bind = "0.0.0.0:80"

# Workers
# Single worker for SQLite compatibility (avoid 'database is locked' under
# concurrent writers across multiple processes).
workers = 1
worker_class = "gthread"
threads = 4

# Timeouts
# 120s matches upstream timeout so long streaming responses don't get killed.
timeout = 120
graceful_timeout = 30
keepalive = 5

# Logging (stdout/stderr so systemd / journald can capture)
accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(D)s "%(f)s" "%(a)s"'

# Process naming
proc_name = "opengateway-ai-proxy"

# Reasonable per-worker request limits to recycle memory.
max_requests = 1000
max_requests_jitter = 50
