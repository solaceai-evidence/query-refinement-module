# Run QueryRefine on macOS

You’re looking at two ready-to-use QueryRefine app bundles—one for Apple silicon (arm64) and one for Intel Macs. Follow the steps below to get the chatbot running and tell us what you think.

## 1. Choose the Right ZIP

| Your Mac | Download |
|----------|----------|
| Apple Silicon (M1/M2/M3) | `QueryRefine-arm64.zip` |
| Intel-based Mac          | `QueryRefine-x86_64.zip` |

Not sure? Click  → **About This Mac** and look for **Chip** (Apple silicon) or **Processor** (Intel).

## 2. Unzip and Review

1. Double-click your ZIP. A folder called `QueryRefine-<arch>` appears.
2. Move that folder somewhere handy, like Desktop or Applications.
3. Open it—you should see:
   - `QueryRefine.app`
   - `Configure Environment.command`
   - `Run Query Refine.command`
   - `sample.env`

> ⚠️ If macOS warns that a `.command` file is from the Internet, right-click it, choose **Open**, then confirm.

## 3. Configure Once

1. Double-click `Configure Environment.command`.
2. A Terminal window will copy `sample.env` into the app and launch TextEdit.
3. In TextEdit:
   - Set `REFINEMENT_FRAMEWORK_PATH` to the full path of the YAML you want to test (there’s a starter `sample_framework.yaml` bundled).
   - Fill in any `QUERY_REFINEMENT_LLM_*` entries you plan to use (API base URL, model name, key, etc.).
4. Save and close TextEdit. Run this script again any time you need to tweak the settings.

## 4. Start Chatting

1. Double-click `Run Query Refine.command`.
2. The script loads your `.env`, checks that `REFINEMENT_FRAMEWORK_PATH` is set, and opens the QueryRefine app.
3. When you’re done, just close the app window.

## 5. Quick Fixes

- **Gatekeeper blocked the script** → Right-click the `.command`, choose **Open**, then **Open** again.
- **“Missing framework path” message** → Re-run `Configure Environment.command` and point `REFINEMENT_FRAMEWORK_PATH` to a valid YAML file.
- **LLM/API errors** → Double-check the credentials in `.env` and make sure your network can reach the API.

## 6. Share Your Feedback

Please send back:

- Which build you tried (arm64 or x86_64).
- Any messages printed in the Terminal windows.
- The steps you took leading up to any issues or confusing moments.

Thanks for helping us refine the experience!
