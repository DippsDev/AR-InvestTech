"""One-off: render the app icon (same design as tray.py's _make_icon) to
packaging/ar_icon.ico, embedding the standard Windows sizes. Run once; the
.ico is a static, checked-in asset from then on.

    python packaging/generate_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def make_icon() -> Image.Image:
    size = 256
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.ellipse([0, 0, size - 1, size - 1], fill=(15, 23, 42))              # slate-900
    draw.ellipse([12, 12, size - 13, size - 13], outline=(34, 197, 94), width=10)  # green ring

    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 90)
    except OSError:
        font = ImageFont.load_default()

    text = "AR"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2, (size - th) / 2 - 4), text, fill="white", font=font)

    return img


if __name__ == "__main__":
    out = Path(__file__).parent / "ar_icon.ico"
    make_icon().save(out, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Saved {out}")
