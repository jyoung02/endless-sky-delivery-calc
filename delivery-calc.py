"""
Endless Sky Rush Delivery Calculator
Reads the save file + star map, runs BFS with fuel state, shows go/no-go for timed missions.
"""

import argparse
import json
import os
import re
import tkinter as tk
from collections import deque
from datetime import date, timedelta
from pathlib import Path

# ─── Defaults ───────────────────────────────────────────────────────────────

def _find_save() -> str | None:
    """Return the most recently modified save file, ignoring backups."""
    saves_dir = Path(os.environ.get("APPDATA", "")) / "endless-sky" / "saves"
    if not saves_dir.is_dir():
        return None
    candidates = [
        p for p in saves_dir.glob("*.txt")
        if "previous" not in p.name and "~~" not in p.name
    ]
    if not candidates:
        return None
    return str(max(candidates, key=lambda p: p.stat().st_mtime))

def _find_map() -> str | None:
    """Return path to map systems.txt from the standard Steam install location."""
    candidates = [
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Endless Sky\data\map systems.txt"),
        Path(r"C:\Program Files\Steam\steamapps\common\Endless Sky\data\map systems.txt"),
        Path(os.environ.get("HOME", "")) / ".local/share/Steam/steamapps/common/Endless Sky/data/map systems.txt",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None

DEFAULT_SAVE  = _find_save()
DEFAULT_MAP   = _find_map()
SNAPSHOT_FILE = Path(__file__).parent / ".delivery-calc-snapshot.json"

FUEL_PER_JUMP = 100

# ─── Snapshot (UUID diff) ────────────────────────────────────────────────────

def load_snapshot() -> dict:
    """Return snapshot dict, or empty dict on failure."""
    try:
        return json.loads(SNAPSHOT_FILE.read_text())
    except Exception:
        return {}

def save_snapshot(missions: list[dict], system: str, planet: str | None) -> None:
    """Save per-location UUID history and last-run location."""
    snapshot = load_snapshot()
    key = f"{system}::{planet}"
    uuids = [m["uuid"] for m in missions if m.get("uuid")]
    snapshot[key] = uuids
    snapshot["_last"] = key
    SNAPSHOT_FILE.write_text(json.dumps(snapshot))

# ─── Star-map parser ─────────────────────────────────────────────────────────

def parse_map(map_path: str) -> tuple[dict[str, set[str]], dict[str, str]]:
    """
    Returns:
        graph         — {system: {neighbour, ...}}  (bidirectional)
        planet_system — {planet_name: system_name}
    """
    graph: dict[str, set[str]] = {}
    planet_system: dict[str, str] = {}

    current_system = None

    with open(map_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip()

            # Top-level system declaration
            if m := re.match(r'^system\s+"?([^"]+)"?\s*$', line):
                current_system = m.group(1)
                if current_system not in graph:
                    graph[current_system] = set()
                continue

            if current_system is None:
                continue

            # Hyperspace link
            if m := re.match(r'^\tlink\s+"?([^"]+)"?\s*$', line):
                neighbour = m.group(1)
                graph[current_system].add(neighbour)
                if neighbour not in graph:
                    graph[neighbour] = set()
                graph[neighbour].add(current_system)
                continue

            # Named object (planet/station) — name may be quoted or unquoted
            if m := re.match(r'^\t+object\s+"([^"]+)"\s*$', line):
                planet_system[m.group(1)] = current_system
                continue
            if m := re.match(r'^\t+object\s+([A-Za-z]\S*)\s*$', line):
                planet_system[m.group(1)] = current_system
                continue

    return graph, planet_system


# ─── Save-file parser ────────────────────────────────────────────────────────

def parse_save(save_path: str) -> dict:
    """
    Returns a dict with:
        current_date    — datetime.date
        current_system  — str
        drive           — "hyperdrive" | "jump drive"
        fuel            — int  (current fuel units)
        fuel_capacity   — int  (max fuel units)
        missions        — list of {name, deadline: date, destination: str}
        visited         — set[str]  (system names)
    """
    result = {
        "current_date": None,
        "current_system": None,
        "current_planet": None,
        "travel": None,
        "drive": "hyperdrive",
        "fuel": 100,
        "fuel_capacity": 100,
        "missions": [],
        "visited": set(),
    }

    with open(save_path, encoding="utf-8") as f:
        lines = f.readlines()

    # ── Pass 1: header fields (date, system) and visited lines ───────────────
    header_done = False
    raw_date: date | None = None
    system_entry_method: str | None = None

    for raw in lines:
        line = raw.rstrip()

        if not header_done:
            if m := re.match(r'^date\s+(\d+)\s+(\d+)\s+(\d+)', line):
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                raw_date = date(y, mo, d)
                continue
            if m := re.match(r'^"system entry method"\s+"?([^"]+)"?\s*$', line):
                system_entry_method = m.group(1)
                continue
            if m := re.match(r'^system\s+"?([^"]+)"?\s*$', line):
                result["current_system"] = m.group(1)
                continue
            if m := re.match(r'^planet\s+"?([^"]+)"?\s*$', line):
                result["current_planet"] = m.group(1)
                continue
            if m := re.match(r'^travel\s+"?([^"]+)"?\s*$', line):
                # Only record the first travel entry; multiple = autopilot route not mid-jump
                if result["travel"] is None:
                    result["travel"] = m.group(1)
                continue
            if re.match(r'^ship\s+', line):
                header_done = True

    # ES saves the departure date, not arrival — each jump costs 1 day.
    # If "system entry method" is set, the player arrived via hyperspace and
    # the save date is 1 day behind the actual current game date.
    if raw_date is not None:
        offset = 1 if system_entry_method is not None else 0
        result["current_date"] = raw_date + timedelta(days=offset)

        if m := re.match(r'^visited\s+"?([^"]+)"?\s*$', line):
            result["visited"].add(m.group(1))

    # ── Pass 2: flagship fuel, fuel_capacity, drive ──────────────────────────
    flagship_found = False
    in_attrs = False
    in_outfits = False

    for raw in lines:
        line = raw.rstrip()
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if not flagship_found:
            if re.match(r'^ship\s+', line):
                flagship_found = True
            continue

        if re.match(r'^ship\s+', line):
            break  # end of flagship block

        if re.match(r'^\tattributes\s*$', line):
            in_attrs = True
            in_outfits = False
            continue

        if re.match(r'^\toutfits\s*$', line):
            in_outfits = True
            in_attrs = False
            continue

        # Leaving a sub-block back to 1-tab level
        if indent == 1 and stripped:
            in_attrs = False
            in_outfits = False

        if in_attrs:
            if m := re.match(r'\t+"fuel capacity"\s+(\d+(?:\.\d+)?)', line):
                result["fuel_capacity"] = int(float(m.group(1)))

        if in_outfits:
            if re.search(r'Jump Drive', stripped, re.IGNORECASE):
                result["drive"] = "jump drive"

        # Current fuel (1-tab level, not inside a sub-block)
        if m := re.match(r'^\tfuel\s+(\d+(?:\.\d+)?)\s*$', line):
            result["fuel"] = int(float(m.group(1)))

    # ── Pass 3: timed mission blocks ─────────────────────────────────────────
    in_mission = False
    mission: dict = {}

    for raw in lines:
        line = raw.rstrip()
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if m := re.match(r'^"available job"\s+"?([^"]+)"?\s*$', line):
            if in_mission and mission.get("deadline") and mission.get("destination"):
                result["missions"].append(mission)
            in_mission = True
            mission = {"name": m.group(1), "deadline": None, "destination": None, "uuid": None}
            continue

        if not in_mission:
            continue

        if indent == 0 and stripped:
            if mission.get("deadline") and mission.get("destination"):
                result["missions"].append(mission)
            in_mission = False
            mission = {}
            continue

        if m := re.match(r'^\tuuid\s+(\S+)\s*$', line):
            mission["uuid"] = m.group(1)
            continue

        if m := re.match(r'^\tname\s+"?([^"]+)"?\s*$', line):
            mission["name"] = m.group(1)
            continue

        if m := re.match(r'^\tdeadline\s+(\d+)\s+(\d+)\s+(\d+)', line):
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            mission["deadline"] = date(y, mo, d)
            continue

        if m := re.match(r'^\tdestination\s+"?([^"]+)"?\s*$', line):
            mission["destination"] = m.group(1)
            continue

    if in_mission and mission.get("deadline") and mission.get("destination"):
        result["missions"].append(mission)

    return result


# ─── BFS with fuel state ─────────────────────────────────────────────────────

def shortest_hops(
    graph: dict[str, set[str]],
    start: str,
    end: str,
    fuel: int,
    fuel_capacity: int,
    inhabited: set[str],
    visited_only: bool = False,
    visited: set[str] | None = None,
) -> int | None:
    """
    BFS from start to end tracking fuel state.
    Refuels to full capacity instantly at any inhabited system (no time cost).
    Returns hop count, or None if unreachable.
    """
    def refuel(system: str, current_fuel: int) -> int:
        return fuel_capacity if system in inhabited else current_fuel

    start_fuel = refuel(start, fuel)

    if start == end:
        return 0

    allowed = visited if (visited_only and visited) else None

    # State: (system, fuel_after_refuel_on_arrival)
    queue: deque[tuple[str, int, int]] = deque([(start, start_fuel, 0)])
    seen: set[tuple[str, int]] = {(start, start_fuel)}

    while queue:
        node, node_fuel, hops = queue.popleft()

        for nbr in graph.get(node, ()):
            if allowed is not None and nbr not in allowed:
                continue

            new_fuel = node_fuel - FUEL_PER_JUMP
            if new_fuel < 0:
                continue  # not enough fuel for this jump

            new_fuel = refuel(nbr, new_fuel)

            if nbr == end:
                return hops + 1

            state = (nbr, new_fuel)
            if state not in seen:
                seen.add(state)
                queue.append((nbr, new_fuel, hops + 1))

    return None


# ─── Calculation core ─────────────────────────────────────────────────────────

def calc_results(
    save_data: dict,
    graph: dict[str, set[str]],
    planet_system: dict[str, str],
    inhabited: set[str],
    visited_only: bool = False,
) -> list[dict]:
    """
    Returns list of result dicts:
        name, destination, dest_system, hops, days, margin, status
        status: "GO" | "TIGHT" | "NO-GO" | "UNKNOWN"
    """
    today        = save_data["current_date"]
    current_sys  = save_data["current_system"]
    visited      = save_data["visited"]
    fuel         = save_data["fuel"]
    fuel_cap     = save_data["fuel_capacity"]
    results      = []

    for m in save_data["missions"]:
        dest_planet = m["destination"]
        deadline    = m["deadline"]
        dest_system = planet_system.get(dest_planet)

        if dest_system is None:
            results.append({
                "name": m["name"],
                "destination": dest_planet,
                "dest_system": "?",
                "hops": None,
                "days": (deadline - today).days,
                "margin": None,
                "status": "UNKNOWN",
            })
            continue

        hops = shortest_hops(
            graph, current_sys, dest_system,
            fuel, fuel_cap, inhabited,
            visited_only, visited,
        )
        days = (deadline - today).days

        if hops is None:
            status = "UNKNOWN"
            margin = None
        else:
            margin = days - hops
            if margin < 0:
                status = "NO-GO"
            elif margin <= 1:
                status = "TIGHT"
            else:
                status = "GO"

        results.append({
            "name": m["name"],
            "destination": dest_planet,
            "dest_system": dest_system,
            "hops": hops,
            "days": days,
            "margin": margin,
            "status": status,
        })

    return results


# ─── Tkinter UI ──────────────────────────────────────────────────────────────

STATUS_COLORS = {
    "GO":      "#2ecc71",
    "TIGHT":   "#f39c12",
    "NO-GO":   "#e74c3c",
    "UNKNOWN": "#95a5a6",
}

STATUS_SYMBOLS = {
    "GO":      "✓ GO",
    "TIGHT":   "⚠ TIGHT",
    "NO-GO":   "✗ NO-GO",
    "UNKNOWN": "? UNKNOWN",
}


def build_ui(save_data: dict, graph: dict, planet_system: dict, inhabited: set[str],
             prev_uuids: set[str]) -> None:
    root = tk.Tk()
    root.title("Endless Sky — Delivery Calculator")
    root.configure(bg="#1e1e2e")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    # ── Header ───────────────────────────────────────────────────────────────
    hdr = tk.Frame(root, bg="#1e1e2e", pady=8)
    hdr.pack(fill="x", padx=16)

    date_str    = save_data["current_date"].strftime("%d %b %Y") if save_data["current_date"] else "?"
    sys_str     = save_data["current_system"] or "?"
    planet      = save_data["current_planet"]
    travel      = save_data["travel"]
    in_transit  = travel is not None and planet is None
    drive_str   = save_data["drive"].title()
    fuel        = save_data["fuel"]
    fuel_cap    = save_data["fuel_capacity"]
    jumps_now   = fuel // FUEL_PER_JUMP
    jumps_max   = fuel_cap // FUEL_PER_JUMP

    location_str = f"System: {sys_str}" + (f"   Planet: {planet}" if planet else "")
    tk.Label(hdr, text=f"Date: {date_str}   {location_str}   Drive: {drive_str}",
             font=("Courier", 11), fg="#cdd6f4", bg="#1e1e2e").pack(anchor="w")
    if in_transit:
        tk.Label(hdr, text=f"In transit → {travel}",
                 font=("Courier", 10), fg="#f39c12", bg="#1e1e2e").pack(anchor="w")
    tk.Label(hdr, text=f"Fuel: {fuel}/{fuel_cap}  ({jumps_now} jumps now, {jumps_max} max)",
             font=("Courier", 10), fg="#a6adc8", bg="#1e1e2e").pack(anchor="w")

    # Filter missions: if we have a previous snapshot, only show new UUIDs
    all_missions  = save_data["missions"]
    is_new_board  = bool(prev_uuids)
    if is_new_board:
        missions = [m for m in all_missions if m.get("uuid") not in prev_uuids]
        hidden   = len(all_missions) - len(missions)
    else:
        missions  = all_missions
        hidden    = 0

    # Override save_data missions for calc_results
    filtered_save = {**save_data, "missions": missions}

    # ── Toggle ───────────────────────────────────────────────────────────────
    visited_var = tk.BooleanVar(value=True)
    toggle_frame = tk.Frame(root, bg="#1e1e2e")
    toggle_frame.pack(fill="x", padx=16, pady=(0, 6))
    tk.Checkbutton(
        toggle_frame,
        text="Explored systems only",
        variable=visited_var,
        font=("Courier", 10),
        fg="#cdd6f4", bg="#1e1e2e",
        selectcolor="#313244",
        activeforeground="#cdd6f4", activebackground="#1e1e2e",
        command=lambda: refresh(),
    ).pack(anchor="w")

    # ── Results area (selectable Text widget) ────────────────────────────────
    txt = tk.Text(root, bg="#1e1e2e", fg="#cdd6f4", font=("Courier", 10),
                  relief="flat", bd=0, wrap="none", cursor="arrow",
                  width=62, height=16)
    txt.pack(fill="both", expand=True, padx=16, pady=(0, 8))

    txt.tag_configure("dim",   foreground="#6c7086")
    txt.tag_configure("muted", foreground="#a6adc8")
    txt.tag_configure("bold",  font=("Courier", 11, "bold"))
    for status, color in STATUS_COLORS.items():
        txt.tag_configure(status, foreground=color, font=("Courier", 10, "bold"))

    def refresh():
        txt.config(state="normal")
        txt.delete("1.0", "end")

        if hidden:
            txt.insert("end", f"{hidden} job(s) from previous landings hidden\n\n", "dim")

        results = calc_results(filtered_save, graph, planet_system, inhabited, visited_var.get())

        if not results:
            txt.insert("end", "No new timed missions at this location.", "dim")
        else:
            for r in results:
                symbol = STATUS_SYMBOLS[r["status"]]
                txt.insert("end", r["name"] + "\n", "bold")
                txt.insert("end", f"→ {r['destination']} ({r['dest_system']})\n", "muted")
                if r["status"] == "UNKNOWN":
                    stats = "Route unknown (unexplored)" if visited_var.get() else "Destination not found"
                else:
                    margin_str = f"+{r['margin']}" if r["margin"] >= 0 else str(r["margin"])
                    stats = f"Hops: {r['hops']}  |  Days: {r['days']}  |  Margin: {margin_str}"
                txt.insert("end", stats + "  ", "muted")
                txt.insert("end", symbol + "\n\n", r["status"])

        txt.config(state="disabled")

    refresh()

    # ── Close button ─────────────────────────────────────────────────────────
    tk.Button(root, text="Close", command=root.destroy,
              font=("Courier", 10), fg="#cdd6f4", bg="#45475a",
              activeforeground="#cdd6f4", activebackground="#585b70",
              relief="flat", padx=12, pady=4).pack(pady=(0, 10))

    root.mainloop()


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Endless Sky delivery deadline calculator")
    parser.add_argument("--save", default=DEFAULT_SAVE, help="Path to save file")
    parser.add_argument("--map",  default=DEFAULT_MAP,  help="Path to map systems.txt")
    args = parser.parse_args()

    if not args.map:
        parser.error("Could not find map systems.txt. Use --map to specify its path.")
    if not args.save:
        parser.error("Could not find a save file. Use --save to specify its path.")

    print("Parsing star map…")
    graph, planet_system = parse_map(args.map)
    inhabited = set(planet_system.values())
    print(f"  {len(graph)} systems, {len(planet_system)} named planets, {len(inhabited)} inhabited systems")

    print("Parsing save file…")
    save_data = parse_save(args.save)
    fuel     = save_data["fuel"]
    fuel_cap = save_data["fuel_capacity"]
    print(f"  Date: {save_data['current_date']}")
    print(f"  System: {save_data['current_system']}")
    print(f"  Planet: {save_data['current_planet']}")
    print(f"  Drive: {save_data['drive']}")
    print(f"  Fuel: {fuel}/{fuel_cap} ({fuel // FUEL_PER_JUMP} jumps now, {fuel_cap // FUEL_PER_JUMP} max)")
    print(f"  Timed missions: {len(save_data['missions'])}")
    print(f"  Visited systems: {len(save_data['visited'])}")

    snapshot    = load_snapshot()
    current_key = f"{save_data['current_system']}::{save_data['current_planet']}"
    last_key    = snapshot.get("_last")
    same_loc    = (last_key == current_key)
    if same_loc:
        prev_uuids = set()          # re-run at same spot → show everything
    else:
        prev_uuids = set(snapshot.get(current_key, []))  # diff vs last visit HERE
    print(f"  Last run: {last_key or 'none'}  Now: {current_key}  same={same_loc}")
    save_snapshot(save_data["missions"], save_data["current_system"], save_data["current_planet"])

    build_ui(save_data, graph, planet_system, inhabited, prev_uuids)


if __name__ == "__main__":
    import traceback, tempfile
    try:
        main()
    except Exception:
        log = Path(tempfile.gettempdir()) / "delivery-calc-error.txt"
        log.write_text(traceback.format_exc())
        # Also show a tkinter error dialog if possible
        try:
            import tkinter.messagebox as mb
            root = tk.Tk(); root.withdraw()
            mb.showerror("delivery-calc crashed", f"Error log: {log}\n\n{traceback.format_exc()}")
        except Exception:
            pass
