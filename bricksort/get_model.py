"""Download the trained model from the project's GitHub Releases into model/lego_model.pt.

Run:  python -m bricksort.get_model          (setup.bat does this for you)
      python -m bricksort.get_model v0.1.0   (a particular release instead of the newest)

The model file is licensed CC BY-SA 4.0 (part of its training data is CC BY-SA 4.0).
An existing model is kept as model/lego_model_before_download.pt.
"""
import os
import sys
import urllib.request

from . import config

REPO = "tobiaswahlund/BrickSort"


def url(tag=None):
    if tag:
        return f"https://github.com/{REPO}/releases/download/{tag}/lego_model.pt"
    return f"https://github.com/{REPO}/releases/latest/download/lego_model.pt"


def main(tag=None):
    config.MODEL_DIR.mkdir(exist_ok=True)
    tmp = config.MODEL_FILE.with_suffix(".download")
    print(f"Downloading the trained model from {url(tag)} ...", flush=True)
    req = urllib.request.Request(url(tag), headers={"User-Agent": "BrickSort/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total, done = int(r.headers.get("Content-Length") or 0), 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e6:.0f} of {total / 1e6:.0f} MB", end="", flush=True)
        print()
    except OSError as e:
        tmp.unlink(missing_ok=True)
        print(f"Couldn't download it ({e}). Download lego_model.pt by hand from "
              f"https://github.com/{REPO}/releases and put it in {config.MODEL_DIR}.")
        return False
    # check it really is a model file before using it (weights_only: it can't run code)
    import torch
    ckpt = torch.load(tmp, map_location="cpu", weights_only=True)
    if "state_dict" not in ckpt or "classes" not in ckpt:
        tmp.unlink(missing_ok=True)
        print("The downloaded file isn't a BrickSort model; nothing was changed.")
        return False
    if config.MODEL_FILE.exists():
        os.replace(config.MODEL_FILE, config.MODEL_DIR / "lego_model_before_download.pt")
    os.replace(tmp, config.MODEL_FILE)
    print(f"Done: {config.MODEL_FILE} knows {len(ckpt['classes'])} parts.")
    return True


if __name__ == "__main__":
    sys.exit(0 if main(*sys.argv[1:2]) else 1)
