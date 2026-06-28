"""Generate Agent Eye icon assets from the master ``logo.png``.

Reads ``logo.png`` (the dark, rounded-square Agent Eye artwork) at the repo
root and renders every icon the app needs:

  src/static/favicon.png        64x64   (browser tab + header logo)
  src/static/icon-192.png       192x192 (PWA)
  src/static/icon-512.png       512x512 (PWA)
  src/static/tray-icon.png      256x256 (colored tray icon)
  src/static/tray-icon.ico      multi   (Windows tray)
  src/static/trayTemplate.png   512x512 (macOS menu-bar template: black + alpha)

The colored icons keep the artwork but get transparent rounded corners. The
macOS template is monochrome: it must be black shapes on transparency (the
system tints it for light/dark menu bars), so a flat colored logo cannot be
used directly — we derive the silhouette from pixel luminance.

Run from repo root:  python scripts/gen_icons.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter

SRC = "logo.png"
OUT = "src/static"
CORNER_RADIUS_FRAC = 0.22  # fraction of width used to round corners


def _rounded(img: Image.Image, radius_frac: float = CORNER_RADIUS_FRAC) -> Image.Image:
    """Return a copy of img with transparent rounded corners (supersampled)."""
    img = img.convert("RGBA")
    w, h = img.size
    ss = 4
    mask = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, w * ss - 1, h * ss - 1], radius=int(w * ss * radius_frac), fill=255
    )
    mask = mask.resize((w, h), Image.LANCZOS)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _resized(master: Image.Image, size: int) -> Image.Image:
    return _rounded(master).resize((size, size), Image.LANCZOS)


def _mono(master: Image.Image, size: int, rgb: tuple[int, int, int]) -> Image.Image:
    """Derive a bold single-color silhouette (given rgb) on transparency.

    The artwork is bright shapes (white eye outline, blue hex, terminal glyph)
    on a near-black background. For a menu-bar / tray icon we want every line to
    read as one solid color, so we threshold luminance into a *binary* mask
    (no faint mid-tones), thicken it slightly, trim the surrounding margin so the
    eye fills the icon, then fill with pure ``rgb``. Anti-aliasing is applied
    only at the true edges, keeping the fill fully opaque.

    macOS (pystray) renders the image's literal colors, so a white fill yields a
    crisp white menu-bar icon.
    """
    work = 1024  # high-res working canvas for clean thresholding
    src = master.convert("RGB").resize((work, work), Image.LANCZOS)
    lum = src.convert("L")

    # binary mask: foreground (eye outline + hex + terminal) vs dark background
    thresh = 70
    mask = lum.point(lambda v: 255 if v >= thresh else 0).convert("L")

    # thicken strokes so they pop when scaled down to ~18px on the menu bar
    grow = max(3, (work // 170) | 1)  # odd kernel
    mask = mask.filter(ImageFilter.MaxFilter(grow))

    # trim transparent margin and re-center with a small padding so the eye
    # fills the icon (bigger visual presence)
    bbox = mask.getbbox()
    if bbox:
        cropped = mask.crop(bbox)
        pad = int(work * 0.06)
        target = work - 2 * pad
        cw, ch = cropped.size
        scale = min(target / cw, target / ch)
        cropped = cropped.resize((max(1, int(cw * scale)), max(1, int(ch * scale))), Image.LANCZOS)
        mask = Image.new("L", (work, work), 0)
        mask.paste(cropped, ((work - cropped.width) // 2, (work - cropped.height) // 2))

    # soften edges for anti-aliasing, then downscale
    mask = mask.filter(ImageFilter.GaussianBlur(work / 512))
    alpha = mask.resize((size, size), Image.LANCZOS)

    out = Image.new("RGBA", (size, size), rgb + (0,))
    out.putalpha(alpha)
    return out


def main() -> None:
    if not os.path.exists(SRC):
        raise SystemExit(f"missing {SRC} at repo root")
    master = Image.open(SRC).convert("RGBA")
    os.makedirs(OUT, exist_ok=True)

    for name, size in [("favicon.png", 64), ("icon-192.png", 192), ("icon-512.png", 512)]:
        _resized(master, size).save(os.path.join(OUT, name))
        print("wrote", name)

    tray = _resized(master, 256)
    tray.save(os.path.join(OUT, "tray-icon.png"))
    print("wrote tray-icon.png")
    tray.save(
        os.path.join(OUT, "tray-icon.ico"),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("wrote tray-icon.ico")

    # macOS menu-bar icon: pystray renders literal colors, so use a white
    # silhouette (matches the original asset and shows white on the menu bar).
    _mono(master, 512, (255, 255, 255)).save(os.path.join(OUT, "trayTemplate.png"))
    print("wrote trayTemplate.png")


if __name__ == "__main__":
    main()
