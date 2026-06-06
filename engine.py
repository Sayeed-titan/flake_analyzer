"""
FlakeScope analysis engine — pure logic, no GUI dependencies.
================================================================
This module contains the image-analysis core for detecting and measuring
graphene / hBN / 2D-material flakes from optical-microscopy images.

It deliberately has **no Qt dependency** so it can be:
  * unit-tested headlessly,
  * scripted for batch processing of many images,
  * reused by other tools.

Two detection strategies are provided:

1. ``detect_flakes``            — HSV colour-range matching (classic, fast,
                                  good when you know the flake colour).
2. ``detect_flakes_by_contrast`` — adaptive optical-contrast layer counting.
                                  Estimates the substrate background per-image
                                  (correcting for uneven illumination), measures
                                  each flake's optical contrast, and converts it
                                  to an estimated layer number N for *any* N via a
                                  calibrated per-layer contrast step. This is the
                                  standard method used in 2D-materials research.

Author : Built for CSU Physics PhD research
Stack  : Python 3 · OpenCV · NumPy · scikit-image
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Tuple

import cv2
import numpy as np
from skimage import measure


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LayerProfile:
    name: str
    material: str          # "Graphene" | "hBN" | "Custom"
    layer_count: str       # "1L" | "2L" | "3L" | "Bulk" | "?"
    h_min: int = 0
    h_max: int = 179
    s_min: int = 0
    s_max: int = 255
    v_min: int = 0
    v_max: int = 255
    color_rgb: Tuple[int, int, int] = (100, 200, 100)
    notes: str = ""

    def to_hsv_bounds(self):
        return (
            np.array([self.h_min, self.s_min, self.v_min]),
            np.array([self.h_max, self.s_max, self.v_max]),
        )


@dataclass
class DetectedFlake:
    profile_name: str
    layer_count: str
    material: str
    area_px: float
    area_um2: float
    centroid_x: float
    centroid_y: float
    perimeter_um: float
    aspect_ratio: float
    # Optical-contrast fields (populated by the contrast detector; default for HSV mode)
    n_layers: Optional[int] = None      # estimated layer number (any N), or None
    contrast: float = 0.0               # mean signed optical contrast vs. substrate
    mean_intensity: float = 0.0         # mean channel intensity inside the flake
    contour: np.ndarray = field(default=None, repr=False)


# Built-in HSV profiles for graphene and hBN on SiO₂ (300 nm oxide).
# These are *starting points* — tune to your specific microscope/camera, or use
# the adaptive contrast detector which needs no per-colour tuning.
BUILTIN_PROFILES = [
    LayerProfile("Graphene 1L",  "Graphene", "1L",  80, 140,  5,  60, 140, 210, (147, 197, 153), "Monolayer graphene on 300nm SiO₂"),
    LayerProfile("Graphene 2L",  "Graphene", "2L",  70, 130, 10,  80, 110, 180, ( 90, 160, 100), "Bilayer graphene on 300nm SiO₂"),
    LayerProfile("Graphene 3L+", "Graphene", "3L+",  60, 120, 15, 100,  80, 150, ( 50, 120,  70), "Trilayer+ graphene on 300nm SiO₂"),
    LayerProfile("hBN Thin",     "hBN",      "1-5L", 15,  45, 10,  80, 160, 230, (230, 200, 130), "Thin hBN (1-5 layers) on 300nm SiO₂"),
    LayerProfile("hBN Medium",   "hBN",      "5-20L",10,  40, 20, 120, 130, 210, (210, 170,  90), "Medium hBN on 300nm SiO₂"),
    LayerProfile("hBN Thick",    "hBN",      "Bulk", 10,  35, 30, 160, 100, 190, (180, 140,  60), "Thick/bulk hBN on 300nm SiO₂"),
]


# Channel selection for contrast computation.
CONTRAST_CHANNELS = {
    "Green (graphene)": "green",
    "Luminance":        "gray",
    "Blue":             "blue",
    "Red":              "red",
}


# ─────────────────────────────────────────────────────────────────────────────
# Analysis engine
# ─────────────────────────────────────────────────────────────────────────────

class AnalysisEngine:
    """Pure-logic image analysis — no GUI dependencies."""

    # ── HSV colour-range detection (classic) ───────────────────────────────────

    @staticmethod
    def detect_flakes(
        bgr_image: np.ndarray,
        profile: LayerProfile,
        min_area_px: int = 50,
        morph_close: int = 3,
        um_per_px: float = 1.0,
    ) -> Tuple[np.ndarray, List[DetectedFlake]]:
        """
        Detect flakes by HSV colour range.
        Returns (mask_uint8, list_of_flakes). mask is 0/255 single-channel.
        """
        hsv = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2HSV)
        lo, hi = profile.to_hsv_bounds()

        # Handle hue wrap-around (e.g. reds near 0/179)
        if lo[0] > hi[0]:
            m1 = cv2.inRange(hsv, np.array([lo[0], lo[1], lo[2]]),
                                  np.array([179,    hi[1], hi[2]]))
            m2 = cv2.inRange(hsv, np.array([0,      lo[1], lo[2]]),
                                  np.array([hi[0],  hi[1], hi[2]]))
            mask = cv2.bitwise_or(m1, m2)
        else:
            mask = cv2.inRange(hsv, lo, hi)

        if morph_close > 0:
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (morph_close * 2 + 1, morph_close * 2 + 1)
            )
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        flakes = AnalysisEngine._regions_to_flakes(
            mask, um_per_px, min_area_px,
            profile_name=profile.name,
            layer_count=profile.layer_count,
            material=profile.material,
        )
        return mask, flakes

    # ── Adaptive optical-contrast layer counting (any N) ───────────────────────

    @staticmethod
    def _channel(bgr_image: np.ndarray, channel: str) -> np.ndarray:
        """Return a single-channel uint8 intensity image for contrast analysis."""
        if channel == "gray":
            return cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
        idx = {"blue": 0, "green": 1, "red": 2}.get(channel, 1)
        return bgr_image[:, :, idx].copy()

    @staticmethod
    def estimate_background(intensity_u8: np.ndarray) -> np.ndarray:
        """
        Estimate the substrate background intensity B(x, y).

        Uses a heavy median filter on a downsampled copy, which removes flakes
        (small features) while preserving the slowly-varying substrate colour and
        the illumination gradient / vignetting. Returned as float32, full-size.
        """
        h, w = intensity_u8.shape[:2]
        long_side = max(h, w)
        # Downsample so the long side is ~400 px → large kernels stay cheap.
        scale = max(1, int(round(long_side / 400.0)))
        sw, sh = max(1, w // scale), max(1, h // scale)
        small = cv2.resize(intensity_u8, (sw, sh), interpolation=cv2.INTER_AREA)

        # Median kernel ≈ a quarter of the (downsampled) short side, odd, capped.
        k = max(3, (min(sw, sh) // 4) | 1)
        k = min(k, 99)
        bg_small = cv2.medianBlur(small, k)
        bg = cv2.resize(bg_small, (w, h), interpolation=cv2.INTER_LINEAR)
        return bg.astype(np.float32)

    @staticmethod
    def compute_contrast(
        bgr_image: np.ndarray,
        channel: str = "green",
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Compute the optical-contrast map.

        Contrast C = (B - I) / B  where B is the local substrate background and
        I is the pixel intensity. C > 0 → flake darker than substrate (e.g. more
        graphene layers); C < 0 → flake brighter (e.g. some hBN interference).

        Returns (contrast_float, intensity_float, background_float).
        """
        inten = AnalysisEngine._channel(bgr_image, channel).astype(np.float32)
        bg = AnalysisEngine.estimate_background(
            AnalysisEngine._channel(bgr_image, channel)
        )
        contrast = (bg - inten) / np.maximum(bg, 1.0)
        return contrast, inten, bg

    @staticmethod
    def detect_flakes_by_contrast(
        bgr_image: np.ndarray,
        min_contrast: float = 0.03,
        delta_c: Optional[float] = None,
        channel: str = "green",
        min_area_px: int = 50,
        morph_close: int = 3,
        um_per_px: float = 1.0,
        max_layers: int = 10,
        material: str = "Graphene",
        direction: str = "darker",
    ) -> Tuple[np.ndarray, List[DetectedFlake], dict]:
        """
        Detect flakes via optical contrast and estimate a layer number for each.

        Parameters
        ----------
        min_contrast : float
            Minimum |contrast| (fraction, e.g. 0.03 = 3 %) for a pixel to count
            as flake rather than substrate.
        delta_c : float or None
            Optical contrast contributed by a single layer. If given, the layer
            number of each flake is N = round(mean_contrast / delta_c), supporting
            *any* N. If None, contrast is still reported but N is left unset.
        channel : str
            Which channel to use ("green" is standard for graphene).
        direction : {"darker", "brighter", "both"}
            Which flakes to keep relative to the substrate. Graphene on SiO₂ gets
            *darker* with each added layer, so "darker" is the default and avoids
            mislabelling brighter interference flakes (some hBN) or bright edges as
            graphene. "both" detects either sign.
        max_layers : int
            Layer numbers above this are reported as this value (treated as bulk
            for colour-coding only; the true rounded N is still recorded).

        Returns
        -------
        (mask_uint8, flakes, info_dict)
            info_dict carries diagnostics: substrate_intensity, channel, etc.
        """
        contrast, inten, bg = AnalysisEngine.compute_contrast(bgr_image, channel)

        # Foreground selection by sign of contrast (darker/brighter than substrate).
        thr = float(min_contrast)
        if direction == "darker":
            fg = contrast >= thr
        elif direction == "brighter":
            fg = contrast <= -thr
        else:  # "both"
            fg = np.abs(contrast) >= thr
        mask = fg.astype(np.uint8) * 255

        if morph_close > 0:
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (morph_close * 2 + 1, morph_close * 2 + 1)
            )
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        flakes = AnalysisEngine._regions_to_flakes(
            mask, um_per_px, min_area_px,
            profile_name="Contrast",
            layer_count="?",
            material=material,
            contrast_map=contrast,
            intensity_map=inten,
            delta_c=delta_c,
            max_layers=max_layers,
        )

        info = {
            "channel": channel,
            "direction": direction,
            "substrate_intensity": float(np.median(bg)),
            "delta_c": delta_c,
            "min_contrast": float(min_contrast),
            "n_flakes": len(flakes),
        }
        return mask, flakes, info

    @staticmethod
    def sample_contrast(
        bgr_image: np.ndarray,
        x: int, y: int,
        channel: str = "green",
        radius: int = 6,
    ) -> float:
        """
        Mean optical contrast in a small patch around (x, y). Use this to read the
        contrast of a *known* monolayer flake → its value is a good estimate of the
        per-layer contrast step (delta_c) for calibration.
        """
        contrast, _, _ = AnalysisEngine.compute_contrast(bgr_image, channel)
        h, w = contrast.shape[:2]
        x1, y1 = max(0, x - radius), max(0, y - radius)
        x2, y2 = min(w, x + radius + 1), min(h, y + radius + 1)
        patch = contrast[y1:y2, x1:x2]
        if patch.size == 0:
            return 0.0
        return float(np.mean(patch))

    # ── Shared region → flake conversion ───────────────────────────────────────

    @staticmethod
    def _regions_to_flakes(
        mask: np.ndarray,
        um_per_px: float,
        min_area_px: int,
        profile_name: str,
        layer_count: str,
        material: str,
        contrast_map: Optional[np.ndarray] = None,
        intensity_map: Optional[np.ndarray] = None,
        delta_c: Optional[float] = None,
        max_layers: int = 10,
    ) -> List[DetectedFlake]:
        """Convert a binary mask into measured DetectedFlake objects."""
        bool_mask = mask > 0
        labeled = measure.label(bool_mask)
        props = measure.regionprops(labeled)

        flakes: List[DetectedFlake] = []
        for prop in props:
            if prop.area < min_area_px:
                continue

            area_um2 = prop.area * (um_per_px ** 2)
            perim_um = prop.perimeter * um_per_px
            maj = getattr(prop, "axis_major_length", None) or getattr(prop, "major_axis_length", 1)
            mino = getattr(prop, "axis_minor_length", None) or getattr(prop, "minor_axis_length", 1e-6)
            ar = maj / (mino + 1e-6)
            cy, cx = prop.centroid

            region = (labeled == prop.label)

            n_layers: Optional[int] = None
            mean_c = 0.0
            mean_i = 0.0
            lc = layer_count
            if contrast_map is not None:
                mean_c = float(np.mean(contrast_map[region]))
            if intensity_map is not None:
                mean_i = float(np.mean(intensity_map[region]))
            if delta_c is not None and abs(delta_c) > 1e-9:
                # Use magnitudes so the math is identical for darker/brighter flakes
                # (within one detection direction all flakes share the contrast sign).
                raw = abs(mean_c) / abs(delta_c)
                n_layers = int(round(raw))
                if n_layers < 1:
                    n_layers = 1
                lc = f"{n_layers}L" if n_layers <= max_layers else f"{max_layers}L+"

            contour_mask = region.astype(np.uint8) * 255
            cnts, _ = cv2.findContours(contour_mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
            contour = cnts[0] if cnts else np.array([])

            flakes.append(DetectedFlake(
                profile_name=profile_name,
                layer_count=lc,
                material=material,
                area_px=float(prop.area),
                area_um2=area_um2,
                centroid_x=cx,
                centroid_y=cy,
                perimeter_um=perim_um,
                aspect_ratio=ar,
                n_layers=n_layers,
                contrast=mean_c,
                mean_intensity=mean_i,
                contour=contour,
            ))
        return flakes

    # ── Colour sampling (eyedropper) ───────────────────────────────────────────

    @staticmethod
    def sample_color(bgr_image: np.ndarray, x: int, y: int, radius: int = 3):
        """Return mean BGR and HSV in a small patch around (x, y)."""
        h, w = bgr_image.shape[:2]
        x1, y1 = max(0, x - radius), max(0, y - radius)
        x2, y2 = min(w, x + radius + 1), min(h, y + radius + 1)
        patch = bgr_image[y1:y2, x1:x2]
        bgr_mean = patch.mean(axis=(0, 1))
        hsv_patch = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        hsv_mean = hsv_patch.mean(axis=(0, 1))
        return bgr_mean, hsv_mean

    # ── Overlay rendering ──────────────────────────────────────────────────────

    @staticmethod
    def layer_color(n: int) -> Tuple[int, int, int]:
        """
        Deterministic, perceptually-distinct BGR colour for layer number N.
        1L, 2L, 3L… each get a distinct hue so any N is visually separable.
        """
        # Spread hues around the wheel; reuse after 12 with a value shift.
        hue = int((n * 28) % 180)
        val = 255 if n <= 12 else 200
        hsv = np.uint8([[[hue, 220, val]]])
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
        return int(bgr[0]), int(bgr[1]), int(bgr[2])

    @staticmethod
    def draw_overlay(
        bgr_image: np.ndarray,
        flakes_by_profile: List[Tuple[LayerProfile, np.ndarray, List[DetectedFlake]]],
        show_labels: bool = True,
        show_contours: bool = True,
        fill_alpha: float = 0.25,
    ) -> np.ndarray:
        """Render HSV-mode overlay: each profile drawn in its own colour."""
        overlay = bgr_image.copy()
        fill_layer = bgr_image.copy()

        for profile, mask, flakes in flakes_by_profile:
            r, g, b = profile.color_rgb
            bgr = (b, g, r)

            fill_layer[mask > 0] = bgr
            cv2.addWeighted(fill_layer, fill_alpha, overlay,
                            1 - fill_alpha, 0, overlay)
            fill_layer = overlay.copy()

            if show_contours:
                for flake in flakes:
                    if flake.contour is not None and len(flake.contour) > 0:
                        cv2.drawContours(overlay, [flake.contour], -1, bgr, 2)

            if show_labels:
                for flake in flakes:
                    label = f"{profile.layer_count}  {flake.area_um2:.1f}um2"
                    AnalysisEngine._draw_label(
                        overlay, label, int(flake.centroid_x), int(flake.centroid_y)
                    )
        return overlay

    @staticmethod
    def draw_contrast_overlay(
        bgr_image: np.ndarray,
        flakes: List[DetectedFlake],
        show_labels: bool = True,
        show_contours: bool = True,
        fill_alpha: float = 0.30,
    ) -> np.ndarray:
        """Render contrast-mode overlay: each flake coloured by its layer number N."""
        overlay = bgr_image.copy()
        fill_layer = bgr_image.copy()

        for flake in flakes:
            if flake.contour is None or len(flake.contour) == 0:
                continue
            n = flake.n_layers if flake.n_layers else 1
            color = AnalysisEngine.layer_color(n)

            cv2.drawContours(fill_layer, [flake.contour], -1, color, thickness=cv2.FILLED)

        cv2.addWeighted(fill_layer, fill_alpha, overlay, 1 - fill_alpha, 0, overlay)

        for flake in flakes:
            if flake.contour is None or len(flake.contour) == 0:
                continue
            n = flake.n_layers if flake.n_layers else 1
            color = AnalysisEngine.layer_color(n)
            if show_contours:
                cv2.drawContours(overlay, [flake.contour], -1, color, 2)
            if show_labels:
                if flake.n_layers:
                    label = f"{flake.layer_count}  {flake.area_um2:.1f}um2"
                else:
                    label = f"C={flake.contrast*100:.1f}%  {flake.area_um2:.1f}um2"
                AnalysisEngine._draw_label(
                    overlay, label, int(flake.centroid_x), int(flake.centroid_y)
                )
        return overlay

    @staticmethod
    def _draw_label(img: np.ndarray, text: str, cx: int, cy: int):
        """Draw a small label with a dark shadow for legibility."""
        cv2.putText(img, text, (cx + 1, cy + 1), cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(img, text, (cx, cy), cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, (255, 255, 255), 1, cv2.LINE_AA)
