"""The recognizer itself: a small image classifier (MobileNetV3) with four answers:
which part (shape), which colour, which broad category, and whether it has a print.

It's small enough to run offline on a laptop or a Raspberry Pi.
"""
import torch
import torchvision
from PIL import Image
from torchvision import transforms as T

from . import config

MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]

eval_transform = T.Compose([T.Resize((config.IMAGE_SIZE, config.IMAGE_SIZE)), T.ToTensor(), T.Normalize(MEAN, STD)])


def _head(n):
    return torch.nn.Sequential(torch.nn.Linear(960, 256), torch.nn.Hardswish(), torch.nn.Dropout(0.2),
                               torch.nn.Linear(256, n))


class LegoNet(torch.nn.Module):
    """One shared 'eye' with four answers: exact part, plastic colour, broad category, printed or not."""

    def __init__(self, num_parts, num_colors, num_categories, pretrained=True):
        super().__init__()
        weights = torchvision.models.MobileNet_V3_Large_Weights.IMAGENET1K_V2 if pretrained else None
        net = torchvision.models.mobilenet_v3_large(weights=weights)
        net.classifier[3] = torch.nn.Linear(net.classifier[3].in_features, num_parts)
        self.backbone = net
        self.color_head = _head(num_colors)
        self.category_head = _head(num_categories)
        self.printed_head = _head(1)   # one number: above 0 means "has a print"

    def forward(self, x):
        b = self.backbone
        f = b.avgpool(b.features(x)).flatten(1)
        return b.classifier(f), self.color_head(f), self.category_head(f), self.printed_head(f)


class Prediction:
    """parts / colors / categories: lists of (id or name, probability), best first.
    printed: chance (0..1) that the piece has a print on it; None for models from before that answer."""

    def __init__(self, parts, colors, categories, printed=None):
        self.parts, self.colors, self.categories, self.printed = parts, colors, categories, printed


def device():
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class Recognizer:
    """Loads the trained model file and answers 'which part is this, in which colour?'."""

    def __init__(self, path=config.MODEL_FILE):
        # weights_only: a model file can only hold numbers and lists, never code that would run
        ckpt = torch.load(path, map_location="cpu", weights_only=True)
        self.classes = ckpt["classes"]
        self.color_classes = ckpt["color_classes"]
        self.category_classes = ckpt["category_classes"]
        self.net = LegoNet(len(self.classes), len(self.color_classes), len(self.category_classes), pretrained=False)
        missing = self.net.load_state_dict(ckpt["state_dict"], strict=False).missing_keys
        self.knows_printed = not any(k.startswith("printed_head") for k in missing)
        self.dev = device()
        self.net.to(self.dev).eval()
        self.info = ckpt.get("info", {})
        from . import catalog  # colours that look the same (Light Gray / Light Bluish Gray) count as one
        self.same = catalog.same_colour_ids(catalog.colors(include_trans=True))

    @torch.no_grad()
    def predict(self, image, top=5, top_colors=3, top_categories=3):
        if not isinstance(image, Image.Image):
            image = Image.fromarray(image)
        x = eval_transform(image.convert("RGB")).unsqueeze(0).to(self.dev)
        outs = self.net(x)
        lists = []
        for out, names, k in zip(outs[:3], (self.classes, self.color_classes, self.category_classes),
                                 (top, top_colors, top_categories)):
            p = torch.softmax(out, 1)[0].cpu()
            if names is self.color_classes:  # add up look-alike colours into one
                merged = {}
                for j, q in enumerate(p.tolist()):
                    cid = self.same.get(names[j], names[j])
                    merged[cid] = merged.get(cid, 0.0) + q
                lists.append(sorted(merged.items(), key=lambda t: -t[1])[:k])
                continue
            v, i = p.topk(min(k, len(names)))
            lists.append([(names[j], float(q)) for q, j in zip(v, i)])
        printed = float(torch.sigmoid(outs[3])[0, 0]) if self.knows_printed else None
        return Prediction(*lists, printed=printed)


# ---------------------------------------------------------------- which model the windows use
CHOICE_FILE = config.PROJECT_DIR / "model_choice.json"   # chosen in the BrickSort menu
MINE, BRICKOGNIZE = "mine", "brickognize"


def chosen():
    """MINE (your trained model) or BRICKOGNIZE (the online service)."""
    import json
    try:
        return json.loads(CHOICE_FILE.read_text(encoding="utf-8")).get("model", MINE)
    except (OSError, ValueError):
        return MINE


def choose(name):
    import json
    CHOICE_FILE.write_text(json.dumps({"model": name}), encoding="utf-8")


def load_recognizer():
    """The model the windows use: your own (None if there isn't one yet) or Brickognize. Brickognize
    has remote=True: it can't be retrained, so the windows hide correcting and retraining."""
    if chosen() == BRICKOGNIZE:
        from .brickognize import BrickognizeRecognizer
        return BrickognizeRecognizer()
    return Recognizer() if config.MODEL_FILE.exists() else None


def is_remote(recognizer):
    return bool(getattr(recognizer, "remote", False))
