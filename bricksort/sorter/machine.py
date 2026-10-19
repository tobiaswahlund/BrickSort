"""The sorting loop: look -> spot -> recognise -> decide -> divert.

Machine.step() is called for every camera picture. When an object crosses the
middle of the picture it is photographed (cropped), recognised, a bin is chosen
with your rules, and the diverter is told which bin the piece arriving at the
belt's end at that moment should go to.

Goes to the rest bin:
  - several objects close together (the flaps couldn't separate them anyway)
  - an object bigger than the recognised part could be (likely stuck-together pieces)
  - anything the model is less sure about than "confidence_needed" in bins.json
"""
import json
import math
import time
from dataclasses import dataclass, field

from .. import config
from . import rules as rules_mod
from .detector import Detector, crop, merge_all

MM_PER_STUD, MM_PER_PLATE = 8.0, 3.2


@dataclass
class Decision:
    time: float
    bin: str
    reason: str
    picture: object            # the cropped picture the model saw
    part: str = ""
    color: str = ""
    guesses: list = field(default_factory=list)
    arrive_at: float = 0.0
    x_px: float = 0.0
    y_px: float = 0.0
    category: str = ""


class Machine:
    def __init__(self, camera, belt, diverter, recognizer, color_names, props, clock, rules=None):
        self.camera, self.belt, self.diverter, self.clock = camera, belt, diverter, clock
        self.recognizer, self.color_names, self.props = recognizer, color_names, props
        self.rules = rules or rules_mod.load()
        self.detector = Detector()
        self.tracks = {}       # id -> [cx, cy, triggered, last_seen_frame]
        self.next_id = 0
        self.frame_no = 0
        self.together_mm = 10.0  # objects closer than this (along the belt) can't be separated
        self.keep_pictures = True  # save pictures + guesses for "Review rest bin" and "Spot check"
        self.real = False          # a real camera: corrections of its pictures count as real photos

    def calibrate(self, empty_frames):
        for f in empty_frames:
            self.detector.learn_background(f)

    def _past_middle(self, x, width):
        return (x - width / 2) * self.camera.belt_direction >= 0

    def _track(self, blobs, width):
        """Follow objects from picture to picture; returns [(track_id, blob)].
        A track is [cx, cy, photographed?, last seen (frame), first seen before the middle?]."""
        out, used = [], set()
        for b in sorted(blobs, key=lambda b: b.cx):
            best, dist = None, 80.0
            for tid, (x, y, _, _seen, _) in self.tracks.items():
                d = math.hypot(b.cx - x, b.cy - y)
                if tid not in used and d < dist and (b.cx - x) * self.camera.belt_direction > -15:
                    best, dist = tid, d
            if best is None:
                best = self.next_id
                self.next_id += 1
                self.tracks[best] = [b.cx, b.cy, False, self.frame_no, not self._past_middle(b.cx, width)]
            used.add(best)
            self.tracks[best][:2] = [b.cx, b.cy]
            self.tracks[best][3] = self.frame_no
            out.append((best, b))
        self.tracks = {t: v for t, v in self.tracks.items() if self.frame_no - v[3] < 10}
        return out

    def step(self, frame):
        """Process one camera picture. Returns (blobs, [new Decisions])."""
        self.frame_no += 1
        h, w = frame.shape[:2]
        blobs = self.detector.find(frame)
        decisions = []
        tracked = self._track(blobs, w)
        for tid, b in tracked:
            track = self.tracks[tid]
            # Photograph each object once, as it crosses the middle line. Something that first shows up
            # already past the middle is a bit of an object that was photographed already (a dark or
            # shiny part of a piece the camera briefly saw as separate), so it doesn't count again.
            if track[2] or not track[4] or not self._past_middle(b.cx, w):
                continue
            # Everything too close along the belt for the flap to separate is decided together, once:
            # one picture, one decision, and none of those bits is photographed again.
            group = [(t, o) for t, o in tracked if self._gap_mm(o, b) < self.together_mm]
            for t, _ in group:
                self.tracks[t][2] = True
            decisions.append(self._decide(frame, b, [o for _, o in group], w))
        return blobs, decisions

    def _gap_mm(self, a, b):
        """Free belt between two objects, along the belt (0 if they overlap)."""
        return max(0, max(a.x0, b.x0) - min(a.x1, b.x1)) / self.camera.px_per_mm

    def _decide(self, frame, blob, near, width):
        """near: this object plus any others too close along the belt for the flap to separate."""
        now = self.clock.now()
        if len(near) > 1:   # one picture of all of them (they share one flap movement anyway)
            blob = merge_all(near)
        # specks (a highlight, a bit of shadow edge) don't count as another object
        near = [o for o in near if o.area >= 0.2 * blob.area]
        mm_past = self.camera.mm_from_camera_centre(blob.cx, width)
        arrive_at = now + (self.belt.camera_to_end_mm - mm_past) / self.belt.speed_mm_s
        picture = crop(frame, blob)
        rest = self.rules["rest_bin"]

        if self.recognizer is None:
            d = Decision(now, rest, "no trained model", picture)
        else:
            pred = self.recognizer.predict(picture)
            guesses = pred.parts
            part, p_conf = pred.parts[0]
            cid, c_conf = pred.colors[0]
            category, g_conf = pred.categories[0]
            color = self.color_names.get(cid, "?")
            bin_name, reason = rules_mod.choose_bin(self.rules, self.props, part, p_conf, color, c_conf,
                                                    len(near), category, g_conf, pred.printed)
            # The camera saw two or more clearly separate objects right next to each other?
            big_bits = [a for a in blob.bits if a >= 0.2 * blob.area]
            if bin_name != rest and len(big_bits) >= 2:
                bin_name, reason = rest, f"{len(big_bits)} pieces lying close together"
            # Too big for that part? Then it's probably several pieces stuck together.
            pr = self.props.get(part, {})
            if bin_name != rest and pr.get("length"):
                diag_mm = math.sqrt((pr["length"] * MM_PER_STUD) ** 2 + (pr["width"] * MM_PER_STUD) ** 2
                                    + (pr["height"] * MM_PER_PLATE) ** 2)
                if blob.long_side / self.camera.px_per_mm > diag_mm * 1.25 + 4:
                    bin_name, reason = rest, f"too big to be one {part}: pieces stuck together?"
            d = Decision(now, bin_name, reason, picture, part, color, guesses, category=category)
        d.arrive_at = arrive_at
        d.x_px, d.y_px = blob.cx, blob.cy  # where in the camera picture it was
        self.diverter.send(d.bin, arrive_at)
        if self.keep_pictures:
            self._save_for_review(d, pred if self.recognizer else None, config.REST_LOG if d.bin == rest
                                  else config.SORTED_LOG)
        return d

    def _save_for_review(self, d, pred, folder):
        """Keep the picture + guesses, so you can later say what a rest-bin piece was,
        or spot-check pieces that were sorted."""
        folder.mkdir(exist_ok=True)
        stem = time.strftime("%Y%m%d-%H%M%S") + f"-{self.frame_no:06d}"
        # the picture as the model saw it (e.g. with the camera's colour tint taken out)
        getattr(self.recognizer, "prepare", lambda p: p)(d.picture).save(folder / f"{stem}.png")
        info = {"bin": d.bin, "reason": d.reason, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "real": self.real}
        if pred:
            info.update(parts=pred.parts, colors=pred.colors, categories=pred.categories, printed=pred.printed)
        (folder / f"{stem}.json").write_text(json.dumps(info), encoding="utf-8")
        if folder == config.SORTED_LOG:  # only keep the newest ones
            old = sorted(folder.glob("*.png"))[:-config.SORTED_LOG_MAX]
            for p in old:
                p.unlink(missing_ok=True)
                p.with_suffix(".json").unlink(missing_ok=True)
