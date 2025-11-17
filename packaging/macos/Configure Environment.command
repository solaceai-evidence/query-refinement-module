#!/bin/zsh
# Ensure the script stops on errors so users get clear feedback.
set -e

APP_DIR=$(cd "$(dirname "$0")"; pwd)
RESOURCE_DIR="$APP_DIR/../Resources"
TARGET_ENV="$RESOURCE_DIR/.env"
TEMPLATE_ENV="$RESOURCE_DIR/sample.env"

if [[ ! -d "$RESOURCE_DIR" ]]; then
	echo "Unable to locate the app's Resources directory at $RESOURCE_DIR"
	exit 1
fi

# Copy template over the first time so users start from hints instead of a blank file.
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