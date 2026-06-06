"""
Generate a synthetic optical microscopy image simulating
graphene and hBN flakes on 300nm SiO₂/Si substrate.
"""
import cv2
import numpy as np
from pathlib import Path


def make_test_image(path="test_microscopy.png", size=(1024, 768)):
    np.random.seed(42)
    w, h = size

    # ── Substrate background: pale purple-blue (SiO₂ 300nm color)
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = (205, 195, 200)   # BGR: very light purple-grey

    # Add subtle noise
    noise = np.random.normal(0, 3, img.shape).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    def draw_irregular_flake(canvas, center, approx_radius, color_bgr, n_pts=12, roughness=0.28):
        cx, cy = center
        angles = np.linspace(0, 2 * np.pi, n_pts, endpoint=False)
        radii  = approx_radius * (1 + np.random.uniform(-roughness, roughness, n_pts))
        pts    = np.array([
            [int(cx + r * np.cos(a)), int(cy + r * np.sin(a))]
            for r, a in zip(radii, angles)
        ], dtype=np.int32)
        cv2.fillPoly(canvas, [pts], color_bgr)
        return pts

    # ── Graphene monolayer flakes — very faint grey-green tinge
    # On 300nm SiO₂, monolayer graphene appears ~5% darker than substrate
    mono_color = (185, 178, 186)   # slight greenish-grey
    mono_positions = [(200, 180, 60), (450, 320, 80), (750, 200, 50),
                      (600, 550, 70), (120, 500, 45), (870, 400, 65)]
    for cx, cy, r in mono_positions:
        draw_irregular_flake(img, (cx, cy), r, mono_color)
    
    # Noise on top
    noise2 = np.random.normal(0, 2, img.shape).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise2, 0, 255).astype(np.uint8)

    # ── Graphene bilayer — slightly darker
    bi_color = (158, 160, 166)   # noticeably darker grey-green
    bi_positions = [(310, 420, 45), (680, 350, 55), (500, 180, 40), (820, 600, 50)]
    for cx, cy, r in bi_positions:
        draw_irregular_flake(img, (cx, cy), r, bi_color, roughness=0.22)

    # ── Graphene trilayer+ — darker still
    tri_color = (130, 138, 142)
    tri_positions = [(150, 320, 35), (730, 500, 42), (400, 620, 38)]
    for cx, cy, r in tri_positions:
        draw_irregular_flake(img, (cx, cy), r, tri_color, roughness=0.20)

    # ── hBN thin (1-5L) — warm yellowish tinge
    hbn_thin_color = (165, 190, 210)   # warm light yellow
    hbn_thin_pos = [(350, 250, 55), (600, 420, 65), (880, 250, 48), (200, 600, 52)]
    for cx, cy, r in hbn_thin_pos:
        draw_irregular_flake(img, (cx, cy), r, hbn_thin_color, roughness=0.30)

    # ── hBN medium
    hbn_med_color = (140, 172, 198)
    hbn_med_pos = [(530, 530, 50), (780, 450, 42), (250, 440, 48)]
    for cx, cy, r in hbn_med_pos:
        draw_irregular_flake(img, (cx, cy), r, hbn_med_color, roughness=0.25)

    # ── hBN thick/bulk — more saturated yellow-brown
    hbn_thick_color = (120, 155, 190)
    hbn_thick_pos = [(400, 130, 38), (950, 350, 45), (100, 700, 40)]
    for cx, cy, r in hbn_thick_pos:
        draw_irregular_flake(img, (cx, cy), r, hbn_thick_color, roughness=0.20)

    # ── Final subtle noise pass
    noise3 = np.random.normal(0, 2.5, img.shape).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise3, 0, 255).astype(np.uint8)

    # ── Scale bar (bottom-right): 10µm at ~0.155µm/px → ~64px
    bar_len = 64
    bar_x1, bar_y = w - 120, h - 30
    bar_x2 = bar_x1 + bar_len
    cv2.rectangle(img, (bar_x1 - 2, bar_y - 8), (bar_x2 + 2, bar_y + 4), (30, 30, 30), -1)
    cv2.rectangle(img, (bar_x1, bar_y - 6), (bar_x2, bar_y + 2), (240, 240, 240), -1)
    cv2.putText(img, "10 um", (bar_x1, bar_y - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (240, 240, 240), 1, cv2.LINE_AA)

    cv2.imwrite(path, img)
    print(f"Test image saved: {path}")
    return path


if __name__ == "__main__":
    make_test_image("test_microscopy.png")
