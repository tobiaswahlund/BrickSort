"""Make BrickSort_share.zip: everything someone else needs to run the demos with your trained model.

Run:  python -m bricksort.share
Leaves out your own photos and corrections, and the big re-creatable data
(setup.bat on the other computer downloads that).
"""
import zipfile

from . import config

INCLUDE = ["bricksort", "model/lego_model.pt", "reference", "parts.json", "category_parts.json",
           "custom_parts.json", "part_properties.json", "bins.json", "belt_pieces.json", "README.md", "LICENSE", "scripts",
           "requirements.txt"]


def main():
    out = config.PROJECT_DIR / "BrickSort_share.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in INCLUDE:
            path = config.PROJECT_DIR / item
            if not path.exists():
                continue
            files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
            for f in files:
                if "__pycache__" in f.parts:
                    continue
                z.write(f, "BrickSort/" + f.relative_to(config.PROJECT_DIR).as_posix())
    print(f"Made {out} ({out.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
