import sys
import unittest
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app  # noqa: E402
from profile_extractor import _subpixel_edge_1d, _subpixel_edge_1d_polarity, extract_profile  # noqa: E402


class ProfileExtractorTests(unittest.TestCase):
    def test_app_and_profile_extractor_share_same_subpixel_function(self):
        self.assertIs(app._subpixel_edge_1d, _subpixel_edge_1d)

    def test_flat_cylinder_profile_stays_nearly_constant(self):
        image = np.full((120, 240, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (20, 40), (220, 80), (70, 70, 70), thickness=-1)

        profile = extract_profile(
            image,
            {
                "blur_ksize": 3,
                "morph_ksize": 3,
                "min_contour_area": 100,
            },
        )

        diameters = np.array(profile["diameter_px"], dtype=float)
        valid = diameters[diameters > 0]

        self.assertGreater(len(valid), 150)
        self.assertLess(np.std(valid), 0.35)
        self.assertAlmostEqual(float(np.median(valid)), 40.0, delta=1.0)
        self.assertIn("overlay_top_edge", profile)
        self.assertIn("overlay_bottom_edge", profile)

    def test_polarity_aware_subpixel_prefers_true_outer_edges(self):
        col = np.full(120, 255, dtype=np.float32)
        col[40:80] = 120
        col[46:49] = 200
        col[72:75] = 60

        top = _subpixel_edge_1d_polarity(col, 40, search_window=8, edge="top")
        bottom = _subpixel_edge_1d_polarity(col, 79, search_window=8, edge="bottom")

        self.assertAlmostEqual(top, 39.5, delta=1.5)
        self.assertAlmostEqual(bottom, 79.5, delta=1.5)


if __name__ == "__main__":
    unittest.main()
