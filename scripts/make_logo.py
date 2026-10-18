"""Draw the BrickSort logo: a red brick dropping through a split into three coloured bins.

Run:  python scripts/make_logo.py
Writes bricksort/assets/logo.png (512 px) and logo.ico (the window and taskbar icon, 16 to 256 px).
Drawn 4x bigger and scaled down, so the edges are smooth.
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "bricksort" / "assets"
S = 2048                      # drawing size; everything below is in 1/1000 of it
NAVY = (27, 38, 59)
RED, RED_DARK, RED_LIGHT = (214, 40, 40), (160, 24, 30), (240, 92, 86)
BINS = [(0, 109, 183), (247, 191, 30), (35, 145, 74)]   # blue, yellow, green


def p(*xy):
    return [v * S / 1000 for v in xy]


def draw():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(p(20, 20, 980, 980), radius=S * 0.2, fill=NAVY)

    # the brick: a 2-stud brick seen from the front, studs on top
    d.rounded_rectangle(p(250, 250, 750, 520), radius=S * 0.03, fill=RED)
    d.rectangle(p(250, 470, 750, 520), fill=RED_DARK)                  # shaded bottom edge
    for cx in (375, 625):
        d.rounded_rectangle(p(cx - 80, 165, cx + 80, 265), radius=S * 0.02, fill=RED)
        d.rectangle(p(cx - 80, 235, cx + 80, 265), fill=RED_DARK)      # stud side, in shadow
        d.rounded_rectangle(p(cx - 62, 180, cx - 30, 225), radius=S * 0.01, fill=RED_LIGHT)   # shine
    d.rounded_rectangle(p(282, 285, 330, 440), radius=S * 0.015, fill=RED_LIGHT)            # shine

    # the split: one path into three
    w = S * 0.034
    for x in (250, 500, 750):
        d.line(p(500, 560, x, 690), fill=(220, 226, 236), width=int(w), joint="curve")
    d.ellipse(p(470, 540, 530, 600), fill=(220, 226, 236))

    # three bins
    for x, colour in zip((250, 500, 750), BINS):
        d.rounded_rectangle(p(x - 95, 700, x + 95, 860), radius=S * 0.025, fill=colour)
        d.rectangle(p(x - 95, 700, x + 95, 735), fill=tuple(int(c * 0.75) for c in colour))
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw()
    big.resize((512, 512), Image.LANCZOS).save(OUT / "logo.png")
    big.resize((256, 256), Image.LANCZOS).save(
        OUT / "logo.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT / "logo.png", "and", OUT / "logo.ico")


if __name__ == "__main__":
    main()
