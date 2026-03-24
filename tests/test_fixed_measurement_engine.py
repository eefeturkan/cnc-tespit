import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fixed_measurement_engine import FixedMeasurementEngine  # noqa: E402


class FixedMeasurementEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = FixedMeasurementEngine()

    def test_fixed_x_supports_absolute_image_coordinates(self):
        profile = {
            "diameter_px": [10.0] * 100,
            "top_edge": [20.0] * 100,
            "bottom_edge": [30.0] * 100,
            "x_start": 50,
        }

        rel = self.engine.measure_diameter_at_fixed_x(
            20,
            profile,
            y_calibration=2.0,
            sample_width_px=0,
            x_mode="relative_to_part_start",
        )
        abs_mode = self.engine.measure_diameter_at_fixed_x(
            70,
            profile,
            y_calibration=2.0,
            sample_width_px=0,
            x_mode="absolute_image",
            search_radius_px=0,
        )

        self.assertEqual(rel, abs_mode)
        self.assertAlmostEqual(rel[0], 5.0, places=4)
        self.assertEqual(rel[5], 70)
        self.assertEqual(rel[6], 20)
        self.assertEqual(rel[7], 0)

    def test_fixed_x_snaps_from_transition_into_stable_band(self):
        profile = {
            "diameter_px": ([10.0] * 10) + [15.0, 18.0, 20.0] + ([20.0] * 27),
            "top_edge": [20.0] * 40,
            "bottom_edge": [40.0] * 40,
            "x_start": 100,
        }

        measured = self.engine.measure_diameter_at_fixed_x(
            10,
            profile,
            y_calibration=1.0,
            sample_width_px=2,
            x_mode="relative_to_part_start",
            search_radius_px=12,
        )

        self.assertAlmostEqual(measured[0], 20.0, places=4)
        self.assertGreaterEqual(measured[6], 13)
        self.assertGreater(measured[7], 0)

    def test_total_length_counts_inclusive_pixel_span(self):
        profile = {
            "diameter_px": [0.0, 12.0, 12.0, 12.0, 0.0],
            "x_start": 100,
        }

        length_mm, x_start, x_end = self.engine.measure_total_length(profile, x_calibration=1.0)

        self.assertEqual((x_start, x_end), (101, 103))
        self.assertAlmostEqual(length_mm, 3.0, places=4)

    def test_fixed_length_uses_absolute_image_coordinates(self):
        length_mm, x_start, x_end = self.engine.measure_fixed_length(
            1392,
            1613,
            x_calibration=20.0,
        )

        self.assertEqual((x_start, x_end), (1392, 1613))
        self.assertAlmostEqual(length_mm, (1613 - 1392) / 20.0, places=4)


if __name__ == "__main__":
    unittest.main()
