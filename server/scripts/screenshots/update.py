"""Puts the new README screenshots in place, but only the ones that look different from those already there, so an
update with no change to these screens changes no picture:
    python update.py NEW_DIR [DEST_DIR]      (DEST_DIR defaults to docs/public/screenshots)
Each new shot is scaled to the README's size (834 x 1194) first. Needs Pillow."""
import sys
from pathlib import Path

from PIL import Image, ImageChops

SIZE = (834, 1194)
NAMES = ["bidding", "play", "review", "stats", "learn"]
# a pixel counts as changed when a color moves by more than this, and a shot when more than this share of pixels did
# (so the same screen, scaled the same way, never counts as a change)
PIXEL, SHARE = 24, 0.0005


def changed(new: Image.Image, old: Image.Image) -> float:
    if new.size != old.size:
        return 1.0
    diff = ImageChops.difference(new, old).convert("L").point(lambda v: 255 if v > PIXEL else 0)
    return diff.histogram()[255] / (new.width * new.height)


def main() -> None:
    new_dir = Path(sys.argv[1])
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[3] / "docs/public/screenshots"
    dest.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        new = Image.open(new_dir / f"{name}.png").convert("RGB").resize(SIZE, Image.LANCZOS)
        target = dest / f"{name}.png"
        share = changed(new, Image.open(target).convert("RGB")) if target.exists() else 1.0
        if share > SHARE:
            new.save(target, optimize=True)
            print(f"{name}: updated ({share:.2%} of it changed)")
        else:
            print(f"{name}: no change")


if __name__ == "__main__":
    main()
