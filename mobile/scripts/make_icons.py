"""Generate the app's icon assets from one source image.

    python scripts/make_icons.py <source> [options]

The four slots the app ships are all derived from a single artwork, so a new
logo is one command rather than four hand-exported files at four sizes that
quietly drift apart.

Nothing about the framing is fixed, because no single framing suits all four.
A store icon wants the whole lockup; a launcher icon at 48px wants the emblem
and nothing else, since a tagline rendered that small is mush. So the crop,
the inset and the background are all arguments, and `--preview` writes
somewhere harmless until the numbers look right.

Examples
--------
Everything, straight from the artwork::

    python scripts/make_icons.py assets/source-logo.png

Look first, without touching assets/::

    python scripts/make_icons.py assets/source-logo.png --preview /tmp/icons

Launcher icon cropped to the emblem — drop the bottom 45% (wordmark, tagline
and feature strip) and a little off each side::

    python scripts/make_icons.py assets/source-logo.png \\
        --crop 8,4,8,45 --only adaptive,favicon

Match Android's icon background to the logo's ring::

    python scripts/make_icons.py assets/source-logo.png --adaptive-bg "#166534"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - a clear message beats a traceback
    sys.exit("Pillow is required:  pip install Pillow")

MOBILE = Path(__file__).resolve().parent.parent
ASSETS = MOBILE / "assets"
APP_JSON = MOBILE / "app.json"

# name -> (size, default inset). The inset is a transparent margin left around
# the artwork, as a fraction of the canvas on each side.
#
# Android masks the adaptive foreground to a circle (or squircle, by launcher)
# and crops roughly a quarter off every edge. At full bleed the corners of a
# square logo — which is where a wordmark usually sits — are simply gone, so
# the default leaves room for the mask to take.
SLOTS: dict[str, tuple[int, float]] = {
    "icon": (1024, 0.0),
    "adaptive": (1024, 0.18),
    "splash": (1024, 0.0),
    "favicon": (196, 0.0),
}
FILENAMES = {
    "icon": "icon.png",
    "adaptive": "adaptive-icon.png",
    "splash": "splash-icon.png",
    "favicon": "favicon.png",
}


def parse_colour(value: str) -> tuple[int, int, int, int]:
    """`#rgb`, `#rrggbb` or `#rrggbbaa` as an RGBA tuple."""
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) == 6:
        text += "ff"
    if len(text) != 8:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a colour like #166534")
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a colour like #166534")


def colour_arg(value: str) -> str:
    """Validate a colour but keep the text — app.json stores it as written."""
    parse_colour(value)
    return value.strip()


def parse_crop(value: str) -> tuple[float, float, float, float]:
    """`left,top,right,bottom` percentages to trim off each edge."""
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "crop takes four percentages: left,top,right,bottom")
    try:
        edges = tuple(float(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError("crop values must be numbers")
    if any(e < 0 or e >= 100 for e in edges):
        raise argparse.ArgumentTypeError("each crop percentage must be 0-99")
    if edges[0] + edges[2] >= 100 or edges[1] + edges[3] >= 100:
        raise argparse.ArgumentTypeError("crop would leave nothing behind")
    return edges  # type: ignore[return-value]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate the app's icon assets from one source image.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", type=Path, help="the artwork to derive from")
    p.add_argument(
        "--crop", type=parse_crop, metavar="L,T,R,B",
        help="trim this percentage off each edge before anything else, e.g. "
             "'8,4,8,45' to keep the emblem and drop a wordmark below it")
    p.add_argument(
        "--inset", type=float, metavar="PCT",
        help="margin left around the artwork, as a percentage of each side. "
             f"Applies to every slot being written; the default is "
             f"{int(SLOTS['adaptive'][1] * 100)}%% for the Android adaptive "
             "icon and 0 for the rest")
    p.add_argument(
        "--bg", type=parse_colour, metavar="#RRGGBB",
        help="flatten onto this colour instead of leaving transparency")
    p.add_argument(
        "--adaptive-bg", type=colour_arg, metavar="#RRGGBB",
        help="also set expo.android.adaptiveIcon.backgroundColor in app.json")
    p.add_argument(
        "--only", metavar="NAMES",
        help="comma-separated subset of: " + ", ".join(SLOTS))
    p.add_argument(
        "--preview", type=Path, metavar="DIR",
        help="write here instead of assets/, to look before committing")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.source.exists():
        sys.exit(f"No such file: {args.source}")

    wanted = list(SLOTS)
    if args.only:
        wanted = [n.strip() for n in args.only.split(",") if n.strip()]
        unknown = [n for n in wanted if n not in SLOTS]
        if unknown:
            sys.exit(f"Unknown slot(s): {', '.join(unknown)}. "
                     f"Choose from: {', '.join(SLOTS)}")

    out_dir = args.preview or ASSETS
    out_dir.mkdir(parents=True, exist_ok=True)

    src = Image.open(args.source).convert("RGBA")
    print(f"source: {args.source.name}  {src.width}x{src.height}")

    if args.crop:
        left, top, right, bottom = args.crop
        box = (
            int(src.width * left / 100),
            int(src.height * top / 100),
            int(src.width * (1 - right / 100)),
            int(src.height * (1 - bottom / 100)),
        )
        src = src.crop(box)
        print(f"  cropped to {src.width}x{src.height}"
              f"  (-{left}% -{top}% -{right}% -{bottom}%)")

    # Square it off by centre-crop. Padding instead would shrink the artwork
    # inside the icon; stretching would simply be wrong.
    if src.width != src.height:
        side = min(src.size)
        left = (src.width - side) // 2
        top = (src.height - side) // 2
        src = src.crop((left, top, left + side, top + side))
        print(f"  squared to {side}x{side}")

    for name in wanted:
        size, default_inset = SLOTS[name]
        inset = default_inset if args.inset is None else args.inset / 100
        if not 0 <= inset < 0.5:
            sys.exit("--inset must be between 0 and 49")

        art_size = max(1, int(size * (1 - inset * 2)))
        art = src.resize((art_size, art_size), Image.LANCZOS)
        canvas = Image.new("RGBA", (size, size), args.bg or (0, 0, 0, 0))
        offset = (size - art_size) // 2
        canvas.alpha_composite(art, (offset, offset))

        target = out_dir / FILENAMES[name]
        canvas.save(target, "PNG")
        note = f"  inset {inset * 100:g}%" if inset else ""
        print(f"  wrote {FILENAMES[name]:20} {size}x{size}{note}")

    # Under --preview nothing outside the preview directory may change, and
    # app.json is very much outside it.
    if args.adaptive_bg and not args.preview:
        colour = args.adaptive_bg
        config = json.loads(APP_JSON.read_text(encoding="utf-8"))
        adaptive = config["expo"]["android"]["adaptiveIcon"]
        was = adaptive.get("backgroundColor")
        adaptive["backgroundColor"] = colour
        APP_JSON.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print(f"  app.json adaptiveIcon.backgroundColor: {was} -> {colour}")

    if args.preview:
        print(f"\nPreview only — nothing in assets/ changed. Look in {out_dir},"
              f"\nthen re-run without --preview when the framing is right.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
