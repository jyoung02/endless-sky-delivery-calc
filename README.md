# Endless Sky Delivery Calculator

A Python GUI tool for [Endless Sky](https://endless-sky.github.io/) that shows go/no-go status for every timed delivery mission based on hop count vs. days remaining.

## How it works

Requires a patched Endless Sky binary that writes a sidecar file (`%APPDATA%\endless-sky\delivery-calc.json`) every time you land at a planet. The sidecar contains your current system, date, drive type, and all timed jobs with deadlines.

`delivery-calc.py` reads the sidecar, runs BFS over the star map, and displays results in a color-coded window.

## Sidecar format

The patched binary writes:

```json
{
  "date": "Sat, 17 Sep 3014",
  "system": "Rastaban",
  "drive": "hyperdrive",
  "jobs": [
    {
      "name": "Rush delivery to Dancer",
      "planet": "Dancer",
      "system": "Rastaban",
      "deadline": "Mon, 19 Sep 3014"
    }
  ]
}
```

The patch is in `source/PlayerInfo.cpp` — see [jyoung02/endless-sky](https://github.com/jyoung02/endless-sky) for the full patched source and build instructions.

## Requirements

- Python 3.10+ with `tkinter` (included with standard Python on Windows)
- Endless Sky installed via Steam
- Patched ES binary (see above)

## Setup

1. Build the patched binary from [jyoung02/endless-sky](https://github.com/jyoung02/endless-sky)
2. Create a desktop shortcut:
   - Target: `pythonw.exe "C:\path\to\delivery-calc.py"`
   - No console window, no terminal needed
3. Launch once — the window stays running and auto-refreshes

## Features

- **Auto-refresh** — updates every second when the sidecar changes (land somewhere → instant update)
- **Ctrl+Alt+Z** — global hotkey brings the window to front from anywhere, including in-game (registered via Win32 `RegisterHotKey`, no AutoHotkey required)
- **Single-instance** — launching a second copy focuses the existing window instead of opening a new one
- **Explored systems only** toggle — restricts BFS to systems you've visited; uncheck for theoretical minimum hops

## Status logic

| Status | Condition |
|--------|-----------|
| GO | days_left − hops ≥ 2 |
| TIGHT | days_left − hops = 1 |
| NO-GO | days_left − hops ≤ 0 |
| UNKNOWN | destination not in map, or no explored route |

Assumes 1 day per hop regardless of drive type.
