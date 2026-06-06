# FlakeScope — Graphene / hBN Layer Analyzer

> Desktop tool for detecting and measuring graphene & hBN flakes from optical
> microscopy images, and **estimating the number of layers** from optical contrast.

Built for real 2D-materials research (graphene, hBN on 300 nm SiO₂/Si). It works
on faint monolayer flakes where simple colour thresholds fail, by adapting to each
image's substrate and measuring optical contrast — the same physical quantity
researchers use to count layers.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

---

## ⚡ One-click start (Windows)

1. Make sure [Python 3.8+](https://www.python.org/downloads/) is installed
   (tick **”Add Python to PATH”** during install).
2. **Double-click `FlakeScope.vbs`.**

On the first run a dialog appears asking to confirm the one-time setup
(~2–3 min). `FlakeScope.vbs` calls `FlakeScope.bat` to create an isolated
virtual environment and install all dependencies, then launches the app
silently using `pythonw.exe` (no console window). Every later run skips
setup and opens the app directly.

### Manual start (any OS)

```bash
pip install -r requirements.txt
python main.py
```

---

## 🔬 Two detection modes

### 1. Optical Contrast (auto layers) — recommended

The physically-grounded method, and the default. For each image it:

1. **Estimates the substrate** automatically, correcting for uneven
   illumination / vignetting (no manual colour picking).
2. **Measures optical contrast** `C = (I_substrate − I_flake) / I_substrate`
   for every flake — the standard metric in 2D-materials microscopy.
3. **Estimates layer number N for *any* N**: graphene darkens by a roughly
   constant contrast step per layer, so `N = round(C / ΔC)` once you calibrate
   the per-layer step `ΔC` from a single known monolayer flake.

This is what lets FlakeScope go from “monolayer only” to **counting arbitrary
layer numbers** — and what makes it work on real, low-contrast data.

**Workflow:**
1. Open your image, set the scale.
2. Pick the channel (Green is standard for graphene) and detection direction
   (*Darker than substrate* for graphene).
3. Click **🎯 Calibrate Δ from a 1-layer flake**, then click a flake you *know*
   is monolayer. (Or type `ΔC` directly if you already know it.)
4. **Analyse.** Flakes are outlined and colour-coded by layer number, with a
   per-layer summary and CSV export.

> Leave `ΔC` at 0 to just map relative contrast without committing to absolute
> layer numbers.

### 2. HSV Colour Profiles — classic

Match flakes by an HSV colour range per material/layer profile. Fast and useful
when you already know the flake colour. Tune profiles with the sliders or sample
a flake with the eyedropper. Built-in starting profiles for graphene 1L/2L/3L+
and hBN thin/medium/thick on 300 nm SiO₂.

---

## Features

| Feature | Details |
|---|---|
| **Adaptive contrast detection** | Per-image substrate + illumination correction |
| **Any-N layer counting** | Calibrate ΔC once from a known monolayer |
| **HSV colour profiles** | Per-profile H/S/V ranges, eyedropper sampling |
| **Scale calibration** | Scale-bar px→µm; presets for 5×–100× objectives |
| **Per-flake measurement** | Area (px² & µm²), perimeter, aspect ratio, contrast, N |
| **Overlay** | Contours, layer-coloured fills, labels; save as PNG/TIFF |
| **Summary + CSV export** | Per-layer counts/areas; full per-flake CSV |
| **Headless engine** | `engine.py` has no GUI deps — scriptable for batch runs |

---

## Batch / scripting (no GUI)

The analysis core lives in `engine.py` with **no Qt dependency**, so you can run
it over many images headlessly:

```bash
python validate_engine.py path/to/images
```

or call it directly:

```python
import cv2
from engine import AnalysisEngine

bgr = cv2.imread("flake.jpg")
mask, flakes, info = AnalysisEngine.detect_flakes_by_contrast(
    bgr, min_contrast=0.03, delta_c=0.03, channel="green", direction="darker",
)
for f in flakes:
    print(f.n_layers, f.area_um2, f.contrast)
```

---

## Calibration tips

- Measure the scale bar in pixels (ImageJ/GIMP), enter px and µm in **Set Scale**.
- For `ΔC`: pick a flake confirmed as monolayer (e.g. by Raman/AFM) and use the
  **Calibrate** button. Re-calibrate per microscope/camera/illumination — white
  balance and exposure shift the absolute contrast.
- Use the **Green** channel for graphene unless your setup says otherwise.

---

## Project layout

```
flake_analyzer/
├── engine.py            ← analysis core (no GUI) — testable & scriptable
├── main.py              ← PyQt6 desktop app
├── validate_engine.py   ← headless batch runner / sanity check
├── generate_test_image.py
├── requirements.txt
├── FlakeScope.vbs       ← one-click Windows launcher (double-click this)
├── FlakeScope.bat       ← setup + venv installer, called by FlakeScope.vbs
├── LICENSE              ← MIT
├── CONTRIBUTING.md
└── README.md
```

> **Note on data:** real research microscopy images are intentionally **not**
> included in this public repository. Put your own images in a local folder and
> open them from the app.

---

## Dependencies

```
PyQt6 >= 6.4
opencv-python >= 4.5
numpy >= 1.21
scikit-image >= 0.18
```

## Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The golden rule:
keep `engine.py` free of GUI code so the science stays testable.

## License

[MIT](LICENSE) — free to use, modify, and build on, including for research and
commercial work.
