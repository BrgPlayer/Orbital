# Orbital — gravity slingshot puzzles (Python edition)

A standalone Python program: slingshot a probe around planets and dock
with the station in as few burns as possible. **50 missions** — the
original 8 (First Light, Twin Pull, The Gate, Heavy Heart, S-Curve,
The Well, Crossfire, Homecoming), 8 more built for this edition (The
Loop, Thread the Needle, Long Haul, Slalom, Twin Suns, Low Orbit,
Crosswind, The Gauntlet), 4 that use the newer mechanics (Drift,
The Shortcut, Patrol, Crossing), and 11 more (Ricochet, The Spiral,
Pinball, Deep Field, Bouncer, The Anvil, Crosshairs, Undertow, The
Pendulum, Final Approach, Patrol Line) and 4 more path missions
(The Gatekeeper, Zigzag, Cross Traffic, The Long Patrol), 5 that
introduce custom-shaped planets (Shards, The Diamond, Hex Field, The
Wedge, Shard Storm), 5 that introduce shaped repulsor planets (Push
Triangle, Diamond Push, Pentagon Gate, Repulsor Patrol, The Star),
and 5 that introduce moving start pads and docks (Moving Dock,
Moving Pad, Both Moving, Patrol Dock, The Finale). Every mission's
cores sit on a verified winning line, so a 3-star run can always
collect them all. **No installs needed** — standard library only
(tkinter).

## Run it

```
python orbital.py
```

(There's also a packaged `Orbital.exe` — same game, double-click to
play. Progress is saved to `orbital_save.json` next to the program:
unlocked missions, best stars, best core and flyby counts and best
times per mission (counted only from completed, docked runs), the
ghost of your best run per mission, your custom levels, your
orbytes and probe colors, your achievements, and your settings.)

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
- **U** undoes the last burn (or the launch itself) while you're
  still flying. **R** resets the mission, **H** pauses and resumes, **P** / **N** switch
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
- Some planets are **shaped** — triangles, diamonds, pentagons,
  hexagons, stars — instead of round, and gravity still pulls from
  their center. Shaped planets can be repulsors too, and can move on
  orbits and paths like round ones. The **start pad and the dock can
  move as well**: a pad or dock can orbit a point or patrol a route,
  so the shot has to meet it where it will be. **Fuel canisters**
  float on some missions — fly through one for +1 burn.
- The dotted **ghost line** on a mission is your best run there — beat
  your own line. **Clear ghost** removes the open level's ghost when
  you want it gone. The **Ghosts** checkbox turns ghost recording and
  display off (saved ghosts are kept, so they come back when you turn
  it on again). The header tracks your campaign totals (stars and
  cores across all 50 missions).
- Winning campaign missions earns **orbytes** — 10 per win, replays
  included. Spend them in **Rewards** on new probe colors (red,
  orange, yellow, green, blue, purple, light, and dark, 100 orbytes
  each). **Achievements** track the big ones: beating a mission under
  par, three flybys in one run, sweeping a chapter 3-star, and
  completing the whole campaign. The fastest docked time on each
  mission is saved as its **best time** and shown in the header and
  on the win screen.
- **Random** builds a fresh mission on the spot: the generator flies a
  design line first, places the station on the path it actually flew,
  and scatters the cores off that path — collecting them all takes a
  deliberate detour. Missions roll 2 to 5 planets and 2 to 5 cores,
  and a planet can be a repulsor, orbit, or patrol a path (sometimes
  a loop); some missions add a wormhole pair. The finished mission is
  verified beatable before it is shown. Random missions are one-off
  challenges: winning one shows your stars on the win screen, but
  nothing is saved for it, so it can never hand its results to
  another level.
- **Editor** lets you build your own missions: place planets (drag to
  move, mouse wheel to resize), start pad, dock, cores, wormholes, and
  fuel canisters, set par and burns, then playtest or save them —
  saved levels live in the pager after the campaign. The editor opens
  from your own levels: **My levels** has a **New level** button, or
  open a saved level and press **Editor** — it stays greyed out on the
  default missions. Open one of your saved levels and
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
  start, instead of ping-ponging. The Orbit and Path tools also work
  on the start pad and the dock, so a mission can have a moving pad,
  a moving dock, or both. The **Shape** tool builds a custom-shaped
  planet: click to lay down corners, then click near the first corner
  to close the shape (or release Shift to finish it) — gravity pulls
  from the polygon's center, and the crash edge is the polygon
  itself. The **Fuel** tool places a fuel canister; click a canister
  to remove it. The **Barrier** tool builds solid
  walls the ship crashes into: drag a rectangle to make one, or hold
  Shift and click to lay down polygon corners, then release Shift to
  close the shape — a barrier needs 3 corners and a real area, so a
  line makes nothing, and a barrier can't cover the pad or the dock.
  **Del Bar** cuts barrier away the same way: drag a rectangle over
  part of a wall to cut it out, or Shift+click a shape — cutting a
  smaller shape out of the middle of a big one leaves a ring. Click a
  planet to select it, then press **Rename** (or double-click the
  planet) to rename it — the name is what the play field shows under
  the planet, and it travels with the level when you save, playtest,
  or share it. The **Description** field under the toolbar sets the
  mission's subtitle — the line shown under the mission name — so a
  level you share can carry a note from whoever made it.
- **My levels** lists all your saved custom levels with their stars,
  cores, and best times, and lets you play, edit, share, rename, or
  delete any of them from one place. It stays greyed out until every
  default mission has been docked at least once. It also has **Save to file** and **Load
  from file**: a level can be saved as a `.orbital` file (or a plain
  `.json` level file) and loaded back from disk, instead of passing a
  code around.
- **Share level** turns the open mission (or the one you're building
  in the editor) into a short text code on your clipboard. Send it to
  anyone who has Orbital; they press **Paste level**, paste the code,
  and the mission is saved into their game. Paste level remembers the
  last 8 codes you imported — double-click one to load it again.
- The **Window 1× / 1.25× / 1.5×** buttons scale the whole window (the layout
  stays fixed at each size). The **Text 1× / 1.25× / 1.5×** buttons scale
  the game text — mission text, HUD, planet labels, and the buttons and
  checkboxes too. The two bars that already fill the window at 1× text
  split into two rows when text is bigger than 1×, so the layout still
  fits. Both scales live in their own row, and the
  active choice in each is highlighted. Preview, Sound, Ghosts, and both
  scales are remembered between launches.
- The options row holds the rest: **Orbit paths** draws the orbit
  circles and patrol routes of moving planets on the field; **Labels**
  shows or hides the planet name tags (the editor always shows its
  detail tags); **Effects** turns particles and starfield twinkle on
  or off; **Auto-advance** jumps to the next mission 1.5 seconds
  after you dock; **Pause on unfocus** auto-pauses a flight when the
  window loses focus, so the 25-second clock doesn't eat the run;
  **Grid** draws a faint coordinate grid on the field. All of them
  are remembered between launches.
- Flights end after **25 seconds**.

## Make it yours

- `CONFIG` at the top of `orbital.py`: field size, power range, burn
  strength, dock radius, flight timeout, gravity softening. Gravity
  scales with planet size: `mu = GRAV_K * radius^2` (GRAV_K = 450), so
  bigger planets always pull harder; enforced when a level loads.
- `LEVELS`: the 50 mission layouts — planet positions, sizes, labels
  and colors (a planet can carry an `orbit` to make it move in a
  circle, a `path` to make it patrol a route, a `shape` to make it a
  polygon, or `repel` to make it push instead of pull), optional
  `wormholes` and `fuel`, start/target (which can move on an orbit or
  a path of their own), cores, burn counts, par.
- The physics (`gravity_at`, `step_physics`, `predict_path`) is pure
  and separate from the UI, so it's easy to experiment with.

Built with **Muse** (Meta AI) on 2026-11-23 — first as a web game,
then ported to Python the same day and aligned mission-for-mission
with the web edition.
