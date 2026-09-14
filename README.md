# Rig Deck

A single-screen dashboard and control panel for Euro Truck Simulator 2 and American
Truck Simulator, running in a browser on an Android tablet. Everything is on one screen:
no pages, no swiping, no scrolling.

Two things it does that a generic button box cannot:

- **Commands are confirmed, not hoped for.** A button stays pending until the game's own
  telemetry reports the new state. If it never arrives, the button says so.
- **Controls go through vJoy, not keystrokes.** The game sees a real controller, so every
  function that appears in Options → Controls can be driven — including those with no
  default key, which keyboard emulation can never reach.

## Install it, without building anything

Two downloads, both on the [latest release](https://github.com/Matozanato/rigdeck/releases/latest):

| File | What it is |
| --- | --- |
| `RigDeck-Setup-<date>.zip` | The PC side. Unpack it somewhere permanent — `C:\RigDeck`, say, not straight out of the zip — and double-click **`1 - INSTALIRAJ RIG DECK.bat`**. It wants administrator rights, then does the rest by itself: no Python to install, no build tools, no account, and no internet once the zip is down. `UPUTE.txt` inside walks through it in Croatian. |
| `RigDeck.apk` | The tablet app. The PC installer also serves it, so the tablet can scan a QR code instead of being plugged in. |

You need Windows 10 or 11 with ETS2 or ATS on it, any Android tablet, and both on the
same Wi-Fi. The map is **not** in the download and never is — the installer reads the
road network out of your own copy of the game, on your own PC. Nothing about it leaves
the machine.

Everything below this line is for building from source instead.

## Layout

```
server/            Python, standard library only — no pip install
tools/             the map exporter: ts-map (C#) plus a headless driver for it
  rigdeck/
    telemetry.py   reads the plugin's shared memory block
    controls.py    action registry: label, vJoy button, game action, read-back
    vjoy.py        vJoy output over ctypes
    keyboard.py    scancode fallback for interface-only actions
    wsserver.py    HTTP + WebSocket, hand-rolled on the stdlib
    mockfeed.py    fake telemetry so the panel can be tested with the game closed
  bindwrite.py     writes every binding into the game's own profile
  selftest.py      end-to-end check of the whole chain
web/               the panel itself (a PWA) and the pairing page
  maps/            road network exported from your own game files
reference/         the plugin header the offsets were derived from
```

## Setup, once

1. **Install the telemetry plugin**

   ```powershell
   powershell -ExecutionPolicy Bypass -File install_plugin.ps1
   ```

   Downloads RenCloud's `scs-sdk-plugin` and drops `scs-telemetry.dll` into
   `bin\win_x64\plugins` for both games. It coexists with plugins that are already there.

2. **Install vJoy** — use the **2.2.2.0** build from
   [BrunnerInnovation/vJoy](https://github.com/BrunnerInnovation/vJoy/releases/tag/v2.2.2.0),
   as administrator. Then configure device 1 with 64 buttons:

   ```powershell
   & "C:\Program Files\vJoy\x64\vJoyConfig.exe" 1 -f -b 64 -a X Y Z
   ```

   The panel uses 32 of them. Reconfiguring re-creates the device, so do it before
   binding anything and restart the game afterwards — a game already running will not
   see the new button count, and may lose the device from its controller slot.

   Then, **with the game closed**:

   ```powershell
   cd server; python bindwrite.py                    # says what it would do
   cd server; python bindwrite.py --write            # does it, keeping a backup
   cd server; python bindwrite.py --list             # every profile it can see
   cd server; python bindwrite.py --profile <dir> --write   # a particular one
   ```

   It takes the newest profile unless told otherwise, and refuses if vJoy is in none
   of that profile's six controller slots — until the game has been told about vJoy
   once, a binding has nothing to hang on. `--claim` skips that trip: it copies vJoy's
   device string from a profile that already has it into the first free slot, which is
   the same slot the game would have picked and the same string it would have written.

   This writes all 31 bindings into the profile's own `controls.sii`. Do not bind them
   by hand. The panel's list and the game's list are in different orders, so binding
   means alternating between two of them thirty-one times, and a single skipped row puts
   every binding after it one button early — silently. The failure looks like the truck
   misbehaving rather than a mistake: the air horn pulls the parking brake, the hazards
   run the wipers, and the last few controls do nothing at all because they fell off the
   end. `bindwrite.py` reads the same table the panel sends from, so the two cannot drift.

   `.\run.ps1 -Bindings` prints the sheet if you want to read what was bound.

   **The game has to put vJoy in a controller slot before it will accept a single
   press.** ETS2 and ATS keep six of them — `joy`, `joy2` … `joy6` in the profile's
   `controls.sii` — and a device the game merely detected sits in none of them. The log
   will happily say `[di8] Initializing device 'vJoy Device'` with all 32 buttons while
   the binding screen ignores every one of them; the tell is `config_lines[4]: "device
   joy2 ``"`, empty, with every existing binding written as `joy.bN`. Selecting vJoy on
   the Controls page fills the first free slot. Check afterwards that your wheel is still
   in `joy` — the slot is what the bindings name, so a device that lands in the wrong one
   takes the other device's bindings with it.

   If nothing registers, `python server\bindtest.py` holds a vJoy button for over a
   second at a time and prints what Windows sees, which separates the game ignoring the
   device from the panel never pressing it.

   Take the version seriously. The older 2.2.1 build cannot load while Windows'
   **Memory Integrity** (Core isolation) is on: its driver is built against KMDF 1.9,
   `WdfCollectionCreate` fails with `0xc000009a`, and the device install silently rolls
   itself back — the installer finishes and leaves you with files but no device. 2.2.2.0
   is EV-signed by Brunner Elektronik and went through Microsoft attestation, so it
   loads with Memory Integrity left on. Turning that off is not a fix worth making.

   The installer ends by asking to restart, in a dialog it forgets to show. If it seems
   to hang at the end, it is waiting on that; the driver is already installed.

3. **Export the map**

   ```powershell
   powershell -ExecutionPolicy Bypass -File export_maps.ps1
   ```

   Reads the road network straight out of the game's `.scs` archives, mods included, and
   writes it under `web\maps`. Run it again whenever you add or remove a map mod —
   start the game once first, because the active mod list is read from `game.log.txt`.

   A standalone map mod — Grand Utopia, Hungary Map — does not extend Europe, it adds a
   second map of its own, often on the very same coordinates. Exported together they
   come out drawn on top of each other, so pick one:

   ```powershell
   powershell -ExecutionPolicy Bypass -File export_maps.ps1 -Game ETS2 -Map hungary
   ```

   The tray menu does the same thing without the names: **Export a map from the game
   files** lists every installed game and the maps it currently offers.

4. **Build the tablet app** (see below), or skip it and use a browser.

5. **Make the desktop shortcut**

   ```powershell
   powershell -ExecutionPolicy Bypass -File install_app.ps1
   ```

   Puts *Rig Deck* on the desktop and in the Start menu. Opening it starts the server in
   the notification area — no console, no PowerShell. The icon says what is happening:
   grey while no game is running, amber once one is, green once a tablet is connected.
   Right-click it for the pairing QR code, the button sheet, or to quit.

   It deliberately does **not** start with Windows. Open it when you sit down to drive.

After that: open Rig Deck, start the game, open the tablet app. The order does not
matter — the panel says `NO GAME` until a game is running and picks it up by itself,
and the tablet reconnects on its own whenever the server appears.

**In a menu the panel says `IN MENU` and the buttons still work.** The game writes no
telemetry while it is in the main menu, the options screens or paused, so the readouts
freeze and grey out — but vJoy is a real controller and the game reads it there just as
it does on the road. That is what makes binding possible at all: the button sheet is
bound in Options → Controls, which is a menu.

## The tablet app

```powershell
powershell -ExecutionPolicy Bypass -File build_apk.ps1
powershell -ExecutionPolicy Bypass -File build_apk.ps1 -Install   # over USB
```

Writes `dist\RigDeck.apk`. It is a WebView pointed at the panel, and it exists for one
reason: **Chrome will not run the panel without its toolbar.** Installing a page as a
full-screen app needs a secure origin, and the server is plain HTTP on the local network,
so *Add to Home screen* in Chrome only makes a shortcut that opens in an ordinary tab.
A WebView has no such rule, and it also brings three things a tab cannot:

- the screen stays awake while the app is open;
- the orientation is pinned to landscape either way up, never portrait;
- the system font size cannot rescale the panel, which is a fixed 1600 px layout.

On first run it sweeps the local network for the server, so there is nothing to type.
The address can be corrected by hand, and pressing Back twice brings that screen back.
If the panel goes unreachable it says so and keeps retrying every five seconds.

The build needs a JDK and an Android SDK but installs neither: `build_apk.ps1` finds the
JDK inside Android Studio and the SDK wherever `ANDROID_HOME` says, falling back to the
place Android Studio puts it, and hands both to Gradle for that run only. It also generates a signing key on first use, under `android\keystore`.
Keep that key — Android refuses to upgrade an app signed with a different one.

## Units and currency

One build covers both games. The panel follows whichever game is running — ETS2 gives
km and €, ATS gives miles and $ — and the chip in the status bar cycles
auto → metric → imperial if you want to override it. The server always sends raw SI
values; formatting happens on the tablet, so switching is instant.

## The map

There is no downloaded map and no online tile service. `export_maps.ps1` reads the
game's own archives — base game, every DLC you own, and every map mod your profile has
enabled — and writes the road network out as vector cells of a few kilometres each.
The tablet fetches only the cells it is driving through, so the mini GPS is sharp at
any zoom and the coordinates line up with telemetry exactly, ProMods and all.

Pinch to zoom, anywhere from 55 km across down to a single yard; the **+** and **−**
keys step between eight named levels from wherever the fingers left it, and a mouse
wheel does the same thing on the desktop. One finger drags, two pinch, and two do both
at once — the midpoint drags while the gap zooms, so a junction can be pulled into the
middle of the screen and opened up in one movement. Mid-gesture the road drawing is
stretched rather than redrawn, because redrawing tens of thousands of segments per
frame would turn a pinch into a slideshow; it is exact again the moment you let go.

Drag the map to look ahead and the view leaves the truck, a **Recentre** button
appears, and if you forget it the map drifts back on its own eight seconds later. The
truck marker stays where the truck really is rather than being pinned to the middle, so
it is always clear how far off the map has been pushed.

### Places worth stopping at

Fuel, parking, service, garages, dealers, weighbridges, recruitment and the company
yards themselves are drawn as chips on the map, each with its own glyph. They are the
game's own map overlays, so whatever it puts on its world map ends up on the tablet,
mods and all — around ten thousand of them in ATS and sixteen thousand in ETS2.

Each kind appears at the zoom where it starts being useful and not before: fuel,
parking, service and garages from the third level in, dealers and weighbridges a level
later, company yards and viewpoints later still, with company names once you are close
enough to be looking for a gate. Below that the map is left as a map. Only one chip is
drawn per patch of screen — a services area stacks a pump, a bed and a spanner within a
few metres of each other, and at this size that is a smudge rather than three icons.

### When ProMods updates or a DLC arrives

The map does not follow the game on its own, and deliberately so: exporting takes
minutes, wants the game closed, and replaces the road network the panel is drawing
from. None of that should happen behind a driver's back, and no amount of cleverness
makes a continent re-parse itself while you are on the motorway.

What it does do is notice. Each export records the mod files it read and the DLC
archives that were in the game folder, and the server compares that against what is
there now — mods from the game's own `game.log.txt`, DLCs from the game folder. When
they differ the panel says so once, and the tray icon has **Export a map from the game
files**, which is `export_maps.ps1` in a window you can watch.

So the routine after installing a new ProMods or buying a map DLC is: start the game
once so it writes its mod list, quit it, then run the export from the tray. The panel
picks the new map up on its next load.

The reader is [ts-map](https://github.com/dariowouters/ts-map), which ships as a
Windows app; `tools\mapexport` drives it headlessly and writes the cells. Both are
built from source by the export script.

## Sending it to somebody else

```powershell
powershell -ExecutionPolicy Bypass -File packaging\fetch_runtime.ps1   # once per clone
powershell -ExecutionPolicy Bypass -File packaging\make_zip.ps1
```

Writes `dist\RigDeck-Setup-<date>.zip`, about 18 MB. Extract it anywhere, double-click
**1 - INSTALIRAJ RIG DECK.bat**, and it installs itself on a PC that has none of the
parts: the telemetry plugin, vJoy 2.2.2.0 and its 64-button device 1, a firewall rule
for port 8384 on private networks only, the shortcuts, the map exported from that PC's
own game files, and the bindings. `UPUTE.txt` beside it is the guide for the person
receiving it.

**Python is bundled**, as the embeddable build from python.org under `runtime\`. It
installs nothing, touches no PATH and ignores any Python already on the machine; the
`._pth` beside it names `..\server` so `-m rigdeck` resolves. That is only possible
because the server is standard library only — which is why it is.

Three things stay out of the zip on purpose: `android\` (the signing key lives there,
and nothing in it is needed to run Rig Deck), `web\maps\` (~70 MB derived from the
game's archives, exported on the receiving PC instead), and `server\config.json`.
`make_zip.ps1` fails the build if a key, a keystore or a local config makes it into the
staging folder anyway.

One step cannot be done for them: the game has to be started once, with vJoy already
installed, and vJoy picked in Options → Controls, before a binding has a slot to hang
on. That is what **2 - POVEZI TIPKE U IGRI.bat** is for, and the installer says so when
it gets that far.

The bundled apk is copied into `web\`, so the pairing page offers a second QR code that
installs the tablet app straight off the server — no cable, no store, nothing to type.

## Testing without the game

```powershell
.\run.ps1 -Mock             # in one window: plausible telemetry into shared memory
.\run.ps1 -Mock -Game ATS   # the same in miles and dollars, driving near Phoenix
.\run.ps1                   # in another: serves the panel
cd server; python selftest.py    # checks the whole chain end to end
cd server; python servetest.py   # checks the panel and the map are served
cd web; node test_qr.js          # checks the QR encoder against a decoder

cd tools\mapexport
node checkcells.js ets2 Duisburg 6000 check.png   # draws the exported roads to a PNG
```

Never run the mock feed with the game open — both write the same shared memory block.
`selftest.py` and `servetest.py` check for a running game and refuse rather than
overwrite it, but `run.ps1 -Mock` will happily do it.

## Notes on what the telemetry can and cannot do

- Wiper **level** is not exposed, only on/off, so the panel confirms wipers as a toggle.
- **A button presses what you bound to it and nothing else.** Controls used to drive the
  game in a loop — pulse, read telemetry, pulse again — and that let a control refuse to
  act at all. The retarder would not fire on a truck the game reported had none, which
  is exactly the truck you want to test it on, and it could not even be bound. High beam
  reported *did not engage* whenever low beam was off, which is simply how the headlights
  work. Both are plain presses now; the read-back reports what happened rather than
  deciding whether to try.
- Lights are one button that steps off → parking → low, the same control the stalk is,
  with high beam separate beside it. The button confirms on the reading *changing*
  rather than reaching a set value, which is what `data-cycle` marks in the markup.
- **Enter and Esc are keystrokes, not vJoy buttons**, and need no binding. They drive
  menus, where the game may refuse a controller binding outright.
- There is no turn-by-turn navigation in the SDK. Distance and time to the destination
  are real, and the roads on the map are your game's own — but the game never says
  which of them it plans to send you down, so the map shows where you are, not the
  route it picked.
- The deck carries what a hand reaches for from the seat and nothing else. Axle lifts,
  the interior light, quick save, the radio and tow-to-road are all on the wheel or the
  keyboard already, and a button that duplicates one of those only makes the ones that
  matter harder to find. Anything dropped from the panel can still be given a keyboard
  fallback under `"keys"` in `server/config.json`.

## Licence

Rig Deck is MIT licensed — see [LICENSE](LICENSE). Do what you like with it, keep the
copyright notice.

What it leans on belongs to other people, all of it MIT, and none of it modified:
[scs-sdk-plugin](https://github.com/RenCloud/scs-sdk-plugin) by RenCloud is the DLL the
game loads to publish telemetry; [ts-map](https://github.com/dariowouters/ts-map) by
Dario Wouters parses the `.scs` archives the map is read from, with
[Json.NET](https://github.com/JamesNK/Newtonsoft.Json) under it; and
[vJoy](https://github.com/BrunnerInnovation/vJoy) is the virtual joystick the buttons
go through. The distribution zip carries them so the install needs no internet, and
`packaging/NOTICE.txt` names each one with where it came from. The Python inside it is
the stock embeddable build from python.org, under the PSF licence.

ETS2, ATS and their map data belong to SCS Software, and none of it is redistributed
here. The road network under the GPS is exported from your own installed copy of the
game and stays on your own machine.
