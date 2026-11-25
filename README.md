# Orbital — gravity slingshot puzzles (Python edition)

A standalone Python program: slingshot a probe around planets and dock
with the station in as few burns as possible. **35 missions** — the
original 8 (First Light, Twin Pull, The Gate, Heavy Heart, S-Curve,
The Well, Crossfire, Homecoming), 8 more built for this edition (The
Loop, Thread the Needle, Long Haul, Slalom, Twin Suns, Low Orbit,
Crosswind, The Gauntlet), 4 that use the newer mechanics (Drift,
The Shortcut, Patrol, Crossing), and 11 more (Ricochet, The Spiral,
Pinball, Deep Field, Bouncer, The Anvil, Crosshairs, Undertow, The
Pendulum, Final Approach, Patrol Line) and 4 more path missions
(The Gatekeeper, Zigzag, Cross Traffic, The Long Patrol). Every
mission's cores sit on a
solver-verified winning line, so a 3-star run can always collect them
all. **No installs needed** — standard library only (tkinter).

## Run it

```
python orbital.py
```

(There's also a packaged `Orbital.exe` — same game, double-click to
play. Progress is saved to `orbital_save.json` next to the program:
unlocked missions, best stars, best core and flyby counts per mission
(counted only from completed, docked runs), the ghost of your best
run per mission, your custom levels, and your settings.)

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
- **U** undoes the last burn (or the launch itself) — even after a
  crash. **R** resets the mission, **Esc** pauses, **P** / **N** switch
  missions, and the **< Level N >** pager under the buttons does too.
- Dock in as few burns as possible: at or under par = 3 stars, one
  over = 2, otherwise 1. Cyan **data cores** are optional pickups.
  Skimming a planet without hitting it scores a **flyby**.
- Some planets **move** — on circular orbits, or along a **path**: a
  straight patrol line, or a custom route through several waypoints,
  ping-ponging back and forth — or, if the path is set to loop, riding
  the route in a circle back to its start, like an orbit. The mission
  clock runs while you
  aim, so *when* you launch is part of the shot, and the preview line
  accounts for the motion. **Wormhole** pairs teleport the probe to
  the other mouth, keeping its velocity.
- **Repulsor** planets (orange dashed ring) push instead of pull,
  with the same strength a normal planet of their size would pull.
  They first appear in Bouncer. Handle with care: a fast shot aimed
  straight at one still crashes into it.
- The dotted **ghost line** on a mission is your best run there — beat
  your own line. **Clear ghost** removes the open level's ghost when
  you want it gone. The header tracks your campaign totals (stars and
  cores across all 35 missions).
- **Random** builds a fresh mission on the spot: the generator flies a
  design line first, places the station on the path it actually flew,
  and scatters the cores off that path — collecting them all takes a
  deliberate detour. Missions roll 2 to 5 planets and 2 to 5 cores,
  and a planet can be a repulsor, orbit, or patrol a path (sometimes
  a loop); some missions add a wormhole pair. The finished mission is
  verified beatable before it is shown.
- **Editor** lets you build your own missions: place planets (drag to
  move, mouse wheel to resize), start pad, dock, cores and wormholes,
  set par and burns, then playtest or save them — saved levels live in
  the pager after the campaign. Open one of your saved levels and
  press **Delete level** to remove just that one (it asks first).
  The **Orbit** tool makes planets move: click a planet, then click
  where its orbit center goes; with the Orbit tool selected, the
  mouse wheel changes the orbit's size and Shift+wheel its speed.
  Click an orbiting planet with the Orbit tool to stop it again.
  **Shift+click** a planet with the Planet tool to toggle it into a
  repulsor (or back). The **Path** tool gives a planet a route to
  patrol: click the planet, then click waypoints (2 points make a
  straight line, more make a custom path), click the planet again to
  finish; the mouse wheel over a pathed planet sets its speed, and
  clicking a pathed planet with the tool removes the path.
  **Shift+click** a pathed planet with the Path tool to toggle
  **loop** mode: the planet rides its route in a circle, back to the
  start, instead of ping-ponging.
- **Share level** turns the open mission (or the one you're building
  in the editor) into a short text code on your clipboard. Send it to
  anyone who has Orbital; they press **Paste level**, paste the code,
  and the mission is saved into their game.
- The **1× / 1.25× / 1.5×** buttons scale the whole window (the layout
  stays fixed at each size). Preview and Sound toggles and the scale
  are remembered between launches.
- Flights end after **25 seconds**.

## Make it yours

- `CONFIG` at the top of `orbital.py`: field size, power range, burn
  strength, dock radius, flight timeout, gravity softening. Gravity
  scales with planet size: `mu = GRAV_K * radius^2` (GRAV_K = 450), so
  bigger planets always pull harder; enforced when a level loads.
- `LEVELS`: the 35 mission layouts — planet positions, sizes, labels
  and colors (a planet can carry an `orbit` to make it move in a
  circle, a `path` to make it patrol a route, or
  `repel` to make it push instead of pull), optional
  `wormholes`, start/target, cores, burn counts, par.
- The physics (`gravity_at`, `step_physics`, `predict_path`) is pure
  and separate from the UI, so it's easy to experiment with.

Built with **Muse** (Meta AI) on 2026-11-23 — first as a web game,
then ported to Python the same day and aligned mission-for-mission
with the web edition.
