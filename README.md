# Endless Sky Delivery Calculator

A small Python tool for [Endless Sky](https://endless-sky.github.io/) that reads your save file and the star map, then shows a go/no-go status for every timed delivery mission based on hop count vs. days remaining.

## What it does

- Reads your current system, date, and drive type from the save file
- Finds all timed missions (`available job` blocks with deadlines)
- Runs BFS on the star map to find the shortest hop count to each destination
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

## Results window

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

## Explored systems toggle

The **"Explored systems only"** checkbox is on by default. When checked, BFS is restricted to systems you've already visited — so the hop count reflects routes you can actually see on your map. If no route exists through explored space, the mission shows as "Route unknown (unexplored)".

Uncheck it to plan routes through unexplored systems and see the theoretical minimum hop count.

Toggling recalculates instantly — no restart needed.

## Notes

- Assumes 1 day per hop regardless of drive type (hyperdrive or jump drive)
- Jump drive can reach non-linked systems in-game, but this tool uses the standard hyperspace link graph for all routing
- Reads the save file at launch — re-run after saving in-game to get fresh results
