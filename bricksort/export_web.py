"""Make the model run in a web browser: model/lego_model.pt -> <out>/model.onnx + <out>/labels.json.

Run:  python -m bricksort.export_web web/model     (the GitHub Pages build does this; see .github/workflows)

The website (web/) runs the same network with onnxruntime-web, on the visitor's own computer: no
server, and no picture leaves the browser unless they choose Brickognize. labels.json holds what the
outputs mean: part numbers with names, colours with names and RGB (and which look-alike colours
count as one), categories, and the input size and normalisation.
"""
import json
import sys
from pathlib import Path

import torch

from . import catalog, config
from .model import MEAN, STD, LegoNet
from .sorter import rules


def export(out, model_file=config.MODEL_FILE):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ckpt = torch.load(model_file, map_location="cpu", weights_only=True)
    net = LegoNet(len(ckpt["classes"]), len(ckpt["color_classes"]), len(ckpt["category_classes"]), pretrained=False)
    net.load_state_dict(ckpt["state_dict"], strict=False)
    net.eval()
    x = torch.zeros(1, 3, config.IMAGE_SIZE, config.IMAGE_SIZE)
    torch.onnx.export(net, x, out / "model.onnx", input_names=["image"],
                      output_names=["parts", "colours", "categories", "printed"], opset_version=17,
                      dynamo=False)

    defaults = config.PROJECT_DIR / "defaults"
    known = {p["id"]: p for f in ("parts.json", "custom_parts.json") if (defaults / f).exists()
             for p in json.loads((defaults / f).read_text(encoding="utf-8"))}
    names = {pid: p["name"] for pid, p in known.items()}
    names.update(catalog.SPECIAL)
    # what the sorting rules (bins) need to know about each part: category, size, flat or not
    sizes = json.loads((defaults / "part_properties.json").read_text(encoding="utf-8"))
    facts = {pid: {"category": known.get(pid, {}).get("category", ""), **sizes.get(pid, {})}
             for pid in ckpt["classes"]}
    table = catalog.colors(include_trans=True)
    same = catalog.same_colour_ids(table)
    colours = [{"id": c, "name": table.get(c, (str(c), (128, 128, 128)))[0],
                "rgb": list(table.get(c, ("", (128, 128, 128)))[1]), "counts_as": same.get(c, c)}
               for c in ckpt["color_classes"]]
    labels = {"parts": [{"id": p, "name": names.get(p, ""), **facts[p]} for p in ckpt["classes"]],
              "colours": colours, "categories": ckpt["category_classes"],
              "size": config.IMAGE_SIZE, "mean": MEAN, "std": STD,
              "trained": ckpt.get("info", {}).get("trained", ""),
              "rules": rules.DEFAULT}   # the sorting machine's bins (the website uses the default ones)
    (out / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    print(f"Wrote {out / 'model.onnx'} ({(out / 'model.onnx').stat().st_size / 1e6:.0f} MB) and labels.json "
          f"({len(labels['parts'])} parts, {len(colours)} colours)")


if __name__ == "__main__":
    export(sys.argv[1] if len(sys.argv) > 1 else "web/model")
