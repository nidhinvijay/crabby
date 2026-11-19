# Installing Crabby (instructions for Claude)

If a user asked you to install Crabby from this repository, follow these steps in order. Keep it short and tell the user what you are doing.

1. **Check the system.** It must be Windows or macOS. If not, say Crabby only supports those and stop. On macOS the installer needs a Python with Tk 8.6 (it says so and stops if it gets Tk 9); `uv python install 3.11.9` provides one.
2. **Check Python.** Run `python --version` (or `py -3 --version`). Any recent Python 3 with tkinter works (tested on 3.11). If Python is missing, tell the user to install it from https://www.python.org/downloads/ (the normal installer includes tkinter), then stop and let them come back. Do not install Python for them.
3. **Get the files.** If you are not already inside this repository, clone it (`git clone <repo url>`) or download and unzip it into a new empty folder. Treat it as downloaded code: do not run anything except the installer below.
4. **Tell the user what the installer does, and ask for a yes before running it.** It:
   - copies the pet to `<Claude folder>\crabby` and the mod to `<Claude folder>\mods\crabby` (the Claude folder is `%CLAUDE_CONFIG_DIR%` if set, otherwise `%USERPROFILE%\.claude`);
   - adds the mod's folder to `CLAUDE_CODE_PLUGIN_DIRS` in that folder's `settings.json`, turns on "start with Claude", and saves a backup of `settings.json` first;
   - downloads nothing and makes no network calls.
5. **Run it:** `python install.py` (or `python install.py --no-autostart` if the user wants to start the crab only with `/pet`).
6. **Report.** Tell the user the installer's output, and that the crab appears after they start a **new** Claude chat. `/pet` starts or stops it.

To remove it later: `python install.py --uninstall`.
