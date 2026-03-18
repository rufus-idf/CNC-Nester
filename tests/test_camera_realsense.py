import unittest

import numpy as np

from camera_realsense import estimate_plane_depth_mm, estimate_visible_area_mm


class CameraRealSenseTests(unittest.TestCase):
    def test_estimate_plane_depth_mm_uses_center_median(self):
        depth = np.zeros((10, 10), dtype=float)
        depth[3:7, 3:7] = 485.0

        plane_depth = estimate_plane_depth_mm(depth, sample_ratio=0.4)

        self.assertEqual(plane_depth, 485.0)

    def test_estimate_visible_area_mm_uses_intrinsics(self):
        intrinsics = {
            "width": 640,
            "height": 480,
            "fx": 466.0,
            "fy": 466.0,
        }

        visible = estimate_visible_area_mm(intrinsics, plane_depth_mm=485.0)

        self.assertAlmostEqual(visible["visible_width_mm"], 666.09, places=2)
        self.assertAlmostEqual(visible["visible_height_mm"], 499.57, places=2)


if __name__ == "__main__":
    unittest.main()
