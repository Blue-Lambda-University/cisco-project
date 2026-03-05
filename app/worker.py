"""
Custom Uvicorn worker for gunicorn: uvloop, httptools, no access log.
(Keep-alive is set via gunicorn CLI: --keep-alive 65)
"""
from uvicorn.workers import UvicornWorker


class CustomUvicornWorker(UvicornWorker):
    CONFIG_KWARGS = {
        "loop": "uvloop",
        "http": "httptools",
        "access_log": False,
    }
