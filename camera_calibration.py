from __future__ import annotations

from collections import deque
import io
from typing import Any

import numpy as np
from PIL import Image


def load_image_array(image_bytes: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(image_bytes)) as image:
        rgb = image.convert("RGB")
        return np.asarray(rgb, dtype=np.uint8)


def _connected_components(mask: np.ndarray, min_pixels: int = 1) -> list[dict[str, Any]]:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[dict[str, Any]] = []

    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue

            queue = deque([(x, y)])
            visited[y, x] = True
            pixels: list[tuple[int, int]] = []

            while queue:
                px, py = queue.popleft()
                pixels.append((px, py))

                for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                    if 0 <= nx < width and 0 <= ny < height and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((nx, ny))

            if len(pixels) < min_pixels:
                continue

            xs = np.array([p[0] for p in pixels], dtype=float)
            ys = np.array([p[1] for p in pixels], dtype=float)
            components.append({
                "pixels": pixels,
                "size": len(pixels),
                "centroid": [float(xs.mean()), float(ys.mean())],
                "bbox": [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())],
            })

    components.sort(key=lambda item: item["size"], reverse=True)
    return components


def detect_calibration_dots(image_rgb: np.ndarray, region_ratio: float = 0.45) -> list[list[float]]:
    height, width, _ = image_rgb.shape
    x_limit = max(1, int(width * region_ratio))
    y_start = max(0, int(height * (1.0 - region_ratio)))
    region = image_rgb[y_start:, :x_limit]

    gray = (0.299 * region[:, :, 0]) + (0.587 * region[:, :, 1]) + (0.114 * region[:, :, 2])
    threshold = min(float(np.percentile(gray, 8)) + 12.0, 140.0)
    dark_mask = gray <= threshold

    min_pixels = max(8, int((height * width) * 0.00002))
    components = _connected_components(dark_mask, min_pixels=min_pixels)
    if len(components) < 4:
        raise ValueError("Could not detect the four calibration dots. Try a clearer photo or darker dots.")

    selected = components[:4]
    centroids = []
    for component in selected:
        cx, cy = component["centroid"]
        centroids.append([cx, cy + y_start])

    centroids.sort(key=lambda point: (point[1], point[0]))
    top = sorted(centroids[:2], key=lambda point: point[0])
    bottom = sorted(centroids[2:], key=lambda point: point[0])
    top_left, top_right = top
    bottom_left, bottom_right = bottom
    return [top_left, top_right, bottom_left, bottom_right]


def _unit_vector(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length <= 1e-9:
        raise ValueError("Calibration dots are too close together to determine scale.")
    return vector / length


def calibrate_board(image_rgb: np.ndarray, dot_spacing_mm: float = 100.0, background_threshold: float = 30.0) -> dict[str, Any]:
    dots = detect_calibration_dots(image_rgb)
    top_left, top_right, bottom_left, bottom_right = [np.array(point, dtype=float) for point in dots]

    x_axis = _unit_vector(((top_right - top_left) + (bottom_right - bottom_left)) / 2.0)
    y_axis = _unit_vector(((top_left - bottom_left) + (top_right - bottom_right)) / 2.0)

    x_scale_px = float((np.linalg.norm(top_right - top_left) + np.linalg.norm(bottom_right - bottom_left)) / 2.0)
    y_scale_px = float((np.linalg.norm(bottom_left - top_left) + np.linalg.norm(bottom_right - top_right)) / 2.0)
    if x_scale_px <= 1e-9 or y_scale_px <= 1e-9:
        raise ValueError("Calibration square could not be measured.")

    mm_per_px_x = float(dot_spacing_mm) / x_scale_px
    mm_per_px_y = float(dot_spacing_mm) / y_scale_px

    border_thickness = max(4, int(min(image_rgb.shape[0], image_rgb.shape[1]) * 0.03))
    border_pixels = np.concatenate([
        image_rgb[:border_thickness, :, :].reshape(-1, 3),
        image_rgb[-border_thickness:, :, :].reshape(-1, 3),
        image_rgb[:, :border_thickness, :].reshape(-1, 3),
        image_rgb[:, -border_thickness:, :].reshape(-1, 3),
    ], axis=0)
    background_color = np.median(border_pixels, axis=0)
    color_distance = np.sqrt(np.sum((image_rgb.astype(float) - background_color) ** 2, axis=2))
    board_mask = color_distance >= float(background_threshold)

    min_pixels = max(100, int((image_rgb.shape[0] * image_rgb.shape[1]) * 0.002))
    components = _connected_components(board_mask, min_pixels=min_pixels)
    if not components:
        raise ValueError("Could not detect the board outline. Increase contrast with the background or adjust threshold.")

    board_component = components[0]
    points = np.array(board_component["pixels"], dtype=float)
    origin = bottom_left
    x_projection = (points - origin) @ x_axis
    y_projection = (points - origin) @ y_axis

    min_x, max_x = float(np.min(x_projection)), float(np.max(x_projection))
    min_y, max_y = float(np.min(y_projection)), float(np.max(y_projection))

    corners = [
        origin + (min_x * x_axis) + (min_y * y_axis),
        origin + (max_x * x_axis) + (min_y * y_axis),
        origin + (max_x * x_axis) + (max_y * y_axis),
        origin + (min_x * x_axis) + (max_y * y_axis),
    ]

    return {
        "dots": [[round(point[0], 2), round(point[1], 2)] for point in dots],
        "board_corners_px": [[round(float(p[0]), 2), round(float(p[1]), 2)] for p in corners],
        "board_width_mm": round((max_x - min_x) * mm_per_px_x, 2),
        "board_height_mm": round(abs(max_y - min_y) * mm_per_px_y, 2),
        "mm_per_px_x": round(mm_per_px_x, 6),
        "mm_per_px_y": round(mm_per_px_y, 6),
        "background_threshold": float(background_threshold),
        "dot_spacing_mm": float(dot_spacing_mm),
    }
