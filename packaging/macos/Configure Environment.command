#!/bin/zsh
# Ensure the script stops on errors so users get clear feedback.
set -e

SCRIPT_DIR=$(cd "$(dirname "$0")"; pwd)
APP_BUNDLE="$SCRIPT_DIR/QueryRefine.app"
RESOURCE_DIR="$APP_BUNDLE/Contents/Resources"
TEMPLATE_ENV="$SCRIPT_DIR/sample.env"
TARGET_ENV="$RESOURCE_DIR/.env"

if [[ ! -d "$APP_BUNDLE" ]]; then
	echo "Could not find QueryRefine.app alongside this script."
	echo "Make sure QueryRefine.app, sample.env, and this command remain in the same folder."
	exit 1
fi

mkdir -p "$RESOURCE_DIR"

if [[ ! -f "$TEMPLATE_ENV" ]]; then
	echo "Missing sample.env next to this script."
	exit 1
fi

if [[ ! -f "$TARGET_ENV" ]]; then
	cp "$TEMPLATE_ENV" "$TARGET_ENV"
fi

cat <<'INSTRUCTIONS'
============================================================
Query Refine Configuration
------------------------------------------------------------
1. Update REFINEMENT_FRAMEWORK_PATH to the absolute path of
	 your custom frameworks YAML file.
2. Fill in the QUERY_REFINEMENT_LLM_* variables (model, keys).
3. Save the file and close the editor.
4. Re-run this script anytime you need to adjust settings.
============================================================
INSTRUCTIONS

# Launch TextEdit so non-technical testers can edit the file.
/usr/bin/open -W -n -a TextEdit "$TARGET_ENV"

echo "Saved settings in $TARGET_ENV"
echo "You can now run 'Run Query Refine.command'."