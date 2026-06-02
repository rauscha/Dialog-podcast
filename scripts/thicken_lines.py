"""One-off: thicken the lines on an externally-generated cover image so it
survives Spotify-thumbnail downscale, then upscale to the canonical 3000x3000
and save as the show's cover. Also writes a 128x128 preview so we can eyeball
thumbnail legibility before shipping.

Usage:
    python scripts/thicken_lines.py <source.png> <slug> [--passes N]

`source.png` is the external image (Gemini/ChatGPT export). `slug` is the show
key (e.g. "ai") so output lands at assets/cover-{slug}.jpg.

Why MaxFilter: the source is mint lines/nodes on a dark charcoal background.
MaxFilter replaces each pixel with the channel-wise max in its window, which
expands bright pixels outward. One pass with size=5 = +2 px on the source;
that scales to ~6 px at 3000x3000, visible at 120 px thumbnail size.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "assets"
TARGET_SIZE = 3000  # Spotify-recommended podcast cover dimension
PREVIEW_SIZE = 128  # Eyeball thumbnail legibility


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="Path to source PNG/JPG")
    parser.add_argument("slug", help="Show slug (writes assets/cover-{slug}.jpg)")
    parser.add_argument(
        "--passes",
        type=int,
        default=1,
        help="MaxFilter passes (default 1; bump if first round looks too thin)",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=5,
        help="MaxFilter kernel size (odd; default 5 = +2 px per pass)",
    )
    args = parser.parse_args()

    src_path = Path(args.source)
    img = Image.open(src_path).convert("RGB")
    print(f"[thicken] loaded {src_path.name} at {img.size}")

    thick = img
    for i in range(args.passes):
        thick = thick.filter(ImageFilter.MaxFilter(size=args.size))
        print(f"[thicken] pass {i + 1}/{args.passes}: MaxFilter(size={args.size})")

    full = thick.resize((TARGET_SIZE, TARGET_SIZE), Image.LANCZOS)
    out_path = ASSETS / f"cover-{args.slug}.jpg"
    full.save(out_path, "JPEG", quality=92, optimize=True)
    print(f"[thicken] wrote {out_path.relative_to(REPO_ROOT)} ({out_path.stat().st_size // 1024} KB)")

    preview = thick.resize((PREVIEW_SIZE, PREVIEW_SIZE), Image.LANCZOS)
    prev_path = ASSETS / f"cover-{args.slug}-thumb-preview.png"
    preview.save(prev_path, "PNG")
    print(f"[thicken] wrote {prev_path.relative_to(REPO_ROOT)} for thumbnail check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
