bind = "127.0.0.1:8945"
workers = 2
threads = 2
timeout = 120
accesslog = "/srv/rlegs3-app/logs/gunicorn.access.log"
errorlog = "/srv/rlegs3-app/logs/gunicorn.error.log"
graceful_timeout = 30
pidfile = "/srv/rlegs3-app/logs/gunicorn.pid"
