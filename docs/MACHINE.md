# Building the real machine

A small BrickSort machine: a webcam above a short belt, a stepper motor that moves the belt, and one
servo that turns a chute to the right bin. An Arduino runs the motor and the servo; the PC does the
seeing, the deciding and the timing. Pieces are put on the belt by hand at first.

The software is ready for it: the camera test (`python -m bricksort.camera_test`), the Real machine
window (`python -m bricksort.real_machine`) and the Arduino program
([firmware/bricksort_machine](../firmware/bricksort_machine/bricksort_machine.ino)). Both windows are in
the BrickSort menu under Real world.

## Parts

Rough prices in Sweden (2026); AliExpress is often about half.

| Part | What for | About |
|---|---|---|
| Arduino Uno or Nano (a clone is fine) | runs the belt motor and the chute | 100–300 kr |
| USB webcam, 1080p (e.g. Logitech C920 or C270) | looks straight down at the belt | 250–700 kr |
| Stepper motor NEMA 17 + driver board (A4988 or TMC2208) | moves the belt at an exact speed | 200–300 kr |
| Servo (MG996R, or MG90S for a light chute) | turns the chute | 40–100 kr |
| 12 V power supply, 2–3 A | motor and LED strip | 100–150 kr |
| 5 V supply for the servo (a step-down converter from 12 V, or a phone charger) | the servo | 30–100 kr |
| White LED strip, 12 V, about 0.5 m | even light, as the model was trained with | 80–150 kr |
| Belt: a matte black band about 60 mm wide (rubber, or fabric glued into a loop) | the belt | 50–150 kr |
| Two rollers about 25 mm across (PVC pipe or wooden dowel), 4 bearings, an axle | belt rollers | 100–200 kr |
| Wood or MDF, screws, glue | frame, camera arm, chute | 150–250 kr |
| Wires, a breadboard, a 100 µF capacitor | connecting it | 50–100 kr |
| Small boxes or cups | bins | 0–50 kr |

About **1,200–2,000 kr** in total, less with parts you already have.

## How it fits together

```
     webcam (about 210 mm above the belt, looking straight down)
        |
 LED strip along the belt, a little to the side of the camera
        |
 [roller]=========== belt (matte black) ===========[roller]--> pieces fall into the chute
    ^                       ^                                       |
 stepper motor        middle of the picture:                  servo turns the chute
 drives this roller   each piece is photographed here          to one of the bins below
```

- The belt runs **left to right** in the camera picture (or set "right to left" in the Real machine window).
- Measure **from the middle of the camera picture to where pieces leave the belt** (about 250 mm is
  fine). The machine uses it to time the chute: piece seen in the middle, speed known, so it knows
  when the piece arrives.
- The chute sits under the belt's end and swings from 30° to 150°; the bins stand in a half circle
  under its tip, the **rest bin last** (it's also where the chute waits).

## Wiring

| From | To |
|---|---|
| Driver STEP, DIR, EN | Arduino pins 3, 4, 5 |
| Driver VMOT, GND | 12 V supply (+, −), with the 100 µF capacitor across them, close to the driver |
| Driver VDD, GND | Arduino 5 V, GND |
| Driver 1A 1B 2A 2B | the stepper motor's four wires (two coils) |
| Driver MS1 MS2 MS3 (A4988) | 5 V, for 16 microsteps (as set in the Arduino program) |
| Servo signal (yellow/orange) | Arduino pin 9 |
| Servo + and − | the separate 5 V supply. Join its − to the Arduino's GND |
| LED strip | the 12 V supply |
| Arduino | the PC, with a USB cable |

Set the driver's current limit for your motor first (the small screw on the driver; its datasheet
says how). Never unplug the motor while the driver has power.

## Software, once

1. Install the free **Arduino IDE**, open `firmware/bricksort_machine/bricksort_machine.ino`, check the
   settings at the top (roller diameter, microsteps, chute angles), choose your board and port, and press
   **Upload**.
2. BrickSort menu → **Camera test**: point the webcam at the belt, press **Learn the empty surface**, then
   put a 2x4 brick (or another brick or plate you choose in the list) under it, lined up with the
   picture's edges, and press **Measure**. That's how many pixels make one millimetre. If the camera
   sees more than the belt, choose **Area** → Rectangle or Circle and drag it over the belt: everything
   outside it is ignored (the Real machine window has the same choice).
3. BrickSort menu → **Real machine**: choose the Arduino's port and press **Connect**. Try **Run the belt
   3 s** (does it go the right way and at a sensible speed?) and **Turn the chute** to each bin.
4. Enter the belt speed and the distance from the camera's middle to the chute.
5. **Learn the empty belt**, then **Start sorting**. Put pieces on the belt one at a time, a few cm apart.

## Making it see better

- Matte belt, even light from the LED strip, no daylight falling on the belt.
- Before trusting it, sort a handful of known pieces and check the bins. Pieces in the rest bin and
  the sorted ones are saved for **Review rest bin** and **Spot check** in the Demo; correcting them
  teaches the model your machine.
- For colours above all, train on your own machine: Model training → Machine setup, with a photo of
  your belt and your lamps' height and colour.

## Later

- An automatic feeder (a vibrating hopper) so pieces don't have to be put on by hand.
- A see-through belt lit from below: every piece, black and transparent too, becomes a sharp shadow
  for the camera.
