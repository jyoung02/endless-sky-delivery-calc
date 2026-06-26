"""
Endless Sky Rush Delivery Calculator
Reads delivery-calc.json (written by the patched game on landing) and
map systems.txt, then shows go/no-go for every timed job/mission.
"""

import ctypes
import ctypes.wintypes
import json
import os
import re
import socket
import sys
import threading
import tkinter as tk
from collections import deque
from datetime import date

# ── Single-instance: focus existing window via local socket ───────────────────
_FOCUS_PORT = 54321

def _try_focus_existing():
    """If another instance is running, tell it to focus and return True."""
    try:
        s = socket.create_connection(("127.0.0.1", _FOCUS_PORT), timeout=0.5)
        s.sendall(b"focus")
        s.close()
        return True
    except OSError:
        return False

def _start_focus_server(on_focus):
    """Listen for focus requests from future instances."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", _FOCUS_PORT))
    srv.listen(5)
    srv.settimeout(1.0)
    def _loop():
        while True:
            try:
                conn, _ = srv.accept()
                conn.recv(16)
                conn.close()
                on_focus()
            except OSError:
                pass
    t = threading.Thread(target=_loop, daemon=True)
    t.start()

# ── Paths ─────────────────────────────────────────────────────────────────────
SIDECAR   = os.path.join(os.environ["APPDATA"], "endless-sky", "delivery-calc.json")
SAVE_DIR  = os.path.join(os.environ["APPDATA"], "endless-sky", "saves")
MAP_FILE  = r"C:\Program Files (x86)\Steam\steamapps\common\Endless Sky\data\map systems.txt"


# ── Parse star map ────────────────────────────────────────────────────────────
def parse_map(path):
    """Return (graph, planet_system) where:
      graph         : dict[str, set[str]]  — bidirectional adjacency list
      planet_system : dict[str, str]       — planet TrueName → system name
    """
    graph = {}
    planet_system = {}
    current_system = None

    token_re = re.compile(r'"([^"]+)"|(\S+)')

    def first_token(line):
        m = token_re.search(line)
        return (m.group(1) or m.group(2)) if m else None

    def all_tokens(line):
        return [m.group(1) or m.group(2) for m in token_re.finditer(line)]

    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n").rstrip("\r")
            stripped = line.lstrip("\t")
            depth = len(line) - len(stripped)

            if depth == 0:
                tokens = all_tokens(stripped)
                if tokens and tokens[0] == "system" and len(tokens) >= 2:
                    current_system = tokens[1]
                    if current_system not in graph:
                        graph[current_system] = set()
                else:
                    current_system = None
                continue

            if current_system is None:
                continue

            tokens = all_tokens(stripped)
            if not tokens:
                continue

            key = tokens[0]

            if key == "link" and len(tokens) >= 2:
                dest = tokens[1]
                graph[current_system].add(dest)
                if dest not in graph:
                    graph[dest] = set()
                graph[dest].add(current_system)

            elif key == "object" and len(tokens) >= 2:
                planet_name = tokens[1]
                planet_system[planet_name] = current_system

    return graph, planet_system


# ── BFS ───────────────────────────────────────────────────────────────────────
def bfs(graph, start, visited_only=False, visited=None):
    """Return dict[system_name -> hop_count] from start."""
    if start not in graph:
        return {}
    dist = {start: 0}
    q = deque([start])
    while q:
        node = q.popleft()
        for nb in graph.get(node, ()):
            if nb in dist:
                continue
            if visited_only and visited and nb not in visited:
                continue
            dist[nb] = dist[node] + 1
            q.append(nb)
    return dist


# ── Date parsing ──────────────────────────────────────────────────────────────
MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
    "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
    "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

def parse_es_date(s):
    """'Sat, 17 Sep 3014' → datetime.date(3014, 9, 17)"""
    # Strip weekday
    s = s.strip()
    if "," in s:
        s = s.split(",", 1)[1].strip()
    parts = s.split()
    day   = int(parts[0])
    month = MONTH_MAP[parts[1]]
    year  = int(parts[2])
    return date(year, month, day)


def days_between(d1, d2):
    """d2 - d1 in days (positive means d2 is later)."""
    return (d2 - d1).days


# ── Load visited systems from save file ───────────────────────────────────────
def load_visited():
    visited = set()
    try:
        saves = [f for f in os.listdir(SAVE_DIR) if f.endswith(".txt")]
        if not saves:
            return visited
        # Most recently modified save
        newest = max(saves, key=lambda f: os.path.getmtime(os.path.join(SAVE_DIR, f)))
        with open(os.path.join(SAVE_DIR, newest), encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r'^visited\s+"?([^"\n]+)"?\s*$', line)
                if m:
                    visited.add(m.group(1).strip())
    except Exception:
        pass
    return visited


# ── Main calculation ──────────────────────────────────────────────────────────
def calculate(explored_only):
    with open(SIDECAR, encoding="utf-8") as f:
        data = json.load(f)

    current_system = data["system"]
    current_date   = parse_es_date(data["date"])
    drive          = data["drive"]
    jobs           = data["jobs"]

    graph, planet_system = parse_map(MAP_FILE)
    visited = load_visited() if explored_only else None

    dist = bfs(graph, current_system, visited_only=explored_only, visited=visited)

    results = []
    for job in jobs:
        dest_planet = job["planet"]
        dest_system = job["system"]
        deadline    = parse_es_date(job["deadline"])

        days_left = days_between(current_date, deadline)

        # Look up hop count
        hops = dist.get(dest_system)
        if hops is None:
            results.append({
                "name":       job["name"],
                "planet":     dest_planet,
                "system":     dest_system,
                "days_left":  days_left,
                "hops":       None,
                "margin":     None,
                "status":     "unknown",
            })
            continue

        # Each hop takes 1 day; need hops days of travel.
        # Margin = days_left - hops (>=1 to make it with 0 spare)
        margin = days_left - hops
        if margin >= 2:
            status = "go"
        elif margin == 1:
            status = "tight"
        else:
            status = "nogo"

        results.append({
            "name":      job["name"],
            "planet":    dest_planet,
            "system":    dest_system,
            "days_left": days_left,
            "hops":      hops,
            "margin":    margin,
            "status":    status,
        })

    # Sort: nogo first, then tight, then go; within each group by margin asc
    order = {"nogo": 0, "tight": 1, "go": 2, "unknown": 3}
    results.sort(key=lambda r: (order[r["status"]], r["margin"] if r["margin"] is not None else 999))

    return data, results


# ── GUI ───────────────────────────────────────────────────────────────────────
COLOR = {
    "go":      "#4caf50",
    "tight":   "#ff9800",
    "nogo":    "#f44336",
    "unknown": "#9e9e9e",
    "bg":      "#1e1e2e",
    "fg":      "#cdd6f4",
    "header":  "#89b4fa",
    "card":    "#313244",
    "sep":     "#45475a",
}


def build_ui():
    root = tk.Tk()
    root.title("Endless Sky — Delivery Calc")
    root.configure(bg=COLOR["bg"])
    root.resizable(True, True)

    explored_var = tk.BooleanVar(value=False)
    last_mtime = [0.0]  # mutable cell for the watch loop

    # ── Header ────────────────────────────────────────────────────────────────
    header_frame = tk.Frame(root, bg=COLOR["bg"])
    header_frame.pack(fill="x", padx=12, pady=(10, 4))

    info_label = tk.Label(header_frame, bg=COLOR["bg"], fg=COLOR["header"],
                          font=("Consolas", 10), anchor="w", justify="left")
    info_label.pack(side="left", fill="x", expand=True)

    chk = tk.Checkbutton(header_frame, text="Explored systems only",
                         variable=explored_var, bg=COLOR["bg"], fg=COLOR["fg"],
                         selectcolor=COLOR["card"], activebackground=COLOR["bg"],
                         activeforeground=COLOR["fg"], font=("Consolas", 9),
                         command=lambda: refresh())
    chk.pack(side="right")

    # ── Scrollable results area ───────────────────────────────────────────────
    canvas = tk.Canvas(root, bg=COLOR["bg"], highlightthickness=0)
    scrollbar = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)

    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))

    scroll_frame = tk.Frame(canvas, bg=COLOR["bg"])
    canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

    def on_configure(event):
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfig(canvas_window, width=canvas.winfo_width())

    scroll_frame.bind("<Configure>", on_configure)
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

    def clear_results():
        for w in scroll_frame.winfo_children():
            w.destroy()

    def refresh():
        clear_results()
        try:
            last_mtime[0] = os.path.getmtime(SIDECAR)
            data, results = calculate(explored_var.get())
        except FileNotFoundError:
            info_label.config(text="delivery-calc.json not found — land at a planet first.")
            return
        except Exception as e:
            info_label.config(text=f"Error: {e}")
            return

        info_label.config(
            text=f"{data['date']}  ·  {data['system']}  ·  {data['drive']}"
        )

        if not results:
            tk.Label(scroll_frame, text="No timed jobs available.",
                     bg=COLOR["bg"], fg=COLOR["fg"],
                     font=("Consolas", 10)).pack(pady=20)
            return

        for r in results:
            color = COLOR[r["status"]]
            card = tk.Frame(scroll_frame, bg=COLOR["card"], pady=6, padx=10)
            card.pack(fill="x", padx=4, pady=3)

            # Status badge + name
            top = tk.Frame(card, bg=COLOR["card"])
            top.pack(fill="x")

            badge_text = {"go": "✓ GO", "tight": "~ TIGHT", "nogo": "✗ NO-GO", "unknown": "? UNKNOWN"}[r["status"]]
            tk.Label(top, text=badge_text, bg=color, fg="white",
                     font=("Consolas", 9, "bold"), padx=6, pady=1).pack(side="left")

            tk.Label(top, text="  " + r["name"], bg=COLOR["card"], fg=COLOR["fg"],
                     font=("Consolas", 10), anchor="w").pack(side="left", fill="x", expand=True)

            # Detail line
            if r["hops"] is not None:
                detail = f"{r['planet']} ({r['system']})   Hops: {r['hops']}  Days left: {r['days_left']}  Margin: {r['margin']:+d}"
            else:
                route_note = "(no explored route)" if explored_var.get() else "(unreachable?)"
                detail = f"{r['planet']} ({r['system']})   Days left: {r['days_left']}  {route_note}"

            tk.Label(card, text=detail, bg=COLOR["card"], fg=COLOR["sep"] if r["status"] == "unknown" else COLOR["fg"],
                     font=("Consolas", 9), anchor="w").pack(fill="x")

    # ── Buttons ───────────────────────────────────────────────────────────────
    btn_frame = tk.Frame(root, bg=COLOR["bg"])
    btn_frame.pack(fill="x", padx=12, pady=(0, 8))

    tk.Button(btn_frame, text="Refresh", command=refresh,
              bg=COLOR["card"], fg=COLOR["fg"], relief="flat",
              font=("Consolas", 9), padx=8).pack(side="left")
    tk.Button(btn_frame, text="Close", command=root.destroy,
              bg=COLOR["card"], fg=COLOR["fg"], relief="flat",
              font=("Consolas", 9), padx=8).pack(side="right")

    def watch():
        try:
            mtime = os.path.getmtime(SIDECAR)
            if mtime != last_mtime[0]:
                refresh()
        except FileNotFoundError:
            pass
        root.after(1000, watch)

    def focus_window():
        def _do():
            root.deiconify()
            root.attributes("-topmost", True)
            root.lift()
            root.focus_force()
            root.after(200, lambda: root.attributes("-topmost", False))
        root.after(0, _do)

    _start_focus_server(focus_window)

    # Register Ctrl+Alt+Z in a dedicated thread with its own Win32 message loop.
    # Tkinter's main loop would eat WM_HOTKEY before a PeekMessage poll could see it,
    # so we let a background thread own the registration and GetMessage loop instead.
    def _hotkey_thread():
        user32 = ctypes.windll.user32
        user32.RegisterHotKey(None, 1, 0x0002 | 0x0001, 0x5A)  # CTRL+ALT+Z
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                focus_window()
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    threading.Thread(target=_hotkey_thread, daemon=True).start()

    refresh()
    root.after(1000, watch)
    root.minsize(520, 200)
    root.mainloop()


if __name__ == "__main__":
    if "--sidecar" in sys.argv:
        idx = sys.argv.index("--sidecar")
        SIDECAR = sys.argv[idx + 1]
    if _try_focus_existing():
        sys.exit(0)  # existing window focused, nothing more to do
    build_ui()
