#!/bin/zsh
APP_DIR=$(cd "$(dirname "$0")"; pwd)
ENV_DIR="$APP_DIR/../Resources"
TARGET="$ENV_DIR/.env"
TEMPLATE="$ENV_DIR/sample.env"

cp "$TEMPLATE" "$TARGET" 2>/dev/null || true
/usr/bin/open -e "$TARGET"