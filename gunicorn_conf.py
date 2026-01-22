"""
Gunicorn configuration for production deployment.

This file configures Gunicorn with optimized settings for the Query Refinement API.
Gunicorn is a production-grade WSGI server that provides:
- Multiple worker processes for handling concurrent requests
- Graceful worker restarts and shutdowns
- Request timeout management
- Worker health monitoring
- Logging integration

Usage:
    gunicorn -c gunicorn_conf.py query_refinement_module.api.main:app

Environment Variables:
    HOST: Bind address (default: 0.0.0.0)
    PORT: Bind port (default: 8000)
    WORKERS: Number of worker processes (default: 4)
    WORKER_CLASS: Worker class (default: uvicorn.workers.UvicornWorker)
    WORKER_TIMEOUT: Worker timeout in seconds (default: 120)
    LOG_LEVEL: Logging level (default: info)
"""
import os
import multiprocessing

# Server socket
bind = f"{os.getenv('HOST', '0.0.0.0')}:{os.getenv('PORT', '8000')}"
backlog = 2048  # Maximum number of pending connections

# Worker processes
#
# Rule of thumb: (2 x $num_cores) + 1
# Can be overridden with WORKERS environment variable
workers = int(os.getenv("WORKERS", (2 * multiprocessing.cpu_count()) + 1))

# Worker class
#
# Use UvicornWorker for async FastAPI support
# This provides the best performance for FastAPI applications
worker_class = os.getenv("WORKER_CLASS", "uvicorn.workers.UvicornWorker")

# Worker configuration (optimized for 20 concurrent users)
worker_connections = 1000  # Maximum simultaneous clients per worker
max_requests = int(os.getenv("MAX_REQUESTS", "3000"))  # Restart worker after N requests (optimized for 20 users)
max_requests_jitter = int(os.getenv("MAX_REQUESTS_JITTER", "300"))  # Add jitter to max_requests
worker_timeout = int(os.getenv("WORKER_TIMEOUT", "180"))  # Worker timeout (increased for LLM calls)
keepalive = int(os.getenv("KEEPALIVE", "5"))  # Seconds to wait for requests on Keep-Alive connection

# Async-specific settings for UvicornWorker
# These optimize performance for async FastAPI applications with high concurrency
threads = int(os.getenv("THREADS", "1"))  # Threads per worker (1 for async workers)

# Graceful shutdown
#
# Give workers time to finish processing requests before killing them
graceful_timeout = 30  # Seconds to wait for workers to finish during shutdown

# Restart workers
#
# Preload application code before worker processes are forked
# This saves memory and speeds up worker spawning, but prevents
# code reloading without full restart
preload_app = True

# Server mechanics
daemon = False  # Run in foreground (container-friendly)
pidfile = None  # Don't create PID file
umask = 0  # File creation mask
user = None  # Don't change user
group = None  # Don't change group
tmp_upload_dir = None  # Use system temp directory

# Logging
#
# Access log: Log all requests
# Error log: Log errors and application logs
# Log level: debug, info, warning, error, critical
accesslog = "-"  # Log to stdout
errorlog = "-"  # Log to stderr
loglevel = os.getenv("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "query-refinement-api"

# Server hooks for custom behavior
def on_starting(server):
    """Called just before the master process is initialized."""
    server.log.info("Starting Query Refinement API")
    server.log.info(f"Workers: {workers}")
    server.log.info(f"Worker class: {worker_class}")
    server.log.info(f"Binding to: {bind}")
    server.log.info(f"Worker timeout: {worker_timeout}s")
    server.log.info(f"Max requests per worker: {max_requests} (+/- {max_requests_jitter})")


def on_reload(server):
    """Called when Gunicorn reloads the configuration."""
    server.log.info("Configuration reloaded")


def when_ready(server):
    """Called just after the server is started."""
    server.log.info("Server is ready to handle requests")


def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass


def post_fork(server, worker):
    """Called just after a worker has been forked."""
    server.log.info(f"Worker spawned (pid: {worker.pid})")


def pre_exec(server):
    """Called just before a new master process is forked."""
    server.log.info("Forking new master process")


def worker_int(worker):
    """Called when a worker receives the INT or QUIT signal."""
    worker.log.info("Worker received INT or QUIT signal")


def worker_abort(worker):
    """Called when a worker receives the SIGABRT signal."""
    worker.log.info("Worker received SIGABRT signal")


def pre_request(worker, req):
    """Called just before a worker processes the request."""
    # Uncomment for detailed request logging (verbose)
    # worker.log.debug(f"{req.method} {req.path}")
    pass


def post_request(worker, req, environ, resp):
    """Called after a worker processes the request."""
    # Uncomment for detailed response logging (verbose)
    # worker.log.debug(f"{req.method} {req.path} - {resp.status}")
    pass


def child_exit(server, worker):
    """Called just after a worker has been exited."""
    server.log.info(f"Worker exited (pid: {worker.pid})")


def worker_exit(server, worker):
    """Called just after a worker has been exited, in the worker process."""
    pass


def nworkers_changed(server, new_value, old_value):
    """Called just after num_workers has been changed."""
    server.log.info(f"Number of workers changed from {old_value} to {new_value}")


def on_exit(server):
    """Called just before exiting Gunicorn."""
    server.log.info("Shutting down Query Refinement API")


# SSL/TLS Configuration (optional)
#
# For HTTPS support, uncomment and configure:
# keyfile = "/path/to/keyfile.key"
# certfile = "/path/to/certfile.crt"
# ssl_version = 2  # TLS 1.2
# cert_reqs = 0  # Don't require client certificate
# ca_certs = None
# suppress_ragged_eofs = True
# do_handshake_on_connect = False
# ciphers = None

# Note: In production, it's often better to handle SSL/TLS at the
# load balancer or reverse proxy (nginx, HAProxy, etc.) level
