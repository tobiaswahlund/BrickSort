"""Train (or re-train) the recognizer on the simulated pictures + your photos and corrections.

Run:  python -m bricksort.train [rounds]      (or use "Model training.bat")
If a model already exists it continues from it, so re-training after a few
corrections is quick. Progress is saved after every round: stop it any time
(close the window), and the next start carries on from the last finished round.

The model learns four things at once:
  part number   from the main parts (parts.json) and your photos
  colour        from every picture whose colour is known
  category      from all of the above plus ~1,000 extra rarer parts (category_parts.json),
                so it can say "minifig accessory" even for a part it doesn't know by number
  printed       whether there's a print on the piece (my_photos/<part>/<colour>/printed/)

Your photos are read from
  my_photos/<part>/<colour name>/*.jpg           part and colour known
  my_photos/<part>/<colour name>/printed/*.jpg   part and plastic colour known, has a print
  my_photos/<part>/*.jpg                         part known, colour not
and the review window saves to corrections/ in the same layout.

Balance: datasets give some pieces thousands of pictures and others a handful. Each round
uses at most PHOTO_CAP camera photos and RENDER_CAP dataset renders per piece (sampling.py; spread over
its colours, different ones every round), so every piece gets a fair share and rare photos
(your own) are shown several times.
"""
import os
import random
import re
import sys
import time

import torch
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms as T
from PIL import Image, ImageOps

from . import catalog, config
from .model import MEAN, STD, LegoNet, device, eval_transform
from .sampling import DATASET_RENDER, Balanced, split_real  # noqa: F401  (caps live there too)

CHECKPOINT = config.MODEL_DIR / "training_in_progress.pt"  # progress of an unfinished training


def say(*args):
    print(*args, flush=True)  # flush so progress shows up right away in the demo's log


train_transform = T.Compose([
    T.RandomResizedCrop(config.IMAGE_SIZE, scale=(0.75, 1.0), ratio=(0.9, 1.1)),
    T.RandomRotation(180, fill=200),          # the camera may see it at any rotation
    T.ColorJitter(0.3, 0.3, 0.15, 0.01),      # gentle on hue, or colours would get mixed up
    T.RandomApply([T.GaussianBlur(5, (0.1, 1.5))], p=0.3),
    T.ToTensor(), T.Normalize(MEAN, STD),
])  # no mirroring: left and right versions of a part are different parts


def load_square(path):
    """Open a picture, turned the right way up, cropped to a centred square."""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    s = min(img.size)
    left, top = (img.width - s) // 2, (img.height - s) // 2
    return img.crop((left, top, left + s, top + s)).resize((config.IMAGE_SIZE, config.IMAGE_SIZE))


def photos_in(folder):
    return sorted(p for p in folder.glob("*") if p.suffix.lower() in config.PHOTO_TYPES)


class Pictures(Dataset):
    """Items are (path, part index, colour index, category index, printed 0/1); -1 = not known."""

    def __init__(self, items, transform):
        self.items, self.transform = items, transform

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        # A photo can be moved or renamed while training runs (e.g. while you sort photos):
        # then just use another picture instead of stopping the whole training.
        for _ in range(10):
            path, part, color, cat, printed = self.items[i]
            try:
                return self.transform(load_square(path)), part, color, cat, printed
            except (OSError, ValueError):
                i = random.randrange(len(self.items))
        raise RuntimeError("Too many pictures could not be opened")


def _color_of(path):
    m = re.search(r"_c(\d+)", path.stem)
    return int(m.group(1)) if m else None


def collect(parts, log=say):
    """Lists of (path, part_id or None, colour_id or None, category, printed 1/0/-1) for simulated
    and real pictures."""
    by_name = catalog.color_by_name()
    cat_of = {p["id"]: p.get("category", "") for p in parts}
    sim, real, unknown_names = [], [], set()
    for p in parts:
        sim += [(f, p["id"], _color_of(f), p.get("category", ""), 0) for f in sorted((config.RENDERS / p["id"]).glob("*.png"))]
    for p in catalog.load_category_parts():   # extra parts: category (and colour) only
        sim += [(f, None, _color_of(f), p["category"], 0) for f in sorted((config.CATEGORY_RENDERS / p["id"]).glob("*.png"))]
    for root in (config.MY_PHOTOS, config.CORRECTIONS):
        if not root.exists():
            continue
        for folder in sorted(x for x in root.iterdir() if x.is_dir()):
            c = catalog.folder_part(folder.name)  # printed version -> plain part; _not_lego, _multiple
            if c not in cat_of:
                continue
            if c in catalog.SPECIAL:  # subfolders (e.g. Stuck / Not_touching) are just for you
                real += [(f, c, None, cat_of[c], -1) for f in sorted(folder.rglob("*"))
                         if f.suffix.lower() in config.PHOTO_TYPES]
                continue
            real += [(f, c, None, cat_of[c], -1) for f in photos_in(folder)]
            for sub in sorted(x for x in folder.iterdir() if x.is_dir()):
                cid = catalog.find_color(sub.name, by_name)
                if cid is None:
                    unknown_names.add(sub.name)
                real += [(f, c, cid, cat_of[c], 0) for f in photos_in(sub)]
                # <colour>/printed/: a print on top of that plastic colour. Teach the part (and that
                # it's printed), not the colour, so a big red print on grey plastic doesn't teach
                # "red looks grey".
                if (sub / "printed").is_dir():
                    real += [(f, c, None, cat_of[c], 1) for f in photos_in(sub / "printed")]
    if unknown_names:
        log(f"Note: these colour folder names aren't Rebrickable colours, so their colour is ignored: "
            f"{', '.join(sorted(unknown_names))}")
    # corrections of simulated pictures (demo drops, the virtual sorter) are renders, not real photos:
    # they train like simulated pictures and never count towards the real-photo test
    from_sim = [it for it in real if it[0].name.startswith(config.SIM_PREFIX)]
    if from_sim:
        real = [it for it in real if not it[0].name.startswith(config.SIM_PREFIX)]
        sim += from_sim
    return sim, real


def evaluate(net, loader, dev):
    """Share right for: part first guess, part in top 5, colour, category, printed yes/no."""
    net.eval()
    hits = {"top1": [0, 0], "top5": [0, 0], "color": [0, 0], "category": [0, 0], "printed": [0, 0]}
    with torch.no_grad():
        for x, y, c, g, pr in loader:
            parts, cols, cats, prints = (o.cpu() for o in net(x.to(dev)))
            has = y >= 0
            if has.any():
                k = parts[has].topk(min(5, parts.shape[1]), 1).indices
                hits["top1"][0] += (k[:, 0] == y[has]).sum().item()
                hits["top5"][0] += (k == y[has][:, None]).any(1).sum().item()
                hits["top1"][1] += has.sum().item()
                hits["top5"][1] += has.sum().item()
            for key, out, lab in (("color", cols, c), ("category", cats, g)):
                has = lab >= 0
                hits[key][0] += (out.argmax(1)[has] == lab[has]).sum().item()
                hits[key][1] += has.sum().item()
            has = pr >= 0
            hits["printed"][0] += ((prints[:, 0] > 0).long()[has] == pr[has]).sum().item()
            hits["printed"][1] += has.sum().item()
    net.train()
    return {k: a / max(n, 1) for k, (a, n) in hits.items()}


def _carry_over(net, old, classes, color_classes, category_classes, log):
    """Start from the previous model, keeping what each answer already learned."""
    state = old["state_dict"]
    heads = {"backbone.classifier.3": (net.backbone.classifier[3], classes, old.get("classes", [])),
             "color_head.3": (net.color_head[3], color_classes, old.get("color_classes", [])),
             "category_head.3": (net.category_head[3], category_classes, old.get("category_classes", []))}
    last = {k: (state.pop(k + ".weight", None), state.pop(k + ".bias", None)) for k in heads}
    net.load_state_dict(state, strict=False)  # a model from before the 'printed' answer: that one starts fresh
    with torch.no_grad():
        for prefix, (layer, new, old_list) in heads.items():
            w, b = last[prefix]
            if w is None:
                continue
            old_i = {c: i for i, c in enumerate(old_list)}
            for i, c in enumerate(new):
                if c in old_i:
                    layer.weight[i], layer.bias[i] = w[old_i[c]], b[old_i[c]]
    log("Continuing from the existing model")


def main(epochs=8, log=say):
    if CHECKPOINT.exists():  # a training that was stopped: carry on with exactly the same pictures
        resume = torch.load(CHECKPOINT, map_location="cpu", weights_only=False)
        classes, color_classes, category_classes = resume["classes"], resume["color_classes"], resume["category_classes"]
        train, n_sim_train, val, test, epochs = (resume[k] for k in ("train", "n_sim_train", "val", "test", "epochs"))
        log(f"Carrying on with a stopped training after round {resume['round']}/{epochs}")
    else:
        resume = None
        parts = catalog.load_parts()
        classes = [p["id"] for p in parts]
        sim, real = collect(parts, log)
        # look-alike colours (Light Gray / Light Bluish Gray) are learned as one: build the colour
        # list from the merged ids, so every colour output has pictures to learn from
        same = catalog.same_colour_ids(catalog.colors(include_trans=True))
        color_classes = sorted({same.get(it[2], it[2]) for it in sim + real if it[2] is not None})
        category_classes = sorted({it[3] for it in sim + real if it[3]})
        n_cat_only = sum(1 for it in sim if it[1] is None)
        n_renders = sum(1 for it in real if DATASET_RENDER.match(it[0].name))
        n_printed = sum(1 for it in real if it[4] == 1)
        log(f"{len(classes)} parts, {len(color_classes)} colours, {len(category_classes)} categories; "
            f"{len(sim) - n_cat_only} simulated pictures of known parts, {n_cat_only} of extra parts "
            f"(category only), {len(real) - n_renders} real photos/corrections ({n_printed} printed), "
            f"{n_renders} dataset renders")

        pidx = {c: i for i, c in enumerate(classes)}
        cidx = {c: i for i, c in enumerate(color_classes)}
        gidx = {c: i for i, c in enumerate(category_classes)}
        enc = lambda items: [(f, pidx.get(p, -1), cidx.get(same.get(c, c), -1), gidx.get(g, -1), pr)
                             for f, p, c, g, pr in items]

        random.seed(0)
        random.shuffle(sim)
        n_val = max(1, len(sim) // 10)
        real_test, real_train = split_real(real)
        val = enc(sim[:n_val])
        n_sim_train = len(sim) - n_val
        train = enc(sim[n_val:] + real_train)   # simulated first: the balancing relies on that order
        test = enc(real_test)
    log(f"{len(test)} of your photos are kept aside as a test the model never trains on")

    dev = device()
    log(f"Training on {'graphics card' if dev.type == 'cuda' else 'processor (slower)'}")
    net = LegoNet(len(classes), len(color_classes), len(category_classes))
    if resume:
        net.load_state_dict(resume["state_dict"])
    elif config.MODEL_FILE.exists():
        _carry_over(net, torch.load(config.MODEL_FILE, map_location="cpu", weights_only=True), classes, color_classes,
                    category_classes, log)
    net.to(dev)

    workers = min(8, os.cpu_count() or 4)
    sampler = Balanced(train, n_sim_train)
    log(f"Each round: {len(sampler)} pictures (of {len(train)}; the big datasets are spread over the rounds)")
    train_dl = DataLoader(Pictures(train, train_transform), batch_size=64, sampler=sampler,
                          num_workers=workers, persistent_workers=True, drop_last=len(sampler) > 64)
    val_dl = DataLoader(Pictures(val, eval_transform), batch_size=128, num_workers=workers)
    # Continuing: smaller steps, so a quick retrain fine-tunes instead of shaking up what it knows
    lr = 3e-4 if config.MODEL_FILE.exists() else 1e-3
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, lr, total_steps=epochs * len(train_dl))
    first = 1
    if resume:
        opt.load_state_dict(resume["opt"])
        sched.load_state_dict(resume["sched"])
        first = resume["round"] + 1
    # Little smoothing, so "97% sure" means something when the sorter needs e.g. 90% to pick a bin
    part_loss = torch.nn.CrossEntropyLoss(label_smoothing=0.02, ignore_index=-1)
    other_loss = torch.nn.CrossEntropyLoss(ignore_index=-1)
    # printed pieces are rare: count each one more, so the model doesn't just always say "no print"
    print_loss = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor(5.0, device=dev))

    r = None
    for ep in range(first, epochs + 1):
        t0, total = time.time(), 0.0
        sampler.set_epoch(ep)
        every = max(1, len(train_dl) // 50)   # progress about every 2% (the Model training window shows it)
        for b, (x, y, c, g, pr) in enumerate(train_dl, 1):
            if b % every == 0:
                log(f"  progress {b}/{len(train_dl)} (round {ep}/{epochs})")
            opt.zero_grad()
            parts_out, cols, cats, prints = net(x.to(dev))
            y, c, g, pr = y.to(dev), c.to(dev), g.to(dev), pr.to(dev)
            loss = 0.0
            if (y >= 0).any():
                loss = loss + part_loss(parts_out, y)
            if (c >= 0).any():
                loss = loss + 0.5 * other_loss(cols, c)
            if (g >= 0).any():
                loss = loss + 0.5 * other_loss(cats, g)
            if (pr >= 0).any():
                has = pr >= 0
                loss = loss + 0.3 * print_loss(prints[has, 0], pr[has].float())
            if isinstance(loss, float):  # nothing labelled in this batch
                continue
            loss.backward()
            opt.step()
            sched.step()
            total += loss.item()
        r = evaluate(net, val_dl, dev)
        log(f"Round {ep}/{epochs}: loss {total / len(train_dl):.3f}, simulated test: part right first guess "
            f"{r['top1']:.0%}, within top 5 {r['top5']:.0%}, colour {r['color']:.0%}, "
            f"category {r['category']:.0%} ({time.time() - t0:.0f}s)")
        # Saved after every round: the computer can be turned off, and the next start carries on from here
        config.MODEL_DIR.mkdir(exist_ok=True)
        torch.save({"round": ep, "epochs": epochs, "state_dict": net.state_dict(), "opt": opt.state_dict(),
                    "sched": sched.state_dict(), "classes": classes, "color_classes": color_classes,
                    "category_classes": category_classes, "train": train, "n_sim_train": n_sim_train,
                    "val": val, "test": test}, str(CHECKPOINT) + ".tmp")
        os.replace(str(CHECKPOINT) + ".tmp", CHECKPOINT)  # never a half-written file if power goes mid-save
        log(f"  (saved progress: safe to stop now and carry on later)")

    if r is None:
        r = evaluate(net, val_dl, dev)
    info = {"top1": r["top1"], "top5": r["top5"], "color": r["color"], "category": r["category"],
            "trained": time.strftime("%Y-%m-%d %H:%M"), "real": len(train) - n_sim_train, "real_test_n": len(test)}
    if test:
        t = evaluate(net, DataLoader(Pictures(test, eval_transform), batch_size=128, num_workers=workers), dev)
        info.update(real_top1=t["top1"], real_top5=t["top5"], real_color=t["color"], real_printed=t["printed"])
        log(f"On your {len(test)} set-aside real photos: part right first guess {t['top1']:.0%}, "
            f"within top 5 {t['top5']:.0%}, colour right {t['color']:.0%}, printed yes/no right {t['printed']:.0%}")
    config.MODEL_DIR.mkdir(exist_ok=True)
    if config.MODEL_FILE.exists():  # keep the previous model, in case the new one is worse
        os.replace(config.MODEL_FILE, config.MODEL_DIR / f"lego_model_before_{time.strftime('%Y%m%d_%H%M')}.pt")
    torch.save({"state_dict": net.state_dict(), "classes": classes, "color_classes": color_classes,
                "category_classes": category_classes, "info": info}, config.MODEL_FILE)
    log(f"Saved model to {config.MODEL_FILE}")
    CHECKPOINT.unlink(missing_ok=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8)
