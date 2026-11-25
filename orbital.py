#!/usr/bin/env python3
"""
ORBITAL - a gravity slingshot puzzle game.

Aim a probe, launch it, and let the planets' gravity bend its path into
the docking ring of the target station. Launch counts as burn #1; you
have a few correction burns per mission. Docking in as few burns as
possible earns stars, and data cores are hidden extras along the way.

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
  U                          : undo the last burn (or the launch)
  R                          : reset the mission
  Esc                        : pause / resume
  P / N                      : previous / next mission (when unlocked)

Extras
------
  Some planets move on orbits - the mission clock runs while you aim,
  so timing is part of the shot. Wormhole pairs teleport the probe,
  keeping its velocity. Skimming a planet closely scores a flyby.
  The Random button builds a fresh mission that is verified beatable
  before you see it, and the Editor lets you build your own missions
  and save them next to the campaign.

Tuning knobs live in the CONFIG section below; mission layouts in LEVELS.
"""

import base64
import json
import math
import os
import random
import sys
import threading
import time
import zlib
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox

# ----------------------------------------------------------------------
# CONFIG - same numbers as the web edition
# ----------------------------------------------------------------------
WIDTH, HEIGHT = 960, 600         # play field, pixels (before UI scale)
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
GRAV_K = 450.0                   # gravity scales with size: mu = GRAV_K * radius^2
# The trail is one point per 60 Hz tick, so 1500 holds a whole flight
# up to the 25 s timeout; the old 900 cut the first seconds off slow
# runs and their ghosts started mid-flight.
TRAIL_MAX = 1500
WORMHOLE_RADIUS = 17             # teleport trigger distance, px
WORMHOLE_COOLDOWN = 0.6          # seconds before another teleport
FLYBY_RANGE = 14.0               # surface distance that counts as a flyby
SCALES = (1.0, 1.25, 1.5)        # window scale choices (fixed layout)
TEXT_SCALES = (1.0, 1.25, 1.5)   # text scale choices (fonts only)

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
    "ghost": "#33507a",
    "warp": "#b388ff",
}

PLANET_COLORS = ["#3a9ad9", "#e08a3c", "#2ec4a6", "#c65b7a", "#7a6fd0",
                 "#d96c4f", "#c9a227", "#8fa8c8"]


def _blend(hex_color, hex_target, frac):
    """Blend two #rrggbb colors; frac 0 -> color, 1 -> target."""
    def parts(h):
        return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
    a, b = parts(hex_color), parts(hex_target)
    return "#%02x%02x%02x" % tuple(
        round(a[i] + (b[i] - a[i]) * frac) for i in range(3))


# Particle fade palettes: 4 shades from full color toward the background.
PARTICLE_SHADES = {
    name: [_blend(col, COLORS["bg"], f) for f in (0.0, 0.35, 0.65, 0.88)]
    for name, col in (("engine", "#ffd75e"), ("core", "#4ef0e0"),
                      ("gold", "#ffc93c"), ("danger", "#ff5d5d"),
                      ("warp", "#b388ff"))
}

# ----------------------------------------------------------------------
# LEVELS - mission layouts.
# planets: (x, y, radius, gravity mu, color, label) for fixed planets,
# or a dict {"x","y","r","color","label","orbit":{...}} for a planet
# moving on a circular orbit around (cx, cy).
# Gravity rule: bigger planets pull harder - mu is always GRAV_K * radius^2,
# enforced in load_level; the mu values below are written to match.
# wormholes: (ax, ay, bx, by) pairs - fly into one end, exit the other.
# ----------------------------------------------------------------------
LEVELS = [
    {"name": "First Light",
     "sub": "Bend around the planet and dock - don't fly straight through it.",
     "start": (90, 300), "target": (870, 300), "par": 1, "max_burns": 3,
     "planets": [(480, 300, 30, 405000, "#3a9ad9", "Kepler")],
     "cores": [(480, 165), (665, 235)]},
    {"name": "Twin Pull",
     "sub": "Two planets tug in turn. Ride the S-curve from low-left to high-right.",
     "start": (90, 470), "target": (870, 130), "par": 2, "max_burns": 4,
     "planets": [(335, 305, 24, 259200, "#e08a3c", "A"),
                 (625, 295, 24, 259200, "#3a9ad9", "B")],
     "cores": [(305, 406), (493, 297), (705, 195)]},
    {"name": "The Gate",
     "sub": "Thread between the twin planets. The gap is safe - the surfaces aren't.",
     "start": (80, 300), "target": (880, 300), "par": 1, "max_burns": 3,
     "planets": [(480, 172, 26, 304200, "#c65b7a", "North"),
                 (480, 428, 26, 304200, "#c65b7a", "South")],
     "cores": [(233, 173), (460, 77), (700, 158)]},
    {"name": "Heavy Heart",
     "sub": "One massive world in the middle. Use its pull - or be swallowed by it.",
     "start": (90, 115), "target": (870, 485), "par": 2, "max_burns": 4,
     "planets": [(480, 300, 44, 871200, "#7a6fd0", "Heavy")],
     "cores": [(389, 138), (696, 286)]},
    {"name": "S-Curve",
     "sub": "Low planet, high planet. Two opposite bends in one flight.",
     "start": (80, 505), "target": (880, 95), "par": 2, "max_burns": 4,
     "planets": [(320, 170, 26, 304200, "#2ec4a6", "Low"),
                 (640, 430, 26, 304200, "#e08a3c", "High")],
     "cores": [(151, 282), (360, 66), (627, 54)]},
    {"name": "The Well",
     "sub": "Drop from the top, swing between two wells, and climb out to the dock.",
     "start": (480, 65), "target": (480, 535), "par": 2, "max_burns": 5,
     "planets": [(235, 300, 28, 352800, "#3a9ad9", "West"),
                 (725, 300, 28, 352800, "#e08a3c", "East")],
     "cores": [(298, 163), (267, 409)]},
    {"name": "Crossfire",
     "sub": "Four planets, one corridor. Small burns beat big ones here.",
     "start": (75, 300), "target": (885, 300), "par": 3, "max_burns": 5,
     "planets": [(300, 155, 22, 217800, "#c65b7a", "1"),
                 (300, 445, 22, 217800, "#3a9ad9", "2"),
                 (660, 155, 22, 217800, "#3a9ad9", "3"),
                 (660, 445, 22, 217800, "#c65b7a", "4")],
     "cores": [(480, 300), (480, 150), (480, 450)]},
    {"name": "Homecoming",
     "sub": "The full run: three worlds in a row. Chain the slingshots and come home.",
     "start": (70, 300), "target": (890, 300), "par": 3, "max_burns": 5,
     "planets": [(295, 300, 24, 259200, "#2ec4a6", "I"),
                 (480, 205, 20, 180000, "#e08a3c", "II"),
                 (665, 395, 24, 259200, "#3a9ad9", "III")],
     "cores": [(385, 205), (575, 395), (780, 300)]},
    {"name": "The Loop", "sub": "Out, around the giant, and home again.",
     "start": (100, 130), "target": (100, 470),
     "par": 2, "max_burns": 4,
     "planets": [(470, 300, 42, 793800, "#7a6fd0", "Loop")],
     "cores": [(61, 209), (44, 294), (49, 379)]},
    {"name": "Thread the Needle", "sub": "A narrow gap of daylight. Fly it straight.",
     "start": (70, 300), "target": (890, 300),
     "par": 2, "max_burns": 4,
     "planets": [(480, 242, 28, 352800, "#2ec4a6", "A"), (480, 358, 28, 352800, "#3a9ad9", "B")],
     "cores": [(214, 131), (462, 35), (719, 112)]},
    {"name": "Long Haul", "sub": "Weak gravity, long road. One patient launch.",
     "start": (60, 545), "target": (900, 55),
     "par": 2, "max_burns": 4,
     "planets": [(480, 300, 18, 145800, "#8fa8c8", "Far")],
     "cores": [(194, 358), (387, 171), (642, 81)]},
    {"name": "Slalom", "sub": "Three gates, three bends. Weave the staircase.",
     "start": (70, 140), "target": (890, 460),
     "par": 2, "max_burns": 4,
     "planets": [(300, 430, 24, 259200, "#2ec4a6", "S1"), (480, 170, 24, 259200, "#e08a3c", "S2"), (660, 430, 24, 259200, "#3a9ad9", "S3")],
     "cores": [(147, 359), (360, 549), (629, 575)]},
    {"name": "Twin Suns", "sub": "Two heavies side by side. Split them or swing wide.",
     "start": (80, 520), "target": (880, 80),
     "par": 2, "max_burns": 4,
     "planets": [(405, 300, 30, 405000, "#e08a3c", "Sun A"), (555, 300, 30, 405000, "#c9a227", "Sun B")],
     "cores": [(196, 295), (391, 123), (657, 66)]},
    {"name": "Low Orbit", "sub": "Skim the giant's sky and fall home.",
     "start": (90, 110), "target": (870, 110),
     "par": 2, "max_burns": 4,
     "planets": [(480, 360, 62, 1729800, "#d96c4f", "Giant")],
     "cores": [(198, 253), (452, 441), (701, 319)]},
    {"name": "Crosswind", "sub": "Four pulls at once in the corridor. Hold the middle.",
     "start": (70, 300), "target": (890, 300),
     "par": 2, "max_burns": 4,
     "planets": [(320, 195, 22, 217800, "#2ec4a6", "N1"), (320, 405, 22, 217800, "#e08a3c", "S1"), (640, 195, 22, 217800, "#3a9ad9", "N2"), (640, 405, 22, 217800, "#7a6fd0", "S2")],
     "cores": [(240, 418), (471, 463), (700, 420)]},
    {"name": "The Gauntlet", "sub": "Everything you have learned, five planets deep.",
     "start": (60, 300), "target": (900, 300),
     "par": 3, "max_burns": 5,
     "planets": [(250, 180, 20, 180000, "#2ec4a6", "G1"), (400, 430, 26, 304200, "#e08a3c", "G2"), (560, 160, 20, 180000, "#3a9ad9", "G3"), (700, 420, 26, 304200, "#7a6fd0", "G4"), (820, 240, 18, 145800, "#d94f8a", "G5")],
     "cores": [(206, 469), (446, 574), (713, 534)]},
    {"name": "Drift", "sub": "The planet won't sit still. Time your launch.",
     "start": (80, 300), "target": (880, 300),
     "par": 2, "max_burns": 4,
     "planets": [{"x": 480, "y": 180, "r": 30, "color": "#3a9ad9",
                  "label": "Drift",
                  "orbit": {"cx": 480, "cy": 300, "radius": 120,
                            "speed": 0.224, "phase": -1.5708}}],
     "cores": [(309, 277), (509, 263), (710, 268)]},
    {"name": "The Shortcut", "sub": "A wormhole jumps the wall. Mind the exit speed.",
     "start": (70, 300), "target": (890, 300),
     "par": 2, "max_burns": 4,
     "planets": [(480, 300, 26, 304200, "#c65b7a", "Block")],
     "wormholes": [(300, 150, 660, 450)],
     "cores": [(192, 214), (678, 439), (785, 369)]},
    {"name": "Patrol", "sub": "Twin planets on patrol. Cross between their passes.",
     "start": (70, 120), "target": (890, 480),
     "par": 2, "max_burns": 4,
     "planets": [{"x": 590, "y": 300, "r": 22, "color": "#2ec4a6",
                  "label": "P1",
                  "orbit": {"cx": 480, "cy": 300, "radius": 110,
                            "speed": 0.26, "phase": 0.0}},
                 {"x": 370, "y": 300, "r": 22, "color": "#e08a3c",
                  "label": "P2",
                  "orbit": {"cx": 480, "cy": 300, "radius": 110,
                            "speed": 0.26, "phase": 3.14159}}],
     "cores": [(251, 312), (466, 447), (705, 494)]},
    {"name": "Crossing", "sub": "A drifting world, a wormhole, and a long way home.",
     "start": (60, 540), "target": (900, 60),
     "par": 3, "max_burns": 5,
     "planets": [(480, 300, 24, 259200, "#3a9ad9", "Mid"),
                 {"x": 250, "y": 120, "r": 20, "color": "#d94f8a",
                  "label": "Rogue",
                  "orbit": {"cx": 250, "cy": 180, "radius": 60,
                            "speed": 0.3, "phase": 0.0}}],
     "wormholes": [(150, 520, 760, 120)],
     "cores": [(315, 425), (532, 316), (725, 178)]},
    {"name": "Ricochet", "sub": "Bank it off both planets.",
     "start": (70, 520), "target": (890, 80),
     "par": 2, "max_burns": 4,
     "planets": [(350, 380, 30, 405000, "#3a9ad9", "Bank A"),
                 (640, 220, 30, 405000, "#e08a3c", "Bank B")],
     "cores": [(316, 564), (583, 494), (798, 322)]},
    {"name": "The Spiral", "sub": "Fall around the big one.",
     "start": (80, 80), "target": (880, 520),
     "par": 2, "max_burns": 4,
     "planets": [(480, 300, 40, 720000, "#2ec4a6", "Maelstrom"),
                 (250, 480, 20, 180000, "#3a9ad9", "Eddy"),
                 (710, 120, 20, 180000, "#e08a3c", "Drift")],
     "cores": [(321, 32), (601, 49), (820, 256)]},
    {"name": "Pinball", "sub": "Four bumpers, one lane.",
     "start": (60, 300), "target": (900, 300),
     "par": 2, "max_burns": 4,
     "planets": [(280, 200, 22, 217800, "#3a9ad9", "B1"),
                 (480, 400, 22, 217800, "#e08a3c", "B2"),
                 (680, 200, 22, 217800, "#2ec4a6", "B3"),
                 (480, 120, 18, 145800, "#c65b7a", "B4")],
     "cores": [(221, 115), (482, 32), (743, 106)]},
    {"name": "Deep Field", "sub": "Small planets, long way home.",
     "start": (60, 90), "target": (900, 510),
     "par": 2, "max_burns": 4,
     "planets": [(300, 300, 18, 145800, "#3a9ad9", "Pebble"),
                 (550, 180, 18, 145800, "#e08a3c", "Grain"),
                 (700, 420, 18, 145800, "#2ec4a6", "Speck")],
     "cores": [(288, 42), (557, 66), (779, 254)]},
    {"name": "Bouncer", "sub": "New planet type: REPULSORS (orange dashed rings) push instead of pull. Thread the gate.",
     "start": (70, 300), "target": (890, 300),
     "par": 2, "max_burns": 4,
     "planets": [{"x": 480, "y": 180, "r": 26, "color": "#e08a3c",
                  "label": "Post N", "repel": True},
                 {"x": 480, "y": 420, "r": 26, "color": "#e08a3c",
                  "label": "Post S", "repel": True}],
     "cores": [(283, 262), (479, 228), (675, 248)]},
    {"name": "The Anvil", "sub": "One huge planet. Everything bends.",
     "start": (70, 300), "target": (890, 300),
     "par": 2, "max_burns": 4,
     "planets": [(520, 300, 44, 871200, "#c65b7a", "Anvil")],
     "cores": [(206, 140), (436, 37), (705, 93)]},
    {"name": "Crosshairs", "sub": "Through the cross, on the diagonal.",
     "start": (70, 90), "target": (890, 510),
     "par": 2, "max_burns": 4,
     "planets": [(480, 300, 24, 259200, "#3a9ad9", "Heart"),
                 (480, 110, 20, 180000, "#e08a3c", "North"),
                 (480, 490, 20, 180000, "#2ec4a6", "South"),
                 (290, 300, 20, 180000, "#c65b7a", "West"),
                 (670, 300, 20, 180000, "#3a9ad9", "East")],
     "cores": [(154, 316), (348, 514), (630, 568)]},
    {"name": "Undertow", "sub": "The gate is blocked. Take the wormhole.",
     "start": (70, 90), "target": (890, 510),
     "par": 2, "max_burns": 4,
     "planets": [{"x": 480, "y": 300, "r": 34, "color": "#e08a3c",
                  "label": "Block", "repel": True}],
     "wormholes": [(200, 510, 760, 90)],
     "cores": [(133, 288), (187, 466), (819, 286)]},
    {"name": "The Pendulum", "sub": "Time the swing.",
     "start": (70, 300), "target": (890, 300),
     "par": 3, "max_burns": 5,
     "planets": [{"x": 480, "y": 300, "r": 22, "color": "#3a9ad9",
                  "label": "Pivot"},
                 {"x": 480, "y": 150, "r": 20, "color": "#e08a3c",
                  "label": "Bob",
                  "orbit": {"cx": 480, "cy": 300, "radius": 150,
                            "speed": 0.3, "phase": -1.5708}}],
     "cores": [(245, 123), (495, 38), (723, 119)]},
    {"name": "Final Approach", "sub": "Everything at once. Good luck, pilot.",
     "start": (60, 60), "target": (900, 540),
     "par": 3, "max_burns": 5,
     "planets": [{"x": 300, "y": 300, "r": 26, "color": "#3a9ad9",
                  "label": "Anchor"},
                 {"x": 700, "y": 180, "r": 24, "color": "#d95f4b",
                  "label": "Bumper", "repel": True},
                 {"x": 560, "y": 295, "r": 18, "color": "#2ec4a6",
                  "label": "Runner",
                  "orbit": {"cx": 560, "cy": 380, "radius": 85,
                            "speed": 0.35, "phase": -1.5708}}],
     "wormholes": [(120, 540, 830, 70)],
     "cores": [(86, 289), (120, 518), (871, 289)]},
    {"name": "Patrol Line", "sub": "New: PATH planets patrol a route instead of circling - a straight line, or a custom path. Time your launch.",
     "start": (60, 520), "target": (900, 80),
     "par": 3, "max_burns": 5,
     "planets": [{"x": 200, "y": 380, "r": 22, "color": "#3a9ad9",
                  "label": "Patrol",
                  "path": {"pts": [[200, 380], [760, 380]],
                           "speed": 60.0, "phase": 0.0}},
                 {"x": 150, "y": 150, "r": 18, "color": "#2ec4a6",
                  "label": "Weaver",
                  "path": {"pts": [[150, 150], [350, 90], [570, 230]],
                           "speed": 45.0, "phase": 0.0}},
                 (480, 120, 22, 217800, "#e08a3c", "North")],
     "cores": [(277, 499), (519, 424), (717, 269)]},
    {"name": 'The Gatekeeper', "sub": 'A path planet patrols the corridor up and down. Slip through when the gate is open.',
     "start": (70, 300), "target": (890, 300),
     "planets": [
        {'x': 480, 'y': 120, 'r': 24, 'mu': 259200, 'color': '#3a9ad9', 'label': 'Gatekeeper', 'path': {'pts': [[480, 120], [480, 480]], 'speed': 55.0, 'phase': 0.0}},
        (300, 130, 20, 180000, '#e08a3c', 'North'),
        (660, 470, 20, 180000, '#c65b7a', 'South'),
     ],
     "par": 2, "max_burns": 4,
     "cores": [(238, 284), (437, 249), (657, 258)]},
    {"name": 'Zigzag', "sub": 'One planet runs a zigzag route across the middle. Read its pattern, then thread past it.',
     "start": (60, 80), "target": (900, 520),
     "planets": [
        {'x': 250, 'y': 300, 'r': 20, 'mu': 180000, 'color': '#7a6fd0', 'label': 'Zigzag', 'path': {'pts': [[250, 300], [400, 180], [550, 420], [700, 260]], 'speed': 50.0, 'phase': 0.0}},
        (480, 90, 18, 145800, '#2ec4a6', 'Top'),
        (200, 480, 22, 217800, '#d96c4f', 'Low'),
     ],
     "par": 3, "max_burns": 5,
     "cores": [(253, 202), (459, 332), (673, 443)]},
    {"name": 'Cross Traffic', "sub": 'Westbound loops the upper field while Southbound runs down. Mind the crossing.',
     "start": (80, 520), "target": (880, 90),
     "planets": [
        {'x': 450, 'y': 200, 'r': 20, 'color': '#e08a3c', 'label': 'Westbound', 'orbit': {'cx': 300, 'cy': 200, 'radius': 150, 'speed': 0.3, 'phase': 0.0}},
        {'x': 620, 'y': 90, 'r': 20, 'mu': 180000, 'color': '#c65b7a', 'label': 'Southbound', 'path': {'pts': [[620, 90], [620, 510]], 'speed': 84.0, 'phase': 0.0}},
        (330, 420, 24, 259200, '#3a9ad9', 'Anchor'),
     ],
     "par": 3, "max_burns": 5,
     "cores": [(295, 472), (506, 369), (695, 245)]},
    {"name": 'The Long Patrol', "sub": 'A heavy hauler circles the hub while a fast scout sweeps the bottom. Two clocks to beat.',
     "start": (60, 300), "target": (905, 300),
     "planets": [
        {'x': 640, 'y': 300, 'r': 28, 'color': '#d96c4f', 'label': 'Hauler', 'orbit': {'cx': 480, 'cy': 300, 'radius': 160, 'speed': 0.2, 'phase': 0.0}},
        {'x': 150, 'y': 520, 'r': 14, 'mu': 88200, 'color': '#2ec4a6', 'label': 'Scout', 'path': {'pts': [[150, 520], [810, 520]], 'speed': 110.0, 'phase': 0.0}},
        (480, 300, 16, 115200, '#7a6fd0', 'Hub'),
     ],
     "par": 3, "max_burns": 5,
     "cores": [(250, 328), (448, 357), (670, 356)]},
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


def check_hit(x, y, planets, target, barriers=()):
    """'crash' | 'dock' | 'lost' | None - same rules as the web edition."""
    for (px, py, r, _mu, _c, _label) in planets:
        if (x - px) ** 2 + (y - py) ** 2 < (r + CRASH_PAD) ** 2:
            return "crash"
    if barriers and point_in_barriers(x, y, barriers):
        return "crash"
    tx, ty = target
    if (x - tx) ** 2 + (y - ty) ** 2 < DOCK_RADIUS ** 2:
        return "dock"
    if x < -LOST_MARGIN or x > WIDTH + LOST_MARGIN \
            or y < -LOST_MARGIN or y > HEIGHT + LOST_MARGIN:
        return "lost"
    return None


# ----------------------------------------------------------------------
# BARRIERS - solid polygonal walls a level can contain. The ship
# crashes if it flies into one. A barrier is just a list of points
# (a polygon); the editor builds them, and the barrier eraser cuts
# pieces out of them. The eraser works by clipping: a point is
# outside a convex clip polygon exactly when it is outside at least
# one of its edges, so subtracting a clip is the union of the
# subject clipped to the outside of each edge (Sutherland-Hodgman).
# That handles a corner bite, a full delete, and a hole punched in
# the middle (the "donut") with one algorithm, and the pieces may
# overlap - they are drawn and collided as a union, so overlaps are
# harmless. A concave eraser shape is triangulated first (triangles
# are convex), so it works too.
# ----------------------------------------------------------------------
BARRIER_FILL = "#6b2f2c"
BARRIER_MAX = 36          # polygons per level
BARRIER_MAX_PTS = 64      # points per polygon
BARRIER_MIN_AREA = 25.0   # px^2 - anything smaller is a sliver, drop it


def polygon_area(pts):
    """Signed area (shoelace); positive = counter-clockwise."""
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def clean_poly(pts):
    """Drop consecutive duplicate points (and a closing repeat of
    the first point)."""
    out = []
    for q in pts:
        if not out or (q[0] != out[-1][0] or q[1] != out[-1][1]):
            out.append([q[0], q[1]])
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def point_in_polygon(x, y, pts):
    """Even-odd ray cast."""
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def point_in_barriers(x, y, barriers):
    return any(point_in_polygon(x, y, pts) for pts in barriers)


def _ed_on_planet(ed, gx, gy):
    """True when the point sits inside a planet's crash radius
    (radius + CRASH_PAD, the same rule check_hit uses): the pad
    and the dock both refuse such a spot, or the ship would crash
    the instant it launched / could never dock there."""
    for p in ed["planets"]:
        if math.hypot(gx - p["x"], gy - p["y"]) < p["r"] + CRASH_PAD:
            return True
    return False


def _clip_halfplane(pts, ax, ay, bx, by):
    """Sutherland-Hodgman: keep the part of polygon `pts` on the
    RIGHT of the directed edge a -> b (the outside of a
    counter-clockwise clip polygon)."""
    if not pts:
        return []

    def cross(px, py):
        return (bx - ax) * (py - ay) - (by - ay) * (px - ax)

    out = []
    n = len(pts)
    for i in range(n):
        cx, cy = pts[i]
        px, py = pts[i - 1]
        cc = cross(cx, cy)
        pc = cross(px, py)
        if cc <= 0.0:
            if pc > 0.0:
                t = pc / (pc - cc)
                out.append([px + (cx - px) * t, py + (cy - py) * t])
            out.append([cx, cy])
        elif pc <= 0.0:
            t = pc / (pc - cc)
            out.append([px + (cx - px) * t, py + (cy - py) * t])
    return clean_poly(out)


def _round_poly(pts):
    return [[round(q[0], 1), round(q[1], 1)] for q in pts]


def _polys_intersect(a, b):
    """True if polygons a and b overlap (an edge crossing, or a
    vertex of one inside the other - which also covers one polygon
    sitting entirely inside the other)."""
    for i in range(len(a)):
        for j in range(len(b)):
            if _segments_cross(a[i], a[(i + 1) % len(a)],
                               b[j], b[(j + 1) % len(b)]):
                return True
    if point_in_polygon(a[0][0], a[0][1], b) or \
            point_in_polygon(b[0][0], b[0][1], a):
        return True
    return False


def subtract_polygon(subject, clip):
    """subject minus clip (both polygons), as a list of polygons.
    The clip must be convex; a concave clip is triangulated first
    by the caller. Pieces may overlap - they are a union."""
    sub = clean_poly(subject)
    clp = clean_poly(clip)
    if len(sub) < 3 or len(clp) < 3:
        return [sub] if len(sub) >= 3 else []
    if abs(polygon_area(sub)) < BARRIER_MIN_AREA:
        return []
    if abs(polygon_area(clp)) < BARRIER_MIN_AREA:
        return [sub]
    if polygon_area(clp) < 0:
        clp = list(reversed(clp))   # interior on the left of each edge
    if not _polys_intersect(sub, clp):
        return [sub]   # nowhere near the clip: leave it alone
    pieces = []
    seen = set()
    for i in range(len(clp)):
        ax, ay = clp[i]
        bx, by = clp[(i + 1) % len(clp)]
        piece = _clip_halfplane(sub, ax, ay, bx, by)
        if len(piece) >= 3 and abs(polygon_area(piece)) >= BARRIER_MIN_AREA:
            piece = _round_poly(piece)
            key = tuple((q[0], q[1]) for q in piece)
            if key not in seen:
                seen.add(key)
                pieces.append(piece)
    return pieces


def subtract_rect(poly, x0, y0, x1, y1):
    """poly minus an axis-aligned rectangle (x0, y0, x1, y1)."""
    return subtract_polygon(poly, [[x0, y0], [x1, y0], [x1, y1], [x0, y1]])


def triangulate(pts):
    """Ear clipping: a (possibly concave) polygon as a list of
    triangles. Returns [] if the polygon is degenerate."""
    poly = clean_poly(pts)
    if len(poly) < 3 or abs(polygon_area(poly)) < BARRIER_MIN_AREA:
        return []
    if polygon_area(poly) < 0:
        poly = list(reversed(poly))
    work = [list(q) for q in poly]
    tris = []
    guard = 0
    while len(work) > 3 and guard < 100:
        guard += 1
        n = len(work)
        cut = False
        for i in range(n):
            a, b, c = work[i - 1], work[i], work[(i + 1) % n]
            # convex corner? (left turn for a CCW polygon)
            if (b[0] - a[0]) * (c[1] - b[1]) - \
                    (b[1] - a[1]) * (c[0] - b[0]) <= 0:
                continue
            ear = True
            for q in work:
                if q is a or q is b or q is c:
                    continue
                if point_in_polygon(q[0], q[1], [a, b, c]):
                    ear = False
                    break
            if ear:
                tris.append([a, b, c])
                del work[i]
                cut = True
                break
        if not cut:
            break   # degenerate (self-intersecting?) - give up
    if len(work) == 3:
        tris.append(work)
    return tris


def _segments_cross(p1, p2, p3, p4):
    """True if segments p1-p2 and p3-p4 properly cross (not just
    touching at a shared endpoint)."""
    def cross(ax, ay, bx, by):
        return ax * by - ay * bx
    d1 = cross(p2[0] - p1[0], p2[1] - p1[1], p3[0] - p1[0], p3[1] - p1[1])
    d2 = cross(p2[0] - p1[0], p2[1] - p1[1], p4[0] - p1[0], p4[1] - p1[1])
    d3 = cross(p4[0] - p3[0], p4[1] - p3[1], p1[0] - p3[0], p1[1] - p3[1])
    d4 = cross(p4[0] - p3[0], p4[1] - p3[1], p2[0] - p3[0], p2[1] - p3[1])
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) \
        and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0


def polygon_is_simple(pts):
    """True if no two non-adjacent edges of the polygon cross
    (a bowtie is not a real shape)."""
    n = len(pts)
    for i in range(n):
        for j in range(i + 1, n):
            if i == j or (i + 1) % n == j or (j + 1) % n == i:
                continue
            if _segments_cross(pts[i], pts[(i + 1) % n],
                               pts[j], pts[(j + 1) % n]):
                return False
    return True


def erase_from_barriers(barriers, clip):
    """Subtract `clip` (a rectangle [x0, y0, x1, y1] or a polygon
    list of points) from every barrier polygon. Returns the new
    list of polygons."""
    if isinstance(clip, tuple) and len(clip) == 4 and \
            all(isinstance(v, (int, float)) for v in clip):
        clips = [[clip[0], clip[1]], [clip[2], clip[1]],
                 [clip[2], clip[3]], [clip[0], clip[3]]]
        clips = [clips]
    else:
        clp = clean_poly(clip)
        if len(clp) < 3 or abs(polygon_area(clp)) < BARRIER_MIN_AREA:
            return barriers
        if _polygon_is_convex(clp):
            clips = [clp]
        else:
            clips = triangulate(clp) or [clp]
    out = []
    for poly in barriers:
        pieces = [poly]
        for clp in clips:
            nxt = []
            for piece in pieces:
                nxt.extend(subtract_polygon(piece, clp))
            pieces = nxt
            if not pieces:
                break
        out.extend(pieces)
    return out[:BARRIER_MAX * 4]


def _polygon_is_convex(pts):
    """True if every turn of the polygon goes the same way."""
    n = len(pts)
    sign = 0
    for i in range(n):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        cx, cy = pts[(i + 1) % n]
        cr = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if cr != 0:
            s = 1 if cr > 0 else -1
            if sign == 0:
                sign = s
            elif sign != s:
                return False
    return True


def level_barriers(lv):
    """Normalize a level dict's barriers to a list of polygons
    (each a list of [x, y] points, clamped to the field). A barrier
    covering the pad or the dock is dropped - the level would be
    unplayable."""
    out = []
    start = lv.get("start")
    target = lv.get("target")
    for b in lv.get("barriers", [])[:BARRIER_MAX]:
        if not isinstance(b, (list, tuple)):
            continue
        pts = [[max(0.0, min(WIDTH, float(q[0]))),
                max(0.0, min(HEIGHT, float(q[1])))]
               for q in b[:BARRIER_MAX_PTS]
               if isinstance(q, (list, tuple)) and len(q) == 2]
        pts = clean_poly(pts)
        if len(pts) < 3 or abs(polygon_area(pts)) < BARRIER_MIN_AREA:
            continue
        if start is not None and point_in_polygon(start[0], start[1], pts):
            continue
        if target is not None and point_in_polygon(target[0], target[1], pts):
            continue
        out.append(pts)
    return out


def path_position(pts, speed, phase, t, loop=False):
    """Position along a polyline path at time t. Normally the planet
    ping-pongs along the points at `speed` px/s; `phase` (0..1) is
    where it starts in the cycle. With `loop` the route closes (the
    last point connects back to the first) and the planet rides it
    in a circle, like an orbit. Pure function of t, like orbits."""
    if len(pts) < 2:
        return float(pts[0][0]), float(pts[0][1])
    route = list(pts) + [pts[0]] if loop else list(pts)
    segs = []
    total = 0.0
    for i in range(len(route) - 1):
        d = math.hypot(route[i + 1][0] - route[i][0],
                       route[i + 1][1] - route[i][1])
        segs.append(d)
        total += d
    if total <= 0:
        return float(pts[0][0]), float(pts[0][1])
    if loop:
        s = (phase * total + speed * t) % total
    else:
        cycle = 2.0 * total
        s = (phase * cycle + speed * t) % cycle
        if s > total:
            s = cycle - s
    for i, d in enumerate(segs):
        if s <= d or i == len(segs) - 1:
            f = 0.0 if d == 0 else s / d
            return (route[i][0] + (route[i + 1][0] - route[i][0]) * f,
                    route[i][1] + (route[i + 1][1] - route[i][1]) * f)
        s -= d
    return float(pts[-1][0]), float(pts[-1][1])


def planet_snapshot(specs, t):
    """Planet tuples (x, y, r, mu, color, label) at mission time t.
    Specs are dicts; a spec with an 'orbit' moves on its circle, a
    spec with a 'path' patrols its polyline (path wins if both)."""
    out = []
    for sp in specs:
        if sp.get("path"):
            px, py = path_position(sp["path"]["pts"],
                                   sp["path"].get("speed", 60.0),
                                   sp["path"].get("phase", 0.0), t,
                                   loop=bool(sp["path"].get("loop")))
        elif sp.get("orbit"):
            orb = sp["orbit"]
            ang = orb["phase"] + orb["speed"] * t
            px = orb["cx"] + math.cos(ang) * orb["radius"]
            py = orb["cy"] + math.sin(ang) * orb["radius"]
        else:
            px, py = sp["x"], sp["y"]
        r = sp["r"]
        mu = GRAV_K * r * r
        if sp.get("repel"):
            mu = -mu   # repulsor: same strength, pushes instead of pulls
        out.append((px, py, r, mu, sp["color"], sp["label"]))
    return out


def wormhole_step(x, y, wormholes, skip=-1):
    """If (x, y) is inside a wormhole mouth, return the other end.
    skip is a pair index to ignore: the cooldown only blocks
    re-entering the pair just warped through (without it, a ship
    standing in the exit mouth would warp straight back). A
    different pair is never blocked, so two pairs side by side
    both work. Returns (x, y, warped, pair)."""
    for k, (ax, ay, bx, by) in enumerate(wormholes):
        if k == skip:
            continue
        if (x - ax) ** 2 + (y - ay) ** 2 < WORMHOLE_RADIUS ** 2:
            return bx, by, True, k
        if (x - bx) ** 2 + (y - by) ** 2 < WORMHOLE_RADIUS ** 2:
            return ax, ay, True, k
    return x, y, False, -1


def predict_path(x, y, vx, vy, specs, target, t0=0.0, wormholes=(),
                 wh_cd=0.0, wh_pair=-1, steps=600, dt=1.0 / 60.0,
                 barriers=()):
    """Simulate ahead; returns (points, outcome). Planet positions and
    wormholes are simulated too, so the preview stays honest on the
    moving levels."""
    points = [(x, y)]
    cd = wh_cd
    last_pair = wh_pair
    for i in range(steps):
        t = t0 + (i + 1) * dt
        planets = planet_snapshot(specs, t)
        x, y, vx, vy = step_physics(x, y, vx, vy, planets, dt)
        cd = max(0.0, cd - dt)
        if wormholes:
            x, y, warped, k = wormhole_step(
                x, y, wormholes, skip=last_pair if cd > 0.0 else -1)
            if warped:
                cd = WORMHOLE_COOLDOWN
                last_pair = k
                points.append(None)      # trail break at the jump
        if i % 3 == 0:
            points.append((x, y))
        outcome = check_hit(x, y, planets, target, barriers)
        if outcome:
            points.append((x, y))
            return points, outcome
    return points, "flying"


def level_specs(lv):
    """Normalize a level dict's planets (tuples or dicts) to spec dicts."""
    specs = []
    for p in lv["planets"]:
        if isinstance(p, dict):
            sp = {"x": p["x"], "y": p["y"], "r": p["r"],
                  "color": p["color"], "label": p["label"]}
            if p.get("orbit"):
                sp["orbit"] = dict(p["orbit"])
            if p.get("path"):
                sp["path"] = {"pts": [list(q) for q in p["path"]["pts"]],
                              "speed": p["path"].get("speed", 60.0),
                              "phase": p["path"].get("phase", 0.0),
                              "loop": p["path"].get("loop") is True}
            if p.get("repel"):
                sp["repel"] = True
        else:
            px, py, r, _mu, color, label = p
            sp = {"x": px, "y": py, "r": r, "color": color, "label": label}
        specs.append(sp)
    return specs


def level_wormholes(lv):
    return [tuple(w) for w in lv.get("wormholes", [])]


# ----------------------------------------------------------------------
# LEVEL SHARING - a level becomes a short text code (compressed JSON,
# base64) that players can send to each other. Paste a code and the
# level is saved with your custom levels. Imported codes are fully
# validated and clamped, so a bad or hostile code can't break the game.
# ----------------------------------------------------------------------
LEVEL_CODE_PREFIX = "ORBITAL1:"


def level_to_code(lv):
    payload = {"name": str(lv["name"]), "sub": str(lv.get("sub", "")),
               "start": [lv["start"][0], lv["start"][1]],
               "target": [lv["target"][0], lv["target"][1]],
               "par": int(lv["par"]), "max_burns": int(lv["max_burns"]),
               "planets": [{"x": p["x"], "y": p["y"], "r": p["r"],
                            "color": p.get("color", "#3fa7ff"),
                            "label": p.get("label", ""),
                            **({"orbit": p["orbit"]} if "orbit" in p else {}),
                            **({"path": p["path"]} if "path" in p else {}),
                            **({"repel": True} if p.get("repel") else {})}
                           for p in level_specs(lv)],
               "cores": [[c[0], c[1]] for c in lv["cores"]],
               "wormholes": [list(w) for w in level_wormholes(lv)],
               "barriers": [[[q[0], q[1]] for q in poly]
                            for poly in level_barriers(lv)]}
    raw = json.dumps(payload, separators=(",", ":"),
                     sort_keys=True).encode("utf-8")
    return LEVEL_CODE_PREFIX + base64.urlsafe_b64encode(
        zlib.compress(raw, 9)).decode("ascii")


def _code_num(value, lo, hi, what):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} is not a number")
    if not math.isfinite(v):
        raise ValueError(f"{what} is not a finite number")
    return max(lo, min(hi, v))


def _code_point(value, what):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{what} is malformed")
    return (_code_num(value[0], 0, WIDTH, what + " x"),
            _code_num(value[1], 0, HEIGHT, what + " y"))


def code_to_level(code):
    """Decode and validate a share code. Returns a level dict in the
    same shape the editor saves, or raises ValueError."""
    s = "".join(str(code).split())
    if len(s) > 20000:
        raise ValueError("that code is far too long")
    if not s.startswith(LEVEL_CODE_PREFIX):
        raise ValueError("that doesn't look like an Orbital level code "
                         "(it should start with " + LEVEL_CODE_PREFIX + ")")
    body = s[len(LEVEL_CODE_PREFIX):]
    body += "=" * (-len(body) % 4)
    try:
        raw = zlib.decompress(base64.urlsafe_b64decode(body.encode("ascii")))
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise ValueError("the code is corrupted or incomplete")
    if not isinstance(data, dict):
        raise ValueError("the code doesn't contain a level")
    for field in ("planets", "cores", "wormholes", "barriers"):
        if field in data and not isinstance(data[field], list):
            raise ValueError(f"the code's {field} are malformed")

    name = str(data.get("name", "Shared mission"))[:60].strip() \
        or "Shared mission"
    sub = str(data.get("sub", ""))[:120]
    start = _code_point(data.get("start"), "start")
    target = _code_point(data.get("target"), "target")
    par = int(_code_num(data.get("par", 2), 1, 20, "par"))
    burns = int(_code_num(data.get("max_burns", 4), 2, 20, "max burns"))
    burns = max(par, burns)

    planets = []
    for i, p in enumerate(data.get("planets", [])[:24]):
        if not isinstance(p, dict):
            raise ValueError("a planet in the code is malformed")
        color = str(p.get("color", ""))
        if not (len(color) == 7 and color.startswith("#") and
                all(ch in "0123456789abcdefABCDEF" for ch in color[1:])):
            color = PLANET_COLORS[i % len(PLANET_COLORS)]
        planet = {"x": _code_num(p.get("x"), 0, WIDTH, "planet x"),
                  "y": _code_num(p.get("y"), 0, HEIGHT, "planet y"),
                  "r": _code_num(p.get("r"), 12, 70, "planet radius"),
                  "color": color,
                  "label": str(p.get("label", ""))[:24]}
        if p.get("repel") is True:
            planet["repel"] = True
        orb = p.get("orbit")
        if isinstance(orb, dict):
            planet["orbit"] = {
                "cx": _code_num(orb.get("cx"), 0, WIDTH, "orbit cx"),
                "cy": _code_num(orb.get("cy"), 0, HEIGHT, "orbit cy"),
                "radius": _code_num(orb.get("radius"), 0, 400,
                                    "orbit radius"),
                "speed": _code_num(orb.get("speed"), -2, 2, "orbit speed"),
                "phase": _code_num(orb.get("phase"), -7, 7, "orbit phase")}
        pth = p.get("path")
        if isinstance(pth, dict) and isinstance(pth.get("pts"), list) \
                and 2 <= len(pth["pts"]) <= 20:
            planet["path"] = {
                "pts": [[_code_num(q[0], 0, WIDTH, "path x"),
                         _code_num(q[1], 0, HEIGHT, "path y")]
                        for q in pth["pts"]
                        if isinstance(q, (list, tuple)) and len(q) == 2],
                "speed": _code_num(pth.get("speed", 60), 5, 300,
                                   "path speed"),
                "phase": _code_num(pth.get("phase", 0), 0, 1, "path phase")}
            if pth.get("loop") is True:
                planet["path"]["loop"] = True
            if len(planet["path"]["pts"]) < 2:
                del planet["path"]
        planets.append(planet)

    cores = [_code_point(c, "core") for c in data.get("cores", [])[:24]]

    wormholes = []
    for w in data.get("wormholes", [])[:8]:
        if not isinstance(w, (list, tuple)) or len(w) != 4:
            raise ValueError("a wormhole in the code is malformed")
        wormholes.append((_code_num(w[0], 0, WIDTH, "wormhole x"),
                          _code_num(w[1], 0, HEIGHT, "wormhole y"),
                          _code_num(w[2], 0, WIDTH, "wormhole x"),
                          _code_num(w[3], 0, HEIGHT, "wormhole y")))

    raw_barriers = []
    for b in data.get("barriers", [])[:BARRIER_MAX]:
        if not isinstance(b, (list, tuple)):
            raise ValueError("a barrier in the code is malformed")
        pts = [[_code_num(q[0], 0, WIDTH, "barrier x"),
                _code_num(q[1], 0, HEIGHT, "barrier y")]
               for q in b[:BARRIER_MAX_PTS]
               if isinstance(q, (list, tuple)) and len(q) == 2]
        raw_barriers.append(pts)
    barriers = level_barriers({"barriers": raw_barriers,
                               "start": start, "target": target})

    return {"name": name, "sub": sub, "start": start, "target": target,
            "par": par, "max_burns": burns, "planets": planets,
            "cores": cores, "wormholes": wormholes, "barriers": barriers}


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

    def warp(self):
        self.play([(1200, 70), (600, 70), (300, 110)])

    def flyby(self):
        self.play([(660, 60)])

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
        root.configure(bg="#0b1020")   # gaps (if any) match the UI, never white
        root.resizable(False, False)  # fixed layout: resizing must not move anything
        # 1 point = 1 pixel for every font, whatever the display DPI:
        # the layout is designed in pixels and the 1x/1.25x/1.5x buttons
        # are the one and only scaling mechanism.
        root.tk.call("tk", "scaling", 1.0)
        self.beeper = Beeper()
        self.save = self.load_save()
        settings = self.save["settings"]
        self.S = float(settings["scale"])
        self.T = float(settings["text_scale"])
        # Every widget without an explicit font (all the buttons, the
        # pager arrows, spinboxes, the name entry) uses TkDefaultFont -
        # size it from the window scale too, so at 1.5x ALL the text
        # grows, not just the headings.
        tkfont.nametofont("TkDefaultFont").configure(size=self.BS(10))
        self.mode = "play"           # play | editor
        self.editor = None
        self.session_levels = []     # generated missions (not persisted)
        self._playtest_pos = None    # slot in session_levels of the
        # current playtest level (None: no playtest yet this edit)

        self.hud1 = tk.Label(root, font=("Consolas", self.FS(13), "bold"),
                             anchor="w", bg="#0b1020", fg=COLORS["text"])
        self.hud1.pack(fill="x")
        self.hud2 = tk.Label(root, font=("Consolas", self.FS(11)), anchor="w",
                             bg="#0b1020", fg=COLORS["dim"])
        self.hud2.pack(fill="x")
        self.canvas = tk.Canvas(root, width=int(WIDTH * self.S),
                                height=int(HEIGHT * self.S),
                                bg=COLORS["bg"], highlightthickness=0)
        self.canvas.pack()
        # wraplength caps this long one-line readout: at big text sizes
        # it wraps to a second line instead of widening the window
        # (same trick as the editor hint below).
        self.stats = tk.Label(root, font=("Consolas", self.FS(11)), anchor="w",
                              bg="#0b1020", fg=COLORS["text"],
                              wraplength=int(950 * self.S))
        self.stats.pack(fill="x")

        # sliders + toggles row (as in the web edition)
        row = tk.Frame(root, bg="#0b1020")
        row.pack(fill="x")
        tk.Label(row, text="Angle", bg="#0b1020", fg=COLORS["dim"],
                 font=("Consolas", self.FS(10))).pack(side="left", padx=(8, 2))
        self.angle_var = tk.DoubleVar(value=0)
        self.angle_scale = tk.Scale(
            row, from_=-180, to=180, orient="horizontal",
            length=int(210 * self.S),
            variable=self.angle_var, command=self._slider_moved,
            bg="#0b1020", fg=COLORS["text"], highlightthickness=0,
            troughcolor="#16213c", takefocus=0, showvalue=False)
        self.angle_scale.pack(side="left")
        self.angle_out = tk.Label(row, width=5, bg="#0b1020",
                                  fg=COLORS["text"],
                                  font=("Consolas", self.FS(10)))
        self.angle_out.pack(side="left")
        tk.Label(row, text="Power", bg="#0b1020", fg=COLORS["dim"],
                 font=("Consolas", self.FS(10))).pack(side="left", padx=(10, 2))
        self.power_var = tk.DoubleVar(value=150)
        self.power_scale = tk.Scale(
            row, from_=POWER_MIN, to=POWER_MAX, orient="horizontal",
            length=int(210 * self.S),
            variable=self.power_var, command=self._slider_moved,
            bg="#0b1020", fg=COLORS["text"], highlightthickness=0,
            troughcolor="#16213c", takefocus=0, showvalue=False)
        self.power_scale.pack(side="left")
        self.power_out = tk.Label(row, width=4, bg="#0b1020",
                                  fg=COLORS["text"],
                                  font=("Consolas", self.FS(10)))
        self.power_out.pack(side="left")
        self.preview_var = tk.BooleanVar(value=bool(settings["preview"]))
        tk.Checkbutton(row, text="Preview", variable=self.preview_var,
                       bg="#0b1020", fg=COLORS["text"], takefocus=0,
                       selectcolor="#16213c", activebackground="#0b1020",
                       activeforeground=COLORS["text"],
                       font=("Consolas", self.BS(10)),
                       command=self._preview_toggled).pack(side="left",
                                                           padx=(12, 0))
        self.sound_var = tk.BooleanVar(value=bool(settings["sound"]))
        tk.Checkbutton(row, text="Sound", variable=self.sound_var,
                       bg="#0b1020", fg=COLORS["text"], takefocus=0,
                       selectcolor="#16213c", activebackground="#0b1020",
                       activeforeground=COLORS["text"],
                       font=("Consolas", self.BS(10)),
                       command=self._sound_toggled).pack(side="left")
        self.beeper.enabled = self.sound_var.get()
        self.pause_btn = tk.Button(row, text="Pause (H)", command=self.toggle_pause,
                                   bg="#16213c", fg=COLORS["text"], takefocus=0,
                                   activebackground="#22335c", relief="flat",
                                   padx=10, pady=2)
        self.pause_btn.pack(side="right", padx=8)

        # buttons + level pager
        bar = tk.Frame(root, bg="#0b1020")
        bar.pack(fill="x")
        self.bar_btns = {}
        for text, cmd in (("Launch (Space)", self.space_action),
                          ("Reset (R)", self.reset),
                          ("Undo (U)", self.undo),
                          ("Random", self.new_random_level),
                          ("Editor", self.enter_editor),
                          ("Share level", self.share_level),
                          ("Paste level", self.paste_level_dialog),
                          ("Delete level", self.delete_saved_level),
                          ("My levels", self.my_levels_dialog),
                          ("Clear ghost", self.clear_ghost)):
            btn = tk.Button(bar, text=text, command=cmd, bg="#16213c",
                            fg=COLORS["text"], activebackground="#22335c",
                            relief="flat", padx=10, pady=4, takefocus=0)
            btn.pack(side="left", padx=4, pady=4)
            self.bar_btns[text] = btn
        # Generate ghosts: when off, wins record no ghost and no saved
        # ghost is drawn. Saved ghosts are kept, so turning it back on
        # brings them back.
        self.ghosts_var = tk.BooleanVar(value=bool(settings["ghosts"]))
        tk.Checkbutton(bar, text="Ghosts", variable=self.ghosts_var,
                       bg="#0b1020", fg=COLORS["text"], takefocus=0,
                       selectcolor="#16213c", activebackground="#0b1020",
                       activeforeground=COLORS["text"],
                       font=("Consolas", self.BS(10)),
                       command=self._ghosts_toggled).pack(side="left",
                                                          padx=(6, 0), pady=4)
        # Window and text scales live in their own row, kept separate:
        # Window resizes the whole fixed layout, Text only grows the
        # fonts. The active choice in each group is highlighted.
        srow = tk.Frame(root, bg="#0b1020")
        srow.pack(fill="x")
        tk.Label(srow, text="Window:", bg="#0b1020", fg=COLORS["dim"],
                 font=("Consolas", self.FS(10))).pack(side="left", padx=(8, 2))
        self.scale_btns = {}
        for s in SCALES:
            btn = tk.Button(srow, text=("%g×" % s),
                            command=lambda v=s: self.apply_scale(v),
                            bg="#16213c", fg=COLORS["text"], takefocus=0,
                            activebackground="#22335c", relief="flat",
                            padx=6, pady=2)
            btn.pack(side="left", padx=2)
            self.scale_btns[s] = btn
        tk.Label(srow, text="Text:", bg="#0b1020", fg=COLORS["dim"],
                 font=("Consolas", self.FS(10))).pack(side="left",
                                                     padx=(24, 2))
        self.text_btns = {}
        for t in TEXT_SCALES:
            btn = tk.Button(srow, text=("%g×" % t),
                            command=lambda v=t: self.apply_text_scale(v),
                            bg="#16213c", fg=COLORS["text"], takefocus=0,
                            activebackground="#22335c", relief="flat",
                            padx=6, pady=2)
            btn.pack(side="left", padx=2)
            self.text_btns[t] = btn
        self._sync_scale_buttons()
        # extra toggles, in their own row: orbit paths and the grid draw
        # on the field, labels hide the planet name tags, effects is
        # particles + starfield twinkle, auto-advance jumps to the next
        # mission after a win, pause-on-unfocus auto-pauses a flight
        # when the window loses focus.
        orow = tk.Frame(root, bg="#0b1020")
        orow.pack(fill="x")
        self._opt_vars = {}
        for text, key in (("Orbit paths", "orbit_paths"),
                          ("Labels", "labels"),
                          ("Effects", "effects"),
                          ("Auto-advance", "auto_advance"),
                          ("Pause on unfocus", "pause_on_unfocus"),
                          ("Grid", "grid")):
            var = tk.BooleanVar(value=bool(settings[key]))
            self._opt_vars[key] = var
            tk.Checkbutton(orow, text=text, variable=var, bg="#0b1020",
                           fg=COLORS["text"], takefocus=0,
                           selectcolor="#16213c", activebackground="#0b1020",
                           activeforeground=COLORS["text"],
                           font=("Consolas", self.BS(10)),
                           command=lambda k=key: self._opt_toggled(k)
                           ).pack(side="left", padx=(8, 2))
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
                                    font=("Consolas", self.FS(11), "bold"))
        self.pager_label.pack(side="left", padx=4)
        self.pager_next = tk.Button(pf, text=">", width=4, takefocus=0,
                                    command=lambda: self.goto(self.level_i + 1),
                                    bg="#16213c", fg=COLORS["text"],
                                    activebackground="#22335c", relief="flat",
                                    pady=4)
        self.pager_next.pack(side="left", padx=4, pady=4)

        # Editor bar is control chrome like the button bar, so its
        # fonts use BS() (window scale only) - FS() text here would
        # push the bar wider than the field at big text sizes.
        self.ed_bar = tk.Frame(root, bg="#0b1020")
        self.ed_tool = tk.StringVar(value="planet")
        self.ed_tool.trace_add("write", self._ed_tool_changed)
        for text, tool in (("Planet", "planet"), ("Start", "start"),
                           ("Dock", "target"), ("Core", "core"),
                           ("Wormhole", "wormhole"), ("Orbit", "orbit"),
                           ("Path", "path"), ("Barrier", "barrier"),
                           ("Del Bar", "delbarrier"),
                           ("Erase", "erase")):
            tk.Radiobutton(self.ed_bar, text=text, value=tool,
                           variable=self.ed_tool, bg="#0b1020",
                           fg=COLORS["text"], takefocus=0,
                           selectcolor="#22335c", activebackground="#0b1020",
                           activeforeground=COLORS["text"],
                           font=("Consolas", self.BS(10)),
                           indicatoron=False, padx=2, pady=3).pack(side="left", padx=1)
        tk.Label(self.ed_bar, text="Name", bg="#0b1020", fg=COLORS["dim"],
                 font=("Consolas", self.BS(10))).pack(side="left", padx=(4, 2))
        self.ed_name = tk.Entry(self.ed_bar, width=8, bg="#16213c",
                                fg=COLORS["text"], insertbackground="#dbe7ff",
                                relief="flat", font=("Consolas", self.BS(10)))
        self.ed_name.pack(side="left")
        tk.Label(self.ed_bar, text="Par", bg="#0b1020", fg=COLORS["dim"],
                 font=("Consolas", self.BS(10))).pack(side="left", padx=(2, 2))
        self.ed_par = tk.Spinbox(self.ed_bar, from_=1, to=20, width=3,
                                 bg="#16213c", fg=COLORS["text"],
                                 relief="flat", font=("Consolas", self.BS(10)))
        self.ed_par.pack(side="left")
        tk.Label(self.ed_bar, text="Burns", bg="#0b1020", fg=COLORS["dim"],
                 font=("Consolas", self.BS(10))).pack(side="left", padx=(2, 2))
        self.ed_burns = tk.Spinbox(self.ed_bar, from_=2, to=20, width=3,
                                   bg="#16213c", fg=COLORS["text"],
                                   relief="flat", font=("Consolas", self.BS(10)))
        self.ed_burns.pack(side="left")
        for text, cmd in (("Playtest", self.editor_playtest),
                          ("Save level", self.editor_save),
                          ("Clear", self.editor_clear),
                          ("Rename", self.rename_planet),
                          ("Exit editor", self.exit_editor)):
            btn = tk.Button(self.ed_bar, text=text, command=cmd,
                            bg="#16213c", fg=COLORS["text"],
                            activebackground="#22335c", relief="flat",
                            padx=5, pady=3, takefocus=0)
            btn.pack(side="left", padx=2)
            if text == "Rename":
                self.ed_rename_btn = btn
        self.ed_hint = tk.Label(root, bg="#0b1020", fg=COLORS["dim"],
                                anchor="w", font=("Consolas", self.FS(10)),
                                justify="left",
                                wraplength=int(950 * self.S))
        self.ed_sub_row = tk.Frame(root, bg="#0b1020")
        tk.Label(self.ed_sub_row, text="Description:", bg="#0b1020",
                 fg=COLORS["dim"],
                 font=("Consolas", self.BS(10))).pack(side="left",
                                                      padx=(2, 4))
        self.ed_sub = tk.Entry(self.ed_sub_row, bg="#16213c",
                               fg=COLORS["text"],
                               insertbackground="#dbe7ff", relief="flat",
                               font=("Consolas", self.BS(10)))
        self.ed_sub.pack(side="left", fill="x", expand=True, padx=(0, 4))

        # result overlay (hidden until a run ends)
        self.overlay = tk.Frame(root, bg="#101a30", bd=2, relief="ridge")
        self.ov_kicker = tk.Label(self.overlay, bg="#101a30",
                                  fg=COLORS["dim"],
                                  font=("Consolas", self.FS(10)))
        self.ov_kicker.pack(padx=18, pady=(12, 0))
        self.ov_title = tk.Label(self.overlay, bg="#101a30",
                                 fg=COLORS["text"],
                                 font=("Consolas", self.FS(17), "bold"))
        self.ov_title.pack(padx=18)
        self.ov_stars = tk.Label(self.overlay, bg="#101a30",
                                 fg=COLORS["station"],
                                 font=("Consolas", self.FS(15)))
        self.ov_stars.pack(padx=18)
        self.ov_text = tk.Label(self.overlay, bg="#101a30", fg=COLORS["text"],
                                font=("Consolas", self.FS(10)),
                                wraplength=int(380 * self.S),
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
        self.canvas.bind("<Double-Button-1>", self.on_double_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        root.bind("<ButtonRelease-1>", self.on_release_anywhere)
        self._key("<space>", self.space_action)
        self._key("<KeyPress-r>", self.reset)
        self._key("<KeyPress-R>", self.reset)
        self._key("<KeyPress-u>", self.undo)
        self._key("<KeyPress-U>", self.undo)
        self._key("<KeyPress-n>", lambda: self.goto(self.level_i + 1))
        self._key("<KeyPress-N>", lambda: self.goto(self.level_i + 1))
        self._key("<KeyPress-p>", lambda: self.goto(self.level_i - 1))
        self._key("<KeyPress-P>", lambda: self.goto(self.level_i - 1))
        self._key("<KeyPress-h>", self.toggle_pause)
        self._key("<KeyPress-H>", self.toggle_pause)
        self._key("<Left>", lambda: self.nudge_aim(-2, 0))
        self._key("<Right>", lambda: self.nudge_aim(2, 0))
        self._key("<Up>", lambda: self.nudge_aim(0, 4))
        self._key("<Down>", lambda: self.nudge_aim(0, -4))
        root.bind("<MouseWheel>", self._on_wheel_guarded)
        root.bind("<KeyRelease-Shift_L>", self._on_shift_release)
        root.bind("<KeyRelease-Shift_R>", self._on_shift_release)
        root.bind("<FocusOut>", self._on_focus_out)
        root.focus_set()

        self.level_i = 0
        self._syncing = False
        self._tick_count = 0
        self.load_level(0)
        self._fit_window()
        if not getattr(root, "_orbital_tick", False):
            root._orbital_tick = True
            self.tick()

    # ---------------- scale helpers ----------------
    def FS(self, pts):
        """Game-text size: window scale times text scale. Control
        chrome (buttons, checkboxes) uses BS() instead, so the fixed
        layout never widens when the text grows."""
        return max(8, int(round(pts * self.S * self.T)))

    def BS(self, pts):
        """Button/chrome text size: window scale only. The button bar
        already fills the window at 1x, so letting its text grow with
        the text scale would push the window wider."""
        return max(8, int(round(pts * self.S)))

    def X(self, v):
        return v * self.S

    def PTS(self, flat):
        s = self.S
        return [v * s for v in flat]

    def _fit_window(self):
        """Size the window to exactly hug its contents. Without this,
        a rebuilt UI (scale change) can keep the old window size and
        clip or pad the rows."""
        self.root.update_idletasks()
        self.root.geometry("%dx%d" % (self.root.winfo_reqwidth(),
                                      self.root.winfo_reqheight()))

    def _sync_scale_buttons(self):
        """Highlight the active choice in each scale group."""
        for s, btn in getattr(self, "scale_btns", {}).items():
            btn.config(bg="#2a4a7a" if s == self.S else "#16213c")
        for t, btn in getattr(self, "text_btns", {}).items():
            btn.config(bg="#2a4a7a" if t == self.T else "#16213c")

    def _rebuild_ui(self):
        """Rebuild the whole layout at the current scales (window
        stays locked; nothing shifts mid-game). Keeps the open level
        and any editor work in progress."""
        keep = self.level_i
        ed_keep = None
        if self.mode == "editor" and self.editor is not None:
            ed_keep = (self.editor, self.ed_name.get(), self.ed_par.get(),
                       self.ed_burns.get(), self.ed_tool.get(),
                       self.ed_sub.get())
        for w in self.root.winfo_children():
            w.destroy()
        self.__init__(self.root)
        total = len(self.all_levels())
        self.load_level(min(keep, total - 1))
        if ed_keep is not None:
            # Back into the editor with the work in progress intact -
            # a scale change must never silently throw it away.
            self.editor = ed_keep[0]
            self.enter_editor()
            self.ed_name.delete(0, "end")
            self.ed_name.insert(0, ed_keep[1])
            self.ed_par.delete(0, "end")
            self.ed_par.insert(0, ed_keep[2])
            self.ed_burns.delete(0, "end")
            self.ed_burns.insert(0, ed_keep[3])
            self.ed_tool.set(ed_keep[4])
            self.ed_sub.delete(0, "end")
            self.ed_sub.insert(0, ed_keep[5])
        self._fit_window()

    def apply_scale(self, scale):
        """Change the window scale: the layout is rebuilt at the new
        fixed size."""
        if scale == self.S or scale not in SCALES:
            return
        self.save["settings"]["scale"] = scale
        self.store_save()
        self._rebuild_ui()

    def apply_text_scale(self, text_scale):
        """Change the text scale: game text grows (HUD, mission text,
        canvas labels), the field and the window stay the same size.
        Buttons and checkboxes keep window-scale sizing (BS()) so the
        fixed layout never widens. Same rebuild as a window-scale
        change, since every font size comes from FS()/BS()."""
        if text_scale == self.T or text_scale not in TEXT_SCALES:
            return
        self.save["settings"]["text_scale"] = text_scale
        self.store_save()
        self._rebuild_ui()

    # ---------------- save / progress ----------------
    def load_save(self):
        fresh = {"unlocked": 0, "stars": {}, "cores": {}, "flybys": {},
                 "ghost": {}, "custom": [], "recent_codes": [],
                 "settings": {"sound": True, "preview": True,
                              "ghosts": True, "scale": 1.0,
                              "text_scale": 1.0, "orbit_paths": True,
                              "labels": True, "effects": True,
                              "auto_advance": False,
                              "pause_on_unfocus": True, "grid": False},
                 "v": 4}
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return fresh
        if not isinstance(data, dict):
            return fresh
        try:
            if data.get("v") not in (2, 3, 4):
                data["stars"] = {}   # missions changed in v2; unlocks only
            out = dict(fresh)
            out["unlocked"] = max(0, min(int(data.get("unlocked", 0)),
                                         len(LEVELS) - 1))
            out["stars"] = dict(data.get("stars", {}))
            if data.get("v") in (3, 4):
                out["cores"] = dict(data.get("cores", {}))
            if data.get("v") == 4:
                out["flybys"] = dict(data.get("flybys", {}))
                # Ghost entries are drawn from directly, so keep only
                # well-formed ones: a dict whose segments are lists of
                # [x, y] number pairs. Old saves stored one flat "pts"
                # list; those migrate to a single segment. Anything else
                # is dropped, not crashed on.
                ghosts = {}
                for key, gh in data.get("ghost", {}).items():
                    if not isinstance(gh, dict):
                        continue
                    segs = gh.get("segs")
                    if not isinstance(segs, list):
                        pts = gh.get("pts")
                        segs = [pts] if isinstance(pts, list) else None
                    if not segs:
                        continue
                    clean_segs = []
                    for seg in segs:
                        if not isinstance(seg, list) or len(seg) < 2:
                            continue
                        clean = []
                        bad = False
                        for q in seg:
                            if not isinstance(q, (list, tuple)) \
                                    or len(q) != 2 \
                                    or not all(isinstance(v, (int, float))
                                               for v in q):
                                bad = True
                                break
                            clean.append([q[0], q[1]])
                        if not bad:
                            clean_segs.append(clean)
                    if not clean_segs:
                        continue
                    try:
                        ghosts[str(key)] = {
                            "segs": clean_segs,
                            "burns": int(gh.get("burns", 99)),
                            "stars": int(gh.get("stars", 0))}
                    except Exception:
                        continue
                out["ghost"] = ghosts
                custom = []
                for lv in data.get("custom", []):
                    if isinstance(lv, dict) and "start" in lv \
                            and "target" in lv \
                            and isinstance(lv.get("planets"), list) \
                            and isinstance(lv.get("cores"), list):
                        custom.append(lv)
                out["custom"] = custom
                # Recently pasted / imported level codes, newest first.
                out["recent_codes"] = [
                    str(c) for c in data.get("recent_codes", [])
                    if isinstance(c, str) and c.startswith(LEVEL_CODE_PREFIX)
                ][:8]
                # Records keyed past the last persistent level are
                # leftovers from session levels (Random / playtest):
                # they share the index space but vanish when the game
                # closes, so a later custom level at that index would
                # inherit a Random run's stars, cores or ghost. Drop
                # them, and clamp surviving core bests to what the
                # level actually has, so "5/0 cores" can never show.
                last = len(LEVELS) + len(out["custom"])
                levels = LEVELS + out["custom"]
                for field in ("stars", "cores", "flybys", "ghost"):
                    kept = {}
                    for k, v in out[field].items():
                        try:
                            ki = int(k)
                        except (TypeError, ValueError):
                            continue
                        if 0 <= ki < last:
                            kept[k] = v
                    out[field] = kept
                for k, v in list(out["cores"].items()):
                    try:
                        total = len(levels[int(k)].get("cores", []))
                        if int(v) > total:
                            out["cores"][k] = total
                    except (TypeError, ValueError, IndexError):
                        continue
                st = data.get("settings", {})
                if not isinstance(st, dict):
                    st = {}
                out["settings"] = {
                    "sound": bool(st.get("sound", True)),
                    "preview": bool(st.get("preview", True)),
                    "ghosts": bool(st.get("ghosts", True)),
                    "scale": float(st.get("scale", 1.0)),
                    "text_scale": float(st.get("text_scale", 1.0)),
                    "orbit_paths": bool(st.get("orbit_paths", True)),
                    "labels": bool(st.get("labels", True)),
                    "effects": bool(st.get("effects", True)),
                    "auto_advance": bool(st.get("auto_advance", False)),
                    "pause_on_unfocus": bool(st.get("pause_on_unfocus",
                                                    True)),
                    "grid": bool(st.get("grid", False))}
                if out["settings"]["scale"] not in SCALES:
                    out["settings"]["scale"] = 1.0
                if out["settings"]["text_scale"] not in TEXT_SCALES:
                    out["settings"]["text_scale"] = 1.0
            return out
        except Exception:
            # A save with wrong-typed fields is corrupt; starting
            # fresh beats crashing on the title screen.
            return fresh

    def store_save(self):
        try:
            with open(SAVE_FILE, "w", encoding="utf-8") as fh:
                json.dump(self.save, fh)
        except Exception:
            pass

    def all_levels(self):
        return LEVELS + self.save["custom"] + self.session_levels

    def is_campaign(self, idx=None):
        return (self.level_i if idx is None else idx) < len(LEVELS)

    def record_cores(self):
        """Track the best core haul for this mission, from completed
        (docked) runs only. Returns True when this run set a new best."""
        got = sum(1 for (_x, _y, g) in self.cores if g)
        key = str(self.level_i)
        if got > int(self.save["cores"].get(key, 0)):
            self.save["cores"][key] = got
            return True
        return False

    def record_flybys(self):
        """Best flyby count for this mission, from docked runs only."""
        key = str(self.level_i)
        if self.flybys_done > int(self.save["flybys"].get(key, 0)):
            self.save["flybys"][key] = self.flybys_done
            return True
        return False

    def record_ghost(self, stars):
        """Keep the flight path of the best run as a faint ghost line.
        A run replaces the ghost when it earns more stars, or the same
        stars in fewer burns. Wormhole jumps break the trail with a
        None marker, so the ghost is stored as segments - one per
        stretch between warps - and the path into the first wormhole
        is kept instead of being wiped. Off while the Ghosts setting
        is off: nothing is recorded."""
        if not self.save["settings"].get("ghosts", True):
            return
        key = str(self.level_i)
        old = self.save["ghost"].get(key)
        if old and (old.get("stars", 0) > stars or
                    (old.get("stars", 0) == stars and
                     old.get("burns", 99) <= self.burns_used)):
            return
        segs = []
        for seg in self._segments(self.trail):
            pts = [[round(px), round(py)] for (px, py) in seg[::3]]
            last = [round(seg[-1][0]), round(seg[-1][1])]
            if pts and pts[-1] != last:
                pts.append(last)
            if len(pts) >= 2:
                segs.append(pts)
        if segs:
            self.save["ghost"][key] = {"segs": segs,
                                       "burns": self.burns_used,
                                       "stars": stars}

    def campaign_totals(self):
        stars = sum(int(self.save["stars"].get(str(i), 0))
                    for i in range(len(LEVELS)))
        cores = sum(int(self.save["cores"].get(str(i), 0))
                    for i in range(len(LEVELS)))
        cores_all = sum(len(lv["cores"]) for lv in LEVELS)
        return stars, 3 * len(LEVELS), cores, cores_all

    # ---------------- level state ----------------
    def load_level(self, idx):
        levels = self.all_levels()
        self.level_i = idx
        lv = levels[idx]
        self.lv = lv
        self.specs = level_specs(lv)
        self.wormholes = level_wormholes(lv)
        self.barriers = level_barriers(lv)
        self.clock = 0.0
        self.planets = planet_snapshot(self.specs, 0.0)
        self.sx, self.sy = lv["start"]
        self.tx, self.ty = lv["target"]
        self.cores = [(cx, cy, False) for (cx, cy) in lv["cores"]]
        self.burns_used = 0
        self.flight_time = 0.0
        self.state = "aim"           # aim | fly | won | ended
        self.end_reason = None
        self.end_detail = ""
        self.crash_idx = None
        self.paused = False
        self.pause_btn.config(text="Pause (H)")
        self.x, self.y = float(self.sx), float(self.sy)
        self.vx = self.vy = 0.0
        self.trail = []
        self.drag = None
        self.burn_aim = None
        self.angle_deg = 0.0
        self.power = 150.0
        self.has_aim = False         # no aim shown until the player aims
        self.wh_cd = 0.0
        self.wh_pair = -1            # pair just warped through (-1: none)
        self.flyby_min = [1e9] * len(self.specs)
        self.flyby_flagged = set()
        self.flybys_done = 0
        self.undo_stack = []
        self.particles = []
        self._sync_sliders()
        rng = random.Random(1000 + idx)
        self.stars_far = [(rng.uniform(0, WIDTH), rng.uniform(0, HEIGHT),
                           rng.uniform(0.5, 1.1),
                           rng.choice(("#46609c", "#5f7bb0", "#38507f")))
                          for _ in range(110)]
        self.stars_near = [(rng.uniform(0, WIDTH), rng.uniform(0, HEIGHT),
                            rng.uniform(1.2, 2.1),
                            rng.choice(("#cfe2ff", "#9db9e8", "#ffffff")))
                           for _ in range(45)]
        self.twinkle = []            # (layer, index) pairs lit this beat
        self.message = lv["sub"] + " Drag to aim, then launch."
        self.overlay.place_forget()
        self.draw_static()
        self._create_dyn_items()
        self.sync_ui()

    def goto(self, idx):
        if self.mode == "editor":
            self.exit_editor()
        total = len(self.all_levels())
        if not (0 <= idx < total):
            return
        if idx < len(LEVELS) and idx > self.save["unlocked"]:
            return
        self.load_level(idx)

    def reset(self):
        if self.mode == "editor":
            return
        self.load_level(self.level_i)

    def _key(self, seq, fn):
        """Bind a hotkey that stays silent while the player is typing
        in a text field (level name, description, dialogs). Without
        this, typing 'r' in the level name would reset the mission,
        and typing a space would launch the ship."""
        def handler(_event):
            w = self.root.focus_get()
            if isinstance(w, (tk.Entry, tk.Text)):
                return
            fn()
        self.root.bind(seq, handler)

    def _on_wheel_guarded(self, event):
        """Mouse wheel, ignored while a text field has focus so
        scrolling over the editor's name box can't resize a planet."""
        w = self.root.focus_get()
        if isinstance(w, (tk.Entry, tk.Text)):
            return
        self.on_wheel(event)

    def toggle_pause(self):
        if self.mode == "editor" or self.state in ("won", "ended"):
            return
        self.paused = not self.paused
        self.pause_btn.config(text="Resume (H)" if self.paused
                              else "Pause (H)")
        if self.paused:
            self.message = "Paused. H to resume."

    def _on_focus_out(self, _event):
        """Auto-pause a flight when the window loses focus (alt-tab),
        so the 25-second clock doesn't eat the run. Only mid-flight;
        the Pause on unfocus setting turns it off."""
        if self.mode != "play" or self.state != "fly" or self.paused:
            return
        if not self.save["settings"].get("pause_on_unfocus", True):
            return
        self.toggle_pause()

    def _sound_toggled(self):
        self.beeper.enabled = self.sound_var.get()
        self.save["settings"]["sound"] = bool(self.sound_var.get())
        self.store_save()

    def _preview_toggled(self):
        self.save["settings"]["preview"] = bool(self.preview_var.get())
        self.store_save()

    def _ghosts_toggled(self):
        self.save["settings"]["ghosts"] = bool(self.ghosts_var.get())
        self.store_save()

    def _opt_toggled(self, key):
        """One handler for the extra settings row: store the toggle,
        then let the next frame redraw (grid / routes / labels follow
        their settings in draw_frame)."""
        self.save["settings"][key] = bool(self._opt_vars[key].get())
        self.store_save()
        if key == "effects" and not self.save["settings"][key]:
            # Un-light any twinkling stars right away instead of
            # leaving them bright until the next twinkle beat.
            for item, base in self._lit:
                try:
                    self.canvas.itemconfig(item, fill=base)
                except tk.TclError:
                    pass
            self._lit = []
            self.twinkle = []
            self._twinkle_dirty = False
        self.sync_ui()

    # ---------------- undo ----------------
    def push_undo(self):
        """Snapshot the flight just before a burn (or the launch), so U
        can take it back."""
        self.undo_stack.append({
            "state": self.state, "x": self.x, "y": self.y,
            "vx": self.vx, "vy": self.vy, "burns": self.burns_used,
            "time": self.flight_time, "clock": self.clock,
            "cores": tuple(g for (_x, _y, g) in self.cores),
            "trail": list(self.trail), "flyby": list(self.flyby_min),
            "flagged": set(self.flyby_flagged), "wh_cd": self.wh_cd,
            "wh_pair": self.wh_pair,
            "angle": self.angle_deg, "power": self.power,
            "has_aim": self.has_aim})

    def undo(self):
        if self.mode != "play" or self.paused \
                or self.state in ("won", "ended"):
            # no undo after the run is over: popping a snapshot
            # would bring the flight back to life underneath the
            # win / crash overlay
            return
        if not self.undo_stack:
            self.message = "Nothing to undo."
            return
        snap = self.undo_stack.pop()
        self.state = snap["state"]
        self.x, self.y = snap["x"], snap["y"]
        self.vx, self.vy = snap["vx"], snap["vy"]
        self.burns_used = snap["burns"]
        self.flight_time = snap["time"]
        self.clock = snap["clock"]
        self.planets = planet_snapshot(self.specs, self.clock)
        self.cores = [(cx, cy, got)
                      for (cx, cy, _g), got in zip(self.cores, snap["cores"])]
        self.trail = snap["trail"]
        self.flyby_min = snap["flyby"]
        self.flyby_flagged = snap["flagged"]
        self.wh_cd = snap["wh_cd"]
        self.wh_pair = snap["wh_pair"]
        self.angle_deg, self.power = snap["angle"], snap["power"]
        self.has_aim = snap["has_aim"]
        self.end_reason = None
        self.crash_idx = None
        self.drag = None
        self.burn_aim = None
        self.overlay.place_forget()
        if self.state == "aim":
            self.message = "Launch undone - aim again, SPACE to launch."
        else:
            self.message = (f"Burn #{self.burns_used + 1} undone. "
                            "Drag to aim a different burn.")
        self._sync_sliders()
        self.sync_ui()

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
        if self.paused or self.mode != "play":
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
        if self.state != "aim" or self.paused or self.mode != "play":
            return
        if not self.has_aim:
            self.angle_deg, self.power = 0.0, 150.0
            self.has_aim = True
        self.angle_deg = max(-180.0, min(180.0, self.angle_deg + d_ang))
        self.power = max(POWER_MIN, min(POWER_MAX, self.power + d_power))
        self._sync_sliders()

    def on_double_click(self, event):
        """Double-click a planet in the editor to rename it. The
        first click of the pair starts a drag, so clear it."""
        if self.mode != "editor" or self.editor is None:
            return
        gx, gy = event.x / self.S, event.y / self.S
        ed = self.editor
        for i, p in enumerate(ed["planets"]):
            if math.hypot(gx - p["x"], gy - p["y"]) <= p["r"] + 4:
                ed["sel"] = i
                ed["drag"] = None
                self.rename_planet()
                return

    def on_press(self, event):
        gx, gy = event.x / self.S, event.y / self.S
        if self.mode == "editor":
            self.ed_press(gx, gy, shift=bool(event.state & 0x1))
            return
        if self.paused:
            return
        if self.state == "aim":
            self.drag = (gx, gy)
            self.aim_from_point(gx, gy)
        elif self.state == "fly":
            if self.burns_used >= self.lv["max_burns"]:
                self.message = ("No burns left - this flight is ballistic "
                                "now. Ride it out or reset.")
                return
            self.drag = (gx, gy)
            self.message = "Aiming correction burn - time frozen."

    def on_drag(self, event):
        gx, gy = event.x / self.S, event.y / self.S
        if self.mode == "editor":
            self.ed_drag(gx, gy)
            return
        if self.drag is None or self.paused:
            return
        self.drag = (gx, gy)
        if self.state == "aim":
            self.aim_from_point(gx, gy)

    def on_release(self, event):
        self._release_at(event.x / self.S, event.y / self.S)

    def on_release_anywhere(self, event):
        # A release that lands off the canvas (over the HUD, outside the
        # window) never reaches the canvas binding - without this, the
        # drag would stay "held" forever and flight would freeze.
        if self.drag is None and self.mode != "editor":
            return
        self._release_at((event.x_root - self.canvas.winfo_rootx()) / self.S,
                         (event.y_root - self.canvas.winfo_rooty()) / self.S)

    def _release_at(self, x, y):
        # Releasing the mouse NEVER fires anything - it only finishes
        # the aim. SPACE is the one and only trigger.
        if self.mode == "editor":
            self.ed_release(x, y)
            return
        if self.drag is None:
            return
        self.drag = None
        if self.state == "aim":
            self.aim_from_point(x, y)
        elif self.state == "fly":
            self.burn_aim = (x, y)

    def on_wheel(self, event):
        if self.mode == "editor":
            gx, gy = event.x / self.S, event.y / self.S
            self.ed_wheel(gx, gy, 1 if event.delta > 0 else -1,
                          shift=bool(event.state & 0x1))

    def space_action(self):
        """SPACE is the only trigger: launch while aiming, or fire the
        burn that has been aimed."""
        if self.paused or self.mode != "play":
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
        self.push_undo()
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
        self.push_undo()
        self.vx += dvx
        self.vy += dvy
        self.burns_used += 1
        left = self.lv["max_burns"] - self.burns_used
        self.message = f"Burn #{self.burns_used} fired. {left} left."
        self.beeper.burn()
        self.sync_ui()

    # ---------------- particles ----------------
    def spawn_particles(self, x, y, family, count, speed=60.0, life=0.5,
                        base_vx=0.0, base_vy=0.0, size=3.5):
        if not self.save["settings"].get("effects", True):
            return   # Effects off: no exhaust, warp, core or win bursts
        for _ in range(count):
            if len(self.particles) >= 48:
                return
            ang = random.uniform(0, math.tau)
            spd = speed * random.uniform(0.3, 1.0)
            self.particles.append({
                "x": x, "y": y,
                "vx": base_vx + math.cos(ang) * spd,
                "vy": base_vy + math.sin(ang) * spd,
                "life": life * random.uniform(0.6, 1.1), "max": life,
                "family": family, "size": size})

    def update_particles(self, dt):
        alive = []
        for p in self.particles:
            p["life"] -= dt
            if p["life"] <= 0:
                continue
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vx"] *= 0.94
            p["vy"] *= 0.94
            alive.append(p)
        self.particles = alive

    # ---------------- simulation ----------------
    def tick(self):
        # Schedule the next frame FIRST: if anything below ever throws,
        # the game loop still survives instead of freezing mid-flight.
        self.root.after(TICK_MS, self.tick)
        if self.mode == "editor":
            if getattr(self, "ed_dirty", False):
                self.ed_dirty = False
                self.draw_editor()
            return
        dt_frame = 1.0 / 60.0
        aiming_burn = self.drag is not None or self.burn_aim is not None
        running = not self.paused and self.state in ("aim", "fly")
        if running and not (self.state == "fly" and aiming_burn):
            self.clock += dt_frame
            self.planets = planet_snapshot(self.specs, self.clock)
        if self.state == "fly" and not aiming_burn and not self.paused:
            self.flight_time += dt_frame
            for _ in range(2):
                self.x, self.y, self.vx, self.vy = step_physics(
                    self.x, self.y, self.vx, self.vy, self.planets, PHYS_DT)
                self.wh_cd = max(0.0, self.wh_cd - PHYS_DT)
                if self.wormholes:
                    nx, ny, warped, k = wormhole_step(
                        self.x, self.y, self.wormholes,
                        skip=self.wh_pair if self.wh_cd > 0.0 else -1)
                    if warped:
                        self.x, self.y = nx, ny
                        self.wh_cd = WORMHOLE_COOLDOWN
                        self.wh_pair = k
                        # Mark the jump instead of wiping the trail: the
                        # old self.trail = [] here is why ghosts never
                        # kept the path into the first wormhole.
                        self.trail.append(None)
                        self.spawn_particles(nx, ny, "warp", 10,
                                             speed=80.0, life=0.45)
                        self.beeper.warp()
                        self.message = "Wormhole! Velocity kept."
                self.check_events()
                if self.state != "fly":
                    break
            if self.state == "fly":
                self.trail.append((self.x, self.y))
                self.trail = self.trail[-TRAIL_MAX:]
                self.spawn_particles(
                    self.x, self.y, "engine", 2, speed=14.0, life=0.35,
                    base_vx=-self.vx * 0.25, base_vy=-self.vy * 0.25,
                    size=3.0)
                if self.flight_time > FLIGHT_TIMEOUT:
                    self.end_run("timeout")
        if not self.paused:
            self.update_particles(dt_frame)
        self.draw_frame()
        # Reconfiguring widgets every frame makes the window flicker on
        # Windows - the HUD only needs ~10 updates a second. (Events like
        # launch / burn / win still call sync_ui directly, instantly.)
        self._tick_count += 1
        if self._tick_count % 6 == 0:
            self.sync_ui()
        if self._tick_count % 15 == 0 and not self.paused \
                and self.save["settings"].get("effects", True):
            # starfield twinkle: relight a few stars in a brighter shade
            rng = random.Random(self._tick_count)
            self.twinkle = [(rng.random() < 0.5, rng.randrange(110))
                            for _ in range(6)]
            self._twinkle_dirty = True

    def check_events(self):
        for i, (px, py, r, _mu, _c, _lab) in enumerate(self.planets):
            d = math.hypot(self.x - px, self.y - py) - r
            if d < self.flyby_min[i]:
                self.flyby_min[i] = d
            if d <= FLYBY_RANGE and i not in self.flyby_flagged \
                    and self.state == "fly":
                self.flyby_flagged.add(i)
                self.beeper.flyby()
                self.message = "Close flyby! Skimmed a planet."
        outcome = check_hit(self.x, self.y, self.planets, (self.tx, self.ty),
                            self.barriers)
        if outcome == "crash":
            label = ""
            for i, (px, py, r, _mu, _c, lab) in enumerate(self.planets):
                if (self.x - px) ** 2 + (self.y - py) ** 2 < (r + CRASH_PAD) ** 2:
                    label = lab
                    self.crash_idx = i
                    break
            if not label:
                label = "a barrier"
            self.spawn_particles(self.x, self.y, "danger", 14,
                                 speed=110.0, life=0.6)
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
                self.spawn_particles(cx, cy, "core", 8, speed=70.0,
                                     life=0.45)
                self.beeper.core()

    def count_flybys(self):
        n = sum(1 for m in self.flyby_min if m <= FLYBY_RANGE)
        if self.crash_idx is not None and \
                self.flyby_min[self.crash_idx] <= FLYBY_RANGE:
            n -= 1   # the planet you hit doesn't count as a flyby
        return max(0, n)

    def stars_for(self, burns_used):
        if burns_used <= self.lv["par"]:
            return 3
        if burns_used <= self.lv["par"] + 1:
            return 2
        return 1

    def win(self):
        self.state = "won"
        stars = self.stars_for(self.burns_used)
        self.flybys_done = self.count_flybys()
        self.spawn_particles(self.tx, self.ty, "gold", 16, speed=100.0,
                             life=0.6)
        # Session levels (Random / playtest) vanish when the game
        # closes, so their results must not be saved: records are
        # keyed by level index, and a saved record at a session
        # index would be inherited by whatever custom level later
        # takes that slot - a Random run's 3 stars and 5 cores
        # showing up on a brand-new custom level ("5/0 cores").
        persistent = self.level_i < len(LEVELS) + len(self.save["custom"])
        if persistent:
            key = str(self.level_i)
            self.save["stars"][key] = max(stars,
                                           self.save["stars"].get(key, 0))
        if self.is_campaign():
            self.save["unlocked"] = max(
                self.save["unlocked"],
                min(self.level_i + 1, len(LEVELS) - 1))
        new_core_best = self.record_cores() if persistent else False
        new_flyby_best = self.record_flybys() if persistent else False
        if persistent:
            self.record_ghost(stars)
        self.store_save()
        self.beeper.win()
        got = sum(1 for (_x, _y, g) in self.cores if g)
        title = "Clean docking" if self.burns_used <= self.lv["par"] else "Docked"
        text = (f"Docked in {self.burns_used} burn"
                f"{'' if self.burns_used == 1 else 's'} "
                f"(par {self.lv['par']}) in {self.flight_time:.1f}s · "
                f"Cores {got}/{len(self.cores)} · Flybys {self.flybys_done}")
        if got == len(self.cores) and self.cores:
            text += " - every core collected."
        elif new_core_best and got:
            text += " New best cores for this mission!"
        if new_flyby_best and self.flybys_done:
            text += " New best flybys!"
        total_stars, max_stars, total_cores, max_cores = \
            self.campaign_totals()
        if total_stars == max_stars and total_cores == max_cores:
            text += " CAMPAIGN COMPLETE - every star and every core!"
        if self.is_campaign() and self.level_i == len(LEVELS) - 1:
            text += " That was the final mission - replay any mission to chase 3 stars."
        nxt = self.level_i + 1
        show_next = nxt < len(self.all_levels()) and \
            (nxt >= len(LEVELS) or nxt <= self.save["unlocked"])
        self.show_overlay(f"Docked · Mission {self.level_i + 1} complete",
                          title, "★" * stars + "☆" * (3 - stars), text,
                          show_next=show_next)
        self.sync_ui()
        if self.save["settings"].get("auto_advance", False) and show_next:
            lvl = self.level_i
            self.root.after(1500, lambda: self._auto_advance(lvl))

    def _auto_advance(self, level):
        """Jump to the next mission after a win, if the player is
        still looking at that win screen (no manual move since)."""
        try:
            if self.state == "won" and self.mode == "play" \
                    and self.level_i == level:
                self.goto(level + 1)
        except tk.TclError:
            pass   # the window closed in the meantime

    def end_run(self, reason, detail=""):
        self.state = "ended"
        self.end_reason = reason
        self.end_detail = detail
        self.flybys_done = self.count_flybys()
        self.beeper.lose()
        titles = {"crash": f"Crashed into {detail}" if detail else "Crashed",
                  "lost": "Lost in deep space",
                  "timeout": "Out of time"}
        hints = {"crash": "The surface is not a landing pad. Bend around it. U undoes the last burn.",
                 "lost": "The probe drifted beyond recovery. R to retry, U to undo.",
                 "timeout": f"Flights end after {FLIGHT_TIMEOUT:.0f} seconds. "
                            "Find a shorter line."}
        text = hints.get(reason, "")
        if self.flybys_done:
            text += f" Flybys this run: {self.flybys_done}."
        self.show_overlay("Run ended", titles.get(reason, "Run ended"), "",
                          text, show_next=False)
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
        total = len(self.all_levels())
        best = self.save["stars"].get(str(self.level_i), 0)
        best_txt = f" · Best: {'★' * best}" if best else ""
        if lv["cores"]:
            core_best = int(self.save["cores"].get(str(self.level_i), 0))
            best_txt += f" · Best cores: {core_best}/{len(lv['cores'])}"
        t_stars, t_max, t_cores, t_cmax = self.campaign_totals()
        self.hud1.config(
            text=f"Mission {self.level_i + 1} of {total}{best_txt} — "
                 f"{lv['name']}")
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
            f"Flybys {self.count_flybys()}   "
            f"Time {self.flight_time:.1f}s   Speed {speed:.0f}   {phase}   "
            f"·   Campaign ★{t_stars}/{t_max} · Cores {t_cores}/{t_cmax}"))
        self.pager_label.config(
            text=f"Level {self.level_i + 1} — {lv['name']}")
        self.pager_prev.config(
            state="normal" if self.level_i > 0 else "disabled")
        nxt = self.level_i + 1
        can_next = nxt < total and \
            (nxt >= len(LEVELS) or nxt <= self.save["unlocked"])
        self.pager_next.config(state="normal" if can_next else "disabled")
        is_saved_custom = len(LEVELS) <= self.level_i < \
            len(LEVELS) + len(self.save["custom"])
        self.bar_btns["Delete level"].config(
            state="normal" if is_saved_custom else "disabled")
        self.bar_btns["Clear ghost"].config(
            state="normal"
            if str(self.level_i) in self.save["ghost"] else "disabled")

    # ---------------- drawing ----------------
    def draw_static(self):
        c = self.canvas
        c.delete("all")
        # The wipe takes the ghost lines with it, so drop the ghost
        # cache too: _draw_ghost skips rebuilding when the key
        # matches, and a stale key after a reset (R) left the ghost
        # invisible until a new best run changed the saved ghost.
        self._ghost_key = None
        self.ghost_items = []
        X = self.X
        c.create_oval(X(self.sx - 12), X(self.sy - 12), X(self.sx + 12),
                      X(self.sy + 12), outline=COLORS["dim"], width=2,
                      tags="static")
        c.create_text(X(self.sx), X(self.sy + 24), text="PAD",
                      fill=COLORS["dim"], font=("Consolas", self.FS(9)),
                      tags="static")
        c.create_oval(X(self.tx - DOCK_RADIUS), X(self.ty - DOCK_RADIUS),
                      X(self.tx + DOCK_RADIUS), X(self.ty + DOCK_RADIUS),
                      outline=COLORS["station"], width=3, tags="static")
        c.create_oval(X(self.tx - 5), X(self.ty - 5), X(self.tx + 5),
                      X(self.ty + 5), fill=COLORS["station"], outline="",
                      tags="static")
        c.create_text(X(self.tx), X(self.ty + DOCK_RADIUS + 14), text="DOCK",
                      fill=COLORS["station"], font=("Consolas", self.FS(9)),
                      tags="static")
        # Barriers are solid walls: a flat fill (no outline - an erased
        # barrier is several overlapping pieces, and outlines would
        # draw seams across its interior).
        for pts in self.barriers:
            c.create_polygon(*[X(v) for q in pts for v in q],
                             fill=BARRIER_FILL, outline="", tags="static")

    def _create_dyn_items(self):
        """Create the moving canvas items ONCE per level. Flicker fix:
        the old code deleted and recreated every item 60 times a
        second, which strobes on Windows. Persistent items are only
        ever moved / shown / hidden - never recreated."""
        c = self.canvas
        X = self.X
        # Create settings-driven items already in the state their
        # setting wants: creating them visible and hiding them in the
        # next draw_frame flashed the grid / routes / labels for a
        # frame on every reset (R).
        grid_state = "normal" \
            if self.save["settings"].get("grid", False) else "hidden"
        routes_state = "normal" \
            if self.save["settings"].get("orbit_paths", True) else "hidden"
        labels_state = "normal" \
            if self.save["settings"].get("labels", True) else "hidden"
        self.it_stars_far = []
        for (sx, sy, sr, col) in self.stars_far:
            self.it_stars_far.append(c.create_oval(
                X(sx - sr), X(sy - sr), X(sx + sr), X(sy + sr),
                fill=col, outline=""))
        self.it_stars_near = []
        for (sx, sy, sr, col) in self.stars_near:
            self.it_stars_near.append(c.create_oval(
                X(sx - sr), X(sy - sr), X(sx + sr), X(sy + sr),
                fill=col, outline=""))
        self._lit = []
        self._twinkle_dirty = False
        # faint coordinate grid (setting) - lines every 120 px with
        # small numbers along the top and left edges
        self.it_grid = []
        for gx in range(120, WIDTH, 120):
            self.it_grid.append(c.create_line(
                X(gx), X(0), X(gx), X(HEIGHT), fill="#16213c", width=1,
                state=grid_state))
            self.it_grid.append(c.create_text(
                X(gx), X(10), text=str(gx), fill=COLORS["dim"],
                font=("Consolas", self.FS(9)), state=grid_state))
        for gy in range(120, HEIGHT, 120):
            self.it_grid.append(c.create_line(
                X(0), X(gy), X(WIDTH), X(gy), fill="#16213c", width=1,
                state=grid_state))
            self.it_grid.append(c.create_text(
                X(10), X(gy), text=str(gy), fill=COLORS["dim"],
                font=("Consolas", self.FS(9)), state=grid_state))
        # orbit circles and patrol routes (setting) - static per level,
        # drawn under the planets
        self.it_routes = []
        for sp in self.specs:
            if sp.get("orbit"):
                orb = sp["orbit"]
                self.it_routes.append(c.create_oval(
                    X(orb["cx"] - orb["radius"]),
                    X(orb["cy"] - orb["radius"]),
                    X(orb["cx"] + orb["radius"]),
                    X(orb["cy"] + orb["radius"]),
                    outline="#3a5a8c", width=1, dash=(4, 4),
                    state=routes_state))
            elif sp.get("path"):
                pts = sp["path"]["pts"]
                if len(pts) >= 2:
                    route = pts + [pts[0]] if sp["path"].get("loop") \
                        else pts
                    self.it_routes.append(c.create_line(
                        *[X(v) for q in route for v in q],
                        fill="#3a5a8c", width=1, dash=(4, 4),
                        state=routes_state))
        self.it_planets = []
        for (px, py, r, _mu, color, label) in self.planets:
            if _mu < 0:   # repulsor: dashed orange push-ring, warm outline
                well = c.create_oval(X(px - r * 1.7), X(py - r * 1.7),
                                     X(px + r * 1.7), X(py + r * 1.7),
                                     outline="#ff9a3c", width=2, dash=(4, 3))
                body = c.create_oval(X(px - r), X(py - r), X(px + r),
                                     X(py + r), fill=color,
                                     outline="#ffd9a8", width=1)
            else:
                well = c.create_oval(X(px - r * 1.7), X(py - r * 1.7),
                                     X(px + r * 1.7), X(py + r * 1.7),
                                     outline="#16294d", width=1)
                body = c.create_oval(X(px - r), X(py - r), X(px + r),
                                     X(py + r), fill=color,
                                     outline="#cdd8ff", width=1)
            hi = c.create_oval(X(px - r * 0.35), X(py - r * 0.35),
                               X(px + r * 0.35), X(py + r * 0.35),
                               fill="#ffffff", outline="", stipple="gray25")
            lab = c.create_text(X(px), X(py + r + 14), text=label,
                                fill=COLORS["dim"],
                                font=("Consolas", self.FS(9)),
                                state=labels_state)
            self.it_planets.append({"well": well, "body": body, "hi": hi,
                                    "label": lab})
        self.it_worms = []
        for (ax, ay, bx, by) in self.wormholes:
            pair = []
            for (wx, wy) in ((ax, ay), (bx, by)):
                ring = c.create_oval(X(wx - 20), X(wy - 20), X(wx + 20),
                                     X(wy + 20), outline=COLORS["warp"],
                                     width=2)
                dot = c.create_oval(X(wx - 4), X(wy - 4), X(wx + 4),
                                    X(wy + 4), fill=COLORS["warp"],
                                    outline="")
                pair.append((ring, dot))
            self.it_worms.append(pair)
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
                X(cx), X(cy - 8), X(cx + 6), X(cy), X(cx), X(cy + 8),
                X(cx - 6), X(cy), fill=COLORS["core"], outline=""))
        self.it_particles = []
        for _ in range(48):
            self.it_particles.append(c.create_oval(
                0, 0, 0, 0, fill="", outline="", state="hidden"))
        self.it_probe = c.create_oval(X(self.x - 6), X(self.y - 6),
                                      X(self.x + 6), X(self.y + 6),
                                      fill=COLORS["probe"], outline="#fff3c4")
        self.it_crash = c.create_text(X(self.x), X(self.y), text="X",
                                      fill=COLORS["danger"],
                                      font=("Consolas", self.FS(20), "bold"),
                                      state="hidden")
        self.it_paused = c.create_text(X(WIDTH / 2), X(40), text="PAUSED",
                                       fill=COLORS["text"],
                                       font=("Consolas", self.FS(18), "bold"),
                                       state="hidden")

    def _show(self, item, points=None, **kw):
        if points is not None:
            self.canvas.coords(item, *points)
        self.canvas.itemconfig(item, state="normal", **kw)

    def _hide(self, item):
        self.canvas.itemconfig(item, state="hidden")

    @staticmethod
    def _segments(points):
        """Split a point list on None markers (wormhole jumps)."""
        segs, cur = [], []
        for p in points:
            if p is None:
                if len(cur) >= 2:
                    segs.append(cur)
                cur = []
            else:
                cur.append(p)
        if len(cur) >= 2:
            segs.append(cur)
        return segs

    def _draw_ghost(self, segs):
        """Show the saved ghost line, one canvas line per segment so
        wormhole jumps stay gaps instead of streaks. The lines are
        rebuilt only when the ghost actually changes; an empty list
        hides the ghost. New lines sit under the planets, where the
        old single ghost line lived."""
        key = tuple(tuple(tuple(p) for p in s) for s in segs) or None
        if key == getattr(self, "_ghost_key", None):
            return
        self._ghost_key = key
        for item in getattr(self, "ghost_items", []):
            self.canvas.delete(item)
        self.ghost_items = []
        for seg in segs:
            item = self.canvas.create_line(
                0, 0, 0, 0, fill=COLORS["ghost"], width=1, dash=(1, 4))
            self.canvas.coords(item, *self.PTS([v for pt in seg for v in pt]))
            if self.it_planets:
                self.canvas.tag_lower(item, self.it_planets[0]["body"])
            self.ghost_items.append(item)

    def draw_frame(self):
        c = self.canvas
        X, PTS = self.X, self.PTS
        # starfield twinkle (a few stars relight every quarter second)
        if self._twinkle_dirty:
            self._twinkle_dirty = False
            for item, base in self._lit:
                try:
                    c.itemconfig(item, fill=base)
                except tk.TclError:
                    pass
            self._lit = []
            for near, idx in self.twinkle:
                layer = self.it_stars_near if near else self.it_stars_far
                if idx < len(layer):
                    item = layer[idx]
                    base = c.itemcget(item, "fill")
                    c.itemconfig(item, fill=_blend(base, "#ffffff", 0.55))
                    self._lit.append((item, base))
        # grid and motion routes follow their settings (the items
        # exist per level; toggling just shows or hides them)
        grid_on = self.save["settings"].get("grid", False)
        for item in self.it_grid:
            c.itemconfig(item, state="normal" if grid_on else "hidden")
        routes_on = self.save["settings"].get("orbit_paths", True)
        for item in self.it_routes:
            c.itemconfig(item, state="normal" if routes_on else "hidden")
        # ghost of the best run on this mission, one line per segment
        # so wormhole jumps stay gaps instead of streaks
        ghost = self.save["ghost"].get(str(self.level_i))
        if ghost and self.save["settings"].get("ghosts", True) \
                and self.state in ("aim", "fly"):
            self._draw_ghost(ghost["segs"])
        else:
            self._draw_ghost([])
        # planets (they move on the orbiting levels)
        labels_on = self.save["settings"].get("labels", True)
        for items, (px, py, r, _mu, _col, _lab) in zip(self.it_planets,
                                                       self.planets):
            c.coords(items["well"], X(px - r * 1.7), X(py - r * 1.7),
                     X(px + r * 1.7), X(py + r * 1.7))
            c.coords(items["body"], X(px - r), X(py - r), X(px + r),
                     X(py + r))
            c.coords(items["hi"], X(px - r * 0.35), X(py - r * 0.35),
                     X(px + r * 0.35), X(py + r * 0.35))
            c.coords(items["label"], X(px), X(py + r + 14))
            c.itemconfig(items["label"],
                         state="normal" if labels_on else "hidden")
        # wormhole mouths pulse gently
        for k, pair in enumerate(self.it_worms):
            ends = ((self.wormholes[k][0], self.wormholes[k][1]),
                    (self.wormholes[k][2], self.wormholes[k][3]))
            for (ring, dot), (wx, wy) in zip(pair, ends):
                rad = WORMHOLE_RADIUS + 4 + math.sin(self.clock * 3.0
                                                     + k * 1.7) * 2.5
                c.coords(ring, X(wx - rad), X(wy - rad), X(wx + rad),
                         X(wy + rad))
                c.coords(dot, X(wx - 4), X(wy - 4), X(wx + 4), X(wy + 4))
        for item, (_cx, _cy, got) in zip(self.it_cores, self.cores):
            if got:
                self._hide(item)
            else:
                self._show(item)
        # Live trail: only the current stretch (after the last wormhole
        # jump) is drawn, so no streak crosses the field at a warp.
        # The full trail, jumps included, still goes to the ghost.
        trail_segs = self._segments(self.trail)
        sample = trail_segs[-1][::2] if trail_segs else []
        if sample and sample[-1] != trail_segs[-1][-1]:
            sample.append(trail_segs[-1][-1])
        if len(sample) >= 2:
            self._show(self.it_trail, PTS([p for pt in sample for p in pt]))
        else:
            self._hide(self.it_trail)

        prediction = None     # (flat_points, outcome)
        if self.state == "aim" and self.has_aim:
            vx, vy = self.aim_velocity()
            self._show(self.it_aim, PTS([self.x, self.y,
                                         self.x + vx * 0.35,
                                         self.y + vy * 0.35]))
            if self.preview_var.get():
                pts, outcome = predict_path(
                    self.x, self.y, vx, vy, self.specs, (self.tx, self.ty),
                    t0=self.clock, wormholes=self.wormholes,
                    wh_cd=self.wh_cd, wh_pair=self.wh_pair,
                    barriers=self.barriers)
                prediction = (pts, outcome)
        else:
            self._hide(self.it_aim)

        if self.state == "fly" and self.burns_used < self.lv["max_burns"] and \
                (self.drag is not None or self.burn_aim is not None):
            mx, my = self.drag if self.drag is not None else self.burn_aim
            dvx, dvy = self.burn_dv(mx, my)
            self._show(self.it_burn, PTS([self.x, self.y,
                                          self.x + dvx, self.y + dvy]))
            if self.preview_var.get():
                pts, outcome = predict_path(
                    self.x, self.y, self.vx + dvx, self.vy + dvy,
                    self.specs, (self.tx, self.ty), t0=self.clock,
                    wormholes=self.wormholes, wh_cd=self.wh_cd,
                    wh_pair=self.wh_pair, barriers=self.barriers)
                prediction = (pts, outcome)
        else:
            self._hide(self.it_burn)

        if prediction is not None:
            pts, outcome = prediction
            segs = self._segments(pts)
            if segs:
                best = max(segs, key=len)
                color = {"dock": COLORS["ok"], "crash": COLORS["danger"],
                         "lost": COLORS["dim"],
                         "flying": COLORS["predict"]}[outcome]
                self._show(self.it_predict,
                           PTS([p for pt in best for p in pt]), fill=color)
            else:
                self._hide(self.it_predict)
        else:
            self._hide(self.it_predict)

        # particles
        for slot, item in enumerate(self.it_particles):
            if slot < len(self.particles):
                p = self.particles[slot]
                frac = 1.0 - p["life"] / p["max"]
                shade = PARTICLE_SHADES[p["family"]][min(3, int(frac * 4))]
                rad = max(0.8, p["size"] * (1.0 - frac * 0.6))
                self._show(item, PTS([p["x"] - rad, p["y"] - rad,
                                      p["x"] + rad, p["y"] + rad]),
                           fill=shade)
            else:
                self._hide(item)

        if self.state == "ended" and self.end_reason == "crash":
            self._hide(self.it_probe)
            self._show(self.it_crash, PTS([self.x, self.y]))
        else:
            self._hide(self.it_crash)
            self._show(self.it_probe, PTS([self.x - 6, self.y - 6,
                                           self.x + 6, self.y + 6]))
        if self.paused:
            self._show(self.it_paused)
        else:
            self._hide(self.it_paused)

    # ---------------- random mission generator ----------------
    def new_random_level(self):
        if self.mode == "editor":
            self.exit_editor()
        lv = generate_random_level()
        self.session_levels.append(lv)
        self.load_level(len(self.all_levels()) - 1)
        self.message = ("Random mission generated - its design line was "
                        "flown and verified before you saw it.")
        self.sync_ui()

    # ---------------- level editor ----------------
    @staticmethod
    def _fresh_editor(lv):
        """Build a complete editor dict from a level dict. This is
        the ONE place an editor dict is made - enter_editor and
        editor_clear both use it, so they can never drift apart and
        leave a key out (a missing 'barriers' key once made every
        redraw after Clear die, so nothing could be placed)."""
        specs = level_specs(lv)
        snap = planet_snapshot(specs, 0.0)
        planets = []
        for sp, pos in zip(specs, snap):
            p = {"x": round(pos[0]), "y": round(pos[1]),
                 "r": sp["r"], "color": sp["color"],
                 "label": sp["label"]}
            if sp.get("orbit"):
                p["orbit"] = dict(sp["orbit"])
            if sp.get("path"):
                p["path"] = {"pts": [list(q) for q in sp["path"]["pts"]],
                             "speed": sp["path"].get("speed", 60.0),
                             "phase": sp["path"].get("phase", 0.0),
                             "loop": sp["path"].get("loop") is True}
            if sp.get("repel"):
                p["repel"] = True
            planets.append(p)
        return {
            "planets": planets,
            "start": [lv["start"][0], lv["start"][1]],
            "target": [lv["target"][0], lv["target"][1]],
            "cores": [[c[0], c[1]] for c in lv["cores"]],
            "wormholes": [list(w) for w in level_wormholes(lv)],
            "barriers": [[list(q) for q in poly]
                         for poly in level_barriers(lv)],
            "drag": None, "sel": None, "worm_next": None,
            "orbit_next": None, "path_next": None,
            "custom_idx": None,
            "barrier_poly": None, "barrier_rect": None,
            "barrier_cur": None, "delbarrier_poly": None,
            "delbarrier_rect": None, "delbarrier_cur": None}

    def enter_editor(self):
        if self.mode == "editor":
            return
        self.mode = "editor"
        if self.editor is None:
            lv = self.lv
            self.editor = self._fresh_editor(lv)
            self._playtest_pos = None
            start = len(LEVELS)
            if start <= self.level_i < start + len(self.save["custom"]):
                # editing a saved custom: Save updates it in place
                self.editor["custom_idx"] = self.level_i - start
                shown_name = lv["name"]
            else:
                shown_name = lv["name"] + " copy"
            self.ed_name.delete(0, "end")
            self.ed_name.insert(0, shown_name)
            self.ed_sub.delete(0, "end")
            self.ed_sub.insert(0, lv.get("sub", ""))
            self.ed_par.delete(0, "end")
            self.ed_par.insert(0, str(lv["par"]))
            self.ed_burns.delete(0, "end")
            self.ed_burns.insert(0, str(lv["max_burns"]))
        self.overlay.place_forget()
        # Pack in the bar's proper slot, above the canvas: a plain
        # pack() appends it below the pager, where the fixed-size
        # window clips it out of sight (the "editor has no tools" bug).
        self.ed_bar.pack(fill="x", before=self.canvas)
        self.ed_sub_row.pack(fill="x", before=self.canvas)
        self.ed_hint.pack(fill="x", before=self.canvas)
        self.ed_hint.config(
            text="Drag planets to move them - wheel over a planet "
                 "resizes it - wormholes go in pairs (A, then B). "
                 "Orbit tool: click a planet, then its center point; "
                 "wheel = orbit size, Shift+wheel = speed. "
                 "Shift+click a planet (Planet tool) toggles REPEL: "
                 "an orange dashed ring means it pushes instead of pulls. "
                 "Path tool: click a planet, then click waypoints to "
                 "build its route (2 points = a straight patrol line, "
                 "more = a custom path); click the planet again to "
                 "finish, wheel over a pathed planet = path speed. "
                 "Shift+click a pathed planet (Path tool) toggles LOOP: "
                 "it rides the route in a circle, back to the start, "
                 "like an orbit, instead of ping-ponging. "
                 "Barrier tool: drag a rectangle to make a solid wall "
                 "(the ship crashes into it), or hold Shift and click "
                 "to lay down polygon corners, then release Shift to "
                 "close the shape - a barrier needs 3 corners and a "
                 "real area, so a line makes nothing. "
                 "Del Bar tool works the same way but cuts barrier out "
                 "instead: drag a rectangle over part of a wall to cut "
                 "it away, or Shift+click a shape - cutting a smaller "
                 "shape out of the middle of a big one leaves a ring. "
                 "Double-click a planet to rename it.")
        self.hud1.config(text="Level Editor")
        self.hud2.config(text="  Build a mission, then Playtest it or "
                              "Save level to keep it.")
        self.stats.config(text="  Editor mode - nothing is saved until "
                               "you press Save level.")
        self.ed_dirty = True
        self.canvas.focus_set()
        self._fit_window()

    def exit_editor(self):
        if self.mode != "editor":
            return
        self.mode = "play"
        self.ed_bar.pack_forget()
        self.ed_sub_row.pack_forget()
        self.ed_hint.pack_forget()
        self.canvas.focus_set()
        self.load_level(self.level_i)
        self._fit_window()

    def _editor_level(self, name_suffix=""):
        ed = self.editor
        try:
            par = int(self.ed_par.get())
        except Exception:
            par = 2
        try:
            burns = int(self.ed_burns.get())
        except Exception:
            burns = 4
        par = max(1, min(20, par))
        burns = max(par, min(20, burns))
        name = (self.ed_name.get().strip() or "Custom mission") + name_suffix
        sub = self.ed_sub.get().strip()[:120] \
            or "A mission built in the editor."
        planets = []
        for p in ed["planets"]:
            q = dict(p)
            if "orbit" in q:
                q["orbit"] = dict(q["orbit"])
            if "path" in q:
                q["path"] = {"pts": [list(pt) for pt in q["path"]["pts"]],
                             "speed": q["path"].get("speed", 60.0),
                             "phase": q["path"].get("phase", 0.0),
                             "loop": q["path"].get("loop") is True}
            planets.append(q)
        return {"name": name, "sub": sub,
                "start": tuple(ed["start"]), "target": tuple(ed["target"]),
                "par": par, "max_burns": burns,
                "planets": planets,
                "cores": [tuple(c) for c in ed["cores"]],
                "wormholes": [tuple(w) for w in ed["wormholes"]],
                "barriers": [[[q[0], q[1]] for q in poly]
                             for poly in ed["barriers"]]}

    def editor_playtest(self):
        lv = self._editor_level(" (playtest)")
        if self._playtest_pos is not None \
                and self._playtest_pos < len(self.session_levels):
            # reusing the one playtest slot: playtesting again
            # replaces the temp level instead of stacking another
            self.session_levels[self._playtest_pos] = lv
            idx = len(LEVELS) + len(self.save["custom"]) \
                + self._playtest_pos
        else:
            self.session_levels.append(lv)
            self._playtest_pos = len(self.session_levels) - 1
            idx = len(self.all_levels()) - 1
        self.mode = "play"
        self.ed_bar.pack_forget()
        self.ed_sub_row.pack_forget()
        self.ed_hint.pack_forget()
        self.canvas.focus_set()
        self.load_level(idx)
        self._fit_window()

    def editor_save(self):
        lv = self._editor_level()
        idx = self.editor.get("custom_idx")
        if idx is not None and 0 <= idx < len(self.save["custom"]):
            # editing a saved custom: update it in place, keeping
            # its stars / cores / ghost records at that index
            self.save["custom"][idx] = lv
            self.store_save()
            saved_idx = len(LEVELS) + idx
            saved_msg = f"Updated '{lv['name']}'."
        else:
            self.save["custom"].append(lv)
            self._clear_records_at(
                len(LEVELS) + len(self.save["custom"]) - 1)
            self.store_save()
            saved_idx = len(LEVELS) + len(self.save["custom"]) - 1
            saved_msg = (f"Saved '{lv['name']}' - it now lives after "
                         "the campaign in the pager.")
        self.mode = "play"
        self.ed_bar.pack_forget()
        self.ed_sub_row.pack_forget()
        self.ed_hint.pack_forget()
        self.canvas.focus_set()
        self.load_level(saved_idx)
        self.message = saved_msg
        self.sync_ui()
        self._fit_window()
        # the work is saved now, so the editor starts fresh from the
        # saved level next time it opens (and a stale playtest temp
        # from this edit goes away with it)
        self.editor = None
        if self._playtest_pos is not None \
                and self._playtest_pos < len(self.session_levels):
            del self.session_levels[self._playtest_pos]
        self._playtest_pos = None

    def share_level(self):
        """Turn the open level (or the editor's work-in-progress) into
        a text code, copy it to the clipboard, and show it in a window
        so it can also be copied by hand."""
        lv = self._editor_level() if self.mode == "editor" else self.lv
        code = level_to_code(lv)
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(code)
            self.root.update()
        except Exception:
            pass
        win = tk.Toplevel(self.root)
        win.title("Share level")
        win.resizable(False, False)
        win.configure(bg="#0b1020")
        tk.Label(win, bg="#0b1020", fg=COLORS["text"],
                 font=("Consolas", self.FS(11), "bold"),
                 text=f"Share '{lv['name']}'").pack(padx=14, pady=(12, 2))
        tk.Label(win, bg="#0b1020", fg=COLORS["dim"],
                 font=("Consolas", self.FS(10)), wraplength=int(430 * self.S),
                 justify="left",
                 text="This code is already on your clipboard. Send it "
                      "to anyone who has Orbital - they press Paste "
                      "level and the mission appears in their game."
                 ).pack(padx=14)
        txt = tk.Text(win, width=62, height=5, wrap="char",
                      bg="#16213c", fg=COLORS["text"], relief="flat",
                      font=("Consolas", self.FS(9)))
        txt.insert("1.0", code)
        txt.pack(padx=14, pady=8)
        tk.Button(win, text="Close", command=win.destroy, bg="#16213c",
                  fg=COLORS["text"], activebackground="#22335c",
                  relief="flat", padx=12, pady=4,
                  takefocus=0).pack(pady=(0, 12))
        self.message = f"Share code for '{lv['name']}' copied to clipboard."
        if self.mode != "editor":
            self.sync_ui()

    def _record_recent(self, code):
        """Remember a level code, newest first (max 8, no duplicates).
        Called on every successful paste / file import."""
        code = "".join(str(code).split())
        if not code:
            return
        recents = [c for c in self.save.get("recent_codes", [])
                   if c != code]
        self.save["recent_codes"] = [code] + recents[:7]

    def _clear_records_at(self, idx):
        """A brand-new level has no best yet: drop any records at its
        index, which can only be leftovers from a session level that
        used to sit there."""
        key = str(idx)
        for field in ("stars", "cores", "flybys", "ghost"):
            self.save[field].pop(key, None)

    def _import_code(self, code_text):
        """Decode a share code and save it as a custom level.
        Returns (level, None) on success, (None, error) on failure."""
        try:
            lv = code_to_level(code_text)
        except ValueError as exc:
            return None, str(exc)
        self.save["custom"].append(lv)
        self._clear_records_at(len(LEVELS) + len(self.save["custom"]) - 1)
        self._record_recent(code_text)
        self.store_save()
        return lv, None

    def _import_file(self, text):
        """Import a level from file contents: an ORBITAL1: code, or a
        raw JSON level dict (re-encoded as a code first, so it goes
        through the same validation). Returns (level, None) or
        (None, error)."""
        s = "".join(str(text).split())
        if s.startswith(LEVEL_CODE_PREFIX):
            return self._import_code(s)
        try:
            data = json.loads(text)
        except Exception:
            return None, ("That file doesn't contain an Orbital level "
                          "code or level data.")
        if not isinstance(data, dict):
            return None, "That file doesn't contain a level."
        raw = json.dumps(data, separators=(",", ":"),
                         sort_keys=True).encode("utf-8")
        code = LEVEL_CODE_PREFIX + base64.urlsafe_b64encode(
            zlib.compress(raw, 9)).decode("ascii")
        return self._import_code(code)

    def _delete_custom(self, idx):
        """Delete the custom level at global index idx. Records keyed
        by level index shift down so they stay with their level, and
        the open level moves to a sensible neighbour if it was the
        one deleted or one after it."""
        start = len(LEVELS)
        del self.save["custom"][idx - start]
        for field in ("stars", "cores", "flybys", "ghost"):
            shifted = {}
            for k, v in self.save[field].items():
                ki = int(k)
                if ki < idx:
                    shifted[k] = v
                elif ki > idx:
                    shifted[str(ki - 1)] = v
            self.save[field] = shifted
        self.store_save()
        if self.mode != "editor" and self.level_i >= idx:
            if self.level_i > idx:
                # the open level slid down one slot with the deletion
                self.load_level(self.level_i - 1)
            else:
                # the open level was the deleted one: show its neighbour
                self.load_level(min(idx, len(self.all_levels()) - 1))

    def paste_level_dialog(self):
        """Ask for a share code and import it as a saved custom level."""
        if self.mode == "editor":
            self.message = "Exit the editor first to paste a level."
            return
        win = tk.Toplevel(self.root)
        win.title("Paste level")
        win.resizable(False, False)
        win.configure(bg="#0b1020")
        tk.Label(win, bg="#0b1020", fg=COLORS["text"],
                 font=("Consolas", self.FS(11), "bold"),
                 text="Paste a level code").pack(padx=14, pady=(12, 2))
        txt = tk.Text(win, width=62, height=5, wrap="char",
                      bg="#16213c", fg=COLORS["text"], relief="flat",
                      font=("Consolas", self.FS(9)),
                      insertbackground="#dbe7ff")
        txt.pack(padx=14, pady=8)
        status = tk.Label(win, bg="#0b1020", fg=COLORS["danger"],
                          font=("Consolas", self.FS(10)),
                          wraplength=int(430 * self.S), justify="left",
                          text="")
        status.pack(padx=14)

        recents = list(self.save.get("recent_codes", []))

        def do_import(code_text=None):
            if code_text is None:
                code_text = txt.get("1.0", "end")
            lv, err = self._import_code(code_text)
            if err:
                status.config(text=err)
                return
            win.destroy()
            idx = len(LEVELS) + len(self.save["custom"]) - 1
            self.load_level(idx)
            self.message = (f"Imported '{lv['name']}' - it now lives "
                            "after the campaign in the pager.")
            self.sync_ui()

        if recents:
            tk.Label(win, bg="#0b1020", fg=COLORS["dim"],
                     font=("Consolas", self.FS(10)),
                     text="Recent codes (double-click to import):"
                     ).pack(padx=14, anchor="w")
            recent_lb = tk.Listbox(win, width=62, height=min(4,
                                                             len(recents)),
                                   bg="#16213c", fg=COLORS["text"],
                                   selectbackground="#2a4a7a",
                                   relief="flat",
                                   font=("Consolas", self.FS(9)),
                                   takefocus=0)
            for code in recents:
                recent_lb.insert("end", code[:48] + ("..." if len(code) > 48
                                                     else ""))
            recent_lb.pack(padx=14, pady=(2, 4))

            def import_recent(_event):
                sel = recent_lb.curselection()
                if sel:
                    do_import(recents[sel[0]])

            recent_lb.bind("<Double-Button-1>", import_recent)

        row = tk.Frame(win, bg="#0b1020")
        row.pack(pady=(2, 12))
        tk.Button(row, text="Import level", command=do_import,
                  bg="#16213c", fg=COLORS["text"],
                  activebackground="#22335c", relief="flat", padx=12,
                  pady=4, takefocus=0).pack(side="left", padx=4)
        tk.Button(row, text="Cancel", command=win.destroy, bg="#16213c",
                  fg=COLORS["text"], activebackground="#22335c",
                  relief="flat", padx=12, pady=4,
                  takefocus=0).pack(side="left", padx=4)
        txt.focus_set()

    def my_levels_dialog(self):
        """Manage saved custom levels: play, edit, share, rename or
        delete one, or save one to / load one from a file."""
        if self.mode == "editor":
            self.message = "Exit the editor first to manage your levels."
            return
        win = tk.Toplevel(self.root)
        win.title("My levels")
        win.resizable(False, False)
        win.configure(bg="#0b1020")
        tk.Label(win, bg="#0b1020", fg=COLORS["text"],
                 font=("Consolas", self.FS(11), "bold"),
                 text="My levels").pack(padx=14, pady=(12, 2))
        body = tk.Frame(win, bg="#0b1020")
        body.pack(padx=14)
        lb = tk.Listbox(body, width=56, height=8, bg="#16213c",
                        fg=COLORS["text"], selectbackground="#2a4a7a",
                        relief="flat", font=("Consolas", self.FS(10)),
                        takefocus=0)
        lb.pack(side="left")
        scroll = tk.Scrollbar(body, command=lb.yview)
        scroll.pack(side="left", fill="y")
        lb.config(yscrollcommand=scroll.set)
        empty = tk.Label(win, bg="#0b1020", fg=COLORS["dim"],
                         font=("Consolas", self.FS(10)),
                         text="No saved levels yet - build one in the "
                              "editor.")

        def refresh():
            lb.delete(0, "end")
            for i, lv in enumerate(self.save["custom"]):
                gi = len(LEVELS) + i
                stars = self.save["stars"].get(str(gi), 0)
                got = int(self.save["cores"].get(str(gi), 0))
                total = len(lv.get("cores", []))
                lb.insert("end",
                          f"{lv['name']}  -  {stars}*  {got}/{total} cores")
            if self.save["custom"]:
                empty.pack_forget()
            else:
                empty.pack(padx=14, pady=4)

        refresh()

        def selected():
            sel = lb.curselection()
            return sel[0] if sel else None

        def go_play():
            i = selected()
            if i is None:
                return
            win.destroy()
            self.load_level(len(LEVELS) + i)
            self.sync_ui()

        def go_edit():
            i = selected()
            if i is None:
                return
            win.destroy()
            self.load_level(len(LEVELS) + i)
            self.enter_editor()

        def go_share():
            i = selected()
            if i is None:
                return
            win.destroy()
            self.load_level(len(LEVELS) + i)
            self.share_level()

        def go_rename():
            i = selected()
            if i is None:
                return
            lv = self.save["custom"][i]
            dlg = tk.Toplevel(win)
            dlg.title("Rename level")
            dlg.resizable(False, False)
            dlg.configure(bg="#0b1020")
            tk.Label(dlg, bg="#0b1020", fg=COLORS["text"],
                     font=("Consolas", self.FS(11), "bold"),
                     text="Rename level").pack(padx=14, pady=(12, 2))
            entry = tk.Entry(dlg, width=32, bg="#16213c",
                             fg=COLORS["text"],
                             insertbackground="#dbe7ff", relief="flat",
                             font=("Consolas", self.FS(10)))
            entry.insert(0, lv["name"])
            entry.pack(padx=14, pady=8)
            entry.select_range(0, "end")
            entry.focus_set()
            dlg.grab_set()

            def do_rename(_event=None):
                name = entry.get().strip()[:60]
                if name:
                    lv["name"] = name
                    self.store_save()
                    refresh()
                    self.sync_ui()
                dlg.destroy()

            entry.bind("<Return>", do_rename)
            btns = tk.Frame(dlg, bg="#0b1020")
            btns.pack(pady=(0, 12))
            tk.Button(btns, text="Rename", command=do_rename, bg="#16213c",
                      fg=COLORS["text"], activebackground="#22335c",
                      relief="flat", padx=12, pady=4,
                      takefocus=0).pack(side="left", padx=4)
            tk.Button(btns, text="Cancel", command=dlg.destroy,
                      bg="#16213c", fg=COLORS["text"],
                      activebackground="#22335c", relief="flat", padx=12,
                      pady=4, takefocus=0).pack(side="left", padx=4)

        def go_delete():
            i = selected()
            if i is None:
                return
            lv = self.save["custom"][i]
            if not messagebox.askyesno(
                    "Delete saved level",
                    f"Delete '{lv['name']}'?\n\nThis cannot be undone."):
                return
            self._delete_custom(len(LEVELS) + i)
            refresh()
            self.sync_ui()

        def go_save_file():
            i = selected()
            if i is None:
                return
            lv = self.save["custom"][i]
            safe = "".join(ch if ch.isalnum() or ch in " -_"
                           else "_" for ch in lv["name"]).strip() or "level"
            path = filedialog.asksaveasfilename(
                defaultextension=".orbital",
                filetypes=[("Orbital level", "*.orbital"),
                           ("All files", "*.*")],
                initialfile=f"{safe}.orbital")
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(level_to_code(lv))
            except OSError as exc:
                messagebox.showerror("Save level",
                                     f"Could not save the file:\n{exc}")
                return
            self.message = (f"Saved '{lv['name']}' to "
                            f"{os.path.basename(path)}.")
            self.sync_ui()

        def go_load_file():
            path = filedialog.askopenfilename(
                filetypes=[("Orbital level", "*.orbital"),
                           ("JSON", "*.json"),
                           ("All files", "*.*")])
            if not path:
                return
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except OSError as exc:
                messagebox.showerror("Load level",
                                     f"Could not read the file:\n{exc}")
                return
            lv, err = self._import_file(text)
            if err:
                messagebox.showerror("Load level", err)
                return
            refresh()
            self.message = (f"Imported '{lv['name']}' - it now lives "
                            "after the campaign in the pager.")
            self.sync_ui()

        row = tk.Frame(win, bg="#0b1020")
        row.pack(pady=(6, 2))
        for text, cmd in (("Play", go_play), ("Edit", go_edit),
                          ("Share", go_share), ("Rename", go_rename),
                          ("Delete", go_delete)):
            tk.Button(row, text=text, command=cmd, bg="#16213c",
                      fg=COLORS["text"], activebackground="#22335c",
                      relief="flat", padx=12, pady=4,
                      takefocus=0).pack(side="left", padx=4)
        row2 = tk.Frame(win, bg="#0b1020")
        row2.pack(pady=(2, 12))
        tk.Button(row2, text="Save to file", command=go_save_file,
                  bg="#16213c", fg=COLORS["text"],
                  activebackground="#22335c", relief="flat", padx=12,
                  pady=4, takefocus=0).pack(side="left", padx=4)
        tk.Button(row2, text="Load from file", command=go_load_file,
                  bg="#16213c", fg=COLORS["text"],
                  activebackground="#22335c", relief="flat", padx=12,
                  pady=4, takefocus=0).pack(side="left", padx=4)
        tk.Button(row2, text="Close", command=win.destroy, bg="#16213c",
                  fg=COLORS["text"], activebackground="#22335c",
                  relief="flat", padx=12, pady=4,
                  takefocus=0).pack(side="left", padx=4)

    def clear_ghost(self):
        """Remove the saved best-run ghost line for the open level.
        The line is just a visual guide - clearing it changes nothing
        else, and the next docked run that beats the old mark records
        a fresh ghost as usual."""
        if self.mode == "editor":
            return
        key = str(self.level_i)
        if key in self.save["ghost"]:
            del self.save["ghost"][key]
            self.store_save()
            self.message = "Ghost cleared for this level."
        else:
            self.message = "This level has no ghost to clear."
        self.sync_ui()

    def delete_saved_level(self):
        """Delete the user-made level that is currently open. Only
        levels saved from the editor can be deleted - campaign levels
        and session levels (Random / playtest) cannot. Records keyed
        by level index shift down so they stay with their level."""
        if self.mode == "editor":
            return
        start = len(LEVELS)
        if not (start <= self.level_i < start + len(self.save["custom"])):
            self.message = ("Open one of your saved levels in the pager "
                            "first - only those can be deleted.")
            self.sync_ui()
            return
        name = self.lv["name"]
        if not messagebox.askyesno(
                "Delete saved level",
                f"Delete '{name}'?\n\nThis cannot be undone."):
            return
        gone = self.level_i
        self._delete_custom(gone)
        self.message = f"Deleted '{name}'."
        self.sync_ui()

    def editor_clear(self):
        self.editor = self._fresh_editor({
            "start": (80, 300), "target": (880, 300),
            "planets": [{"x": 480, "y": 300, "r": 30,
                         "color": PLANET_COLORS[0], "label": "P1"}],
            "cores": [], "wormholes": [], "barriers": []})
        self._playtest_pos = None
        # a blank level gets blank fields: leaving the old level's
        # name / par / burns in place made Clear save under the
        # old level's identity
        self.ed_name.delete(0, "end")
        self.ed_sub.delete(0, "end")
        self.ed_par.delete(0, "end")
        self.ed_par.insert(0, "2")
        self.ed_burns.delete(0, "end")
        self.ed_burns.insert(0, "4")
        self.ed_dirty = True

    def rename_planet(self):
        """Rename the selected planet (editor). The label is what the
        play field shows under it, and it travels with the level
        through save / playtest / share."""
        ed = self.editor
        if ed is None or ed["sel"] is None \
                or ed["sel"] >= len(ed["planets"]):
            return
        p = ed["planets"][ed["sel"]]
        win = tk.Toplevel(self.root)
        win.title("Rename planet")
        win.resizable(False, False)
        win.configure(bg="#0b1020")
        tk.Label(win, bg="#0b1020", fg=COLORS["text"],
                 font=("Consolas", self.FS(11), "bold"),
                 text="Rename planet").pack(padx=14, pady=(12, 2))
        entry = tk.Entry(win, width=24, bg="#16213c", fg=COLORS["text"],
                         insertbackground="#dbe7ff", relief="flat",
                         font=("Consolas", self.FS(10)))
        entry.insert(0, p["label"])
        entry.pack(padx=14, pady=8)
        entry.select_range(0, "end")
        entry.focus_set()
        win.grab_set()

        def do_rename(_event=None):
            name = entry.get().strip()[:18]
            if name:
                p["label"] = name
                self.ed_dirty = True
            win.destroy()

        entry.bind("<Return>", do_rename)
        btns = tk.Frame(win, bg="#0b1020")
        btns.pack(pady=(0, 12))
        tk.Button(btns, text="Rename", command=do_rename, bg="#16213c",
                  fg=COLORS["text"], activebackground="#22335c",
                  relief="flat", padx=12, pady=4,
                  takefocus=0).pack(side="left", padx=4)
        tk.Button(btns, text="Cancel", command=win.destroy, bg="#16213c",
                  fg=COLORS["text"], activebackground="#22335c",
                  relief="flat", padx=12, pady=4,
                  takefocus=0).pack(side="left", padx=4)

    @staticmethod
    def _ed_sync_orbit_pos(p):
        """An editor planet's x/y always holds its position at t=0,
        so hit tests and drawing work the same for orbiting planets."""
        orb = p.get("orbit")
        if orb:
            p["x"] = round(orb["cx"] + math.cos(orb["phase"])
                           * orb["radius"])
            p["y"] = round(orb["cy"] + math.sin(orb["phase"])
                           * orb["radius"])

    def ed_press(self, gx, gy, shift=False):
        ed = self.editor
        if ed is None:
            return
        tool = self.ed_tool.get()
        gx = max(10.0, min(WIDTH - 10.0, gx))
        gy = max(10.0, min(HEIGHT - 10.0, gy))
        if tool == "planet":
            for i, p in enumerate(ed["planets"]):
                if math.hypot(gx - p["x"], gy - p["y"]) <= p["r"] + 4:
                    if shift:
                        # Shift+click toggles a repulsor (pushes
                        # instead of pulls) on the clicked planet.
                        if p.get("repel"):
                            del p["repel"]
                        else:
                            p["repel"] = True
                        ed["sel"] = i
                        self.ed_dirty = True
                        return
                    ed["drag"] = i
                    ed["sel"] = i
                    self.ed_dirty = True
                    return
            n = len(ed["planets"])
            if n < 24:
                ed["planets"].append(
                    {"x": round(gx), "y": round(gy), "r": 26,
                     "color": PLANET_COLORS[n % len(PLANET_COLORS)],
                     "label": f"P{n + 1}"})
                ed["sel"] = n
        elif tool == "start":
            if not point_in_barriers(gx, gy, ed["barriers"]) \
                    and not _ed_on_planet(ed, gx, gy):
                ed["start"] = [round(gx), round(gy)]
        elif tool == "target":
            if not point_in_barriers(gx, gy, ed["barriers"]) \
                    and not _ed_on_planet(ed, gx, gy):
                ed["target"] = [round(gx), round(gy)]
        elif tool == "core":
            if len(ed["cores"]) < 24:
                ed["cores"].append([round(gx), round(gy)])
        elif tool == "wormhole":
            if ed["worm_next"] is None:
                ed["worm_next"] = [round(gx), round(gy)]
            elif len(ed["wormholes"]) < 8:
                ed["wormholes"].append(ed["worm_next"] + [round(gx),
                                                          round(gy)])
                ed["worm_next"] = None
            else:
                # at the cap: the second mouth is refused, so the
                # half-placed first mouth is dropped too - leaving
                # it pending left the tool stuck, refusing every
                # further click with no way to cancel it
                ed["worm_next"] = None
        elif tool == "orbit":
            if ed["orbit_next"] is not None \
                    and ed["orbit_next"] >= len(ed["planets"]):
                ed["orbit_next"] = None   # the planet it pointed at is gone
            if ed["orbit_next"] is not None:
                i = ed["orbit_next"]
                p = ed["planets"][i]
                if math.hypot(gx - p["x"], gy - p["y"]) <= p["r"] + 4:
                    ed["orbit_next"] = None      # clicked it again: cancel
                else:
                    radius = max(30.0, min(380.0, math.hypot(
                        gx - p["x"], gy - p["y"])))
                    p["orbit"] = {
                        "cx": round(gx), "cy": round(gy),
                        "radius": round(radius, 1),
                        "speed": 0.25,
                        "phase": round(math.atan2(p["y"] - gy,
                                                  p["x"] - gx), 4)}
                    p.pop("path", None)   # one motion type per planet
                    ed["orbit_next"] = None
                    ed["sel"] = i
            else:
                for i, p in enumerate(ed["planets"]):
                    if math.hypot(gx - p["x"], gy - p["y"]) <= p["r"] + 4:
                        ed["sel"] = i
                        if "orbit" in p:
                            del p["orbit"]       # click again: stop it
                        else:
                            ed["orbit_next"] = i
                        break
        elif tool == "path":
            hit = None
            for i, p in enumerate(ed["planets"]):
                if math.hypot(gx - p["x"], gy - p["y"]) <= p["r"] + 4:
                    hit = i
                    break
            if ed["path_next"] is not None \
                    and ed["path_next"] >= len(ed["planets"]):
                ed["path_next"] = None   # the planet it pointed at is gone
            if ed["path_next"] is not None:
                i = ed["path_next"]
                p = ed["planets"][i]
                if hit == i:
                    # Clicked the armed planet again: finish. A path
                    # with fewer than 2 points is no path at all.
                    if "path" in p and len(p["path"]["pts"]) < 2:
                        del p["path"]
                    ed["path_next"] = None
                    ed["sel"] = i
                    self.ed_dirty = True
                    return
                if hit is None:
                    if "path" not in p:
                        p["path"] = {"pts": [[p["x"], p["y"]]],
                                     "speed": 60.0, "phase": 0.0}
                        p.pop("orbit", None)   # one motion type each
                    if len(p["path"]["pts"]) < 20:
                        p["path"]["pts"].append([round(gx), round(gy)])
                    self.ed_dirty = True
                    return
                # Clicked a different planet: finish this one, then
                # treat it as a fresh click on the new planet below.
                if "path" in p and len(p["path"]["pts"]) < 2:
                    del p["path"]
                ed["path_next"] = None
            if hit is not None:
                p = ed["planets"][hit]
                ed["sel"] = hit
                if shift and "path" in p:
                    # Shift+click a pathed planet: toggle LOOP - the
                    # planet rides its route in a circle, back to the
                    # start, instead of ping-ponging along it.
                    if p["path"].get("loop"):
                        del p["path"]["loop"]
                    else:
                        p["path"]["loop"] = True
                elif "path" in p:
                    del p["path"]        # click a pathed planet: stop it
                else:
                    ed["path_next"] = hit
                self.ed_dirty = True
                return
        elif tool == "barrier":
            if shift:
                # Shift+click lays down polygon corners, one per
                # click; releasing Shift finishes the shape (see
                # _on_shift_release). A barrier must be a real 2D
                # shape - two points is a line, and lines are not
                # allowed.
                if ed["barrier_poly"] is None:
                    ed["barrier_poly"] = []
                ed["barrier_poly"].append([round(gx), round(gy)])
                ed["barrier_rect"] = None
                ed["barrier_cur"] = None
                self.ed_dirty = True
                return
            # Plain click starts a rectangle drag (finished on
            # release by ed_release).
            ed["barrier_poly"] = None
            ed["barrier_rect"] = [round(gx), round(gy)]
            ed["barrier_cur"] = [round(gx), round(gy)]
            self.ed_dirty = True
            return
        elif tool == "delbarrier":
            if shift:
                if ed["delbarrier_poly"] is None:
                    ed["delbarrier_poly"] = []
                ed["delbarrier_poly"].append([round(gx), round(gy)])
                ed["delbarrier_rect"] = None
                ed["delbarrier_cur"] = None
                self.ed_dirty = True
                return
            ed["delbarrier_poly"] = None
            ed["delbarrier_rect"] = [round(gx), round(gy)]
            ed["delbarrier_cur"] = [round(gx), round(gy)]
            self.ed_dirty = True
            return
        elif tool == "erase":
            for i, p in enumerate(ed["planets"]):
                if math.hypot(gx - p["x"], gy - p["y"]) <= p["r"] + 4:
                    del ed["planets"][i]
                    ed["sel"] = None
                    ed["orbit_next"] = None   # indices just shifted
                    ed["path_next"] = None
                    self.ed_dirty = True
                    return
            for i, cr in enumerate(ed["cores"]):
                if math.hypot(gx - cr[0], gy - cr[1]) <= 14:
                    del ed["cores"][i]
                    self.ed_dirty = True
                    return
            for i, w in enumerate(ed["wormholes"]):
                if math.hypot(gx - w[0], gy - w[1]) <= 20 or \
                        math.hypot(gx - w[2], gy - w[3]) <= 20:
                    del ed["wormholes"][i]
                    self.ed_dirty = True
                    return
            ed["worm_next"] = None
        self.ed_dirty = True

    def _ed_finish_barrier_poly(self, erase):
        """Finish a pending barrier polygon (Shift released): the
        shape is closed by joining the last point back to the
        first, and kept only if it is a real 2D shape."""
        ed = self.editor
        if ed is None:
            return
        key = "delbarrier_poly" if erase else "barrier_poly"
        pts = ed[key]
        ed[key] = None
        if pts is None:
            return
        pts = clean_poly(pts)
        if len(pts) < 3 or abs(polygon_area(pts)) < BARRIER_MIN_AREA:
            return   # two points is a line, and a line is no barrier
        if not polygon_is_simple(pts):
            return   # a bowtie is not a real shape
        if erase:
            ed["barriers"] = erase_from_barriers(ed["barriers"], pts)
        else:
            if len(ed["barriers"]) >= BARRIER_MAX:
                return
            if point_in_polygon(ed["start"][0], ed["start"][1], pts) or \
                    point_in_polygon(ed["target"][0], ed["target"][1], pts):
                return   # a barrier on the pad or dock breaks the level
            ed["barriers"].append(pts)
        self.ed_dirty = True

    def _ed_finish_barrier_rect(self, erase):
        """Finish a rectangle drag (mouse released). A drag that is a
        straight line - no width or no height - makes no barrier."""
        ed = self.editor
        if ed is None:
            return
        key = "delbarrier_rect" if erase else "barrier_rect"
        curkey = "delbarrier_cur" if erase else "barrier_cur"
        start = ed[key]
        cur = ed[curkey]
        ed[key] = None
        ed[curkey] = None
        if start is None or cur is None:
            return
        x0, y0 = start
        x1, y1 = cur
        if abs(x1 - x0) < 8 or abs(y1 - y0) < 8:
            return
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        if erase:
            ed["barriers"] = erase_from_barriers(ed["barriers"],
                                                 (x0, y0, x1, y1))
        else:
            if len(ed["barriers"]) >= BARRIER_MAX:
                return
            pts = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
            if point_in_polygon(ed["start"][0], ed["start"][1], pts) or \
                    point_in_polygon(ed["target"][0], ed["target"][1], pts):
                return   # a barrier on the pad or dock breaks the level
            ed["barriers"].append(pts)
        self.ed_dirty = True

    def _on_shift_release(self, _event):
        """Releasing Shift finishes a pending barrier polygon: the
        shape is closed by joining the last point back to the
        first."""
        if self.mode != "editor" or self.editor is None:
            return
        w = self.root.focus_get()
        if isinstance(w, (tk.Entry, tk.Text)):
            return
        tool = self.ed_tool.get()
        if tool == "barrier" and self.editor["barrier_poly"]:
            self._ed_finish_barrier_poly(erase=False)
        elif tool == "delbarrier" and self.editor["delbarrier_poly"]:
            self._ed_finish_barrier_poly(erase=True)

    def _ed_tool_changed(self, *_args):
        """Switching tools drops any half-drawn barrier (a rectangle
        drag or a polygon in progress) - it belongs to the old tool -
        and any half-placed wormhole mouth."""
        ed = self.editor
        if ed is None:
            return
        ed["worm_next"] = None
        ed["barrier_poly"] = None
        ed["barrier_rect"] = None
        ed["barrier_cur"] = None
        ed["delbarrier_poly"] = None
        ed["delbarrier_rect"] = None
        ed["delbarrier_cur"] = None
        self.ed_dirty = True

    def ed_drag(self, gx, gy):
        ed = self.editor
        if ed is None:
            return
        if ed["barrier_rect"] is not None:
            ed["barrier_cur"] = [round(max(10.0, min(WIDTH - 10.0, gx))),
                                 round(max(10.0, min(HEIGHT - 10.0, gy)))]
            self.ed_dirty = True
            return
        if ed["delbarrier_rect"] is not None:
            ed["delbarrier_cur"] = [round(max(10.0, min(WIDTH - 10.0, gx))),
                                    round(max(10.0, min(HEIGHT - 10.0, gy)))]
            self.ed_dirty = True
            return
        if ed["drag"] is None:
            return
        p = ed["planets"][ed["drag"]]
        gx = max(30.0, min(WIDTH - 30.0, gx))
        gy = max(30.0, min(HEIGHT - 30.0, gy))
        if "path" in p:
            # Dragging a pathed planet moves its whole route.
            dx, dy = gx - p["x"], gy - p["y"]
            p["path"]["pts"] = [
                [round(max(0.0, min(WIDTH, qx + dx))),
                 round(max(0.0, min(HEIGHT, qy + dy)))]
                for (qx, qy) in p["path"]["pts"]]
            p["x"] = round(gx)
            p["y"] = round(gy)
        elif "orbit" in p:
            # Dragging an orbiting planet moves its whole orbit.
            orb = p["orbit"]
            orb["cx"] = round(max(0.0, min(WIDTH, orb["cx"]
                                           + (gx - p["x"]))))
            orb["cy"] = round(max(0.0, min(HEIGHT, orb["cy"]
                                           + (gy - p["y"]))))
            self._ed_sync_orbit_pos(p)
        else:
            p["x"] = round(gx)
            p["y"] = round(gy)
        self.ed_dirty = True

    def ed_release(self, _x, _y):
        if self.editor is None:
            return
        self.editor["drag"] = None
        if self.editor["barrier_rect"] is not None:
            self._ed_finish_barrier_rect(erase=False)
        elif self.editor["delbarrier_rect"] is not None:
            self._ed_finish_barrier_rect(erase=True)

    def ed_wheel(self, gx, gy, direction, shift=False):
        ed = self.editor
        if ed is None:
            return
        target = None
        for i, p in enumerate(ed["planets"]):
            if math.hypot(gx - p["x"], gy - p["y"]) <= p["r"] + 6:
                target = p
                ed["sel"] = i
                break
        if target is None and ed["sel"] is not None \
                and ed["sel"] < len(ed["planets"]):
            target = ed["planets"][ed["sel"]]
        if target is None:
            return
        if self.ed_tool.get() == "path" and "path" in target:
            pth = target["path"]
            pth["speed"] = round(max(5.0, min(300.0,
                                               pth["speed"]
                                               + direction * 5)), 1)
            self.ed_dirty = True
            return
        if self.ed_tool.get() == "orbit" and "orbit" in target:
            orb = target["orbit"]
            if shift:
                speed = orb["speed"] + direction * 0.05
                speed = max(-1.5, min(1.5, speed))
                if abs(speed) < 0.025:
                    speed = 0.05 if direction > 0 else -0.05
                orb["speed"] = round(speed, 2)
            else:
                orb["radius"] = round(max(30.0, min(380.0,
                                                     orb["radius"]
                                                     + direction * 5)), 1)
                self._ed_sync_orbit_pos(target)
            self.ed_dirty = True
            return
        target["r"] = max(12, min(70, target["r"] + direction * 2))
        self.ed_dirty = True

    def draw_editor(self):
        ed = self.editor
        if ed is None:
            return
        sel_planet = ed["sel"] is not None \
            and ed["sel"] < len(ed["planets"])
        self.ed_rename_btn.config(
            state="normal" if sel_planet else "disabled")
        c = self.canvas
        X = self.X
        c.delete("all")
        for (sx, sy, sr, col) in self.stars_far:
            c.create_oval(X(sx - sr), X(sy - sr), X(sx + sr), X(sy + sr),
                          fill=col, outline="")
        for w in ed["wormholes"]:
            for (wx, wy) in ((w[0], w[1]), (w[2], w[3])):
                c.create_oval(X(wx - 20), X(wy - 20), X(wx + 20),
                              X(wy + 20), outline=COLORS["warp"], width=2)
                c.create_oval(X(wx - 4), X(wy - 4), X(wx + 4), X(wy + 4),
                              fill=COLORS["warp"], outline="")
        for pts in ed["barriers"]:
            c.create_polygon(*[X(v) for q in pts for v in q],
                             fill=BARRIER_FILL, outline="")
        # in-progress barrier rectangle / polygon (dashed, red for a
        # wall, orange for the cutter)
        for rkey, ckey, pkey, col in (
                ("barrier_rect", "barrier_cur", "barrier_poly",
                 COLORS["danger"]),
                ("delbarrier_rect", "delbarrier_cur", "delbarrier_poly",
                 "#ff9a3c")):
            if ed[rkey] is not None and ed[ckey] is not None:
                x0, y0 = ed[rkey]
                x1, y1 = ed[ckey]
                c.create_rectangle(X(min(x0, x1)), X(min(y0, y1)),
                                   X(max(x0, x1)), X(max(y0, y1)),
                                   outline=col, width=2, dash=(4, 3))
            poly = ed[pkey]
            if poly:
                if len(poly) >= 2:
                    c.create_line(*[X(v) for q in poly for v in q],
                                  fill=col, width=2, dash=(4, 3))
                for (qx, qy) in poly:
                    c.create_oval(X(qx - 3), X(qy - 3), X(qx + 3),
                                  X(qy + 3), outline=col, width=1)
        if ed["worm_next"]:
            wx, wy = ed["worm_next"]
            c.create_oval(X(wx - 20), X(wy - 20), X(wx + 20), X(wy + 20),
                          outline=COLORS["danger"], width=2)
        for i, p in enumerate(ed["planets"]):
            orb = p.get("orbit")
            if orb:
                cx, cy, orad = orb["cx"], orb["cy"], orb["radius"]
                c.create_oval(X(cx - orad), X(cy - orad), X(cx + orad),
                              X(cy + orad), outline=COLORS["dim"],
                              width=1, dash=(4, 4))
                c.create_oval(X(cx - 3), X(cy - 3), X(cx + 3), X(cy + 3),
                              outline=COLORS["dim"], width=1)
                c.create_line(X(cx), X(cy), X(p["x"]), X(p["y"]),
                              fill=COLORS["dim"], dash=(2, 3))
            if ed.get("orbit_next") == i:
                r0 = p["r"]
                c.create_oval(X(p["x"] - r0 - 10), X(p["y"] - r0 - 10),
                              X(p["x"] + r0 + 10), X(p["y"] + r0 + 10),
                              outline=COLORS["danger"], width=2,
                              dash=(3, 3))
            if p.get("path"):
                pts = p["path"]["pts"]
                if len(pts) >= 2:
                    route = pts + [pts[0]] if p["path"].get("loop") else pts
                    flat = [X(v) for q in route for v in q]
                    c.create_line(*flat, fill=COLORS["dim"], width=1,
                                  dash=(4, 4))
                for (qx, qy) in pts:
                    c.create_oval(X(qx - 3), X(qy - 3), X(qx + 3),
                                  X(qy + 3), outline=COLORS["dim"],
                                  width=1)
            if ed.get("path_next") == i:
                r0 = p["r"]
                c.create_oval(X(p["x"] - r0 - 10), X(p["y"] - r0 - 10),
                              X(p["x"] + r0 + 10), X(p["y"] + r0 + 10),
                              outline=COLORS["danger"], width=2,
                              dash=(3, 3))
        for i, p in enumerate(ed["planets"]):
            r = p["r"]
            if ed["sel"] == i:
                c.create_oval(X(p["x"] - r - 6), X(p["y"] - r - 6),
                              X(p["x"] + r + 6), X(p["y"] + r + 6),
                              outline=COLORS["probe"], width=1, dash=(3, 3))
            c.create_oval(X(p["x"] - r), X(p["y"] - r), X(p["x"] + r),
                          X(p["y"] + r), fill=p["color"],
                          outline="#ffd9a8" if p.get("repel") else "#cdd8ff",
                          width=1)
            if p.get("repel"):
                c.create_oval(X(p["x"] - r * 1.7), X(p["y"] - r * 1.7),
                              X(p["x"] + r * 1.7), X(p["y"] + r * 1.7),
                              outline="#ff9a3c", width=2, dash=(4, 3))
            label = f'{p["label"]} r{r}'
            if p.get("repel"):
                label += " - REPEL"
            if p.get("path"):
                label += (f' - path {len(p["path"]["pts"])}pts'
                          f' speed {p["path"]["speed"]:.0f}')
                if p["path"].get("loop"):
                    label += " LOOP"
            if p.get("orbit"):
                label += (f' - orbit {p["orbit"]["radius"]:.0f}'
                          f' speed {p["orbit"]["speed"]:+.2f}')
            c.create_text(X(p["x"]), X(p["y"] + r + 14),
                          text=label, fill=COLORS["dim"],
                          font=("Consolas", self.FS(9)))
        sx, sy = ed["start"]
        tx, ty = ed["target"]
        c.create_oval(X(sx - 12), X(sy - 12), X(sx + 12), X(sy + 12),
                      outline=COLORS["dim"], width=2)
        c.create_text(X(sx), X(sy + 24), text="PAD", fill=COLORS["dim"],
                      font=("Consolas", self.FS(9)))
        c.create_oval(X(tx - DOCK_RADIUS), X(ty - DOCK_RADIUS),
                      X(tx + DOCK_RADIUS), X(ty + DOCK_RADIUS),
                      outline=COLORS["station"], width=3)
        c.create_oval(X(tx - 5), X(ty - 5), X(tx + 5), X(ty + 5),
                      fill=COLORS["station"], outline="")
        c.create_text(X(tx), X(ty + DOCK_RADIUS + 14), text="DOCK",
                      fill=COLORS["station"], font=("Consolas", self.FS(9)))
        for (cx, cy) in ed["cores"]:
            c.create_polygon(X(cx), X(cy - 8), X(cx + 6), X(cy), X(cx),
                             X(cy + 8), X(cx - 6), X(cy),
                             fill=COLORS["core"], outline="")


# ----------------------------------------------------------------------
# RANDOM MISSION GENERATOR - build by construction: fly a design line
# first and put the station on the path it actually flew, then put
# the cores on a second, differently-arced line that also docks -
# collecting them takes that detour instead of riding the one obvious
# line. A level is handed over only
# once a single launch is verified to dock and collect every core, so
# it is always beatable.
# ----------------------------------------------------------------------
def _dense_flight(specs, start, vx, vy, target, cores=(), seconds=14.0,
                  wormholes=(), barriers=()):
    """Simulate one launch exactly the way the game flies it: planets
    are snapshotted at the flight time of each step (so orbiting and
    patrolling planets move), and wormholes teleport with the game's
    cooldown. Static levels keep the cheap single snapshot."""
    x, y = float(start[0]), float(start[1])
    moving = any(sp.get("orbit") or sp.get("path") for sp in specs)
    planets = planet_snapshot(specs, 0.0)
    pts = [(x, y)]
    got = [False] * len(cores)
    cd = 0.0
    last_pair = -1
    for i in range(int(seconds / PHYS_DT)):
        if moving:
            planets = planet_snapshot(specs, (i + 1) * PHYS_DT)
        x, y, vx, vy = step_physics(x, y, vx, vy, planets, PHYS_DT)
        cd = max(0.0, cd - PHYS_DT)
        if wormholes:
            x, y, warped, k = wormhole_step(
                x, y, wormholes, skip=last_pair if cd > 0.0 else -1)
            if warped:
                cd = WORMHOLE_COOLDOWN
                last_pair = k
        pts.append((x, y))
        for i, (cx, cy) in enumerate(cores):
            if not got[i] and (x - cx) ** 2 + (y - cy) ** 2 <= CORE_RADIUS ** 2:
                got[i] = True
        outcome = check_hit(x, y, planets, target, barriers)
        if outcome:
            return outcome, pts, got
        if x < -350 or x > WIDTH + 350 or y < -350 or y > HEIGHT + 350:
            # Far outside the field the planets' pull is negligible,
            # so the probe is effectively ballistic and will not come
            # back in time - stop burning steps on a lost flight.
            return "timeout", pts, got
    return "timeout", pts, got


def _cores_on_detour(pts_b, planets, start, station, pts_a, fracs):
    """Place the cores on a second flight path (line B) that also
    docks but arcs differently from the design line A: the cores sit
    on B's route, off A's, so the obvious line leaves them behind and
    collecting them takes the detour. Returns None when the placement
    breaks a fairness rule (inside a planet's crash zone, on the
    start or station, on the straight start->station axis, back on
    line A's route, nearly in a line themselves, or outside the
    field where nobody could see them)."""
    cores = []
    total = len(pts_b)
    for frac in fracs:
        cx, cy = pts_b[int(total * frac)]
        cores.append((round(cx), round(cy)))
    ax, ay = station[0] - start[0], station[1] - start[1]
    alen = math.hypot(ax, ay) or 1.0
    for (x, y) in cores:
        if not (34 <= x <= WIDTH - 34 and 34 <= y <= HEIGHT - 34):
            return None
        if any(math.hypot(x - px, y - py) < r + 26
               for (px, py, r) in planets):
            return None
        if math.hypot(x - start[0], y - start[1]) < 60:
            return None
        if math.hypot(x - station[0], y - station[1]) < 46:
            return None
        if abs((x - start[0]) * ay - (y - start[1]) * ax) / alen < 30:
            return None
        if min(math.hypot(x - qx, y - qy) for (qx, qy) in pts_a[::4]) < 26:
            return None
    for a in range(len(cores)):
        for b in range(a + 1, len(cores)):
            if math.hypot(cores[a][0] - cores[b][0],
                          cores[a][1] - cores[b][1]) < 55:
                return None
    if len(cores) >= 3:
        (x1, y1) = cores[0]
        (x2, y2) = cores[len(cores) // 2]
        (x3, y3) = cores[-1]
        if abs(x1 * (y2 - y3) + x2 * (y3 - y1)
               + x3 * (y1 - y2)) / 2 < 900:
            return None
    return cores


def _seg_point_dist(ax, ay, bx, by, px, py):
    """Distance from point P to segment AB."""
    dx, dy = bx - ax, by - ay
    ll = dx * dx + dy * dy
    if ll <= 0:
        return math.hypot(px - ax, py - ay)
    f = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ll))
    return math.hypot(px - (ax + dx * f), py - (ay + dy * f))


def _add_motion(rng, specs, planets, idx, start):
    """Give one planet of a random level an orbit or a patrol path.
    Returns False (leaving it static) when neither fits cleanly: the
    swept disc / route must stay in the field, off the launch pad,
    and clear of the other planets."""
    sp = specs[idx]
    px, py, r = planets[idx]
    others = [(qx, qy, qr)
              for j, (qx, qy, qr) in enumerate(planets) if j != idx]
    if rng.random() < 0.50:
        max_r = min(px - r - 12, WIDTH - r - 12 - px,
                    py - r - 12, HEIGHT - r - 12 - py,
                    math.hypot(px - start[0], py - start[1]) - r - 70)
        for (qx, qy, qr) in others:
            max_r = min(max_r,
                        math.hypot(px - qx, py - qy) - r - qr - 10)
        if max_r < 42:
            return False
        radius = rng.uniform(42, min(115.0, max_r))
        speed = rng.uniform(0.25, 0.6) * rng.choice([-1, 1])
        phase = rng.uniform(0, math.tau)
        sp["orbit"] = {"cx": round(px), "cy": round(py),
                       "radius": round(radius, 1),
                       "speed": round(speed, 3),
                       "phase": round(phase, 3)}
        sp["x"] = round(px + math.cos(phase) * radius)
        sp["y"] = round(py + math.sin(phase) * radius)
        return True
    pts = [[round(px), round(py)]]
    for _ in range(rng.choice([1, 2, 2, 3])):
        placed = False
        for _try in range(30):
            wx = min(max(px + rng.uniform(-260, 260), 40), WIDTH - 40)
            wy = min(max(py + rng.uniform(-260, 260), 40), HEIGHT - 40)
            lx, ly = pts[-1]
            if math.hypot(wx - lx, wy - ly) < 110:
                continue
            if any(math.hypot(wx - qx, wy - qy) < qr + r + 8
                   for (qx, qy, qr) in others):
                continue
            if any(_seg_point_dist(lx, ly, wx, wy, qx, qy) < qr + r + 6
                   for (qx, qy, qr) in others):
                continue
            if _seg_point_dist(lx, ly, wx, wy,
                               start[0], start[1]) < r + 30:
                continue
            pts.append([round(wx), round(wy)])
            placed = True
            break
        if not placed:
            break
    if len(pts) < 2:
        return False
    path = {"pts": pts, "speed": round(rng.uniform(40, 85), 1),
            "phase": round(rng.random(), 3)}
    if len(pts) >= 3 and rng.random() < 0.3:
        path["loop"] = True
    sp["path"] = path
    return True


def _random_features(rng, specs, planets, start):
    """Roll a random level's twists: repulsors, one moving planet
    (orbit or path), and maybe a wormhole pair. Mutates the specs and
    returns the wormhole list. Most levels stay classic, and anything
    that cannot be placed cleanly is skipped."""
    n_repel = 0
    for sp in specs:
        if n_repel < 2 and rng.random() < 0.15:
            sp["repel"] = True
            n_repel += 1
    if rng.random() < 0.38:
        order = list(range(len(specs)))
        rng.shuffle(order)
        for idx in order:
            if _add_motion(rng, specs, planets, idx, start):
                break
    wormholes = []
    if rng.random() < 0.30:
        for _try in range(40):
            ax, ay = (rng.uniform(60, WIDTH - 60),
                      rng.uniform(60, HEIGHT - 60))
            bx, by = (rng.uniform(60, WIDTH - 60),
                      rng.uniform(60, HEIGHT - 60))
            if math.hypot(bx - ax, by - ay) < 300:
                continue
            ok = True
            for (mx, my) in ((ax, ay), (bx, by)):
                if math.hypot(mx - start[0], my - start[1]) < 90:
                    ok = False
                if any(math.hypot(mx - px, my - py) < r + 34
                       for (px, py, r) in planets):
                    ok = False
            if ok:
                wormholes = [(round(ax), round(ay),
                              round(bx), round(by))]
                break
    return wormholes


def generate_random_level():
    seed = random.randrange(100000)
    rng = random.Random(seed)
    budget = [900]
    deadline = time.time() + 1.4   # the Random button must stay snappy:
                                   # past the deadline, stop searching
                                   # and settle for a simpler layout
    for _attempt in range(80):
        if time.time() > deadline:
            budget[0] = 0
        n = rng.choice([2, 3, 3, 4, 4, 5])
        start = (rng.uniform(50, 110), rng.uniform(90, 510))
        planets = []
        tries = 0
        while len(planets) < n and tries < 90:
            tries += 1
            px, py = rng.uniform(170, 800), rng.uniform(85, 515)
            r = rng.uniform(18, 38)
            if math.hypot(px - start[0], py - start[1]) < r + 130:
                continue
            if any(math.hypot(px - qx, py - qy) < r + qr + 70
                   for (qx, qy, qr) in planets):
                continue
            planets.append((px, py, r))
        if len(planets) < n:
            continue
        specs = [{"x": px, "y": py, "r": r,
                  "color": PLANET_COLORS[i % len(PLANET_COLORS)],
                  "label": f"R{i + 1}"}
                 for i, (px, py, r) in enumerate(planets)]
        wormholes = _random_features(rng, specs, planets, start)
        base = math.atan2(300 - start[1], 480 - start[0])
        ang = base + rng.uniform(-0.55, 0.55)
        power = rng.uniform(95, 205)
        vx, vy = math.cos(ang) * power, math.sin(ang) * power
        _outcome, pts, _got = _dense_flight(specs, start, vx, vy,
                                            (-9999, -9999), seconds=12.0,
                                            wormholes=wormholes)
        total = len(pts)
        if total < 300:
            continue
        cand = []
        for i in range(int(total * 0.45), total - 1, 6):
            px, py = pts[i]
            if not (45 <= px <= WIDTH - 45 and 45 <= py <= HEIGHT - 45):
                continue   # the design flight can leave the field; the
                           # station must not - it would be invisible
            if all(math.hypot(px - qx, py - qy) > qr + 50
                   for (qx, qy, qr) in planets):
                cand.append(i)
        if not cand:
            continue
        si = rng.choice(cand)
        station = pts[si]
        n_cores = rng.choice([2, 3, 3, 4, 5])
        fracs = [0.25 + 0.57 * i / (n_cores - 1) for i in range(n_cores)]
        cores = None
        a0 = math.atan2(vy, vx)
        p0 = math.hypot(vx, vy)
        for da_deg in (6, -6, 9, -9, 12, -12, 16, -16, 20, -20,
                       25, -25, 30, -30):
            if cores is not None or budget[0] <= 0:
                break
            for f in (1.0, 0.93, 1.07, 0.86, 1.15):
                if budget[0] <= 0:
                    break
                budget[0] -= 1
                ang_b = a0 + math.radians(da_deg)
                pow_b = p0 * f
                outcome_b, pts_b, _g = _dense_flight(
                    specs, start, math.cos(ang_b) * pow_b,
                    math.sin(ang_b) * pow_b, station, seconds=12.0,
                    wormholes=wormholes)
                if outcome_b != "dock":
                    continue
                placed = None
                for shift in (0.0, -0.07, 0.07):
                    fset = [min(max(fr + shift, 0.08), 0.92)
                            for fr in fracs]
                    placed = _cores_on_detour(pts_b, planets, start,
                                              station, pts, fset)
                    if placed is not None:
                        break
                if placed is None:
                    continue
                outcome_c, _p2, got_c = _dense_flight(
                    specs, start, math.cos(ang_b) * pow_b,
                    math.sin(ang_b) * pow_b, station, cores=placed,
                    seconds=12.0, wormholes=wormholes)
                if outcome_c == "dock" and all(got_c):
                    cores = placed
                    break
        if cores is None:
            if budget[0] > 150:
                continue   # budget remains: try a fresh layout rather
                           # than settle for cores lined up on the path
            cores = []
            in_bounds = True
            for frac in fracs:
                cx, cy = pts[int(si * frac)]
                if not (34 <= cx <= WIDTH - 34
                        and 34 <= cy <= HEIGHT - 34):
                    in_bounds = False
                cores.append((round(cx), round(cy)))
            if not in_bounds:
                if time.time() > deadline:
                    break
                continue
            outcome, _p, got = _dense_flight(specs, start, vx, vy,
                                             station, cores=cores,
                                             seconds=12.0,
                                             wormholes=wormholes)
            if not (outcome == "dock" and all(got)):
                if time.time() > deadline:
                    break
                continue
        # Bigger fields earn more burns: 2-3 planets keep the classic
        # 3 burns, then the budget matches the planet count.
        max_burns = max(3, len(planets))
        level = {"name": f"Random #{seed}",
                 "sub": "A generated mission - verified beatable "
                        "before it reached you.",
                 "start": (round(start[0]), round(start[1])),
                 "target": (round(station[0]), round(station[1])),
                 "par": max_burns // 2, "max_burns": max_burns,
                 "planets": specs,
                 "cores": cores}
        if wormholes:
            level["wormholes"] = wormholes
        return level
    lv = dict(LEVELS[0])   # fallback: a renamed First Light
    lv["name"] = f"Random #{seed}"
    lv["sub"] = "A generated mission - verified beatable before it reached you."
    return lv


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
    # DPI awareness first (Windows): without it, Windows bitmap-stretches
    # the window by the display scale (150% on some setups), which blurs
    # everything and can push the bottom rows off the screen. With it,
    # the game renders at native pixels and Tk sizes the window itself.
    if sys.platform.startswith("win"):
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    if not acquire_single_instance():
        focus_existing_window()
        return
    root = tk.Tk()
    OrbitalGame(root)
    root.mainloop()


if __name__ == "__main__":
    main()
