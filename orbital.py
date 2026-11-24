#!/usr/bin/env python3
"""
ORBITAL - a gravity slingshot puzzle game.

Aim a probe, launch it, and let the planets' gravity bend its path into
the docking ring of the target station. Launch counts as burn #1; you
have a few correction burns per mission. Docking in as few burns as
possible earns stars, and data cores are hidden extras along the way.

This is the full port of the Orbital web game: same 8 missions, same
planet layouts and gravity, same burn model, star rules, flight timer
and sounds - rebuilt as a native window.

Pure Python standard library (tkinter). No installs needed:
    python orbital.py

Controls
--------
  Mouse drag (before launch) : aim - or use the Angle / Power sliders.
                               Releasing the mouse only aims, it never
                               launches. A fresh mission starts with no
                               aim shown.
  SPACE                      : launch (the only trigger)
  Mouse drag (during flight) : aim a correction burn - time freezes
                               while a burn is aimed
  SPACE                      : fire the aimed burn
  Arrow keys                 : Left/Right angle, Up/Down power
  R                          : reset the mission
  Esc                        : pause / resume
  P / N                      : previous / next mission (when unlocked)

Tuning knobs live in the CONFIG section below; mission layouts in LEVELS.
"""

import json
import math
import os
import random
import sys
import threading
import tkinter as tk

# ----------------------------------------------------------------------
# CONFIG - same numbers as the web edition
# ----------------------------------------------------------------------
WIDTH, HEIGHT = 960, 600         # play field, pixels
TICK_MS = 16                     # frame timer (~60 fps)
PHYS_DT = 1.0 / 120.0            # physics step (2 substeps per frame)
POWER_MIN, POWER_MAX = 40.0, 240.0   # launch speed range, px/s
AIM_SCALE = 0.9                  # drag pixels -> launch speed
BURN_CAP_LEN = 95.0              # burn drag length cap, px
BURN_SCALE = 1.15                # drag pixels -> burn delta-v
BURN_MIN_DV = 7.0                # smaller drags don't count as a burn
DOCK_RADIUS = 27                 # station docking ring radius, px
CORE_RADIUS = 19                 # data core pickup distance, px
CRASH_PAD = 3                    # crash if within planet radius + this
LOST_MARGIN = 70                 # px beyond the field = lost
FLIGHT_TIMEOUT = 25.0            # seconds; longer flights end the run
GRAV_SOFT = 400.0                # gravity softening (mu / (d^2 + 400))
GRAV_K = 300.0                   # gravity scales with size: mu = GRAV_K * radius^2
TRAIL_MAX = 900

if getattr(sys, "frozen", False):   # running as a PyInstaller .exe
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_FILE = os.path.join(_BASE_DIR, "orbital_save.json")

COLORS = {
    "bg": "#070b16",
    "probe": "#ffd75e",
    "trail": "#3d5a80",
    "predict": "#8ecae6",
    "station": "#ffc93c",
    "core": "#4ef0e0",
    "text": "#dbe7ff",
    "dim": "#5c6f94",
    "danger": "#ff5d5d",
    "ok": "#7bf1a8",
}

# ----------------------------------------------------------------------
# LEVELS - mission layouts.
# planets: (x, y, radius, gravity mu, color, label)
# Gravity rule: bigger planets pull harder - mu is always GRAV_K * radius^2,
# enforced in load_level; the mu values below are written to match.
# ----------------------------------------------------------------------
LEVELS = [
    {"name": "First Light",
     "sub": "Bend around the planet and dock - don't fly straight through it.",
     "start": (90, 300), "target": (870, 300), "par": 1, "max_burns": 3,
     "planets": [(480, 300, 30, 270000, "#3a9ad9", "Kepler")],
     "cores": [(480, 165), (665, 235)]},
    {"name": "Twin Pull",
     "sub": "Two planets tug in turn. Ride the S-curve from low-left to high-right.",
     "start": (90, 470), "target": (870, 130), "par": 2, "max_burns": 4,
     "planets": [(335, 305, 24, 172800, "#e08a3c", "A"),
                 (625, 295, 24, 172800, "#3a9ad9", "B")],
     "cores": [(305, 406), (493, 297), (705, 195)]},
    {"name": "The Gate",
     "sub": "Thread between the twin planets. The gap is safe - the surfaces aren't.",
     "start": (80, 300), "target": (880, 300), "par": 1, "max_burns": 3,
     "planets": [(480, 172, 26, 202800, "#c65b7a", "North"),
                 (480, 428, 26, 202800, "#c65b7a", "South")],
     "cores": [(480, 300), (250, 300), (710, 300)]},
    {"name": "Heavy Heart",
     "sub": "One massive world in the middle. Use its pull - or be swallowed by it.",
     "start": (90, 115), "target": (870, 485), "par": 2, "max_burns": 4,
     "planets": [(480, 300, 44, 580800, "#7a6fd0", "Heavy")],
     "cores": [(389, 138), (696, 286)]},
    {"name": "S-Curve",
     "sub": "Low planet, high planet. Two opposite bends in one flight.",
     "start": (80, 505), "target": (880, 95), "par": 2, "max_burns": 4,
     "planets": [(320, 170, 26, 202800, "#2ec4a6", "Low"),
                 (640, 430, 26, 202800, "#e08a3c", "High")],
     "cores": [(298, 405), (496, 301), (710, 196)]},
    {"name": "The Well",
     "sub": "Drop from the top, swing between two wells, and climb out to the dock.",
     "start": (480, 65), "target": (480, 535), "par": 2, "max_burns": 5,
     "planets": [(235, 300, 28, 235200, "#3a9ad9", "West"),
                 (725, 300, 28, 235200, "#e08a3c", "East")],
     "cores": [(480, 300), (480, 185)]},
    {"name": "Crossfire",
     "sub": "Four planets, one corridor. Small burns beat big ones here.",
     "start": (75, 300), "target": (885, 300), "par": 3, "max_burns": 5,
     "planets": [(300, 155, 22, 145200, "#c65b7a", "1"),
                 (300, 445, 22, 145200, "#3a9ad9", "2"),
                 (660, 155, 22, 145200, "#3a9ad9", "3"),
                 (660, 445, 22, 145200, "#c65b7a", "4")],
     "cores": [(480, 300), (480, 150), (480, 450)]},
    {"name": "Homecoming",
     "sub": "The full run: three worlds in a row. Chain the slingshots and come home.",
     "start": (70, 300), "target": (890, 300), "par": 3, "max_burns": 5,
     "planets": [(295, 300, 24, 172800, "#2ec4a6", "I"),
                 (480, 205, 20, 120000, "#e08a3c", "II"),
                 (665, 395, 24, 172800, "#3a9ad9", "III")],
     "cores": [(385, 205), (575, 395), (780, 300)]},
    {"name": "The Loop", "sub": "Out, around the giant, and home again.",
     "start": (100, 130), "target": (100, 470),
     "par": 2, "max_burns": 4,
     "planets": [(470, 300, 42, 529200, "#7a6fd0", "Loop")],
     "cores": [(83, 223), (74, 303), (71, 391)]},
    {"name": "Thread the Needle", "sub": "A narrow gap of daylight. Fly it straight.",
     "start": (70, 300), "target": (890, 300),
     "par": 2, "max_burns": 4,
     "planets": [(480, 242, 28, 235200, "#2ec4a6", "A"), (480, 358, 28, 235200, "#3a9ad9", "B")],
     "cores": [(301, 300), (546, 300), (748, 300)]},
    {"name": "Long Haul", "sub": "Weak gravity, long road. One patient launch.",
     "start": (60, 545), "target": (900, 55),
     "par": 2, "max_burns": 4,
     "planets": [(480, 300, 18, 97200, "#8fa8c8", "Far")],
     "cores": [(260, 372), (453, 224), (689, 116)]},
    {"name": "Slalom", "sub": "Three gates, three bends. Weave the staircase.",
     "start": (70, 140), "target": (890, 460),
     "par": 2, "max_burns": 4,
     "planets": [(300, 430, 24, 172800, "#2ec4a6", "S1"), (480, 170, 24, 172800, "#e08a3c", "S2"), (660, 430, 24, 172800, "#3a9ad9", "S3")],
     "cores": [(285, 220), (482, 292), (700, 367)]},
    {"name": "Twin Suns", "sub": "Two heavies side by side. Split them or swing wide.",
     "start": (80, 520), "target": (880, 80),
     "par": 2, "max_burns": 4,
     "planets": [(405, 300, 30, 270000, "#e08a3c", "Sun A"), (555, 300, 30, 270000, "#c9a227", "Sun B")],
     "cores": [(196, 295), (391, 123), (657, 66)]},
    {"name": "Low Orbit", "sub": "Skim the giant's sky and fall home.",
     "start": (90, 110), "target": (870, 110),
     "par": 2, "max_burns": 4,
     "planets": [(480, 360, 62, 1153200, "#d96c4f", "Giant")],
     "cores": [(198, 253), (452, 441), (701, 319)]},
    {"name": "Crosswind", "sub": "Four pulls at once in the corridor. Hold the middle.",
     "start": (70, 300), "target": (890, 300),
     "par": 2, "max_burns": 4,
     "planets": [(320, 195, 22, 145200, "#2ec4a6", "N1"), (320, 405, 22, 145200, "#e08a3c", "S1"), (640, 195, 22, 145200, "#3a9ad9", "N2"), (640, 405, 22, 145200, "#7a6fd0", "S2")],
     "cores": [(290, 300), (483, 300), (692, 300)]},
    {"name": "The Gauntlet", "sub": "Everything you have learned, five planets deep.",
     "start": (60, 300), "target": (900, 300),
     "par": 3, "max_burns": 5,
     "planets": [(250, 180, 20, 120000, "#2ec4a6", "G1"), (400, 430, 26, 202800, "#e08a3c", "G2"), (560, 160, 20, 120000, "#3a9ad9", "G3"), (700, 420, 26, 202800, "#7a6fd0", "G4"), (820, 240, 18, 97200, "#d94f8a", "G5")],
     "cores": [(284, 298), (479, 294), (694, 294)]},
]


# ----------------------------------------------------------------------
# PHYSICS - pure functions, shared by the game and the trajectory preview
# ----------------------------------------------------------------------
def gravity_at(x, y, planets):
    """Total gravitational acceleration at (x, y), web-style softened."""
    ax = ay = 0.0
    for (px, py, _r, mu, _c, _label) in planets:
        dx, dy = px - x, py - y
        d2 = dx * dx + dy * dy
        d = math.sqrt(d2) or 1.0
        a = mu / (d2 + GRAV_SOFT)
        ax += a * dx / d
        ay += a * dy / d
    return ax, ay


def step_physics(x, y, vx, vy, planets, dt):
    """One semi-implicit Euler step. Returns (x, y, vx, vy)."""
    ax, ay = gravity_at(x, y, planets)
    vx += ax * dt
    vy += ay * dt
    x += vx * dt
    y += vy * dt
    return x, y, vx, vy


def check_hit(x, y, planets, target):
    """'crash' | 'dock' | 'lost' | None - same rules as the web edition."""
    for (px, py, r, _mu, _c, _label) in planets:
        if (x - px) ** 2 + (y - py) ** 2 < (r + CRASH_PAD) ** 2:
            return "crash"
    tx, ty = target
    if (x - tx) ** 2 + (y - ty) ** 2 < DOCK_RADIUS ** 2:
        return "dock"
    if x < -LOST_MARGIN or x > WIDTH + LOST_MARGIN \
            or y < -LOST_MARGIN or y > HEIGHT + LOST_MARGIN:
        return "lost"
    return None


def predict_path(x, y, vx, vy, planets, target, steps=600, dt=1.0 / 60.0):
    """Simulate ahead; returns (points, outcome)."""
    points = [(x, y)]
    for i in range(steps):
        x, y, vx, vy = step_physics(x, y, vx, vy, planets, dt)
        if i % 3 == 0:
            points.append((x, y))
        outcome = check_hit(x, y, planets, target)
        if outcome:
            points.append((x, y))
            return points, outcome
    return points, "flying"


# ----------------------------------------------------------------------
# SOUND - tiny threaded beeper (Windows winsound; silent elsewhere).
# Sequences mirror the web edition's WebAudio beeps.
# ----------------------------------------------------------------------
class Beeper:
    def __init__(self):
        self.enabled = True
        try:
            import winsound
            self._winsound = winsound
        except Exception:
            self._winsound = None

    def play(self, notes):
        """notes: list of (freq Hz, ms). Plays in a thread so the game
        loop never stalls."""
        if not self.enabled or self._winsound is None:
            return
        def run():
            for freq, ms in notes:
                try:
                    self._winsound.Beep(freq, ms)
                except Exception:
                    break
        threading.Thread(target=run, daemon=True).start()

    def launch(self):
        self.play([(180, 130), (340, 120)])

    def burn(self):
        self.play([(220, 120)])

    def core(self):
        self.play([(920, 90)])

    def win(self):
        self.play([(523, 120), (659, 120), (784, 220)])

    def lose(self):
        self.play([(196, 160), (147, 260)])


# ----------------------------------------------------------------------
# GAME
# ----------------------------------------------------------------------
class OrbitalGame:
    def __init__(self, root):
        self.root = root
        root.title("Orbital - gravity slingshot puzzles")
        self.beeper = Beeper()

        self.hud1 = tk.Label(root, font=("Consolas", 13, "bold"), anchor="w",
                             bg="#0b1020", fg=COLORS["text"])
        self.hud1.pack(fill="x")
        self.hud2 = tk.Label(root, font=("Consolas", 11), anchor="w",
                             bg="#0b1020", fg=COLORS["dim"])
        self.hud2.pack(fill="x")
        self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT,
                                bg=COLORS["bg"], highlightthickness=0)
        self.canvas.pack()
        self.stats = tk.Label(root, font=("Consolas", 11), anchor="w",
                              bg="#0b1020", fg=COLORS["text"])
        self.stats.pack(fill="x")

        # sliders + toggles row (as in the web edition)
        row = tk.Frame(root, bg="#0b1020")
        row.pack(fill="x")
        tk.Label(row, text="Angle", bg="#0b1020", fg=COLORS["dim"],
                 font=("Consolas", 10)).pack(side="left", padx=(8, 2))
        self.angle_var = tk.DoubleVar(value=0)
        self.angle_scale = tk.Scale(
            row, from_=-180, to=180, orient="horizontal", length=210,
            variable=self.angle_var, command=self._slider_moved,
            bg="#0b1020", fg=COLORS["text"], highlightthickness=0,
            troughcolor="#16213c", takefocus=0, showvalue=False)
        self.angle_scale.pack(side="left")
        self.angle_out = tk.Label(row, width=5, bg="#0b1020",
                                  fg=COLORS["text"], font=("Consolas", 10))
        self.angle_out.pack(side="left")
        tk.Label(row, text="Power", bg="#0b1020", fg=COLORS["dim"],
                 font=("Consolas", 10)).pack(side="left", padx=(10, 2))
        self.power_var = tk.DoubleVar(value=150)
        self.power_scale = tk.Scale(
            row, from_=POWER_MIN, to=POWER_MAX, orient="horizontal",
            length=210, variable=self.power_var, command=self._slider_moved,
            bg="#0b1020", fg=COLORS["text"], highlightthickness=0,
            troughcolor="#16213c", takefocus=0, showvalue=False)
        self.power_scale.pack(side="left")
        self.power_out = tk.Label(row, width=4, bg="#0b1020",
                                  fg=COLORS["text"], font=("Consolas", 10))
        self.power_out.pack(side="left")
        self.preview_var = tk.BooleanVar(value=True)
        tk.Checkbutton(row, text="Preview", variable=self.preview_var,
                       bg="#0b1020", fg=COLORS["text"], takefocus=0,
                       selectcolor="#16213c", activebackground="#0b1020",
                       activeforeground=COLORS["text"],
                       font=("Consolas", 10)).pack(side="left", padx=(12, 0))
        self.sound_var = tk.BooleanVar(value=True)
        tk.Checkbutton(row, text="Sound", variable=self.sound_var,
                       bg="#0b1020", fg=COLORS["text"], takefocus=0,
                       selectcolor="#16213c", activebackground="#0b1020",
                       activeforeground=COLORS["text"],
                       font=("Consolas", 10),
                       command=self._sound_toggled).pack(side="left")
        self.pause_btn = tk.Button(row, text="Pause", command=self.toggle_pause,
                                   bg="#16213c", fg=COLORS["text"], takefocus=0,
                                   activebackground="#22335c", relief="flat",
                                   padx=10, pady=2)
        self.pause_btn.pack(side="right", padx=8)

        # buttons + level pager
        bar = tk.Frame(root, bg="#0b1020")
        bar.pack(fill="x")
        for text, cmd in (("Launch (Space)", self.space_action),
                          ("Reset (R)", self.reset)):
            tk.Button(bar, text=text, command=cmd, bg="#16213c",
                      fg=COLORS["text"], activebackground="#22335c",
                      relief="flat", padx=10, pady=4,
                      takefocus=0).pack(side="left", padx=4, pady=4)
        pager = tk.Frame(root, bg="#0b1020")
        pager.pack(fill="x")
        pf = tk.Frame(pager, bg="#0b1020")
        pf.pack()
        self.pager_prev = tk.Button(pf, text="<", width=4, takefocus=0,
                                    command=lambda: self.goto(self.level_i - 1),
                                    bg="#16213c", fg=COLORS["text"],
                                    activebackground="#22335c", relief="flat",
                                    pady=4)
        self.pager_prev.pack(side="left", padx=4, pady=4)
        self.pager_label = tk.Label(pf, text="", width=36, bg="#0b1020",
                                    fg=COLORS["text"],
                                    font=("Consolas", 11, "bold"))
        self.pager_label.pack(side="left", padx=4)
        self.pager_next = tk.Button(pf, text=">", width=4, takefocus=0,
                                    command=lambda: self.goto(self.level_i + 1),
                                    bg="#16213c", fg=COLORS["text"],
                                    activebackground="#22335c", relief="flat",
                                    pady=4)
        self.pager_next.pack(side="left", padx=4, pady=4)

        # result overlay (hidden until a run ends)
        self.overlay = tk.Frame(root, bg="#101a30", bd=2, relief="ridge")
        self.ov_kicker = tk.Label(self.overlay, bg="#101a30",
                                  fg=COLORS["dim"], font=("Consolas", 10))
        self.ov_kicker.pack(padx=18, pady=(12, 0))
        self.ov_title = tk.Label(self.overlay, bg="#101a30",
                                 fg=COLORS["text"], font=("Consolas", 17, "bold"))
        self.ov_title.pack(padx=18)
        self.ov_stars = tk.Label(self.overlay, bg="#101a30",
                                 fg=COLORS["station"], font=("Consolas", 15))
        self.ov_stars.pack(padx=18)
        self.ov_text = tk.Label(self.overlay, bg="#101a30", fg=COLORS["text"],
                                font=("Consolas", 10), wraplength=380,
                                justify="center")
        self.ov_text.pack(padx=18, pady=(2, 6))
        ov_bar = tk.Frame(self.overlay, bg="#101a30")
        ov_bar.pack(pady=(0, 12))
        self.ov_next = tk.Button(ov_bar, text="Next mission",
                                 command=lambda: self.goto(self.level_i + 1),
                                 bg="#16213c", fg=COLORS["text"], takefocus=0,
                                 activebackground="#22335c", relief="flat",
                                 padx=10, pady=4)
        self.ov_next.pack(side="left", padx=4)
        tk.Button(ov_bar, text="Replay", command=self.reset, bg="#16213c",
                  fg=COLORS["text"], takefocus=0, activebackground="#22335c",
                  relief="flat", padx=10, pady=4).pack(side="left", padx=4)

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        root.bind("<ButtonRelease-1>", self.on_release_anywhere)
        root.bind("<space>", lambda _e: self.space_action())
        root.bind("<KeyPress-r>", lambda _e: self.reset())
        root.bind("<KeyPress-R>", lambda _e: self.reset())
        root.bind("<KeyPress-n>", lambda _e: self.goto(self.level_i + 1))
        root.bind("<KeyPress-N>", lambda _e: self.goto(self.level_i + 1))
        root.bind("<KeyPress-p>", lambda _e: self.goto(self.level_i - 1))
        root.bind("<KeyPress-P>", lambda _e: self.goto(self.level_i - 1))
        root.bind("<Escape>", lambda _e: self.toggle_pause())
        root.bind("<Left>", lambda _e: self.nudge_aim(-2, 0))
        root.bind("<Right>", lambda _e: self.nudge_aim(2, 0))
        root.bind("<Up>", lambda _e: self.nudge_aim(0, 4))
        root.bind("<Down>", lambda _e: self.nudge_aim(0, -4))
        root.focus_set()

        self.save = self.load_save()
        self.level_i = 0
        self._syncing = False
        self._tick_count = 0
        self.load_level(0)
        self.tick()

    # ---------------- save / progress ----------------
    def load_save(self):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            unlocked = int(data.get("unlocked", 0))
            stars = dict(data.get("stars", {}))
            cores_best = dict(data.get("cores", {})) if data.get("v") == 3 else {}
            if data.get("v") not in (2, 3):
                stars = {}   # missions changed in v2; keep unlocks only
            return {"unlocked": max(0, min(unlocked, len(LEVELS) - 1)),
                    "stars": stars, "cores": cores_best, "v": 3}
        except Exception:
            return {"unlocked": 0, "stars": {}, "cores": {}, "v": 3}

    def record_cores(self):
        """Track the best core haul for this mission, from completed
        (docked) runs only. Returns True when this run set a new best."""
        got = sum(1 for (_x, _y, g) in self.cores if g)
        key = str(self.level_i)
        if got > int(self.save["cores"].get(key, 0)):
            self.save["cores"][key] = got
            return True
        return False

    def store_save(self):
        try:
            with open(SAVE_FILE, "w", encoding="utf-8") as fh:
                json.dump(self.save, fh)
        except Exception:
            pass

    # ---------------- level state ----------------
    def load_level(self, idx):
        self.level_i = idx
        lv = LEVELS[idx]
        self.lv = lv
        self.planets = [(px, py, r, GRAV_K * r * r, c, lab)
                        for (px, py, r, _mu, c, lab) in lv["planets"]]
        self.sx, self.sy = lv["start"]
        self.tx, self.ty = lv["target"]
        self.cores = [(cx, cy, False) for (cx, cy) in lv["cores"]]
        self.burns_used = 0
        self.flight_time = 0.0
        self.state = "aim"           # aim | fly | won | ended
        self.end_reason = None
        self.end_detail = ""
        self.paused = False
        self.pause_btn.config(text="Pause")
        self.x, self.y = float(self.sx), float(self.sy)
        self.vx = self.vy = 0.0
        self.trail = []
        self.drag = None
        self.burn_aim = None
        self.angle_deg = 0.0
        self.power = 150.0
        self.has_aim = False         # no aim shown until the player aims
        self._sync_sliders()
        rng = random.Random(1000 + idx)
        self.stars_bg = [(rng.uniform(0, WIDTH), rng.uniform(0, HEIGHT),
                          rng.uniform(0.6, 1.9)) for _ in range(130)]
        self.message = lv["sub"] + " Drag to aim, then launch."
        self.overlay.place_forget()
        self.draw_static()
        self._create_dyn_items()
        self.sync_ui()

    def goto(self, idx):
        if 0 <= idx < len(LEVELS) and idx <= self.save["unlocked"]:
            self.load_level(idx)

    def reset(self):
        self.load_level(self.level_i)

    def toggle_pause(self):
        if self.state in ("won", "ended"):
            return
        self.paused = not self.paused
        self.pause_btn.config(text="Resume" if self.paused else "Pause")
        if self.paused:
            self.message = "Paused. Esc to resume."

    def _sound_toggled(self):
        self.beeper.enabled = self.sound_var.get()

    # ---------------- aiming ----------------
    def aim_velocity(self):
        r = math.radians(self.angle_deg)
        return math.cos(r) * self.power, math.sin(r) * self.power

    def _sync_sliders(self):
        self._syncing = True
        self.angle_var.set(self.angle_deg)
        self.power_var.set(self.power)
        self._syncing = False
        self.angle_out.config(text=f"{self.angle_deg:.0f}°")
        self.power_out.config(text=f"{self.power:.0f}")

    def _slider_moved(self, _value):
        if self._syncing:
            return
        angle = float(self.angle_var.get())
        power = float(self.power_var.get())
        self.angle_out.config(text=f"{angle:.0f}°")
        self.power_out.config(text=f"{power:.0f}")
        if self.paused:
            return
        if self.state == "aim":
            self.angle_deg = angle
            self.power = power
            self.has_aim = True
        elif self.state == "fly" and self.burns_used < self.lv["max_burns"]:
            # The sliders aim correction burns too: angle = direction,
            # power scales the burn strength up to the drag cap. Stored
            # as a burn-aim point so the preview and SPACE work as usual.
            r = math.radians(angle)
            dv = power / POWER_MAX * BURN_CAP_LEN * BURN_SCALE
            self.burn_aim = (self.x + math.cos(r) * dv / BURN_SCALE,
                             self.y + math.sin(r) * dv / BURN_SCALE)
            self.message = "Burn aimed with the sliders - SPACE to fire."

    def aim_from_point(self, mx, my):
        dx, dy = mx - self.x, my - self.y
        dist = math.hypot(dx, dy)
        if dist < 6:
            return
        self.angle_deg = math.degrees(math.atan2(dy, dx))
        self.power = max(POWER_MIN, min(POWER_MAX, round(dist * AIM_SCALE)))
        self.has_aim = True
        self._sync_sliders()

    def nudge_aim(self, d_ang, d_power):
        if self.state != "aim" or self.paused:
            return
        if not self.has_aim:
            self.angle_deg, self.power = 0.0, 150.0
            self.has_aim = True
        self.angle_deg = max(-180.0, min(180.0, self.angle_deg + d_ang))
        self.power = max(POWER_MIN, min(POWER_MAX, self.power + d_power))
        self._sync_sliders()

    def on_press(self, event):
        if self.paused:
            return
        if self.state == "aim":
            self.drag = (event.x, event.y)
            self.aim_from_point(event.x, event.y)
        elif self.state == "fly":
            if self.burns_used >= self.lv["max_burns"]:
                self.message = ("No burns left - this flight is ballistic "
                                "now. Ride it out or reset.")
                return
            self.drag = (event.x, event.y)
            self.message = "Aiming correction burn - time frozen."

    def on_drag(self, event):
        if self.drag is None or self.paused:
            return
        self.drag = (event.x, event.y)
        if self.state == "aim":
            self.aim_from_point(event.x, event.y)

    def on_release(self, event):
        self._release_at(event.x, event.y)

    def on_release_anywhere(self, event):
        # A release that lands off the canvas (over the HUD, outside the
        # window) never reaches the canvas binding - without this, the
        # drag would stay "held" forever and flight would freeze.
        if self.drag is None:
            return
        self._release_at(event.x_root - self.canvas.winfo_rootx(),
                         event.y_root - self.canvas.winfo_rooty())

    def _release_at(self, x, y):
        # Releasing the mouse NEVER fires anything - it only finishes
        # the aim. SPACE is the one and only trigger.
        if self.drag is None:
            return
        self.drag = None
        if self.state == "aim":
            self.aim_from_point(x, y)
        elif self.state == "fly":
            self.burn_aim = (x, y)

    def space_action(self):
        """SPACE is the only trigger: launch while aiming, or fire the
        burn that has been aimed."""
        if self.paused:
            return
        if self.state == "aim":
            self.launch()
        elif self.state == "fly":
            point = self.drag if self.drag is not None else self.burn_aim
            if point is not None:
                self.drag = None
                self.burn_aim = None
                self.fire_burn(point[0], point[1])

    def launch(self):
        if self.state != "aim":
            return
        if not self.has_aim:
            self.message = "Aim first - drag or use the sliders."
            return
        self.vx, self.vy = self.aim_velocity()
        self.state = "fly"
        self.drag = None
        self.burns_used = 1
        self.flight_time = 0.0
        self.message = ("Launched - burn #1 spent. Drag to aim a "
                        "correction burn; SPACE to fire it.")
        self.beeper.launch()
        self.sync_ui()

    def burn_dv(self, mx, my):
        dx, dy = mx - self.x, my - self.y
        dist = math.hypot(dx, dy)
        if dist > BURN_CAP_LEN:
            dx, dy = dx / dist * BURN_CAP_LEN, dy / dist * BURN_CAP_LEN
        return dx * BURN_SCALE, dy * BURN_SCALE

    def fire_burn(self, mx, my):
        if self.burns_used >= self.lv["max_burns"]:
            self.message = "No burns left!"
            return
        dvx, dvy = self.burn_dv(mx, my)
        if math.hypot(dvx, dvy) <= BURN_MIN_DV:
            self.message = "Burn cancelled - drag farther from the probe."
            return
        self.vx += dvx
        self.vy += dvy
        self.burns_used += 1
        left = self.lv["max_burns"] - self.burns_used
        self.message = f"Burn #{self.burns_used} fired. {left} left."
        self.beeper.burn()
        self.sync_ui()

    # ---------------- simulation ----------------
    def tick(self):
        # Schedule the next frame FIRST: if anything below ever throws,
        # the game loop still survives instead of freezing mid-flight.
        self.root.after(TICK_MS, self.tick)
        aiming_burn = self.drag is not None or self.burn_aim is not None
        if self.state == "fly" and not aiming_burn and not self.paused:
            dt_frame = 1.0 / 60.0
            self.flight_time += dt_frame
            for _ in range(2):
                self.x, self.y, self.vx, self.vy = step_physics(
                    self.x, self.y, self.vx, self.vy, self.planets, PHYS_DT)
                self.check_events()
                if self.state != "fly":
                    break
            if self.state == "fly":
                self.trail.append((self.x, self.y))
                self.trail = self.trail[-TRAIL_MAX:]
                if self.flight_time > FLIGHT_TIMEOUT:
                    self.end_run("timeout")
        self.draw_frame()
        # Reconfiguring widgets every frame makes the window flicker on
        # Windows - the HUD only needs ~10 updates a second. (Events like
        # launch / burn / win still call sync_ui directly, instantly.)
        self._tick_count += 1
        if self._tick_count % 6 == 0:
            self.sync_ui()

    def check_events(self):
        outcome = check_hit(self.x, self.y, self.planets, (self.tx, self.ty))
        if outcome == "crash":
            label = ""
            for (px, py, r, _mu, _c, lab) in self.planets:
                if (self.x - px) ** 2 + (self.y - py) ** 2 < (r + CRASH_PAD) ** 2:
                    label = lab
                    break
            self.end_run("crash", label)
            return
        if outcome == "dock":
            self.win()
            return
        if outcome == "lost":
            self.end_run("lost")
            return
        for i, (cx, cy, got) in enumerate(self.cores):
            if not got and (self.x - cx) ** 2 + (self.y - cy) ** 2 <= CORE_RADIUS ** 2:
                self.cores[i] = (cx, cy, True)
                self.beeper.core()

    def stars_for(self, burns_used):
        if burns_used <= self.lv["par"]:
            return 3
        if burns_used <= self.lv["par"] + 1:
            return 2
        return 1

    def win(self):
        self.state = "won"
        stars = self.stars_for(self.burns_used)
        key = str(self.level_i)
        self.save["stars"][key] = max(stars, self.save["stars"].get(key, 0))
        self.save["unlocked"] = max(self.save["unlocked"],
                                    min(self.level_i + 1, len(LEVELS) - 1))
        new_core_best = self.record_cores()
        self.store_save()
        self.beeper.win()
        got = sum(1 for (_x, _y, g) in self.cores if g)
        title = "Clean docking" if self.burns_used <= self.lv["par"] else "Docked"
        text = (f"Docked in {self.burns_used} burn"
                f"{'' if self.burns_used == 1 else 's'} "
                f"(par {self.lv['par']}) in {self.flight_time:.1f}s · "
                f"Cores {got}/{len(self.cores)}")
        if got == len(self.cores) and self.cores:
            text += " - every core collected."
        elif new_core_best and got:
            text += " New best cores for this mission!"
        if self.level_i == len(LEVELS) - 1:
            text += " That was the final mission - replay any mission to chase 3 stars."
        self.show_overlay(f"Docked · Mission {self.level_i + 1} complete",
                          title, "★" * stars + "☆" * (3 - stars), text,
                          show_next=self.level_i < len(LEVELS) - 1)
        self.sync_ui()

    def end_run(self, reason, detail=""):
        self.state = "ended"
        self.end_reason = reason
        self.end_detail = detail
        self.beeper.lose()
        titles = {"crash": f"Crashed into {detail}" if detail else "Crashed",
                  "lost": "Lost in deep space",
                  "timeout": "Out of time"}
        hints = {"crash": "The surface is not a landing pad. Bend around it.",
                 "lost": "The probe drifted beyond recovery. R to retry.",
                 "timeout": f"Flights end after {FLIGHT_TIMEOUT:.0f} seconds. "
                            "Find a shorter line."}
        self.show_overlay("Run ended", titles.get(reason, "Run ended"), "",
                          hints.get(reason, ""), show_next=False)
        self.sync_ui()

    def show_overlay(self, kicker, title, stars, text, show_next):
        self.ov_kicker.config(text=kicker)
        self.ov_title.config(text=title)
        self.ov_stars.config(text=stars)
        self.ov_text.config(text=text)
        if show_next:
            self.ov_next.pack(side="left", padx=4)
        else:
            self.ov_next.pack_forget()
        self.overlay.place(relx=0.5, rely=0.5, anchor="center")

    # ---------------- HUD ----------------
    def sync_ui(self):
        lv = self.lv
        best = self.save["stars"].get(str(self.level_i), 0)
        best_txt = f" · Best: {'★' * best}" if best else ""
        if lv["cores"]:
            core_best = int(self.save["cores"].get(str(self.level_i), 0))
            best_txt += f" · Best cores: {core_best}/{len(lv['cores'])}"
        self.hud1.config(text=f"Mission {self.level_i + 1} of {len(LEVELS)}"
                              f"{best_txt} — {lv['name']}")
        self.hud2.config(text="  " + self.message)
        left = lv["max_burns"] - self.burns_used
        pips = "●" * self.burns_used + "○" * left
        got = sum(1 for (_x, _y, g) in self.cores if g)
        speed = math.hypot(self.vx, self.vy) if self.state == "fly" else 0.0
        phase = {"aim": "Aiming", "fly": "In flight",
                 "won": "Docked", "ended": "Run ended"}[self.state]
        if self.paused:
            phase = "Paused"
        self.stats.config(text=(
            f"  Par {lv['par']}   Burns {pips} ({left} left)   "
            f"Cores {got}/{len(self.cores)}   "
            f"Time {self.flight_time:.1f}s   Speed {speed:.0f}   {phase}"))
        self.pager_label.config(
            text=f"Level {self.level_i + 1} — {lv['name']}")
        self.pager_prev.config(
            state="normal" if self.level_i > 0 else "disabled")
        can_next = (self.level_i < len(LEVELS) - 1
                    and self.level_i + 1 <= self.save["unlocked"])
        self.pager_next.config(state="normal" if can_next else "disabled")

    # ---------------- drawing ----------------
    def draw_static(self):
        c = self.canvas
        c.delete("all")
        for (sx, sy, sr) in self.stars_bg:
            c.create_oval(sx - sr, sy - sr, sx + sr, sy + sr,
                          fill="#a9c6ff", outline="", tags="static")
        c.create_oval(self.sx - 12, self.sy - 12, self.sx + 12, self.sy + 12,
                      outline=COLORS["dim"], width=2, tags="static")
        c.create_text(self.sx, self.sy + 24, text="PAD", fill=COLORS["dim"],
                      font=("Consolas", 9), tags="static")
        for (px, py, r, _mu, color, label) in self.planets:
            c.create_oval(px - r * 1.7, py - r * 1.7, px + r * 1.7, py + r * 1.7,
                          outline="#16294d", width=1, tags="static")
            c.create_oval(px - r, py - r, px + r, py + r,
                          fill=color, outline="#cdd8ff", width=1, tags="static")
            c.create_oval(px - r * 0.35, py - r * 0.35, px + r * 0.35, py + r * 0.35,
                          fill="#ffffff", outline="", stipple="gray25", tags="static")
            c.create_text(px, py + r + 14, text=label, fill=COLORS["dim"],
                          font=("Consolas", 9), tags="static")
        c.create_oval(self.tx - DOCK_RADIUS, self.ty - DOCK_RADIUS,
                      self.tx + DOCK_RADIUS, self.ty + DOCK_RADIUS,
                      outline=COLORS["station"], width=3, tags="static")
        c.create_oval(self.tx - 5, self.ty - 5, self.tx + 5, self.ty + 5,
                      fill=COLORS["station"], outline="", tags="static")
        c.create_text(self.tx, self.ty + DOCK_RADIUS + 14, text="DOCK",
                      fill=COLORS["station"], font=("Consolas", 9), tags="static")

    def _create_dyn_items(self):
        """Create the moving canvas items ONCE per level. Flicker fix:
        the old code deleted and recreated every item 60 times a
        second, which strobes on Windows. Persistent items are only
        ever moved / shown / hidden - never recreated."""
        c = self.canvas
        self.it_trail = c.create_line(0, 0, 0, 0, fill=COLORS["trail"],
                                      width=2, state="hidden")
        self.it_predict = c.create_line(0, 0, 0, 0, fill=COLORS["predict"],
                                        width=2, dash=(2, 3), state="hidden")
        self.it_aim = c.create_line(0, 0, 0, 0, fill=COLORS["probe"],
                                    width=2, arrow="last", state="hidden")
        self.it_burn = c.create_line(0, 0, 0, 0, fill=COLORS["core"],
                                     width=2, arrow="last", state="hidden")
        self.it_cores = []
        for (cx, cy, _got) in self.cores:
            self.it_cores.append(c.create_polygon(
                cx, cy - 8, cx + 6, cy, cx, cy + 8, cx - 6, cy,
                fill=COLORS["core"], outline=""))
        self.it_probe = c.create_oval(self.x - 6, self.y - 6,
                                      self.x + 6, self.y + 6,
                                      fill=COLORS["probe"], outline="#fff3c4")
        self.it_crash = c.create_text(self.x, self.y, text="X",
                                      fill=COLORS["danger"],
                                      font=("Consolas", 20, "bold"),
                                      state="hidden")
        self.it_paused = c.create_text(WIDTH / 2, 40, text="PAUSED",
                                       fill=COLORS["text"],
                                       font=("Consolas", 18, "bold"),
                                       state="hidden")

    def _show(self, item, points=None, **kw):
        if points is not None:
            self.canvas.coords(item, *points)
        self.canvas.itemconfig(item, state="normal", **kw)

    def _hide(self, item):
        self.canvas.itemconfig(item, state="hidden")

    def draw_frame(self):
        c = self.canvas
        for item, (_cx, _cy, got) in zip(self.it_cores, self.cores):
            if got:
                self._hide(item)
            else:
                self._show(item)
        sample = self.trail[::2]
        if sample and sample[-1] != self.trail[-1]:
            sample.append(self.trail[-1])
        if len(sample) >= 2:
            self._show(self.it_trail, [p for pt in sample for p in pt])
        else:
            self._hide(self.it_trail)

        prediction = None     # (flat_points, outcome)
        if self.state == "aim" and self.has_aim:
            vx, vy = self.aim_velocity()
            self._show(self.it_aim, [self.x, self.y,
                                     self.x + vx * 0.35, self.y + vy * 0.35])
            if self.preview_var.get():
                pts, outcome = predict_path(self.x, self.y, vx, vy,
                                            self.planets, (self.tx, self.ty))
                prediction = ([p for pt in pts for p in pt], outcome)
        else:
            self._hide(self.it_aim)

        if self.state == "fly" and self.burns_used < self.lv["max_burns"] and \
                (self.drag is not None or self.burn_aim is not None):
            mx, my = self.drag if self.drag is not None else self.burn_aim
            dvx, dvy = self.burn_dv(mx, my)
            self._show(self.it_burn, [self.x, self.y,
                                      self.x + dvx, self.y + dvy])
            if self.preview_var.get():
                pts, outcome = predict_path(self.x, self.y, self.vx + dvx,
                                            self.vy + dvy, self.planets,
                                            (self.tx, self.ty))
                prediction = ([p for pt in pts for p in pt], outcome)
        else:
            self._hide(self.it_burn)

        if prediction is not None:
            flat, outcome = prediction
            color = {"dock": COLORS["ok"], "crash": COLORS["danger"],
                     "lost": COLORS["dim"],
                     "flying": COLORS["predict"]}[outcome]
            self._show(self.it_predict, flat, fill=color)
        else:
            self._hide(self.it_predict)

        if self.state == "ended" and self.end_reason == "crash":
            self._hide(self.it_probe)
            self._show(self.it_crash, [self.x, self.y])
        else:
            self._hide(self.it_crash)
            self._show(self.it_probe, [self.x - 6, self.y - 6,
                                       self.x + 6, self.y + 6])
        if self.paused:
            self._show(self.it_paused)
        else:
            self._hide(self.it_paused)


_instance_lock = None


def acquire_single_instance():
    """True only for the first running copy. The lock is a localhost
    socket held open for the life of the process - a second copy can't
    bind it, so it knows to step aside. Freed automatically on exit."""
    global _instance_lock
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 47813))
        sock.listen(1)
    except OSError:
        return False
    _instance_lock = sock
    return True


def focus_existing_window():
    """Bring the already-running game window to the front (Windows).

    Windows blocks background processes from stealing the foreground,
    so a plain SetForegroundWindow silently fails and the launch looks
    like a glitch - the icon just flashes. A brief Alt press first
    lifts that lock for this process, which makes the call work."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(
                None, "Orbital - gravity slingshot puzzles")
            if hwnd:
                user32.keybd_event(0x12, 0, 0, 0)   # Alt down
                user32.keybd_event(0x12, 0, 2, 0)   # Alt up
                user32.ShowWindow(hwnd, 9)          # SW_RESTORE
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass


def main():
    if not acquire_single_instance():
        focus_existing_window()
        return
    root = tk.Tk()
    OrbitalGame(root)
    root.mainloop()


if __name__ == "__main__":
    main()
