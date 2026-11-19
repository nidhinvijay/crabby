# Changelog

Changes in this fork (CarlRodabaugh/crabby), newest first.

## 2026-11-19

- **Fixed (macOS): new crabs no longer steal keyboard focus.** Tk asks macOS to activate the app every time it shows a window, so a crab spawning for a new chat (or a hover card opening) pulled focus away from whatever you were typing in. The pet now lets that activation through only while a mouse button is held: clicking, dragging and right-click menus work as before, and a crab that simply appears leaves your focus alone.
- **New: crabs arrive and leave in a puff of smoke.** A new chat's crab (or a subagent's helper) steps out of the same puff and sparkles used for an outfit change, holding still until the smoke clears. When a chat closes or a subagent finishes, its crab vanishes into the puff instead of blinking out. Both take 1.1 seconds. Resizing from the menu rebuilds the crabs without a puff, and a crab you're dragging, or one that leaves while the pet is hidden, still goes at once.

## 2026-11-18

- **New: window climbing (macOS), pointer play, more tool props, and saved settings** (speed, options menu, `settings.json`).
- **New: macOS support.**
