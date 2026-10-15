"""Which pictures training uses: the real-world test split and the per-round balance.

Kept apart from train.py (which needs torch) so these choices can be tested on their own.
"""
import random
import re
import zlib

REAL_WEIGHT = 10   # a piece with few photos: each photo is shown up to this many times per round
PHOTO_CAP = 200    # per piece per round: at most this many camera photos...
RENDER_CAP = 150   # ...and this many dataset renders (Dataset_02 renders, Dataset_03 cut-outs)
TEST_CAP = 40      # per piece: photos kept aside as the real-world test
DATASET_RENDER = re.compile(r"^(d02_|b200_)")


def split_real(real):
    """Keep about 1 in 5 of your camera photos aside as a real-world test (never trained on),
    at most TEST_CAP per piece. Only for parts with at least 3 photos, and the choice is fixed by
    file name, so the same photos stay in the test set every time you retrain. Dataset renders
    are never in the test: it's about real photos."""
    by_part = {}
    for item in real:
        by_part.setdefault(item[1], []).append(item)
    test, train = [], []
    for items in by_part.values():
        photos = [it for it in items if not DATASET_RENDER.match(it[0].name)]
        train += [it for it in items if DATASET_RENDER.match(it[0].name)]
        if len(photos) < 3:
            train += photos
            continue
        ranked = sorted(photos, key=lambda it: zlib.crc32(it[0].name.encode()))
        k = min(TEST_CAP, max(1, len(photos) // 5))
        test += ranked[:k]
        train += ranked[k:]
    return test, train


class Balanced:
    """Which pictures one round uses (see 'Balance' at the top). Simulated pictures: all of them.
    Real ones: per piece up to PHOTO_CAP photos and RENDER_CAP dataset renders, taking the colours
    in turn so a common colour doesn't crowd out a rare one. Different ones every round, but the
    same choice for the same round number, so a stopped training carries on exactly.
    (A plain class: the DataLoader takes anything with __iter__ and __len__ as its sampler.)"""

    def __init__(self, items, n_sim):
        self.n_sim, self.epoch = n_sim, 0
        groups = {}
        for i in range(n_sim, len(items)):
            path, part = items[i][0], items[i][1]
            kind = "render" if DATASET_RENDER.match(path.name) else "photo"
            groups.setdefault((part, kind), {}).setdefault(items[i][2], []).append(i)
        self.groups = []
        for (part, kind), by_colour in sorted(groups.items(), key=lambda kv: str(kv[0])):
            n = sum(len(v) for v in by_colour.values())
            cap = PHOTO_CAP if kind == "photo" else RENDER_CAP
            take = min(cap, n * (REAL_WEIGHT if kind == "photo" else 1))
            self.groups.append((list(by_colour.values()), take))
        self.length = n_sim + sum(t for _, t in self.groups)

    def set_epoch(self, epoch):
        self.epoch = epoch

    def __len__(self):
        return self.length

    def __iter__(self):
        rng = random.Random(1000 + self.epoch)
        chosen = list(range(self.n_sim))
        for colours, take in self.groups:
            pools = [rng.sample(c, len(c)) for c in colours]
            rng.shuffle(pools)
            got, i = [], 0
            while len(got) < take:  # one from each colour in turn, until enough
                more = [pool[i] for pool in pools if i < len(pool)]
                if not more:  # every picture used: go round again (a piece with few photos)
                    every = [x for pool in pools for x in pool]
                    got += [every[k % len(every)] for k in range(take - len(got))]
                    break
                got += more[:take - len(got)]
                i += 1
            chosen += got
        rng.shuffle(chosen)
        return iter(chosen)
