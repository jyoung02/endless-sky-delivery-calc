"""
Endless Sky Rush Delivery Calculator
Reads the save file + star map, runs BFS with fuel state, shows go/no-go for timed missions.
"""

import argparse
import os
import re
import tkinter as tk
from collections import deque
from datetime import date
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

DEFAULT_SAVE = _find_save()
DEFAULT_MAP  = _find_map()

FUEL_PER_JUMP = 100

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
    for raw in lines:
        line = raw.rstrip()

        if not header_done:
            if m := re.match(r'^date\s+(\d+)\s+(\d+)\s+(\d+)', line):
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                result["current_date"] = date(y, mo, d)
                continue
            if m := re.match(r'^system\s+"?([^"]+)"?\s*$', line):
                result["current_system"] = m.group(1)
                continue
            if re.match(r'^ship\s+', line):
                header_done = True

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
            mission = {"name": m.group(1), "deadline": None, "destination": None}
            continue

        if not in_mission:
            continue

        if indent == 0 and stripped:
            if mission.get("deadline") and mission.get("destination"):
                result["missions"].append(mission)
            in_mission = False
            mission = {}
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


def build_ui(save_data: dict, graph: dict, planet_system: dict, inhabited: set[str]) -> None:
    root = tk.Tk()
    root.title("Endless Sky — Delivery Calculator")
    root.configure(bg="#1e1e2e")
    root.resizable(False, False)

    # ── Header ───────────────────────────────────────────────────────────────
    hdr = tk.Frame(root, bg="#1e1e2e", pady=8)
    hdr.pack(fill="x", padx=16)

    date_str  = save_data["current_date"].strftime("%d %b %Y") if save_data["current_date"] else "?"
    sys_str   = save_data["current_system"] or "?"
    drive_str = save_data["drive"].title()
    fuel      = save_data["fuel"]
    fuel_cap  = save_data["fuel_capacity"]
    jumps_now = fuel // FUEL_PER_JUMP
    jumps_max = fuel_cap // FUEL_PER_JUMP

    tk.Label(hdr, text=f"Date: {date_str}   System: {sys_str}   Drive: {drive_str}",
             font=("Courier", 11), fg="#cdd6f4", bg="#1e1e2e").pack(anchor="w")
    tk.Label(hdr, text=f"Fuel: {fuel}/{fuel_cap}  ({jumps_now} jumps now, {jumps_max} max)",
             font=("Courier", 10), fg="#a6adc8", bg="#1e1e2e").pack(anchor="w")

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

    # ── Results area ─────────────────────────────────────────────────────────
    results_frame = tk.Frame(root, bg="#1e1e2e")
    results_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

    def refresh():
        for widget in results_frame.winfo_children():
            widget.destroy()

        results = calc_results(save_data, graph, planet_system, inhabited, visited_var.get())

        if not results:
            tk.Label(results_frame, text="No timed missions found.",
                     font=("Courier", 11), fg="#6c7086", bg="#1e1e2e").pack(pady=8)
            return

        for r in results:
            color  = STATUS_COLORS[r["status"]]
            symbol = STATUS_SYMBOLS[r["status"]]

            card = tk.Frame(results_frame, bg="#313244", pady=6, padx=10)
            card.pack(fill="x", pady=4)

            tk.Label(card, text=r["name"],
                     font=("Courier", 11, "bold"),
                     fg="#cdd6f4", bg="#313244").pack(anchor="w")

            tk.Label(card, text=f"→ {r['destination']} ({r['dest_system']})",
                     font=("Courier", 10), fg="#a6adc8", bg="#313244").pack(anchor="w")

            if r["status"] == "UNKNOWN":
                stats = "Route unknown (unexplored)" if visited_var.get() else "Destination not found in star map"
            else:
                margin_str = f"+{r['margin']}" if r["margin"] >= 0 else str(r["margin"])
                stats = f"Hops: {r['hops']}  |  Days: {r['days']}  |  Margin: {margin_str}"

            stats_frame = tk.Frame(card, bg="#313244")
            stats_frame.pack(fill="x", pady=(2, 0))
            tk.Label(stats_frame, text=stats,
                     font=("Courier", 10), fg="#a6adc8", bg="#313244").pack(side="left")
            tk.Label(stats_frame, text=f"  {symbol}",
                     font=("Courier", 10, "bold"), fg=color, bg="#313244").pack(side="left")

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
    print(f"  Drive: {save_data['drive']}")
    print(f"  Fuel: {fuel}/{fuel_cap} ({fuel // FUEL_PER_JUMP} jumps now, {fuel_cap // FUEL_PER_JUMP} max)")
    print(f"  Timed missions: {len(save_data['missions'])}")
    print(f"  Visited systems: {len(save_data['visited'])}")

    build_ui(save_data, graph, planet_system, inhabited)


if __name__ == "__main__":
    main()
