#!/bin/zsh
APP_DIR=$(cd "$(dirname "$0")"; pwd)
ENV_DIR="$APP_DIR/../Resources"
export $(grep -v '^#' "$ENV_DIR/.env" | xargs)
"$APP_DIR/../MacOS/QueryRefine" "$@"