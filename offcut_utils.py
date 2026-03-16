from __future__ import annotations


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _intersects(a, b):
    return not (
        a["x"] + a["w"] <= b["x"]
        or b["x"] + b["w"] <= a["x"]
        or a["y"] + a["h"] <= b["y"]
        or b["y"] + b["h"] <= a["y"]
    )


def _rect_contained(inner, outer, tol=1e-6):
    return (
        inner["x"] >= outer["x"] - tol
        and inner["y"] >= outer["y"] - tol
        and inner["x"] + inner["w"] <= outer["x"] + outer["w"] + tol
        and inner["y"] + inner["h"] <= outer["y"] + outer["h"] + tol
    )


def _subtract_rect(container, cut):
    if not _intersects(container, cut):
        return [container]

    cx, cy, cw, ch = container["x"], container["y"], container["w"], container["h"]
    kx, ky, kw, kh = cut["x"], cut["y"], cut["w"], cut["h"]

    ix1 = max(cx, kx)
    iy1 = max(cy, ky)
    ix2 = min(cx + cw, kx + kw)
    iy2 = min(cy + ch, ky + kh)

    if ix2 <= ix1 or iy2 <= iy1:
        return [container]

    pieces = []

    if iy2 < cy + ch:
        pieces.append({"x": cx, "y": iy2, "w": cw, "h": (cy + ch) - iy2})
    if iy1 > cy:
        pieces.append({"x": cx, "y": cy, "w": cw, "h": iy1 - cy})
    if ix1 > cx:
        pieces.append({"x": cx, "y": iy1, "w": ix1 - cx, "h": iy2 - iy1})
    if ix2 < cx + cw:
        pieces.append({"x": ix2, "y": iy1, "w": (cx + cw) - ix2, "h": iy2 - iy1})

    return [p for p in pieces if p["w"] > 1e-6 and p["h"] > 1e-6]


def _prune_contained(rects):
    kept = []
    for i, rect in enumerate(rects):
        contained = False
        for j, other in enumerate(rects):
            if i == j:
                continue
            if _rect_contained(rect, other):
                contained = True
                break
        if not contained:
            kept.append(rect)
    return kept




def _overlap_area(a, b):
    ix1 = max(a["x"], b["x"])
    iy1 = max(a["y"], b["y"])
    ix2 = min(a["x"] + a["w"], b["x"] + b["w"])
    iy2 = min(a["y"] + a["h"], b["y"] + b["h"])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return (ix2 - ix1) * (iy2 - iy1)


def _usable_sheet_and_parts(layout, sheet):
    margin = _safe_float(layout.get("margin"), 0.0)
    sheet_w = _safe_float(layout.get("sheet_w"), 0.0)
    sheet_h = _safe_float(layout.get("sheet_h"), 0.0)

    usable = {
        "x": margin,
        "y": margin,
        "w": max(0.0, sheet_w - (2.0 * margin)),
        "h": max(0.0, sheet_h - (2.0 * margin)),
    }

    parts = []
    for part in sheet.get("parts", []):
        px = max(usable["x"], _safe_float(part.get("x"), 0.0))
        py = max(usable["y"], _safe_float(part.get("y"), 0.0))
        pw = _safe_float(part.get("w"), 0.0)
        ph = _safe_float(part.get("h"), 0.0)
        px2 = min(usable["x"] + usable["w"], px + pw)
        py2 = min(usable["y"] + usable["h"], py + ph)
        cw = max(0.0, px2 - px)
        ch = max(0.0, py2 - py)
        if cw > 0 and ch > 0:
            parts.append({"x": px, "y": py, "w": cw, "h": ch})

    parts.sort(key=lambda r: (r["y"], r["x"]))
    return usable, parts


def _compute_free_rects(usable, parts):
    free_rects = [usable]
    for part in parts:
        next_rects = []
        for free_rect in free_rects:
            next_rects.extend(_subtract_rect(free_rect, part))
        free_rects = _prune_contained(next_rects)
    return free_rects


def calculate_sheet_offcuts(layout, sheet, min_width=120.0, min_height=120.0, min_area=25000.0):
    usable, parts = _usable_sheet_and_parts(layout, sheet)
    interior_area = usable["w"] * usable["h"]

    free_rects = _compute_free_rects(usable, parts)

    used_area = sum(p["w"] * p["h"] for p in parts)
    waste_area = sum(r["w"] * r["h"] for r in free_rects)

    reusable = [
        {
            "x": round(r["x"], 2),
            "y": round(r["y"], 2),
            "width": round(r["w"], 2),
            "height": round(r["h"], 2),
            "area": round(r["w"] * r["h"], 2),
        }
        for r in free_rects
        if r["w"] >= min_width and r["h"] >= min_height and (r["w"] * r["h"]) >= min_area
    ]
    reusable.sort(key=lambda r: r["area"], reverse=True)

    return {
        "interior_area": round(interior_area, 2),
        "used_area": round(used_area, 2),
        "waste_area": round(waste_area, 2),
        "utilization_pct": round((used_area / interior_area * 100.0), 2) if interior_area > 0 else 0.0,
        "reusable_offcuts": reusable,
    }


def build_sheet_usage_heatmap(layout, sheet, cell_size=100.0):
    usable, parts = _usable_sheet_and_parts(layout, sheet)
    if usable["w"] <= 0 or usable["h"] <= 0:
        return []

    size = max(10.0, _safe_float(cell_size, 100.0))
    x_start = usable["x"]
    y_start = usable["y"]
    x_end = usable["x"] + usable["w"]
    y_end = usable["y"] + usable["h"]

    cells = []
    y = y_start
    row_idx = 0
    while y < y_end - 1e-6:
        x = x_start
        col_idx = 0
        cell_h = min(size, y_end - y)
        while x < x_end - 1e-6:
            cell_w = min(size, x_end - x)
            cell = {"x": x, "y": y, "w": cell_w, "h": cell_h}
            cell_area = cell_w * cell_h
            used_area = sum(_overlap_area(cell, part) for part in parts)
            usage_ratio = (used_area / cell_area) if cell_area > 0 else 0.0
            cells.append({
                "x": round(x, 2),
                "y": round(y, 2),
                "x2": round(x + cell_w, 2),
                "y2": round(y + cell_h, 2),
                "cell_col": col_idx,
                "cell_row": row_idx,
                "used_area": round(used_area, 2),
                "cell_area": round(cell_area, 2),
                "usage_ratio": round(usage_ratio, 4),
                "usage_pct": round(usage_ratio * 100.0, 2),
            })
            x += size
            col_idx += 1
        y += size
        row_idx += 1

    return cells


def build_sheet_offcut_preview(layout, sheet):
    usable, parts = _usable_sheet_and_parts(layout, sheet)

    free_rects = _compute_free_rects(usable, parts)

    return {
        "usable": {
            "x": round(usable["x"], 2),
            "y": round(usable["y"], 2),
            "width": round(usable["w"], 2),
            "height": round(usable["h"], 2),
        },
        "parts": [
            {
                "x": round(p["x"], 2),
                "y": round(p["y"], 2),
                "width": round(p["w"], 2),
                "height": round(p["h"], 2),
            }
            for p in parts
        ],
        "free_regions": [
            {
                "x": round(r["x"], 2),
                "y": round(r["y"], 2),
                "width": round(r["w"], 2),
                "height": round(r["h"], 2),
                "area": round(r["w"] * r["h"], 2),
            }
            for r in free_rects
        ],
    }


def _touches(a, b, tol=1e-6):
    vertical_touch = abs((a["x"] + a["w"]) - b["x"]) <= tol or abs((b["x"] + b["w"]) - a["x"]) <= tol
    vertical_overlap = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])

    horizontal_touch = abs((a["y"] + a["h"]) - b["y"]) <= tol or abs((b["y"] + b["h"]) - a["y"]) <= tol
    horizontal_overlap = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])

    return (vertical_touch and vertical_overlap > tol) or (horizontal_touch and horizontal_overlap > tol)


def _polygon_from_rects(rects):
    xs = sorted({r["x"] for r in rects} | {r["x"] + r["w"] for r in rects})
    ys = sorted({r["y"] for r in rects} | {r["y"] + r["h"] for r in rects})
    if len(xs) < 2 or len(ys) < 2:
        return []

    occupied = set()
    for ix in range(len(xs) - 1):
        cx = (xs[ix] + xs[ix + 1]) / 2.0
        for iy in range(len(ys) - 1):
            cy = (ys[iy] + ys[iy + 1]) / 2.0
            if any((r["x"] <= cx <= r["x"] + r["w"]) and (r["y"] <= cy <= r["y"] + r["h"]) for r in rects):
                occupied.add((ix, iy))

    if not occupied:
        return []

    edges = set()

    def toggle_edge(p1, p2):
        key = (p1, p2) if p1 <= p2 else (p2, p1)
        if key in edges:
            edges.remove(key)
        else:
            edges.add(key)

    for ix, iy in occupied:
        x1, x2 = xs[ix], xs[ix + 1]
        y1, y2 = ys[iy], ys[iy + 1]
        toggle_edge((x1, y1), (x2, y1))
        toggle_edge((x2, y1), (x2, y2))
        toggle_edge((x2, y2), (x1, y2))
        toggle_edge((x1, y2), (x1, y1))

    if not edges:
        return []

    adjacency = {}
    for p1, p2 in edges:
        adjacency.setdefault(p1, []).append(p2)
        adjacency.setdefault(p2, []).append(p1)

    start = min(adjacency.keys(), key=lambda p: (p[1], p[0]))
    polygon = [start]
    prev = None
    current = start
    max_steps = len(edges) + 5
    for _ in range(max_steps):
        neighbors = adjacency.get(current, [])
        nxt = neighbors[0] if len(neighbors) == 1 else (neighbors[1] if neighbors[0] == prev else neighbors[0])
        if nxt == start:
            break
        polygon.append(nxt)
        prev, current = current, nxt

    rounded = [[round(p[0], 2), round(p[1], 2)] for p in polygon]
    if len(rounded) < 3:
        return rounded

    simplified = []
    n = len(rounded)
    for i in range(n):
        prev_p = rounded[i - 1]
        curr_p = rounded[i]
        next_p = rounded[(i + 1) % n]

        prev_vec = (curr_p[0] - prev_p[0], curr_p[1] - prev_p[1])
        next_vec = (next_p[0] - curr_p[0], next_p[1] - curr_p[1])
        cross = (prev_vec[0] * next_vec[1]) - (prev_vec[1] * next_vec[0])
        if abs(cross) > 1e-6:
            simplified.append(curr_p)

    return simplified


def _is_l_shape(vertices):
    if len(vertices) != 6:
        return False
    xs = [p[0] for p in vertices]
    ys = [p[1] for p in vertices]
    return len(set(xs)) == 3 and len(set(ys)) == 3


def calculate_l_mix_offcuts(layout, sheet, min_width=120.0, min_height=120.0, min_area=25000.0):
    usable, parts = _usable_sheet_and_parts(layout, sheet)
    free_rects = _compute_free_rects(usable, parts)

    pair_candidates = []
    for i in range(len(free_rects)):
        for j in range(i + 1, len(free_rects)):
            a = free_rects[i]
            b = free_rects[j]
            if not _touches(a, b):
                continue
            vertices = _polygon_from_rects([a, b])
            if not _is_l_shape(vertices):
                continue
            xs = [v[0] for v in vertices]
            ys = [v[1] for v in vertices]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            width = max_x - min_x
            height = max_y - min_y
            area = (a["w"] * a["h"]) + (b["w"] * b["h"])
            if width < min_width or height < min_height or area < min_area:
                continue
            pair_candidates.append((area, i, j, {
                "shape_type": "L",
                "x": round(min_x, 2),
                "y": round(min_y, 2),
                "width": round(width, 2),
                "height": round(height, 2),
                "area": round(area, 2),
                "vertices": vertices,
            }))

    pair_candidates.sort(key=lambda x: x[0], reverse=True)
    used = set()
    l_shapes = []
    for _, i, j, candidate in pair_candidates:
        if i in used or j in used:
            continue
        used.add(i)
        used.add(j)
        l_shapes.append(candidate)

    rectangles = []
    for idx, r in enumerate(free_rects):
        if idx in used:
            continue
        area = r["w"] * r["h"]
        if r["w"] >= min_width and r["h"] >= min_height and area >= min_area:
            rectangles.append({
                "shape_type": "RECT",
                "x": round(r["x"], 2),
                "y": round(r["y"], 2),
                "width": round(r["w"], 2),
                "height": round(r["h"], 2),
                "area": round(area, 2),
            })

    result = l_shapes + rectangles
    result.sort(key=lambda r: r["area"], reverse=True)
    return result
