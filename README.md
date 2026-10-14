# BrickSort

A small AI model that recognises LEGO parts from a picture, plus a virtual
world to try it in. Everything runs offline once it's set up.

**Windows only for now.** The launchers are Windows `.bat` files in `scripts/windows/`;
the Python commands further down work the same anywhere Python, PyTorch and MuJoCo run.

## Setup

Double-click **scripts/windows/setup.bat** once. It installs Python 3.12, PyTorch,
MuJoCo and BrickSort itself into `C:\Users\<you>\BrickSortData\venv`, and downloads
the part library (about 160 MB).

## Everyday use

Double-click **scripts/windows/Start demo.bat**.

1. Pick a piece in the list (type in the search box to filter), and a colour.
2. Press **Drop it!** The piece falls onto a virtual tray with real physics,
   so it lands differently every time. A camera above takes a picture.
3. A window pops up with the model's top 5 part guesses (with a reference
   picture of each) and its top 3 colour guesses. Fix the colour if needed,
   then click the right part, or type the correct part number and press Save.
4. Press **Retrain with my corrections** now and then. The model learns from
   everything you've confirmed.

**Open a real photo…** runs the same check on any photo.
**Go through my_photos/unknown** shows each photo in that folder; when you pick
the part, the photo is moved to `my_photos/<part number>/`.

## The virtual sorting machine

Double-click **scripts/windows/Start sorting machine.bat**. Pieces ride a conveyor belt under a
camera. The camera spots each piece, the model recognises it, your bin rules
choose a bin, and a flap at the end of the belt sends it there. Press
**Start**; the sliders set the speed and how often non-LEGO objects and pairs
of pieces show up.

**Edit bins…** opens `bins.json`. Each bin has a name and a `when` with
conditions, checked top to bottom (first match wins):

| Condition | Example | Meaning |
|---|---|---|
| `part` | `["3001", "3626c"]` | these part numbers (look-alikes count too) |
| `category` | `"minifig heads"` or a list | Rebrickable category contains this text |
| `name` | `"slope"` | part name contains this text |
| `color` | `["Black", "Red"]` | Rebrickable colour names |
| `flat` | `true` | plates and tiles (not bricks) |
| `min_length` / `max_length` | `6` | longest side in studs |
| `min_width` / `max_width` | `2` | shortest side in studs |
| `min_height` / `max_height` | `3` | height in plates (a brick is 3) |

`"when": {}` matches every LEGO piece. `confidence_needed` (0.9 = 90%) is how
sure the model must be. The **rest bin** gets: several pieces at once, pieces
too big to be one part (stuck together), and anything the model isn't sure
enough about. If the exact part is unsure but the category is clear, a bin
that only asks for a category (and maybe a colour) can still take it.
The **Not Lego** bin gets things the model is sure aren't LEGO. Photos of
non-LEGO things in `my_photos/not_lego/` teach it this from real examples.
Saving in the bin editor reloads the bins.

The real machine later uses the same code, with `sorter/hardware.py`'s webcam
and microcontroller (e.g. Arduino) parts in place of the virtual ones.

## Your own photos

Put them in `my_photos/<part number>/<colour name>/`, for example
`my_photos/3001/Red/` for a red 2x4 brick. Use Rebrickable's colour names
(Black, White, Red, Blue, Yellow, Light Bluish Gray, Dark Bluish Gray, Tan,
Reddish Brown, Dark Red, ...; capitals and spaces/underscores don't matter).
If you don't know the colour name, put the photo straight in
`my_photos/<part number>/`; it's then used for the shape only.
5 to 10 photos per piece, from different sides. Any file name works
(.jpg, .png). Photos you can't identify go in `my_photos/unknown/`.
Keep the piece roughly in the middle of the photo: the program uses the
centred square.

Real photos count 10 times as much as simulated pictures when training.

## Where things are

| What | Where |
|---|---|
| Program code | `bricksort/` |
| Trained model (copy this to another machine) | `model/lego_model.pt` |
| Parts the model knows | `parts.json` (first copied from `defaults/`) |
| Reference pictures | `reference/` |
| Corrections made in the review window | `corrections/<part>/` |
| Your photos | `my_photos/<part>/` |
| Windows launchers | `scripts/windows/` |
| Python, downloads, simulated pictures (big, re-creatable) | `C:\Users\<you>\BrickSortData\` (set `BRICKSORT_DATA` to move it) |

## Commands (for the curious)

Run from this folder with the Python in `C:\Users\<you>\BrickSortData\venv\Scripts\`
(or any Python where you ran `pip install -e .`):

- `python -m bricksort.catalog 300` picks the 300 most common parts (Rebrickable data)
- `python -m bricksort.render 40` makes 40 simulated pictures per part (LDraw 3D models)
- `python -m bricksort.train 8` trains for 8 rounds
- `python -m bricksort.demo` opens the demo (or just `bricksort-demo`)
- `python -m bricksort.conveyor_demo` opens the sorting machine (or `bricksort-sorter`)

Data: part lists from [Rebrickable](https://rebrickable.com/downloads/),
3D models from the [LDraw](https://www.ldraw.org) parts library.
