#! /usr/bin/env sh
set -e

# Match dockerfile: WORKDIR /app, app package at /app/app (base image sets PYTHONPATH=/app)
APP_ROOT=${APP_ROOT:-/app}
if [ -f "$APP_ROOT/app/main.py" ]; then
    DEFAULT_MODULE_NAME=app.main
elif [ -f "$APP_ROOT/main.py" ]; then
    DEFAULT_MODULE_NAME=main
fi
MODULE_NAME=${MODULE_NAME:-$DEFAULT_MODULE_NAME}
VARIABLE_NAME=${VARIABLE_NAME:-app}
export APP_MODULE=${APP_MODULE:-"$MODULE_NAME:$VARIABLE_NAME"}

export WORKER_CLASS=${WORKER_CLASS:-"app.worker.CustomUvicornWorker"}
export PORT=${PORT:-8006}

# If there's a prestart.sh script, run it before starting
PRE_START_PATH=${PRE_START_PATH:-$APP_ROOT/prestart.sh}
echo "Checking for script in $PRE_START_PATH"
if [ -f "$PRE_START_PATH" ]; then
    echo "Running script $PRE_START_PATH"
    . "$PRE_START_PATH"
else
    echo "There is no script $PRE_START_PATH"
fi

# Gunicorn: all options on CLI. CustomUvicornWorker gives uvloop/httptools/no-access-log;
# --keep-alive 65 matches old uvicorn --timeout-keep-alive 65
exec gunicorn --bind "0.0.0.0:$PORT" --workers 3 --threads 3 \
  --max-requests 1000 --max-requests-jitter 100 --timeout 0 \
  --keep-alive 65 \
  -k "$WORKER_CLASS" "$APP_MODULE"
