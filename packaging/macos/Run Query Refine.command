#!/bin/zsh
set -e

SCRIPT_DIR=$(cd "$(dirname "$0")"; pwd)
APP_BUNDLE="$SCRIPT_DIR/QueryRefine.app"
RESOURCE_DIR="$APP_BUNDLE/Contents/Resources"
ENV_FILE="$RESOURCE_DIR/.env"
APP_BINARY="$APP_BUNDLE/Contents/MacOS/QueryRefine"

if [[ ! -x "$APP_BINARY" ]]; then
	echo "Unable to locate QueryRefine binary at $APP_BINARY"
	echo "Make sure QueryRefine.app is in the same folder as this script."
	exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
	echo "Missing configuration file: $ENV_FILE"
	echo "Run 'Configure Environment.command' first to create it."
	exit 1
fi

set -a
source "$ENV_FILE"
set +a

if [[ -z "$REFINEMENT_FRAMEWORK_PATH" ]]; then
	cat <<'EOF'
REFINEMENT_FRAMEWORK_PATH is not set.
Edit the .env file and provide the absolute path to your custom frameworks YAML
before launching the app.
EOF
	exit 1
fi

"$APP_BINARY" "$@"