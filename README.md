# Crabby 🦀

A tiny pixel-art crab that lives on your Windows desktop and reacts to your Claude Code chats.
One crab per open chat, a smaller helper crab for every running subagent, and a costume for every job.

> Unofficial fan project for Claude Code. Not made, endorsed or supported by Anthropic.

<p align="center">
  <img src="media/crabby-hero.gif" alt="A pixel crab walks along the bottom of the screen, hops, changes into a chef costume and falls asleep in the corner." width="640">
</p>

**Website: [crabby.website](https://crabby.website)** (try the crab in your browser)

<p align="center">
  <a href="https://crabby.website/#tour"><img src="media/poster.png" alt="Watch the 1-minute tour" width="640"></a>
</p>



## Install

Paste this into Claude (Desktop or Code):

```
Install Crabby from https://github.com/nidhinvijay/crabby
```

Claude reads [INSTALL.md](INSTALL.md), checks that Python is there, runs the installer and tells you when to start a new chat.
Prefer to do it yourself?

```
git clone https://github.com/nidhinvijay/crabby
cd crabby
python install.py
```

Then start a **new** Claude chat. The crab shows up by itself and goes away when you close Claude.

**On a Mac:** it also runs on macOS (Apple silicon tested). Use a Python that carries Tk 8.6, because Tk 9 draws the see-through window black: `uv python install 3.11.9`, then `"$(uv python find 3.11.9)" install.py`. The crab stands on the Dock, or on a Dock replacement such as uBar.

**You need:** Windows, Claude Code or Claude Desktop (Code tab), and [Python](https://www.python.org/downloads/) with tkinter (the normal python.org installer has it). Tested on Python 3.11.

## What it does

- **Walks, hops and climbs.** It walks along the bottom of your screen (on top of the taskbar when the taskbar is showing), hops, and climbs the outer side walls. Drag it anywhere and let go: it falls, lands, and sticks to screen edges.
- **One crab per chat.** With two or more chats open, hover a crab for a card with the project name, what that chat is doing, how long it has been working and your 5-hour usage.
- **A helper crab per subagent**, one size smaller, in its own costume.
- **Reacts to Claude's work:** thinking dots while Claude works, a magnifier while reading or searching, a hammer while editing, a terminal while running commands, hearts when a task finishes, a shake on errors, and a wave when Claude needs you.
- **Moods:** tired as you pass 80% of your 5-hour limit, collapsed at 100%, and a happy hop when the limit resets.
- **Sleeps in the corner.** When Claude goes quiet it wanders for a minute, then walks to the bottom-right corner and falls asleep. A chat that stays idle for a minute loses its crab (the newest chat always keeps one).
- **Several monitors.** A crab left on a second screen walks back to your main screen after five minutes.
- **Costumes:** Plain, Chef, Pirate, Dev, Student, Manager, Teacher, Wizard, Scientist, Ninja, Musician, Gardener and Viking, plus a Santa hat in December. It changes outfit now and then.
- **Little extras:** a morning coffee cup, a stretch and yawn after an hour of non-stop work, crabs waving at each other, hold the mouse on a crab to pet it.
- **Light:** under 50 MB of memory (about 33 MB measured on one PC), no network access, and it only reads and writes its own folder.

## Controls

| | |
|---|---|
| `/pet` | start or stop the pet |
| right-click a crab | outfit, size, sleep, hide for an hour |

## How it works

A small Claude mod (`mod/`) writes one little state file per chat: busy or idle, which tool is running, how many subagents, plan usage. The pet (`pet/crab_pet.py`, Python and tkinter) reads those files and draws the crabs. The mod starts the pet when a chat starts, and the pet notices when chats close. No data leaves your computer.

The installer copies both into your Claude folder (`%USERPROFILE%\.claude`) and adds one entry to its `settings.json` (backed up first).

## Uninstall

```
python install.py --uninstall
```

## Known limits

- Windows and macOS. On macOS the pet uses about 120 MB of memory, not 50.
- Works with Claude Desktop (Code tab) and Claude Code.
- The crabs only appear for chats started after installing.

## License

[MIT](LICENSE)
