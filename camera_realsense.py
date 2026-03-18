from __future__ import annotations

import importlib
from typing import Any

import numpy as np


def realsense_status() -> tuple[bool, str]:
    try:
        importlib.import_module("pyrealsense2")
    except ImportError:
        return False, "pyrealsense2 is not installed in this Python environment."
    return True, "Intel RealSense runtime available."


def capture_realsense_frame(width: int = 640, height: int = 480, fps: int = 30, warmup_frames: int = 15) -> dict[str, Any]:
    rs = importlib.import_module("pyrealsense2")
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
    config.enable_stream(rs.stream.color, width, height, rs.format.bgr8, fps)

    profile = pipeline.start(config)
    align = rs.align(rs.stream.color)

    try:
        frames = None
        for _ in range(max(1, warmup_frames)):
            frames = pipeline.wait_for_frames()
        assert frames is not None

        aligned_frames = align.process(frames)
        depth_frame = aligned_frames.get_depth_frame()
        color_frame = aligned_frames.get_color_frame()
        if not depth_frame or not color_frame:
            raise RuntimeError("Could not read both depth and color frames from the RealSense camera.")

        depth_image = np.asanyarray(depth_frame.get_data()).astype(np.float32)
        color_bgr = np.asanyarray(color_frame.get_data())
        color_rgb = color_bgr[:, :, ::-1].copy()

        intrinsics = color_frame.profile.as_video_stream_profile().get_intrinsics()
        depth_scale = float(profile.get_device().first_depth_sensor().get_depth_scale())
        depth_mm = depth_image * depth_scale * 1000.0

        return {
            "color_rgb": color_rgb,
            "depth_mm": depth_mm,
            "intrinsics": {
                "width": int(intrinsics.width),
                "height": int(intrinsics.height),
                "fx": float(intrinsics.fx),
                "fy": float(intrinsics.fy),
                "ppx": float(intrinsics.ppx),
                "ppy": float(intrinsics.ppy),
            },
            "depth_scale_mm": depth_scale * 1000.0,
        }
    finally:
        pipeline.stop()


def estimate_plane_depth_mm(depth_mm: np.ndarray, sample_ratio: float = 0.35) -> float:
    if depth_mm.size == 0:
        raise ValueError("Depth frame is empty.")

    height, width = depth_mm.shape
    crop_w = max(10, int(width * sample_ratio))
    crop_h = max(10, int(height * sample_ratio))
    x0 = max(0, (width - crop_w) // 2)
    y0 = max(0, (height - crop_h) // 2)
    sample = depth_mm[y0:y0 + crop_h, x0:x0 + crop_w]
    valid = sample[sample > 0.0]
    if valid.size == 0:
        raise ValueError("No valid depth pixels were found in the center sample area.")
    return float(np.median(valid))


def estimate_visible_area_mm(intrinsics: dict[str, float], plane_depth_mm: float) -> dict[str, float]:
    fx = float(intrinsics.get("fx", 0.0))
    fy = float(intrinsics.get("fy", 0.0))
    width_px = float(intrinsics.get("width", 0.0))
    height_px = float(intrinsics.get("height", 0.0))
    if fx <= 1e-6 or fy <= 1e-6 or width_px <= 0.0 or height_px <= 0.0:
        raise ValueError("Invalid camera intrinsics; cannot estimate visible area.")

    return {
        "visible_width_mm": round((plane_depth_mm * width_px) / fx, 2),
        "visible_height_mm": round((plane_depth_mm * height_px) / fy, 2),
    }
