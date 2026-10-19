# Design decisions

The main choices behind BrickSort, why I made them, and what they cost.

## Training on rendered pictures

The model mostly learns from pictures rendered from LDraw's 3D models, not from photos. It was the
easiest and fastest way to get started, so that I had something to work with. Every rendered picture
already knows its exact part number and colour, so I get about 100 pictures of each of about 1,300 parts
(and some of 1,100 more) without labelling any by hand. The renders stay in use because I can copy the setting the model will actually
be used in: the sorting machine's light, belt and background.

The cost is that renders can't capture the shine and texture of real pieces, all the scratches and
bumps. This gap between simulation and reality is called sim-to-real. My grey pieces are an example:
the plastic didn't shine like real plastic in the renders, so in real photos the model saw light grey as
white. That's why I mix in real photos and match the renders' shine and lamps to real photos. Real
photos are scarce, though, and rendering is much faster.

At first I tried taking my own photos for the training data and built tools to make that faster. It
still took a few minutes per picture, while downloading existing datasets was far quicker.

## An honest test set

Training prints two scores: one on renders held back from training, and one on real photos held back
from training. Both come out too high. The held-back renders are made exactly like the training renders.
The held-back photos come from the same photo sessions and often the same physical bricks as the training
photos: same lamp, same background, the same brick from another angle. The model has almost seen them
already. This is called a leak.

So the real test is 163 different bricks, photographed with my phone and never used in training.
Training skips the test folder, so it stays unseen however often I retrain. I took them from my own
collection by blindly scooping a handful from my LEGO bin, so I didn't choose them, but my collection is
heavily biased towards Star Wars and Castle, so it's not a sample of all LEGO. I dropped them on a black
surface so they'd land randomly, then spread them out while keeping each one at the angle it landed, so I
could cut them out cleanly afterwards. My own earlier training photos were taken with the same phone, but
on my wooden desk under a yellowish desk lamp, so the test is a different setting. Those early photos were
a first try to learn how everything worked, and I'll probably stop using them. I labelled the test pieces myself before looking at any model guess, so that they're labelled
with what they truly are. Some pieces aren't clear to the naked eye, and seeing the model's guess could
bias me towards its answer (anchoring bias). The result is in [the README](../README.md#results).

## Starting from a pretrained network

The model doesn't start from zero. It starts from a network already trained on ImageNet, over a million
everyday photos of things like dogs, cars and cups. That network has already learned to see edges,
corners, textures and shapes, and those are useful for LEGO too, so training only has to teach it what's
specific to LEGO pieces. It needs far less data and time than learning to see from scratch, and it copes
better with real photos, because it was trained on real photos to begin with. This is called transfer
learning.

## Messy training pictures on purpose

The renders are made messy on purpose: random lamps, surfaces, blur, camera noise and scratches. This is
to simulate the variety of real life. All LEGO pieces have some scratches and bite marks, and if the
machine is bumped some pictures will be blurry. Every setup has its own lighting, which also changes with
the daylight. With all these variations the model copes better with changing surroundings and all the
small imperfections real life brings. This is called domain randomisation.

## A fair share for every piece

Some pieces have thousands of pictures and others only a handful. Each training round uses at most a set
number of pictures per piece, so the model doesn't favour some pieces over others. If it's trained much
more on one piece, it will lean towards that answer and give wrong answers because of it. Pieces with only
a few of my own photos get them shown several times instead.

## The rest bin

When the model isn't sure enough, the piece goes to the rest bin instead of its best guess. A wrong bin
is worse than the rest bin: one wrong piece spoils a whole bin and is hard to find later, while a piece in
the rest bin just gets checked again. Low confidence means a higher chance it would have been sorted
wrong, and this way that gets caught.

The unsure pieces are also the ones worth training on. With them all in one bin (and their pictures
saved), they can be corrected and used to train the model further on exactly the pieces it struggles
with, which is harder if they're mixed in with everything else.

## Two pieces at once

When two bricks touch on the belt, the camera sees them as one object. If the model answers "several
pieces", or the object finder sees it's made of two separate bits, it goes to the rest bin so it can be
put back on the belt by hand, not touching. A guess would put at least one brick in the wrong bin.

## One model, four answers

From one picture the model answers four questions: the part, the colour, the category and whether the
piece is printed. All four depend on the same things in the picture (edges, studs, shape, shine), so one
shared network learns those once and every answer benefits, and it runs once per piece instead of four
times. As a first project it was also easier to start with one model. In the future I'd like to try four
separate models and see whether that gives better results.

The category helps with parts the model doesn't know by number: about 1,100 rarer parts are trained by
category only. For those it can still say, for example, "minifig accessory", and a category bin can take
the piece instead of the rest bin.

## A small model

The model is MobileNetV3, a small, fast network made for phones. On a sorting machine the piece has
little time before it has to be sent into the right bin, so the decision must be fast. A small model also
runs on cheaper hardware, which makes it more accessible for others. It needs less training data, too,
and data can be hard to come by, especially if you have to collect your own to specialise the model for
your own setup.

## Look-alike colours and parts

LEGO replaced Light Gray with Light Bluish Gray at some point. To the eye they're almost identical, so
there's no real reason to separate them, and the same goes for a few other colours. For part numbers, a
builder rarely cares about the version letter (3062a or 3062b): the differences are mostly on the inside
and practically impossible for a camera to see. So these colours and versions count as the same when the
model is scored and when a piece is matched to a bin, and the model isn't punished for a difference a
camera can't see. If it ever matters, it's better to check the difference yourself.

## Hardware kept apart from the logic

The sorting logic (finding objects in the picture, following them along the belt, asking the model,
choosing a bin, timing the flap) only talks to a camera, a belt, a flap and a clock through one small
interface (`bricksort/sorter/hardware.py`). Right now the simulation is plugged in.

This was a good way to see how a machine would and could work in theory, and to show others how it
works. It also let me test everything, and see how training on the exact setting the model is used in
would work, even though the simulation can't give a truly honest score. The logic was built and tested
without owning a single motor. A real machine only needs a real camera, belt and flap swapped in, and if
it misbehaves while the simulation doesn't, the problem is in the hardware part.

## Corrections make it better with use

In the demo, and for pieces in the rest bin, I can correct the model when it's wrong, and the next training
uses the corrections. The idea is that it gets better the more it's used on a specific machine, adapting
over time to the setting it happens to be used in. When it's wrong, it's likely bad at that particular
part, so it gets more training exactly where it's needed most.

## What the results tell me

In the first test (model v0.1.0), the right part was the first guess 53% of the time, but among the top
five guesses 82% of the time. So it's often close, and not clueless even when the first guess is wrong. For many uses that's
enough: to sort all the reds, blues and yellows, it only needs to know a piece is blue, not whether it's
Medium Blue or Bright Light Blue, and to pull out the Technic pieces it doesn't need to tell a Technic axle 3
from an axle 3 with a stop.

Colour is affected far more by lighting than shape is, which makes it important to train on the lighting
the machine actually has. So it matters less that colour is weak out of the box: it gets better with
training on the machine's own setup and corrections. To raise the colour score, the lighting in the
training pictures needs to be closer to the real pictures. For v0.2.0 I matched the plastic's shine to real
bricks by eye and used the machine's LED-strip lighting, and colour went from 30% to 44%. Also, the model was trained on pictures from all kinds of angles, but the
sorting machine only ever sees pieces from above. So v0.2.0 was trained only on pictures from above, with
the piece anywhere in the camera's view, which suits its real job at the cost of recognising pieces in
photos taken from any angle.

## What I'd do differently

This was a learning project, and the mistakes were good learning experiences. If I started over, I'd go
for existing datasets and renders from the start instead of photographing training pictures myself, and
I'd make all the tools into one single app instead of many separate windows.
