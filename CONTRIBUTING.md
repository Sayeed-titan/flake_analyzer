# Contributing to FlakeScope

Thanks for your interest in improving FlakeScope! This tool is used for real
2D-materials (graphene / hBN) microscopy research, so correctness and
measurement accuracy matter a lot. Contributions of all sizes are welcome —
bug reports, accuracy improvements, new material profiles, docs, and tests.

## Project layout

```
flake_analyzer/
├── engine.py            ← pure analysis logic (NO GUI) — easy to test & script
├── main.py              ← PyQt5 desktop application (imports engine.py)
├── validate_engine.py   ← headless runner over a folder of images
├── generate_test_image.py
├── requirements.txt
├── FlakeScope.bat       ← one-click Windows launcher (auto-installs deps)
└── README.md
```

The most important design rule: **keep `engine.py` free of any Qt / GUI import.**
That separation is what lets the science be unit-tested and batch-scripted
independently of the desktop app.

## Development setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

Run the app:

```bash
python main.py
```

Run the headless engine over a folder of images:

```bash
python validate_engine.py path/to/images
```

## Where to make changes

- **Detection accuracy / new algorithms** → `engine.py` (`AnalysisEngine`).
  Add a `@staticmethod` and keep it pure (numpy/OpenCV/skimage in, numbers out).
- **New material presets** → `BUILTIN_PROFILES` in `engine.py`.
- **UI / interaction** → `main.py`.

## Guidelines

1. **No Qt in `engine.py`.** If your feature needs the GUI, wire it in `main.py`
   and call into a pure engine function for the actual computation.
2. **Validate on real images.** If you change detection, run `validate_engine.py`
   before and after and note the difference in your PR.
3. **Match the surrounding style** — small focused functions, clear names,
   comments only where the physics/intent isn't obvious from the code.
4. **Keep it dependency-light.** The current stack is OpenCV + NumPy +
   scikit-image + PyQt5. Please discuss before adding new heavy dependencies.

## Reporting bugs

Open an issue with:
- what you did, what you expected, what happened;
- a sample image if possible (or a synthetic one from `generate_test_image.py`);
- your OS and Python version.

## Submitting changes

1. Fork the repo and create a branch (`git checkout -b fix/short-description`).
2. Make your change; run the app and `validate_engine.py`.
3. Open a pull request describing the change and its effect on detection.

By contributing you agree that your contributions are licensed under the
project's MIT License.
