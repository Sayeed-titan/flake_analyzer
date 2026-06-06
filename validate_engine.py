"""
Headless validation of the FlakeScope analysis engine against real images.

Runs the adaptive optical-contrast detector on every image in real_images/
(or a folder passed as argv[1]) and prints what it finds — no GUI required.
Also writes an annotated overlay next to each image (suffix _overlay.png) so
you can eyeball detection quality.

Usage:
    python validate_engine.py [image_folder]
"""
import sys
from pathlib import Path

import cv2
import numpy as np

from engine import AnalysisEngine


def run_on_image(path: Path, write_overlay: bool = True):
    bgr = cv2.imread(str(path))
    if bgr is None:
        print(f"  !! could not read {path.name}")
        return
    h, w = bgr.shape[:2]

    # First pass: detect flakes and read their contrasts (no calibration yet).
    mask, flakes, info = AnalysisEngine.detect_flakes_by_contrast(
        bgr, min_contrast=0.04, delta_c=None, channel="green",
        min_area_px=200, morph_close=3, um_per_px=1.0,
    )

    print(f"\n=== {path.name}  ({w}x{h}) ===")
    print(f"  substrate green level : {info['substrate_intensity']:.1f}/255")
    print(f"  flakes detected       : {len(flakes)}")

    if not flakes:
        print("  (nothing above contrast threshold)")
        return

    contrasts = sorted(abs(f.contrast) for f in flakes)
    # Use the smallest clearly-resolved contrast as a rough 1-layer reference.
    ref = np.percentile(contrasts, 25)
    print(f"  contrast range        : {contrasts[0]*100:.1f}% .. {contrasts[-1]*100:.1f}%")
    print(f"  rough 1L reference dC : {ref*100:.2f}%  (25th pct of |contrast|)")

    # Second pass: estimate layer numbers using that reference as delta_c.
    if ref > 1e-4:
        mask, flakes, info = AnalysisEngine.detect_flakes_by_contrast(
            bgr, min_contrast=0.04, delta_c=ref, channel="green",
            min_area_px=200, morph_close=3, um_per_px=1.0,
        )
        from collections import Counter
        hist = Counter(f.layer_count for f in flakes)
        layer_summary = ", ".join(f"{k}:{v}" for k, v in sorted(hist.items()))
        print(f"  layer histogram       : {layer_summary}")
        biggest = max(flakes, key=lambda f: f.area_px)
        print(f"  largest flake         : {biggest.area_px:.0f}px  "
              f"contrast={biggest.contrast*100:.1f}%  est={biggest.layer_count}")

    if write_overlay:
        ov = AnalysisEngine.draw_contrast_overlay(bgr, flakes,
                                                  show_labels=True, show_contours=True)
        out = path.with_name(path.stem + "_overlay.png")
        cv2.imwrite(str(out), ov)
        print(f"  overlay written       : {out.name}")


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("real_images")
    if not folder.exists():
        print(f"Folder not found: {folder}")
        sys.exit(1)
    imgs = sorted(
        p for p in folder.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
        and "_overlay" not in p.stem
    )
    if not imgs:
        print(f"No images in {folder}")
        sys.exit(1)
    print(f"Validating engine on {len(imgs)} image(s) in {folder}/")
    # Only write overlays for the first few to avoid clutter.
    for i, p in enumerate(imgs):
        run_on_image(p, write_overlay=(i < 3))


if __name__ == "__main__":
    main()
