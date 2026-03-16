# gunicorn_config.py
workers = 2
worker_class = "sync"
timeout = 60
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
bind = "127.0.0.1:8000"
accesslog = "/var/log/pattern_access.log"
errorlog = "/var/log/pattern_error.log"
loglevel = "info"
