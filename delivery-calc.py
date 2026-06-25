"""
Endless Sky Rush Delivery Calculator
Reads the save file + star map, runs BFS, shows go/no-go for timed missions.
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

# ─── Star-map parser ─────────────────────────────────────────────────────────

def parse_map(map_path: str) -> tuple[dict[str, set[str]], dict[str, str]]:
    """
    Returns:
        graph        — {system: {neighbour, ...}}  (bidirectional)
        planet_system — {planet_name: system_name}
    """
    graph: dict[str, set[str]] = {}
    planet_system: dict[str, str] = {}

    current_system = None
    in_object = False   # inside an `object` block (planet/moon)
    object_depth = 0    # indentation depth when `object` started

    with open(map_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip()
            stripped = line.lstrip()
            indent = len(line) - len(stripped)

            # Top-level system declaration
            if m := re.match(r'^system\s+"?([^"]+)"?\s*$', line):
                current_system = m.group(1)
                if current_system not in graph:
                    graph[current_system] = set()
                in_object = False
                continue

            if current_system is None:
                continue

            # link (only at indent level 1 tab = 1)
            if m := re.match(r'^\tlink\s+"?([^"]+)"?\s*$', line):
                neighbour = m.group(1)
                graph[current_system].add(neighbour)
                if neighbour not in graph:
                    graph[neighbour] = set()
                graph[neighbour].add(current_system)
                continue

            # object NAME  — a named planet/moon
            if m := re.match(r'^(\t+)object\s+"?([^"]+)"?\s*$', line):
                planet_name = m.group(2)
                planet_system[planet_name] = current_system
                in_object = True
                object_depth = indent
                continue

            # anonymous `object` (no name) — just track we're inside it
            if re.match(r'^(\t+)object\s*$', line):
                in_object = True
                object_depth = indent
                continue

    return graph, planet_system


# ─── Save-file parser ────────────────────────────────────────────────────────

def parse_save(save_path: str) -> dict:
    """
    Returns a dict with:
        current_date    — datetime.date
        current_system  — str
        drive           — "hyperdrive" | "jump drive"
        missions        — list of {name, deadline: date, destination: str}
        visited         — set[str]  (system names)
    """
    result = {
        "current_date": None,
        "current_system": None,
        "drive": "hyperdrive",
        "missions": [],
        "visited": set(),
    }

    with open(save_path, encoding="utf-8") as f:
        lines = f.readlines()

    # ── Pass 1: header fields (date, system, visited) ────────────────────────
    # The header ends at the first `ship` line.
    header_done = False
    for raw in lines:
        line = raw.rstrip()
        stripped = line.lstrip()

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
                # fall through to continue processing the rest of the file

        if m := re.match(r'^visited\s+"?([^"]+)"?\s*$', line):
            result["visited"].add(m.group(1))

    # ── Pass 2: flagship outfits ──────────────────────────────────────────────
    # Flagship is the first `ship` block.  Find its `outfits` section.
    in_flagship_outfits = False
    flagship_found = False

    for raw in lines:
        line = raw.rstrip()
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if not flagship_found and re.match(r'^ship\s+', line):
            flagship_found = True
            continue

        if flagship_found:
            if re.match(r'^ship\s+', line):
                break  # second ship block — stop

            if re.match(r'^\toutfits\s*$', line):
                in_flagship_outfits = True
                continue

            if in_flagship_outfits:
                if indent < 2:
                    in_flagship_outfits = False
                else:
                    if re.search(r'Jump Drive', stripped, re.IGNORECASE):
                        result["drive"] = "jump drive"

    # ── Pass 3: mission blocks ────────────────────────────────────────────────
    # Look for "available job" or active job blocks that contain both
    # `deadline` and `destination`.
    in_mission = False
    mission: dict = {}

    for raw in lines:
        line = raw.rstrip()
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # Start of a mission block — flush any current mission first
        if m := re.match(r'^"available job"\s+"?([^"]+)"?\s*$', line):
            if in_mission and mission.get("deadline") and mission.get("destination"):
                result["missions"].append(mission)
            in_mission = True
            mission = {"name": m.group(1), "deadline": None, "destination": None}
            continue

        if not in_mission:
            continue

        # End of mission block (top-level non-empty line that isn't a mission)
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

    # Flush last mission if file ends without blank line
    if in_mission and mission.get("deadline") and mission.get("destination"):
        result["missions"].append(mission)

    return result


# ─── BFS ─────────────────────────────────────────────────────────────────────

def shortest_hops(
    graph: dict[str, set[str]],
    start: str,
    end: str,
    visited_only: bool = False,
    visited: set[str] | None = None,
) -> int | None:
    """BFS from start to end.  Returns hop count, or None if unreachable."""
    if start == end:
        return 0

    allowed = visited if (visited_only and visited) else None

    queue: deque[tuple[str, int]] = deque([(start, 0)])
    seen = {start}

    while queue:
        node, hops = queue.popleft()
        for nbr in graph.get(node, ()):
            if nbr in seen:
                continue
            if allowed is not None and nbr not in allowed:
                continue
            if nbr == end:
                return hops + 1
            seen.add(nbr)
            queue.append((nbr, hops + 1))

    return None


# ─── Calculation core ─────────────────────────────────────────────────────────

def calc_results(
    save_data: dict,
    graph: dict[str, set[str]],
    planet_system: dict[str, str],
    visited_only: bool = False,
) -> list[dict]:
    """
    Returns list of result dicts:
        name, destination, dest_system, hops, days, margin, status
        status: "GO" | "TIGHT" | "NO-GO" | "UNKNOWN"
    """
    today = save_data["current_date"]
    current_sys = save_data["current_system"]
    visited = save_data["visited"]
    results = []

    for m in save_data["missions"]:
        dest_planet = m["destination"]
        deadline = m["deadline"]
        dest_system = planet_system.get(dest_planet, None)

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

        hops = shortest_hops(graph, current_sys, dest_system, visited_only, visited)
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
    "GO":      "#2ecc71",   # green
    "TIGHT":   "#f39c12",   # amber
    "NO-GO":   "#e74c3c",   # red
    "UNKNOWN": "#95a5a6",   # grey
}

STATUS_SYMBOLS = {
    "GO":      "✓ GO",
    "TIGHT":   "⚠ TIGHT",
    "NO-GO":   "✗ NO-GO",
    "UNKNOWN": "? UNKNOWN",
}


def build_ui(save_data: dict, graph: dict, planet_system: dict) -> None:
    root = tk.Tk()
    root.title("Endless Sky — Delivery Calculator")
    root.configure(bg="#1e1e2e")
    root.resizable(False, False)

    # ── Header ───────────────────────────────────────────────────────────────
    hdr = tk.Frame(root, bg="#1e1e2e", pady=8)
    hdr.pack(fill="x", padx=16)

    date_str = save_data["current_date"].strftime("%d %b %Y") if save_data["current_date"] else "?"
    sys_str  = save_data["current_system"] or "?"
    drive_str = save_data["drive"].title()

    tk.Label(hdr, text=f"Date: {date_str}   System: {sys_str}   Drive: {drive_str}",
             font=("Courier", 11), fg="#cdd6f4", bg="#1e1e2e").pack(anchor="w")

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

        results = calc_results(save_data, graph, planet_system, visited_var.get())

        if not results:
            tk.Label(results_frame, text="No timed missions found.",
                     font=("Courier", 11), fg="#6c7086", bg="#1e1e2e").pack(pady=8)
            return

        for r in results:
            color = STATUS_COLORS[r["status"]]
            symbol = STATUS_SYMBOLS[r["status"]]

            card = tk.Frame(results_frame, bg="#313244", pady=6, padx=10)
            card.pack(fill="x", pady=4)

            # Title line
            title_frame = tk.Frame(card, bg="#313244")
            title_frame.pack(fill="x")
            tk.Label(title_frame,
                     text=f"{r['name']}",
                     font=("Courier", 11, "bold"),
                     fg="#cdd6f4", bg="#313244").pack(side="left")

            # Destination line
            dest_text = f"→ {r['destination']} ({r['dest_system']})"
            tk.Label(card, text=dest_text,
                     font=("Courier", 10), fg="#a6adc8", bg="#313244").pack(anchor="w")

            # Stats line
            if r["hops"] is None and r["status"] == "UNKNOWN":
                if visited_var.get():
                    stats = "Route unknown (unexplored)"
                else:
                    stats = f"Destination planet not found in star map"
            else:
                hops_str = str(r["hops"]) if r["hops"] is not None else "?"
                margin_str = (f"+{r['margin']}" if r["margin"] is not None and r["margin"] >= 0
                              else str(r["margin"]) if r["margin"] is not None else "?")
                stats = f"Hops: {hops_str}  |  Days: {r['days']}  |  Margin: {margin_str}"

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
    print(f"  {len(graph)} systems, {len(planet_system)} named planets")

    print("Parsing save file…")
    save_data = parse_save(args.save)
    print(f"  Date: {save_data['current_date']}")
    print(f"  System: {save_data['current_system']}")
    print(f"  Drive: {save_data['drive']}")
    print(f"  Timed missions: {len(save_data['missions'])}")
    print(f"  Visited systems: {len(save_data['visited'])}")

    build_ui(save_data, graph, planet_system)


if __name__ == "__main__":
    main()
