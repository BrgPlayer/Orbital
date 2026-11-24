# Orbital — gravity slingshot puzzles (Python edition)

The full port of the Orbital web game as a standalone Python program:
the web edition's **8 missions** (First Light, Twin Pull, The Gate,
Heavy Heart, S-Curve, The Well, Crossfire, Homecoming) with the same
planet layouts, gravity, burn model and star rules — plus **8 more
missions built for this edition** (The Loop, Thread the Needle, Long
Haul, Slalom, Twin Suns, Low Orbit, Crosswind, The Gauntlet), for 16
total. Every mission's cores sit on a solver-verified winning line, so
a 3-star run can always collect them all. **No installs needed** —
standard library only (tkinter).

## Run it

```
python orbital.py
```

(There's also a packaged `Orbital.exe` — same game, double-click to
play. Progress is saved to `orbital_save.json` next to the program:
unlocked missions, best star ratings, and the best core count per
mission, counted only from completed (docked) runs. The mission
header shows "Best cores" next to the best stars.)

## How to play

- **Drag** to aim the probe, or use the **Angle / Power sliders** (arrow
  keys fine-tune). The dotted line is a live simulation of the real
  gravity. A fresh mission shows **no aim** — nothing is drawn until
  you aim it yourself.
- **Space** is the only trigger. Releasing the mouse only aims — it
  never launches and never fires.
- Launch counts as **burn #1**. During flight, drag to aim a correction
  burn (time freezes while a burn is aimed), Space to fire it. The
  **sliders aim burns too** — Angle sets the direction, Power the
  strength. Burns are limited per mission; the pips track them.
- Dock in as few burns as possible: at or under par = 3 stars, one
  over = 2, otherwise 1. Cyan **data cores** are optional pickups,
  reported on the results panel.
- Flights end after **25 seconds**. **Esc** pauses. **R** resets,
  **P** / **N** go to the previous / next mission. The **< Level N >** pager under
  the buttons switches missions too (the arrow greys out when the next
  mission is locked), and the Preview / Sound toggles are in the slider
  row.

## Make it yours

- `CONFIG` at the top of `orbital.py`: field size, power range, burn
  strength, dock radius, flight timeout, gravity softening. Gravity
  scales with planet size: `mu = GRAV_K * radius^2` (GRAV_K = 300), so
  bigger planets always pull harder; enforced when a level loads.
- `LEVELS`: the 16 mission layouts — planet positions, sizes, labels
  and colors, start/target, cores, burn counts, par.
- The physics (`gravity_at`, `step_physics`, `predict_path`) is pure
  and separate from the UI, so it's easy to experiment with.

Built with **Muse** (Meta AI) on 2026-11-23 — first as a web game,
then ported to Python the same day and aligned mission-for-mission
with the web edition.
