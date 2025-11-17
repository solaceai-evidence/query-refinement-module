#!/bin/zsh
set -e

APP_DIR=$(cd "$(dirname "$0")"; pwd)
RESOURCE_DIR="$APP_DIR/../Resources"
ENV_FILE="$RESOURCE_DIR/.env"
APP_BINARY="$APP_DIR/../MacOS/QueryRefine"

if [[ ! -x "$APP_BINARY" ]]; then
	echo "Unable to locate QueryRefine binary at $APP_BINARY"
	exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
	echo "Missing configuration file: $ENV_FILE"
	echo "Run 'Configure Environment.command' first."
	exit 1
fi

# Export variables while respecting quoted values and spaces.
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