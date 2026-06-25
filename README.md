# Endless Sky Delivery Calculator

A small Python tool for [Endless Sky](https://endless-sky.github.io/) that reads your save file and the star map, then shows a go/no-go status for every timed delivery mission based on hop count vs. days remaining.

## What it does

- Reads your current system, date, drive type, and current fuel from the save file
- Finds all timed missions (`available job` blocks with deadlines)
- Runs BFS on the star map tracking fuel state — refuels at inhabited systems along the route (no time cost)
- Displays results in a small window with color-coded GO / TIGHT / NO-GO status

## Requirements

- Python 3.10+
- `tkinter` (included with standard Python on Windows)
- Endless Sky installed via Steam

## Usage

```bash
python delivery-calc.py
```

Save file and map path are auto-detected from standard locations. If auto-detection fails, specify them manually:

```
--save  PATH   Path to your .txt save file
--map   PATH   Path to "map systems.txt" in the Endless Sky data folder
```

## Bind to a hotkey (Windows)

So you can pop it up without leaving the game:

1. Create a shortcut to `pythonw.exe` (no console window):
   - Right-click desktop → New → Shortcut
   - Target: `C:\Users\<you>\AppData\Local\Programs\Python\Python312\pythonw.exe "C:\path\to\delivery-calc.py"`
   - Start in: `C:\path\to\endless-sky\`
2. Right-click the shortcut → Properties → **Shortcut key** → press your combo (e.g. `Ctrl+Alt+D`)
3. Move the shortcut somewhere permanent — the hotkey stops working if the shortcut is deleted or moved

The window will pop up on top of the game. Use `pythonw.exe` (not `python.exe`) so no console window appears.

## Results window

The header shows your current system, date, drive type, and fuel. If you saved mid-jump, it shows where you're headed:

```
Date: 22 Aug 3014   System: Rastaban   Drive: Hyperdrive
In transit → Girtab
Fuel: 300/300  (3 jumps now, 3 max)
```

Each timed mission is listed with hop count, days remaining until deadline, and margin:

```
Disaster relief to New India → New India (Albaldah)
Hops: 2  |  Days: 4  |  Margin: +2    ✓ GO

Rush delivery to Arabia → Arabia (Ascella)
Hops: 3  |  Days: 6  |  Margin: +3    ✓ GO
```

**Status colors:**
- Green — GO (margin > 1 day)
- Yellow — TIGHT (margin = 1 day)
- Red — NO-GO (deadline will be missed)
- Gray — UNKNOWN (destination not found or route impossible)

## Fuel modeling

The routing accounts for fuel. Each jump costs 100 fuel. If your ship can't reach the destination without running dry, the BFS finds a route that stops at an inhabited system to refuel — landing is free time-wise, so only detours off the direct path cost extra hops.

If no viable route exists within explored space (or at all), the mission shows as UNKNOWN.

## Mid-jump behavior

If you save while in hyperspace, the tool starts routing from your last system (not your destination). The in-progress jump counts as hop 1 in the BFS, so hop count and margin are still correct. The header shows "In transit → [destination]" so you know it's accounted for.

## Explored systems toggle

The **"Explored systems only"** checkbox is on by default. When checked, BFS is restricted to systems you've already visited — so the hop count reflects routes you can actually see on your map.

Uncheck it to route through unexplored systems and see the theoretical minimum hop count.

Toggling recalculates instantly — no restart needed.

## Notes

- Assumes 1 day per hop regardless of drive type (hyperdrive or jump drive)
- Jump drive can reach non-linked systems in-game, but this tool uses the standard hyperspace link graph for all routing
- Reads the save file at launch — re-run after saving in-game to get fresh results
