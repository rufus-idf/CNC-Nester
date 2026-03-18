import io
import unittest

import numpy as np
from PIL import Image

from camera_calibration import calibrate_board, detect_calibration_dots, load_image_array


class CameraCalibrationTests(unittest.TestCase):
    def _build_test_image(self):
        image = np.full((400, 400, 3), 245, dtype=np.uint8)
        image[60:340, 40:340] = 180

        dot_centers = [
            (70, 310),
            (120, 310),
            (70, 360),
            (120, 360),
        ]
        for cx, cy in dot_centers:
            image[cy - 6:cy + 7, cx - 6:cx + 7] = 20

        return image

    def test_load_image_array_reads_jpeg_bytes(self):
        image = self._build_test_image()
        buffer = io.BytesIO()
        Image.fromarray(image).save(buffer, format="JPEG")

        loaded = load_image_array(buffer.getvalue())

        self.assertEqual(loaded.shape, image.shape)

    def test_detect_calibration_dots_finds_four_bottom_left_markers(self):
        image = self._build_test_image()

        dots = detect_calibration_dots(image)

        self.assertEqual(len(dots), 4)
        self.assertLess(dots[0][0], dots[1][0])
        self.assertLess(dots[0][1], dots[2][1])

    def test_calibrate_board_reports_expected_board_size(self):
        image = self._build_test_image()

        calibration = calibrate_board(image, dot_spacing_mm=100.0, background_threshold=20.0)

        self.assertAlmostEqual(calibration["board_width_mm"], 600.0, delta=20.0)
        self.assertAlmostEqual(calibration["board_height_mm"], 560.0, delta=20.0)
        self.assertEqual(len(calibration["board_corners_px"]), 4)


if __name__ == "__main__":
    unittest.main()
