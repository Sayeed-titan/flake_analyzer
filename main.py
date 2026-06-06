"""
Graphene / hBN Flake Analyzer
================================
Desktop tool for detecting and measuring graphene & hBN layers
from optical microscopy images based on flake color.

Author  : Built for CSU Physics PhD research
Stack   : Python 3 · PyQt5 · OpenCV · NumPy · scikit-image
"""

import sys
import os
import csv
import json
import math
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Tuple

try:
    import cv2
    import numpy as np
    from skimage import measure
    from skimage.morphology import remove_small_objects, closing, disk

    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QSlider, QFileDialog, QGroupBox, QSpinBox,
        QDoubleSpinBox, QScrollArea, QSplitter, QColorDialog, QTableWidget,
        QTableWidgetItem, QHeaderView, QComboBox, QCheckBox, QToolBar,
        QAction, QStatusBar, QTabWidget, QTextEdit, QFrame, QProgressBar,
        QMessageBox, QDialog, QFormLayout, QDialogButtonBox, QSizePolicy,
        QListWidget, QListWidgetItem, QMenu,
    )
    from PyQt5.QtCore import (
        Qt, QThread, pyqtSignal, QRectF, QPointF, QTimer, QSize,
    )
    from PyQt5.QtGui import (
        QImage, QPixmap, QPainter, QPen, QColor, QFont, QIcon,
        QBrush, QCursor, QWheelEvent, QMouseEvent, QPainterPath,
        QLinearGradient, QPalette,
    )
except ImportError as _import_err:
    _msg = (
        f"Missing required package: {_import_err}\n\n"
        "Install all dependencies by running:\n\n"
        "    FlakeScope.bat          (Windows — double-click)\n\n"
        "or manually:\n\n"
        "    pip install PyQt5 opencv-python numpy scikit-image"
    )
    print(f"\nERROR: {_msg}\n", file=sys.stderr)
    try:
        import tkinter as _tk
        import tkinter.messagebox as _mb
        _root = _tk.Tk()
        _root.withdraw()
        _mb.showerror("FlakeScope — Missing Package", _msg)
        _root.destroy()
    except Exception:
        pass
    sys.exit(1)


# ---------------------------------------------------------------------------
# Analysis engine & data structures live in engine.py (no Qt deps), so they
# can be unit-tested headlessly and reused for batch scripting.
# ---------------------------------------------------------------------------

from engine import (
    LayerProfile, DetectedFlake, AnalysisEngine,
    BUILTIN_PROFILES, CONTRAST_CHANNELS,
)

# ─────────────────────────────────────────────────────────────────────────────
# Zoomable Image Viewer widget
# ─────────────────────────────────────────────────────────────────────────────

class ImageViewer(QLabel):
    pixelClicked = pyqtSignal(int, int)          # image-space coords
    zoomChanged  = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background:#1a1a2e; border:1px solid #2d2d4a;")
        self.setMinimumSize(400, 400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)

        self._orig_pixmap: Optional[QPixmap] = None
        self._zoom = 1.0
        self._offset = QPointF(0, 0)
        self._drag_start = None
        self._drag_offset = None
        self._eyedropper = False

    # ── public API ────────────────────────────────────────────────────────────

    def set_pixmap(self, pm: QPixmap):
        self._orig_pixmap = pm
        self._zoom = 1.0
        self._offset = QPointF(0, 0)
        self.update()

    def set_eyedropper(self, on: bool):
        self._eyedropper = on
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)

    def zoom_to_fit(self):
        if self._orig_pixmap is None:
            return
        w, h = self.width(), self.height()
        pw, ph = self._orig_pixmap.width(), self._orig_pixmap.height()
        self._zoom = min(w / pw, h / ph) * 0.95
        self._offset = QPointF(0, 0)
        self.update()

    # ── painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#1a1a2e"))

        if self._orig_pixmap is None:
            # Placeholder
            painter.setPen(QColor("#3d3d6b"))
            painter.setFont(QFont("Consolas", 12))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "No image loaded\n\nFile → Open Image  (Ctrl+O)")
            return

        pm = self._orig_pixmap
        sw = pm.width()  * self._zoom
        sh = pm.height() * self._zoom
        cx = self.width()  / 2 + self._offset.x()
        cy = self.height() / 2 + self._offset.y()
        rect = QRectF(cx - sw/2, cy - sh/2, sw, sh)
        painter.drawPixmap(rect, pm, QRectF(pm.rect()))

    # ── interactions ──────────────────────────────────────────────────────────

    def wheelEvent(self, event: QWheelEvent):
        if self._orig_pixmap is None:
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom = max(0.05, min(50.0, self._zoom * factor))
        self.update()
        self.zoomChanged.emit(self._zoom)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if self._eyedropper:
                ix, iy = self._widget_to_image(event.x(), event.y())
                if ix is not None:
                    self.pixelClicked.emit(ix, iy)
            else:
                self._drag_start  = event.pos()
                self._drag_offset = QPointF(self._offset)
                self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self._eyedropper and self._drag_start is not None:
            delta = event.pos() - self._drag_start
            self._offset = self._drag_offset + QPointF(delta)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_start = None
        if not self._eyedropper:
            self.setCursor(Qt.ArrowCursor)

    def _widget_to_image(self, wx, wy):
        if self._orig_pixmap is None:
            return None, None
        pw = self._orig_pixmap.width()
        ph = self._orig_pixmap.height()
        cx = self.width()  / 2 + self._offset.x()
        cy = self.height() / 2 + self._offset.y()
        ix = int((wx - (cx - pw * self._zoom / 2)) / self._zoom)
        iy = int((wy - (cy - ph * self._zoom / 2)) / self._zoom)
        if 0 <= ix < pw and 0 <= iy < ph:
            return ix, iy
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Profile Editor Dialog
# ─────────────────────────────────────────────────────────────────────────────

class ProfileEditorDialog(QDialog):
    def __init__(self, profile: Optional[LayerProfile] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Layer Profile")
        self.setModal(True)
        self.setFixedWidth(420)
        self._color = (100, 200, 100)
        self._build_ui(profile)

    def _build_ui(self, p: Optional[LayerProfile]):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.name_edit = self._line_edit(p.name if p else "")
        self.material_combo = QComboBox()
        self.material_combo.addItems(["Graphene", "hBN", "MoS₂", "WSe₂", "Custom"])
        if p:
            idx = self.material_combo.findText(p.material)
            self.material_combo.setCurrentIndex(max(0, idx))

        self.layer_edit = self._line_edit(p.layer_count if p else "1L")
        self.notes_edit = self._line_edit(p.notes if p else "")

        form.addRow("Name:", self.name_edit)
        form.addRow("Material:", self.material_combo)
        form.addRow("Layer Count:", self.layer_edit)
        form.addRow("Notes:", self.notes_edit)

        layout.addLayout(form)

        # HSV sliders
        hsv_box = QGroupBox("HSV Range  (Hue 0–179 · Sat/Val 0–255)")
        grid = QVBoxLayout(hsv_box)
        self.sliders = {}
        defs = {
            "H min": (0, 179,  p.h_min if p else 0),
            "H max": (0, 179,  p.h_max if p else 179),
            "S min": (0, 255,  p.s_min if p else 0),
            "S max": (0, 255,  p.s_max if p else 255),
            "V min": (0, 255,  p.v_min if p else 0),
            "V max": (0, 255,  p.v_max if p else 255),
        }
        for label, (lo, hi, val) in defs.items():
            row = QHBoxLayout()
            lbl = QLabel(f"{label}:"); lbl.setFixedWidth(48)
            sl  = QSlider(Qt.Horizontal); sl.setRange(lo, hi); sl.setValue(val)
            num = QLabel(str(val)); num.setFixedWidth(30)
            sl.valueChanged.connect(lambda v, n=num: n.setText(str(v)))
            row.addWidget(lbl); row.addWidget(sl); row.addWidget(num)
            grid.addLayout(row)
            self.sliders[label] = sl

        layout.addWidget(hsv_box)

        # Overlay color
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Overlay Color:"))
        self.color_btn = QPushButton()
        if p:
            self._color = p.color_rgb
        self._update_color_btn()
        self.color_btn.setFixedSize(60, 26)
        self.color_btn.clicked.connect(self._pick_color)
        color_row.addWidget(self.color_btn)
        color_row.addStretch()
        layout.addLayout(color_row)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _line_edit(self, text=""):
        from PyQt5.QtWidgets import QLineEdit
        le = QLineEdit(text)
        return le

    def _update_color_btn(self):
        r, g, b = self._color
        self.color_btn.setStyleSheet(
            f"background:{QColor(r,g,b).name()}; border-radius:3px;"
        )

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(*self._color), self)
        if c.isValid():
            self._color = (c.red(), c.green(), c.blue())
            self._update_color_btn()

    def get_profile(self) -> LayerProfile:
        return LayerProfile(
            name=self.name_edit.text() or "Unnamed",
            material=self.material_combo.currentText(),
            layer_count=self.layer_edit.text() or "?",
            h_min=self.sliders["H min"].value(),
            h_max=self.sliders["H max"].value(),
            s_min=self.sliders["S min"].value(),
            s_max=self.sliders["S max"].value(),
            v_min=self.sliders["V min"].value(),
            v_max=self.sliders["V max"].value(),
            color_rgb=self._color,
            notes=self.notes_edit.text(),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Scale Calibration Dialog
# ─────────────────────────────────────────────────────────────────────────────

class CalibrationDialog(QDialog):
    def __init__(self, current_um_per_px: float = 1.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scale Calibration")
        self.setFixedWidth(380)
        layout = QVBoxLayout(self)

        info = QLabel(
            "Measure the scale bar in your image in pixels, then enter\n"
            "its physical length in µm to calibrate measurements."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.px_spin = QDoubleSpinBox()
        self.px_spin.setRange(1, 100000); self.px_spin.setValue(100); self.px_spin.setSuffix(" px")
        self.um_spin = QDoubleSpinBox()
        self.um_spin.setRange(0.001, 1e6); self.um_spin.setValue(10); self.um_spin.setSuffix(" µm")
        self.result_lbl = QLabel()
        form.addRow("Scale bar length (pixels):", self.px_spin)
        form.addRow("Scale bar length (µm):", self.um_spin)
        form.addRow("→ µm/pixel:", self.result_lbl)
        layout.addLayout(form)

        def update_result():
            self.result_lbl.setText(f"{self.um_spin.value() / self.px_spin.value():.5f} µm/px")
        self.px_spin.valueChanged.connect(update_result)
        self.um_spin.valueChanged.connect(update_result)
        update_result()

        # Common objective presets
        preset_box = QGroupBox("Quick presets (common objectives on SiO₂/Si)")
        preset_layout = QHBoxLayout(preset_box)
        presets = [
            ("5×",   "5× obj",   0.620),
            ("10×",  "10× obj",  0.310),
            ("20×",  "20× obj",  0.155),
            ("50×",  "50× obj",  0.062),
            ("100×", "100× obj", 0.031),
        ]
        for label, tip, um_px in presets:
            btn = QPushButton(label)
            btn.setToolTip(f"{tip}: ~{um_px} µm/px (typical)")
            btn.setFixedWidth(44)
            _u = um_px  # capture
            btn.clicked.connect(lambda _, u=_u: self.um_spin.setValue(u * self.px_spin.value()))
            preset_layout.addWidget(btn)
        layout.addWidget(preset_box)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # Init
        self.um_spin.setValue(current_um_per_px * 100)
        self.px_spin.setValue(100)

    def get_um_per_px(self) -> float:
        return self.um_spin.value() / self.px_spin.value()


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FlakeScope — Graphene / hBN Layer Analyzer")
        self.setMinimumSize(1200, 800)
        self._apply_dark_theme()

        # State
        self._bgr: Optional[np.ndarray] = None
        self._bgr_overlay: Optional[np.ndarray] = None
        self._image_path: str = ""
        self._um_per_px: float = 1.0
        self._profiles: List[LayerProfile] = list(BUILTIN_PROFILES)
        self._active_profiles: set = set(p.name for p in BUILTIN_PROFILES)
        self._results: List[DetectedFlake] = []
        self._min_area_px: int = 50
        self._morph_close: int = 3
        self._show_labels: bool = True
        self._show_contours: bool = True
        self._calib_arm: bool = False          # one-shot Δ-per-layer calibration

        self._build_ui()
        self._build_menu()
        self._refresh_profile_list()
        self._on_mode_changed()                # set initial mode visibility

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        # ── Left panel ────────────────────────────────────────────────────────
        left = QWidget(); left.setFixedWidth(320)
        left.setStyleSheet("background:#12122a; border-right:1px solid #2d2d4a;")
        lv = QVBoxLayout(left); lv.setContentsMargins(10, 10, 10, 10); lv.setSpacing(6)

        # Header
        hdr = QLabel("FlakeScope"); hdr.setStyleSheet(
            "font-size:20px; font-weight:bold; color:#7eb8f7; font-family:Consolas; padding:6px 0;"
        )
        sub = QLabel("Graphene · hBN · 2D Materials"); sub.setStyleSheet(
            "font-size:11px; color:#5a7a9a; margin-bottom:8px;"
        )
        lv.addWidget(hdr); lv.addWidget(sub)

        # Image loading
        img_box = QGroupBox("Image"); lv.addWidget(img_box)
        img_lay = QVBoxLayout(img_box); img_lay.setSpacing(4)
        self._open_btn = QPushButton("Open Microscopy Image…"); self._open_btn.clicked.connect(self._open_image)
        self._img_label = QLabel("No image loaded"); self._img_label.setStyleSheet("color:#5a7a9a; font-size:10px;")
        img_lay.addWidget(self._open_btn); img_lay.addWidget(self._img_label)

        # Scale calibration
        cal_box = QGroupBox("Scale Calibration"); lv.addWidget(cal_box)
        cal_lay = QHBoxLayout(cal_box)
        self._cal_btn = QPushButton("Set Scale…"); self._cal_btn.clicked.connect(self._set_calibration)
        self._scale_label = QLabel("1.000 µm/px"); self._scale_label.setStyleSheet("color:#7eb8f7;")
        cal_lay.addWidget(self._cal_btn); cal_lay.addWidget(self._scale_label)

        # Profiles
        prof_box = QGroupBox("Layer Profiles"); lv.addWidget(prof_box)
        self._prof_box = prof_box
        prof_lay = QVBoxLayout(prof_box); prof_lay.setSpacing(4)
        self._profile_list = QListWidget()
        self._profile_list.setMaximumHeight(180)
        self._profile_list.setStyleSheet("font-size:11px;")
        self._profile_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._profile_list.customContextMenuRequested.connect(self._profile_context_menu)
        self._profile_list.itemChanged.connect(self._profile_check_changed)
        prof_lay.addWidget(self._profile_list)

        pbtns = QHBoxLayout()
        add_btn  = QPushButton("＋ Add");    add_btn.clicked.connect(self._add_profile)
        edit_btn = QPushButton("✎ Edit");   edit_btn.clicked.connect(self._edit_profile)
        del_btn  = QPushButton("✕ Remove"); del_btn.clicked.connect(self._remove_profile)
        eye_btn  = QPushButton("⊕ Pick Color"); eye_btn.setCheckable(True)
        eye_btn.toggled.connect(self._toggle_eyedropper)
        self._eye_btn = eye_btn
        for b in [add_btn, edit_btn, del_btn]: pbtns.addWidget(b)
        prof_lay.addLayout(pbtns)
        prof_lay.addWidget(eye_btn)

        # Detection mode selector
        mode_box = QGroupBox("Detection Mode"); lv.addWidget(mode_box)
        mode_lay = QVBoxLayout(mode_box); mode_lay.setSpacing(4)
        self._mode_combo = QComboBox()
        self._mode_combo.addItems([
            "Optical Contrast (auto layers)",
            "HSV Colour Profiles",
        ])
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_lay.addWidget(self._mode_combo)
        self._mode_hint = QLabel(
            "Contrast mode auto-detects the substrate and estimates layer count "
            "for any N. Calibrate Δ-per-layer from a known monolayer for accuracy."
        )
        self._mode_hint.setWordWrap(True)
        self._mode_hint.setStyleSheet("color:#5a7a9a; font-size:10px;")
        mode_lay.addWidget(self._mode_hint)

        # ── Contrast-mode options ──────────────────────────────────────────────
        self._contrast_box = QGroupBox("Contrast Settings"); lv.addWidget(self._contrast_box)
        c_lay = QFormLayout(self._contrast_box); c_lay.setSpacing(4)

        self._channel_combo = QComboBox()
        self._channel_combo.addItems(list(CONTRAST_CHANNELS.keys()))

        self._direction_combo = QComboBox()
        self._direction_combo.addItems(["Darker than substrate (graphene)",
                                        "Brighter than substrate", "Both"])

        self._min_contrast_spin = QDoubleSpinBox()
        self._min_contrast_spin.setRange(0.1, 90.0); self._min_contrast_spin.setValue(3.0)
        self._min_contrast_spin.setSingleStep(0.5); self._min_contrast_spin.setSuffix(" %")

        self._delta_c_spin = QDoubleSpinBox()
        self._delta_c_spin.setRange(0.0, 90.0); self._delta_c_spin.setValue(0.0)
        self._delta_c_spin.setSingleStep(0.1); self._delta_c_spin.setSuffix(" % / layer")
        self._delta_c_spin.setToolTip("Optical contrast added by ONE layer. "
                                      "0 = don't estimate N (report contrast only).")

        self._calib_btn = QPushButton("🎯 Calibrate Δ from a 1-layer flake")
        self._calib_btn.setCheckable(True)
        self._calib_btn.toggled.connect(self._toggle_calibrate)

        self._max_layers_spin = QSpinBox()
        self._max_layers_spin.setRange(2, 100); self._max_layers_spin.setValue(10)

        c_lay.addRow("Channel:", self._channel_combo)
        c_lay.addRow("Detect:", self._direction_combo)
        c_lay.addRow("Min contrast:", self._min_contrast_spin)
        c_lay.addRow("Δ per layer:", self._delta_c_spin)
        c_lay.addRow("", self._calib_btn)
        c_lay.addRow("Max layers (colour):", self._max_layers_spin)

        # ── Shared detection options ───────────────────────────────────────────
        opt_box = QGroupBox("Detection Options"); lv.addWidget(opt_box)
        opt_lay = QFormLayout(opt_box); opt_lay.setSpacing(4)

        self._min_area_spin = QSpinBox(); self._min_area_spin.setRange(5, 10_000_000); self._min_area_spin.setValue(200); self._min_area_spin.setSuffix(" px²")
        self._morph_spin    = QSpinBox(); self._morph_spin.setRange(0, 20);       self._morph_spin.setValue(3)
        self._label_chk     = QCheckBox("Show labels");   self._label_chk.setChecked(True)
        self._contour_chk   = QCheckBox("Show contours"); self._contour_chk.setChecked(True)
        opt_lay.addRow("Min area:", self._min_area_spin)
        opt_lay.addRow("Morph close:", self._morph_spin)
        opt_lay.addRow("", self._label_chk)
        opt_lay.addRow("", self._contour_chk)

        # Analyse button
        self._analyse_btn = QPushButton("▶  Analyse Image")
        self._analyse_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #1e6fbf, stop:1 #0d4a8c);
                color: white; font-size: 14px; font-weight: bold;
                border-radius: 6px; padding: 10px;
            }
            QPushButton:hover  { background: #2a80d0; }
            QPushButton:pressed{ background: #0d4a8c; }
            QPushButton:disabled{ background: #333; color:#666; }
        """)
        self._analyse_btn.clicked.connect(self._run_analysis)
        self._analyse_btn.setEnabled(False)
        lv.addWidget(self._analyse_btn)

        # Export
        exp_btn = QPushButton("Export Results (.csv)")
        exp_btn.clicked.connect(self._export_csv)
        lv.addWidget(exp_btn)

        lv.addStretch()

        # ── Centre: image viewer + results tabs ───────────────────────────────
        right_splitter = QSplitter(Qt.Vertical)

        # Viewer
        viewer_container = QWidget()
        vc_lay = QVBoxLayout(viewer_container); vc_lay.setContentsMargins(0, 0, 0, 0); vc_lay.setSpacing(0)

        # Viewer toolbar
        vtbar = QWidget(); vtbar.setStyleSheet("background:#1a1a2e; border-bottom:1px solid #2d2d4a; padding:2px 6px;")
        vtbar_lay = QHBoxLayout(vtbar); vtbar_lay.setContentsMargins(4, 2, 4, 2)
        fit_btn = QPushButton("⊡ Fit"); fit_btn.setFixedWidth(55); fit_btn.clicked.connect(self._zoom_fit)
        zoom_in  = QPushButton("＋"); zoom_in.setFixedWidth(30);  zoom_in.clicked.connect(lambda: self._step_zoom(1.2))
        zoom_out = QPushButton("－"); zoom_out.setFixedWidth(30); zoom_out.clicked.connect(lambda: self._step_zoom(1/1.2))
        self._zoom_lbl = QLabel("100%"); self._zoom_lbl.setStyleSheet("color:#7eb8f7; font-size:11px;")
        self._overlay_chk = QCheckBox("Show overlay"); self._overlay_chk.setChecked(True)
        self._overlay_chk.stateChanged.connect(self._refresh_display)
        for w in [fit_btn, zoom_out, zoom_in, self._zoom_lbl, QLabel("   "), self._overlay_chk]:
            vtbar_lay.addWidget(w)
        vtbar_lay.addStretch()
        self._coord_lbl = QLabel(""); self._coord_lbl.setStyleSheet("color:#5a7a9a; font-size:10px;")
        vtbar_lay.addWidget(self._coord_lbl)
        vc_lay.addWidget(vtbar)

        # Eyedropper info bar
        self._eyedropper_bar = QLabel(" 🔬 Eyedropper active — click a pixel to read its HSV color")
        self._eyedropper_bar.setStyleSheet(
            "background:#1e3a50; color:#7eb8f7; font-size:11px; padding:4px 8px; border-bottom:1px solid #2d5a7a;"
        )
        self._eyedropper_bar.setVisible(False)
        vc_lay.addWidget(self._eyedropper_bar)

        self._viewer = ImageViewer()
        self._viewer.pixelClicked.connect(self._on_pixel_clicked)
        self._viewer.zoomChanged.connect(lambda z: self._zoom_lbl.setText(f"{z*100:.0f}%"))
        vc_lay.addWidget(self._viewer)

        right_splitter.addWidget(viewer_container)

        # Results tabs
        self._tabs = QTabWidget()
        self._tabs.setMaximumHeight(260)

        # Results table
        self._table = QTableWidget()
        headers = ["Profile", "Material", "Layers", "N", "Contrast %",
                   "Area (µm²)", "Area (px²)",
                   "Perimeter (µm)", "Aspect Ratio", "Cx (px)", "Cy (px)"]
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("font-size:11px;")
        self._tabs.addTab(self._table, "Detected Flakes")

        # Summary
        self._summary_text = QTextEdit(); self._summary_text.setReadOnly(True)
        self._summary_text.setStyleSheet("font-family:Consolas; font-size:11px; background:#0d0d1a; color:#b0d4f7;")
        self._tabs.addTab(self._summary_text, "Summary")

        # Log
        self._log = QTextEdit(); self._log.setReadOnly(True)
        self._log.setStyleSheet("font-family:Consolas; font-size:10px; background:#0d0d1a; color:#8a8a9a;")
        self._tabs.addTab(self._log, "Log")

        right_splitter.addWidget(self._tabs)
        right_splitter.setSizes([600, 220])

        splitter.addWidget(left)
        splitter.addWidget(right_splitter)
        splitter.setSizes([320, 880])
        root.addWidget(splitter)

        # Status bar
        self._status = QStatusBar()
        self._status.setStyleSheet("font-size:11px; color:#7eb8f7;")
        self.setStatusBar(self._status)
        self._status.showMessage("Ready — open a microscopy image to begin")

    def _build_menu(self):
        mb = self.menuBar()
        mb.setStyleSheet("QMenuBar { background:#12122a; color:#ccd; } QMenuBar::item:selected { background:#2d2d4a; }")

        fm = mb.addMenu("&File")
        fm.addAction("&Open Image…\tCtrl+O", self._open_image)
        fm.addAction("&Save Overlay…\tCtrl+S", self._save_overlay)
        fm.addSeparator()
        fm.addAction("Export CSV…", self._export_csv)
        fm.addSeparator()
        fm.addAction("E&xit", self.close)

        am = mb.addMenu("&Analysis")
        am.addAction("▶ Run Analysis\tCtrl+R", self._run_analysis)
        am.addAction("Set Scale…", self._set_calibration)

        hm = mb.addMenu("&Help")
        hm.addAction("About", self._show_about)
        hm.addAction("HSV Color Guide", self._show_hsv_guide)

    # ── Theming ───────────────────────────────────────────────────────────────

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#16162c; color:#c8d0e0; }
            QGroupBox {
                border:1px solid #2d2d4a; border-radius:5px;
                margin-top:10px; padding-top:6px; font-size:11px; color:#8ab4e8;
            }
            QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 3px; }
            QPushButton {
                background:#252550; color:#c8d0e0; border:1px solid #3d3d6b;
                border-radius:4px; padding:4px 10px; font-size:12px;
            }
            QPushButton:hover { background:#2d2d6a; }
            QPushButton:checked { background:#1e5ca0; border-color:#4a8cd0; }
            QSlider::groove:horizontal { background:#2d2d4a; height:4px; border-radius:2px; }
            QSlider::handle:horizontal { background:#4a8cd0; width:12px; height:12px;
                border-radius:6px; margin:-4px 0; }
            QTableWidget { background:#0d0d1a; gridline-color:#2d2d4a; border:none; }
            QTableWidget QHeaderView::section { background:#1a1a3a; border:1px solid #2d2d4a; padding:3px; }
            QListWidget { background:#0d0d1a; border:1px solid #2d2d4a; }
            QTabWidget::pane { border:1px solid #2d2d4a; background:#12122a; }
            QTabBar::tab { background:#1a1a2e; border:1px solid #2d2d4a; padding:5px 12px; }
            QTabBar::tab:selected { background:#252550; color:#7eb8f7; }
            QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {
                background:#1a1a3a; border:1px solid #3d3d6b; color:#c8d0e0;
                padding:2px 4px; border-radius:3px;
            }
            QScrollBar:vertical { background:#1a1a2e; width:10px; }
            QScrollBar::handle:vertical { background:#3d3d6b; border-radius:5px; }
            QCheckBox { color:#c8d0e0; }
        """)

    # ── Profile management ────────────────────────────────────────────────────

    def _refresh_profile_list(self):
        self._profile_list.blockSignals(True)
        self._profile_list.clear()
        for p in self._profiles:
            item = QListWidgetItem(f"  {p.name}  [{p.material} · {p.layer_count}]")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if p.name in self._active_profiles else Qt.Unchecked)
            px = QPixmap(14, 14); px.fill(QColor(*p.color_rgb))
            item.setIcon(QIcon(px))
            self._profile_list.addItem(item)
        self._profile_list.blockSignals(False)

    def _profile_check_changed(self, item):
        idx = self._profile_list.row(item)
        p   = self._profiles[idx]
        if item.checkState() == Qt.Checked:
            self._active_profiles.add(p.name)
        else:
            self._active_profiles.discard(p.name)

    def _add_profile(self):
        dlg = ProfileEditorDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._profiles.append(dlg.get_profile())
            self._active_profiles.add(self._profiles[-1].name)
            self._refresh_profile_list()

    def _edit_profile(self):
        idx = self._profile_list.currentRow()
        if idx < 0: return
        dlg = ProfileEditorDialog(self._profiles[idx], parent=self)
        if dlg.exec_() == QDialog.Accepted:
            old_name = self._profiles[idx].name
            self._profiles[idx] = dlg.get_profile()
            self._active_profiles.discard(old_name)
            self._active_profiles.add(self._profiles[idx].name)
            self._refresh_profile_list()

    def _remove_profile(self):
        idx = self._profile_list.currentRow()
        if idx < 0: return
        self._active_profiles.discard(self._profiles[idx].name)
        self._profiles.pop(idx)
        self._refresh_profile_list()

    def _profile_context_menu(self, pos):
        menu = QMenu()
        menu.addAction("Edit…",   self._edit_profile)
        menu.addAction("Remove",  self._remove_profile)
        menu.exec_(self._profile_list.mapToGlobal(pos))

    # ── Detection mode ──────────────────────────────────────────────────────────

    def _is_contrast_mode(self) -> bool:
        return self._mode_combo.currentIndex() == 0

    def _on_mode_changed(self, *_):
        contrast = self._is_contrast_mode()
        self._contrast_box.setVisible(contrast)
        self._prof_box.setVisible(not contrast)
        # The eyedropper/calibrate tools belong to different modes.
        self._eye_btn.setVisible(not contrast)
        if contrast:
            self._mode_hint.setText(
                "Contrast mode auto-detects the substrate and estimates layer "
                "count for any N. Calibrate Δ-per-layer from a known monolayer."
            )
        else:
            self._mode_hint.setText(
                "HSV mode matches flakes by colour range. Tune each profile's "
                "H/S/V, or use the eyedropper to sample a flake's colour."
            )

    def _toggle_calibrate(self, on: bool):
        """Arm a one-shot click to read a known monolayer's contrast as Δ/layer."""
        if on and self._bgr is None:
            self._calib_btn.setChecked(False)
            QMessageBox.information(self, "No image", "Open an image first.")
            return
        self._calib_arm = on
        # Turn off the HSV eyedropper if it was on, and reuse the pick cursor.
        if on:
            self._eye_btn.setChecked(False)
        self._viewer.set_eyedropper(on)
        self._eyedropper_bar.setVisible(on)
        self._eyedropper_bar.setText(
            " 🎯 Calibration active — click the centre of a KNOWN 1-layer flake"
        )

    # ── Eyedropper ────────────────────────────────────────────────────────────

    def _toggle_eyedropper(self, on: bool):
        if on:
            self._calib_btn.setChecked(False)
            self._calib_arm = False
        self._viewer.set_eyedropper(on)
        self._eyedropper_bar.setVisible(on)
        self._eyedropper_bar.setText(
            " 🔬 Eyedropper active — click a pixel to read its HSV color"
        )

    def _on_pixel_clicked(self, ix: int, iy: int):
        if self._bgr is None:
            return

        # ── Contrast calibration click ─────────────────────────────────────────
        if self._calib_arm:
            channel = CONTRAST_CHANNELS[self._channel_combo.currentText()]
            c = AnalysisEngine.sample_contrast(self._bgr, ix, iy,
                                               channel=channel, radius=8)
            c_pct = abs(c) * 100.0
            if c_pct < 0.05:
                QMessageBox.information(self, "Very low contrast",
                    f"Sampled contrast here is only {c_pct:.2f}%.\n\n"
                    "Click on the centre of a clearly-visible monolayer flake, "
                    "or pick a different channel.")
            self._delta_c_spin.setValue(c_pct)
            self._log.append(
                f"[Calibrate] 1-layer Δ = {c_pct:.2f}% contrast "
                f"(pixel {ix},{iy}, {channel} channel)")
            self._status.showMessage(f"Δ per layer set to {c_pct:.2f}%")
            self._calib_btn.setChecked(False)   # one-shot
            return

        # ── HSV eyedropper click ───────────────────────────────────────────────
        bgr_mean, hsv_mean = AnalysisEngine.sample_color(self._bgr, ix, iy, radius=4)
        h, s, v = int(hsv_mean[0]), int(hsv_mean[1]), int(hsv_mean[2])
        r, g, b = int(bgr_mean[2]), int(bgr_mean[1]), int(bgr_mean[0])
        msg = (
            f"Pixel ({ix}, {iy})  |  "
            f"RGB ({r}, {g}, {b})  |  "
            f"HSV ({h}, {s}, {v})"
        )
        self._log.append(f"[Eyedropper] {msg}")
        self._status.showMessage(msg)

        # Suggest or pre-fill a profile
        idx = self._profile_list.currentRow()
        if idx >= 0:
            p = self._profiles[idx]
            reply = QMessageBox.question(
                self, "Apply to profile?",
                f"Apply sampled HSV ({h}, {s}, {v}) as center ±20 to\n'{p.name}'?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                p.h_min = max(0,   h - 20)
                p.h_max = min(179, h + 20)
                p.s_min = max(0,   s - 40)
                p.s_max = min(255, s + 40)
                p.v_min = max(0,   v - 40)
                p.v_max = min(255, v + 40)
                p.color_rgb = (r, g, b)
                self._refresh_profile_list()
                self._log.append(f"  → Applied HSV range to '{p.name}'")

    # ── File operations ───────────────────────────────────────────────────────

    def _open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Microscopy Image", "",
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp);;All files (*.*)"
        )
        if not path:
            return
        try:
            bgr = cv2.imread(path)
            if bgr is None:
                QMessageBox.critical(self, "Cannot Open Image",
                    f"OpenCV could not read this file:\n{path}\n\n"
                    "Make sure it is a valid image (PNG, JPEG, TIFF, BMP).")
                return
            self._bgr = bgr
            self._bgr_overlay = None
            self._image_path = path
            name = Path(path).name
            h, w = bgr.shape[:2]
            self._img_label.setText(f"{name}  ({w}×{h} px)")
            self._status.showMessage(f"Loaded: {name}  ({w}×{h})")
            self._log.append(f"[Open] {path}  {w}×{h} px")
            self._show_bgr(bgr)
            self._analyse_btn.setEnabled(True)
            self._results = []
            self._table.setRowCount(0)
            self._summary_text.clear()
        except Exception as e:
            QMessageBox.critical(self, "Error Opening Image", str(e))
            self._log.append(f"[Error] Open: {e}")

    def _save_overlay(self):
        if self._bgr_overlay is None:
            QMessageBox.information(self, "No overlay", "Run analysis first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Overlay", "", "PNG (*.png);;TIFF (*.tiff)"
        )
        if path:
            cv2.imwrite(path, self._bgr_overlay)
            self._status.showMessage(f"Saved: {path}")

    def _export_csv(self):
        if not self._results:
            QMessageBox.information(self, "No results", "Run analysis first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "flake_results.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                fieldnames = [
                    "profile_name", "material", "layer_count", "n_layers",
                    "contrast_pct", "area_um2", "area_px", "perimeter_um",
                    "aspect_ratio", "centroid_x", "centroid_y",
                ]
                w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                w.writeheader()
                for fl in self._results:
                    row = {
                        "profile_name": fl.profile_name,
                        "material":     fl.material,
                        "layer_count":  fl.layer_count,
                        "n_layers":     fl.n_layers if fl.n_layers is not None else "",
                        "contrast_pct": f"{fl.contrast*100:.3f}",
                        "area_um2":     fl.area_um2,
                        "area_px":      fl.area_px,
                        "perimeter_um": fl.perimeter_um,
                        "aspect_ratio": fl.aspect_ratio,
                        "centroid_x":   fl.centroid_x,
                        "centroid_y":   fl.centroid_y,
                    }
                    w.writerow(row)
            self._status.showMessage(f"Exported {len(self._results)} flakes → {path}")
            self._log.append(f"[Export] {path}")
        except OSError as e:
            QMessageBox.critical(self, "Export Failed",
                f"Could not write file:\n{path}\n\n{e}")
            self._log.append(f"[Error] Export: {e}")

    # ── Analysis ──────────────────────────────────────────────────────────────

    def _run_analysis(self):
        if self._bgr is None:
            return
        self._results = []
        self._table.setRowCount(0)

        min_a  = self._min_area_spin.value()
        morph  = self._morph_spin.value()
        show_l = self._label_chk.isChecked()
        show_c = self._contour_chk.isChecked()

        self._status.showMessage("Running analysis…")
        self._analyse_btn.setEnabled(False)
        try:
            if self._is_contrast_mode():
                self._run_contrast_analysis(min_a, morph, show_l, show_c)
            else:
                self._run_hsv_analysis(min_a, morph, show_l, show_c)
            self._populate_table()
            self._refresh_display()
        except Exception as e:
            QMessageBox.critical(self, "Analysis Error",
                f"An error occurred during analysis:\n\n{e}\n\n"
                "Check the Log tab for details.")
            self._log.append(f"[Error] Analysis: {e}")
            self._status.showMessage("Analysis failed — see Log tab")
        finally:
            self._analyse_btn.setEnabled(True)

    def _run_hsv_analysis(self, min_a, morph, show_l, show_c):
        active = [p for p in self._profiles if p.name in self._active_profiles]
        if not active:
            QMessageBox.warning(self, "No profiles", "Check at least one profile.")
            return
        self._log.append(f"\n[Analysis · HSV] {len(active)} profiles  µm/px={self._um_per_px:.5f}")

        flakes_by_profile = []
        for p in active:
            mask, flakes = AnalysisEngine.detect_flakes(
                self._bgr, p, min_a, morph, self._um_per_px
            )
            flakes_by_profile.append((p, mask, flakes))
            self._results.extend(flakes)
            self._log.append(f"  {p.name}: {len(flakes)} flakes detected")

        self._bgr_overlay = AnalysisEngine.draw_overlay(
            self._bgr, flakes_by_profile, show_l, show_c
        )
        self._build_summary_hsv(flakes_by_profile)
        self._status.showMessage(
            f"Analysis complete — {len(self._results)} flakes across {len(active)} profiles"
        )

    def _run_contrast_analysis(self, min_a, morph, show_l, show_c):
        channel = CONTRAST_CHANNELS[self._channel_combo.currentText()]
        direction = ["darker", "brighter", "both"][self._direction_combo.currentIndex()]
        min_contrast = self._min_contrast_spin.value() / 100.0
        delta_pct = self._delta_c_spin.value()
        delta_c = (delta_pct / 100.0) if delta_pct > 0 else None
        max_layers = self._max_layers_spin.value()

        self._log.append(
            f"\n[Analysis · Contrast] channel={channel} dir={direction} "
            f"min={min_contrast*100:.1f}% Δ={delta_pct:.2f}%/L µm/px={self._um_per_px:.5f}"
        )

        mask, flakes, info = AnalysisEngine.detect_flakes_by_contrast(
            self._bgr, min_contrast=min_contrast, delta_c=delta_c,
            channel=channel, min_area_px=min_a, morph_close=morph,
            um_per_px=self._um_per_px, max_layers=max_layers, direction=direction,
        )
        self._results = flakes
        self._bgr_overlay = AnalysisEngine.draw_contrast_overlay(
            self._bgr, flakes, show_l, show_c
        )
        self._log.append(
            f"  substrate {channel} level: {info['substrate_intensity']:.0f}/255  "
            f"→ {len(flakes)} flakes")
        self._build_summary_contrast(flakes, info)
        if delta_c is None:
            self._status.showMessage(
                f"{len(flakes)} flakes — calibrate Δ/layer to estimate layer numbers")
        else:
            self._status.showMessage(
                f"Analysis complete — {len(flakes)} flakes, layers estimated")

    def _populate_table(self):
        self._table.setRowCount(len(self._results))
        for row, fl in enumerate(self._results):
            n_str = str(fl.n_layers) if fl.n_layers is not None else "—"
            c_str = f"{fl.contrast*100:.1f}" if fl.contrast else "—"
            vals = [
                fl.profile_name, fl.material, fl.layer_count, n_str, c_str,
                f"{fl.area_um2:.3f}", f"{fl.area_px:.0f}",
                f"{fl.perimeter_um:.2f}", f"{fl.aspect_ratio:.2f}",
                f"{fl.centroid_x:.1f}", f"{fl.centroid_y:.1f}",
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignCenter)
                self._table.setItem(row, col, item)

    def _build_summary_hsv(self, flakes_by_profile):
        lines = self._summary_header()
        total_flakes = 0
        for p, _, flakes in flakes_by_profile:
            if not flakes:
                continue
            areas = [f.area_um2 for f in flakes]
            lines.append(f"\n▸ {p.name}  ({p.material} · {p.layer_count})")
            lines.append(f"  Flakes     : {len(flakes)}")
            lines.append(f"  Total area : {sum(areas):.2f} µm²")
            lines.append(f"  Mean area  : {np.mean(areas):.2f} µm²")
            lines.append(f"  Min / Max  : {min(areas):.2f} / {max(areas):.2f} µm²")
            total_flakes += len(flakes)
        lines.append(f"\n{'─'*52}")
        lines.append(f"  Total flakes: {total_flakes}")
        self._summary_text.setPlainText("\n".join(lines))

    def _build_summary_contrast(self, flakes, info):
        from collections import defaultdict
        lines = self._summary_header()
        lines.append(f"  Mode  : Optical contrast ({info['channel']}, {info['direction']})")
        lines.append(f"  Substrate level : {info['substrate_intensity']:.0f}/255")
        if info.get("delta_c"):
            lines.append(f"  Δ per layer     : {info['delta_c']*100:.2f}% contrast")
        else:
            lines.append("  Δ per layer     : not calibrated (layer N not estimated)")
        lines.append("=" * 52)

        if not flakes:
            lines.append("\n  No flakes detected above the contrast threshold.")
            self._summary_text.setPlainText("\n".join(lines))
            return

        groups = defaultdict(list)
        for f in flakes:
            key = f.n_layers if f.n_layers is not None else "?"
            groups[key].append(f)

        def sort_key(k):
            return (1, 0) if k == "?" else (0, k)

        lines.append("\n  Layer    Count   TotalArea(µm²)   MeanArea(µm²)")
        lines.append("  " + "─" * 46)
        for key in sorted(groups, key=sort_key):
            fs = groups[key]
            areas = [f.area_um2 for f in fs]
            label = f"{key}L" if key != "?" else " ? "
            lines.append(f"  {label:<7} {len(fs):>5}   {sum(areas):>13.2f}   {np.mean(areas):>12.2f}")

        lines.append("\n" + "─" * 52)
        lines.append(f"  Total flakes: {len(flakes)}")
        thinnest = [f for f in flakes if f.n_layers == 1]
        if thinnest:
            lines.append(f"  Monolayer (1L) flakes: {len(thinnest)}  "
                         f"(largest {max(f.area_um2 for f in thinnest):.1f} µm²)")
        self._summary_text.setPlainText("\n".join(lines))

    def _summary_header(self):
        return ["=" * 52,
                "  FlakeScope Analysis Report",
                f"  Image : {Path(self._image_path).name}",
                f"  Scale : {self._um_per_px:.5f} µm/px"]

    # ── Display helpers ───────────────────────────────────────────────────────

    def _show_bgr(self, bgr: np.ndarray):
        h, w, ch = bgr.shape
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        qi = QImage(rgb.data, w, h, w * ch, QImage.Format_RGB888)
        pm = QPixmap.fromImage(qi.copy())   # copy so QImage can be freed safely
        self._viewer.set_pixmap(pm)
        QTimer.singleShot(100, self._viewer.zoom_to_fit)

    def _refresh_display(self):
        if self._bgr is None:
            return
        if self._overlay_chk.isChecked() and self._bgr_overlay is not None:
            self._show_bgr(self._bgr_overlay)
        else:
            self._show_bgr(self._bgr)

    def _zoom_fit(self):
        self._viewer.zoom_to_fit()

    def _step_zoom(self, factor: float):
        self._viewer._zoom = max(0.05, min(50.0, self._viewer._zoom * factor))
        self._zoom_lbl.setText(f"{self._viewer._zoom*100:.0f}%")
        self._viewer.update()

    # ── Calibration ───────────────────────────────────────────────────────────

    def _set_calibration(self):
        dlg = CalibrationDialog(self._um_per_px, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._um_per_px = dlg.get_um_per_px()
            self._scale_label.setText(f"{self._um_per_px:.4f} µm/px")
            self._log.append(f"[Calibration] {self._um_per_px:.5f} µm/px")

    # ── Help ──────────────────────────────────────────────────────────────────

    def _show_about(self):
        QMessageBox.about(self, "About FlakeScope",
            "<b>FlakeScope</b><br>"
            "Graphene &amp; hBN Layer Detection Tool<br><br>"
            "Built for optical microscopy analysis of 2D materials.<br>"
            "Detects flakes by HSV color matching and measures area in µm².<br><br>"
            "Stack: Python · PyQt5 · OpenCV · scikit-image<br>"
            "Built for CSU Physics PhD research"
        )

    def _show_hsv_guide(self):
        txt = (
            "<b>HSV Color Space Guide</b><br><br>"
            "<b>H (Hue):</b> 0–179 in OpenCV<br>"
            "&nbsp;&nbsp;0/179 = Red, 30 = Yellow, 60 = Green, 90 = Cyan, 120 = Blue, 150 = Magenta<br><br>"
            "<b>S (Saturation):</b> 0 = grey/white, 255 = fully saturated color<br><br>"
            "<b>V (Value/Brightness):</b> 0 = black, 255 = full brightness<br><br>"
            "<b>Tips for graphene on 300 nm SiO₂:</b><br>"
            "• Use the eyedropper (⊕ Pick Color) to sample your actual images<br>"
            "• Monolayer typically shows very low saturation (S: 5–60)<br>"
            "• Camera white balance affects H ranges — always tune per-microscope<br>"
            "• Adjust V range to exclude the substrate background<br>"
        )
        msg = QMessageBox(self)
        msg.setWindowTitle("HSV Color Guide")
        msg.setText(txt)
        msg.exec_()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FlakeScope")
    app.setOrganizationName("CSU Physics")
    app.setStyle("Fusion")

    # Base Fusion dark palette
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor("#16162c"))
    palette.setColor(QPalette.WindowText,      QColor("#c8d0e0"))
    palette.setColor(QPalette.Base,            QColor("#0d0d1a"))
    palette.setColor(QPalette.AlternateBase,   QColor("#141428"))
    palette.setColor(QPalette.ToolTipBase,     QColor("#1a1a3a"))
    palette.setColor(QPalette.ToolTipText,     QColor("#c8d0e0"))
    palette.setColor(QPalette.Text,            QColor("#c8d0e0"))
    palette.setColor(QPalette.Button,          QColor("#252550"))
    palette.setColor(QPalette.ButtonText,      QColor("#c8d0e0"))
    palette.setColor(QPalette.BrightText,      QColor("#ffffff"))
    palette.setColor(QPalette.Link,            QColor("#7eb8f7"))
    palette.setColor(QPalette.Highlight,       QColor("#1e5ca0"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    import traceback

    def _crash_hook(exc_type, exc_value, exc_tb):
        """Write any unhandled exception to a file so silent crashes are visible."""
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        crash_path = Path(__file__).parent / "flakescope_crash.log"
        with open(crash_path, "w", encoding="utf-8") as f:
            f.write(msg)
        # Also try to show it in a message box if Qt is alive
        try:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(None, "FlakeScope crashed", msg)
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _crash_hook
    main()
