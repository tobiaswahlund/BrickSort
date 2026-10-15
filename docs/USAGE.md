# Using BrickSort

All launchers are in `scripts/windows/` (double-click them). Each one also works as a Python
command, listed at the end.

Pictures of every window, with what each button does: [WINDOWS.md](WINDOWS.md).

## Setup

Double-click **setup.bat** once. It installs Python 3.12, PyTorch (the graphics-card version if
there's an NVIDIA card), MuJoCo and BrickSort itself into `C:\Users\<you>\BrickSortData\venv`, and
downloads the LDraw part library and Rebrickable's part lists (about 160 MB).

## The demo

Double-click **Start demo.bat**.

1. Pick a piece in the list (type in the search box to filter) and a colour.
2. Press **Drop** (or double-click the piece). It falls onto a virtual tray with real physics, so
   it lands differently every time, and a camera above takes a picture.
3. A window shows the model's top 5 part guesses as 3D pieces you can spin, and its top colour
   guesses. Fix the colour if needed, then select the right part, or type its number and press Save.
4. Corrections are kept and used the next time the model is trained.

The toolbar runs the same check on any photo (**Open photo…**), goes through the photos in
`my_photos/unknown/` (**Sort unknown photos…**), and reviews what the sorting machine set aside
(**Review rest bin…**, **Spot check…**).

## The virtual sorting machine

Double-click **Start sorting machine.bat**. Pieces ride a conveyor belt under a camera. The camera
spots each piece, the model recognises it, your bin rules choose a bin, and a flap at the end of the
belt sends it there. Press **Start** (or Space). The sliders set the speed, how often non-LEGO objects
and touching pieces show up, and how sure the model must be before a piece goes in a bin.

**Edit bins…** lists the bins, checked from the top (the first one a piece fits wins). Each bin can
ask for categories, part names or numbers, colours (picked in a list grouped by main colour), flat
or not, printed or not, and sizes in studs or plates. A bin can also ask for its own confidence,
for example 99% for valuable pieces; otherwise it follows the slider. The **rest bin** gets several
pieces at once, pieces too big to be one part (stuck together), and anything the model isn't sure
enough about. The **Not Lego** bin gets things the model is sure aren't LEGO.

A real machine uses the same code, with the webcam and microcontroller classes in
`bricksort/sorter/hardware.py` in place of the virtual ones.

## Your own photos

Put them in `my_photos/<part number>/<colour name>/`, for example `my_photos/3001/Red/` for a red
2x4 brick, using Rebrickable's colour names. 5 to 10 photos per piece, from different sides, with
the piece roughly in the middle. Photos you can't identify go in `my_photos/unknown/`.

- **Cut out pieces.bat** cuts photos with several pieces spread out (put them in
  `my_photos/_to_cut/`) into one picture per piece. It finds the pieces, suggests part and colour,
  and lets you pick a part's version (3062a / 3062b) or leave it unknown. Pieces whose colour you
  leave as "Unknown" go to Check colours.
- **Check colours.bat** goes through photos whose colour isn't confirmed yet, piece by piece, with
  the model's suggestion. Ctrl+Z undoes the last step.

## Training

Double-click **Model training.bat**.

- **Training tab:** Start makes any missing training pictures, then trains. Pause stops it; Start
  carries on where it stopped (progress is saved after every round). It shows progress, time left,
  the scores of each round, and the current model.
- **Machine setup tab:** make the training pictures look like your own machine: belt (a built-in
  one or a photo of yours), camera height, lamps, and how much of the training looks like the
  machine. **Shine like my photos** uses the plastic shine measured on your real photos. The 3D
  preview shows a piece with all the settings; drag to turn it. After changing the setup, **Make all
  training pictures again** and train.
- **Training pictures (right side):** the pictures being made now, or all of them, to check they look
  right. Click one to see it big; a bad one can be taken out, and a new one is made next time.

## The honest accuracy test

The scores the training prints come from photos taken in the same sessions as its training photos, so
they're optimistic. The real test uses pieces the model has never seen:

1. Draw about 150 pieces at random from a mixed tub (no choosing; pieces the model doesn't know are kept,
   they show how much of a real collection it covers).
2. Photograph them on a plain surface from above, several apart per photo, with the camera a sorting
   machine would use. Put the photos in `my_photos/_to_cut_test/`.
3. **Cut out test pieces.bat**: like Cut out pieces, but the model's guesses are hidden, so your answers
   can't lean towards them. The pieces go to `my_photos/_test/<part>/<colour>/`, which training never uses.
4. **Test accuracy.bat** (or `python -m bricksort.evaluate`) scores the model: first guess, top 5 and
   colour on the parts it knows, the category on the parts it doesn't, each with a 95% range, and the
   most-confused parts. It writes `results/RESULTS.md`.

Never correct test pieces in the demo: corrections are used for training. One photo per piece; several
photos of one piece can share a name start with two underscores (`piece07__a.jpg`, `piece07__b.jpg`).

## Where things are

| What | Where |
|---|---|
| Program code | `bricksort/` |
| Trained model | `model/lego_model.pt` |
| Parts the model knows | `parts.json` (first copied from `defaults/`) |
| Bin rules / machine setup | `bins.json` / `machine_setup.json` |
| Your photos / corrections | `my_photos/<part>/` / `corrections/<part>/` |
| Python, downloads, training pictures (big, re-creatable) | `C:\Users\<you>\BrickSortData\` (set `BRICKSORT_DATA` to move it) |

## Commands

Run from the project folder with the Python in `BrickSortData\venv\Scripts\` (or any Python where
you ran `pip install -e .`):

| Command | Does |
|---|---|
| `python -m bricksort.demo` (or `bricksort-demo`) | the demo |
| `python -m bricksort.conveyor_demo` (or `bricksort-sorter`) | the sorting machine |
| `python -m bricksort.training_app` (or `bricksort-training`) | the Model training window |
| `python -m bricksort.catalog 300` | pick the 300 most common parts (Rebrickable data) |
| `python -m bricksort.render 100` | make 100 training pictures per part |
| `python -m bricksort.train 10` | train for 10 rounds |
| `python -m bricksort.cut` / `colour_review` | cut out pieces / check colours |
| `python -m bricksort.plastic_look` | measure the plastic's shine on your photos |
| `python -m bricksort.evaluate` | the honest accuracy test (`Test accuracy.bat`) |
| `pip install -e .[dev]`, then `pytest` and `ruff check .` | run the tests and the code checks (GitHub runs them on every push) |
