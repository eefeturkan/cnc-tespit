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

    def _set_template(self, measurement_points, settings=None):
        self.engine.template = {
            "template_id": "TEST",
            "description": "test",
            "measurement_points": measurement_points,
            "settings": settings or {},
        }
        self.engine.measurement_points = measurement_points

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
            search_radius_px=0,
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

    def test_fixed_x_with_zero_search_radius_stays_in_local_window(self):
        profile = {
            "diameter_px": [10.0] * 100,
            "top_edge": [20.0] * 100,
            "bottom_edge": [30.0] * 100,
            "x_start": 0,
        }

        measured = self.engine.measure_diameter_at_fixed_x(
            40,
            profile,
            y_calibration=2.0,
            sample_width_px=3,
            x_mode="absolute_image",
            search_radius_px=0,
        )

        self.assertEqual(measured[1], 37)
        self.assertEqual(measured[2], 43)
        self.assertEqual(measured[5], 40)
        self.assertEqual(measured[7], 0)

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

    def test_local_y_correction_removes_position_dependent_scale_error(self):
        profile = {
            "diameter_px": (
                [0.0] * 10 +
                [100.0] * 30 +
                [0.0] * 10 +
                [200.0] * 30 +
                [0.0] * 10 +
                [300.0] * 30
            ),
            "top_edge": [20.0] * 120,
            "bottom_edge": [40.0] * 120,
            "x_start": 0,
        }

        points = [
            {
                "code": "03",
                "type": "diameter",
                "method": "fixed_x",
                "x_mode": "absolute_image",
                "x_abs": 20,
                "sample_width_px": 1,
                "search_radius_px": 0,
                "nominal_mm": 10.0,
                "lower_tol_mm": -0.1,
                "upper_tol_mm": 0.1,
                "description": "d03",
                "unit": "mm",
            },
            {
                "code": "06",
                "type": "diameter",
                "method": "fixed_x",
                "x_mode": "absolute_image",
                "x_abs": 55,
                "sample_width_px": 1,
                "search_radius_px": 0,
                "nominal_mm": 19.0,
                "lower_tol_mm": -0.1,
                "upper_tol_mm": 0.1,
                "description": "d06",
                "unit": "mm",
            },
            {
                "code": "08",
                "type": "diameter",
                "method": "fixed_x",
                "x_mode": "absolute_image",
                "x_abs": 95,
                "sample_width_px": 1,
                "search_radius_px": 0,
                "nominal_mm": 30.0,
                "lower_tol_mm": -0.1,
                "upper_tol_mm": 0.1,
                "description": "d08",
                "unit": "mm",
            },
        ]

        self._set_template(points, settings={"use_local_y_correction": True})
        results = self.engine.perform_measurements(
            profile,
            sections=[],
            y_calibration=10.0,
            x_calibration=10.0,
        )

        measured = {result.code: result.measured_mm for result in results}
        self.assertAlmostEqual(measured["03"], 10.0, places=4)
        self.assertAlmostEqual(measured["06"], 19.0, places=4)
        self.assertAlmostEqual(measured["08"], 30.0, places=4)

    def test_local_x_correction_removes_position_dependent_scale_error(self):
        profile = {
            "diameter_px": [10.0] * 2000,
            "top_edge": [20.0] * 2000,
            "bottom_edge": [30.0] * 2000,
            "x_start": 0,
        }

        points = [
            {
                "code": "17",
                "type": "length",
                "method": "fixed_range",
                "x_start_abs": 379,
                "x_end_abs": 603,
                "nominal_mm": 4.0,
                "lower_tol_mm": -0.1,
                "upper_tol_mm": 0.1,
                "description": "l17",
                "unit": "mm",
            },
            {
                "code": "21",
                "type": "length",
                "method": "fixed_range",
                "x_start_abs": 1,
                "x_end_abs": 1641,
                "nominal_mm": 30.0,
                "lower_tol_mm": -0.2,
                "upper_tol_mm": 0.2,
                "description": "l21",
                "unit": "mm",
            },
            {
                "code": "22",
                "type": "length",
                "method": "fixed_range",
                "x_start_abs": 604,
                "x_end_abs": 1641,
                "nominal_mm": 18.9,
                "lower_tol_mm": -0.1,
                "upper_tol_mm": 0.1,
                "description": "l22",
                "unit": "mm",
            },
            {
                "code": "24",
                "type": "length",
                "method": "fixed_range",
                "x_start_abs": 873,
                "x_end_abs": 1641,
                "nominal_mm": 14.0,
                "lower_tol_mm": -0.1,
                "upper_tol_mm": 0.1,
                "description": "l24",
                "unit": "mm",
            },
        ]

        settings = {
            "use_local_x_correction": True,
            "local_x_ppmm_points": [
                {"x_abs": 1.5, "pixels_per_mm_x": 53.3736762482},
                {"x_abs": 378.5, "pixels_per_mm_x": 53.3736762482},
                {"x_abs": 379.5, "pixels_per_mm_x": 56.0},
                {"x_abs": 603.5, "pixels_per_mm_x": 56.0},
                {"x_abs": 604.5, "pixels_per_mm_x": 54.8979591837},
                {"x_abs": 872.5, "pixels_per_mm_x": 54.8979591837},
                {"x_abs": 873.5, "pixels_per_mm_x": 54.8571428571},
                {"x_abs": 1640.5, "pixels_per_mm_x": 54.8571428571},
            ],
        }

        self._set_template(points, settings=settings)
        results = self.engine.perform_measurements(
            profile,
            sections=[],
            y_calibration=10.0,
            x_calibration=55.5,
        )

        measured = {result.code: result.measured_mm for result in results}
        self.assertAlmostEqual(measured["17"], 4.0, places=4)
        self.assertAlmostEqual(measured["21"], 30.0, places=4)
        self.assertAlmostEqual(measured["22"], 18.9, places=4)
        self.assertAlmostEqual(measured["24"], 14.0, places=4)


if __name__ == "__main__":
    unittest.main()
