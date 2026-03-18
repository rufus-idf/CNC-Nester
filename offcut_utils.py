from __future__ import annotations

import itertools


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
    sheet_w = _safe_float(sheet.get("sheet_w"), _safe_float(layout.get("sheet_w"), 0.0))
    sheet_h = _safe_float(sheet.get("sheet_h"), _safe_float(layout.get("sheet_h"), 0.0))

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


def _edge_lengths(vertices):
    if len(vertices) < 2:
        return []
    lengths = []
    for idx, current in enumerate(vertices):
        nxt = vertices[(idx + 1) % len(vertices)]
        dx = abs(nxt[0] - current[0])
        dy = abs(nxt[1] - current[1])
        lengths.append(max(dx, dy))
    return lengths


def _polygon_area(vertices):
    if len(vertices) < 3:
        return 0.0
    area = 0.0
    for idx, current in enumerate(vertices):
        nxt = vertices[(idx + 1) % len(vertices)]
        area += (current[0] * nxt[1]) - (nxt[0] * current[1])
    return abs(area) / 2.0


def _classify_orthogonal_polygon(vertices):
    vertex_count = len(vertices)
    if vertex_count < 4 or (vertex_count % 2) != 0:
        return {
            "vertex_count": vertex_count,
            "rectangle_count": 0,
            "l_shape_count": 0,
            "l_rect_count": 0,
            "c_shape_count": 0,
            "c_rect_count": 0,
        }

    rectangle_count = max(0, (vertex_count // 2) - 1)
    return {
        "vertex_count": vertex_count,
        "rectangle_count": rectangle_count,
        "l_shape_count": rectangle_count // 2,
        "l_rect_count": rectangle_count % 2,
        "c_shape_count": rectangle_count // 3,
        "c_rect_count": rectangle_count % 3,
    }


def _normalize_polygon_vertices(vertices, min_edge):
    if len(vertices) < 3:
        return vertices

    def _collapse_axis(values):
        sorted_values = sorted(set(values))
        groups = [[sorted_values[0]]]
        for value in sorted_values[1:]:
            if value - groups[-1][-1] < min_edge:
                groups[-1].append(value)
            else:
                groups.append([value])

        mapping = {}
        for group in groups:
            representative = group[0]
            for value in group:
                mapping[value] = representative
        return mapping

    x_mapping = _collapse_axis([p[0] for p in vertices])
    y_mapping = _collapse_axis([p[1] for p in vertices])

    normalized = [[x_mapping[p[0]], y_mapping[p[1]]] for p in vertices]

    deduped = []
    for point in normalized:
        if not deduped or deduped[-1] != point:
            deduped.append(point)
    if len(deduped) > 1 and deduped[0] == deduped[-1]:
        deduped.pop()

    changed = True
    while changed and len(deduped) >= 3:
        changed = False
        for idx in range(len(deduped)):
            prev_point = deduped[idx - 1]
            curr_point = deduped[idx]
            next_point = deduped[(idx + 1) % len(deduped)]
            if (
                (prev_point[0] == curr_point[0] == next_point[0])
                or (prev_point[1] == curr_point[1] == next_point[1])
            ):
                deduped.pop(idx)
                changed = True
                break

    return deduped


def _point_in_polygon(x, y, vertices):
    inside = False
    j = len(vertices) - 1
    for i in range(len(vertices)):
        xi, yi = vertices[i]
        xj, yj = vertices[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) if abs(yj - yi) > 1e-9 else 1e-9) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _polygon_within_rect_union(vertices, rects):
    if len(vertices) < 3:
        return False
    xs = sorted({p[0] for p in vertices} | {r['x'] for r in rects} | {r['x'] + r['w'] for r in rects})
    ys = sorted({p[1] for p in vertices} | {r['y'] for r in rects} | {r['y'] + r['h'] for r in rects})
    if len(xs) < 2 or len(ys) < 2:
        return False

    for ix in range(len(xs) - 1):
        cx = (xs[ix] + xs[ix + 1]) / 2.0
        for iy in range(len(ys) - 1):
            cy = (ys[iy] + ys[iy + 1]) / 2.0
            in_poly = _point_in_polygon(cx, cy, vertices)
            if not in_poly:
                continue
            in_union = any(
                (r['x'] <= cx <= r['x'] + r['w']) and (r['y'] <= cy <= r['y'] + r['h'])
                for r in rects
            )
            if not in_union:
                return False
    return True


def _is_connected_rect_group(rects):
    if not rects:
        return False
    seen = {0}
    stack = [0]
    while stack:
        current = stack.pop()
        for idx in range(len(rects)):
            if idx in seen:
                continue
            if _touches(rects[current], rects[idx]):
                seen.add(idx)
                stack.append(idx)
    return len(seen) == len(rects)


def _connected_rect_components(rects):
    components = []
    visited = set()
    for start_idx in range(len(rects)):
        if start_idx in visited:
            continue
        stack = [start_idx]
        visited.add(start_idx)
        component_indices = []
        while stack:
            current = stack.pop()
            component_indices.append(current)
            for idx in range(len(rects)):
                if idx in visited:
                    continue
                if _touches(rects[current], rects[idx]):
                    visited.add(idx)
                    stack.append(idx)
        components.append(component_indices)
    return components


def _largest_rect_in_union(rects):
    if not rects:
        return None

    xs = sorted({r['x'] for r in rects} | {r['x'] + r['w'] for r in rects})
    ys = sorted({r['y'] for r in rects} | {r['y'] + r['h'] for r in rects})
    if len(xs) < 2 or len(ys) < 2:
        return None

    occupied = set()
    for ix in range(len(xs) - 1):
        cx = (xs[ix] + xs[ix + 1]) / 2.0
        for iy in range(len(ys) - 1):
            cy = (ys[iy] + ys[iy + 1]) / 2.0
            if any((r['x'] <= cx <= r['x'] + r['w']) and (r['y'] <= cy <= r['y'] + r['h']) for r in rects):
                occupied.add((ix, iy))

    best = None
    best_area = 0.0
    for ix1 in range(len(xs) - 1):
        for ix2 in range(ix1 + 1, len(xs)):
            width = xs[ix2] - xs[ix1]
            if width <= 0:
                continue
            for iy1 in range(len(ys) - 1):
                for iy2 in range(iy1 + 1, len(ys)):
                    height = ys[iy2] - ys[iy1]
                    if height <= 0:
                        continue
                    all_filled = True
                    for ix in range(ix1, ix2):
                        for iy in range(iy1, iy2):
                            if (ix, iy) not in occupied:
                                all_filled = False
                                break
                        if not all_filled:
                            break
                    if not all_filled:
                        continue
                    area = width * height
                    if area > best_area:
                        best_area = area
                        best = {'x': xs[ix1], 'y': ys[iy1], 'w': width, 'h': height}

    return best


def calculate_l_mix_offcuts(layout, sheet, min_width=120.0, min_height=120.0, min_area=25000.0):
    usable, parts = _usable_sheet_and_parts(layout, sheet)
    free_rects = _compute_free_rects(usable, parts)

    l_shapes = []
    rectangles = []
    for component_indices in _connected_rect_components(free_rects):
        component_rects = [free_rects[idx] for idx in component_indices]
        component_polygon = _normalize_polygon_vertices(_polygon_from_rects(component_rects), min_height)
        component_classification = _classify_orthogonal_polygon(component_polygon)

        l_candidates = []
        seen_signatures = set()
        max_combo_size = min(5, len(component_rects))
        for combo_size in range(2, max_combo_size + 1):
            for local_indices in itertools.combinations(range(len(component_rects)), combo_size):
                rect_group = [component_rects[idx] for idx in local_indices]
                if not _is_connected_rect_group(rect_group):
                    continue

                raw_vertices = _polygon_from_rects(rect_group)
                if len(raw_vertices) < 6:
                    continue
                vertices = _normalize_polygon_vertices(raw_vertices, min_height)
                if not _is_l_shape(vertices):
                    continue
                if any(edge < min_height for edge in _edge_lengths(vertices)):
                    continue

                union_area = sum(rect["w"] * rect["h"] for rect in rect_group)
                polygon_area = _polygon_area(vertices)
                if polygon_area > (union_area + 1e-6):
                    continue
                if not _polygon_within_rect_union(vertices, rect_group):
                    continue

                xs = [v[0] for v in vertices]
                ys = [v[1] for v in vertices]
                min_x, max_x = min(xs), max(xs)
                min_y, max_y = min(ys), max(ys)
                width = max_x - min_x
                height = max_y - min_y
                area = union_area
                if width < min_width or height < min_height or area < min_area:
                    continue

                signature = tuple(tuple(v) for v in vertices)
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)

                l_candidates.append((area, set(local_indices), {
                    "shape_type": "L",
                    "x": round(min_x, 2),
                    "y": round(min_y, 2),
                    "width": round(width, 2),
                    "height": round(height, 2),
                    "area": round(area, 2),
                    "vertices": vertices,
                    "source_vertex_count": component_classification["vertex_count"],
                }))

        l_candidates.sort(key=lambda item: item[0], reverse=True)
        used = set()
        selected_l_count = 0
        for _, candidate_indices, candidate in l_candidates:
            if selected_l_count >= component_classification["l_shape_count"]:
                break
            if used.intersection(candidate_indices):
                continue
            used.update(candidate_indices)
            selected_l_count += 1
            l_shapes.append(candidate)

        remaining_rects = [r for idx, r in enumerate(component_rects) if idx not in used]
        if not remaining_rects:
            continue

        for remaining_component_indices in _connected_rect_components(remaining_rects):
            remaining_component_rects = [remaining_rects[idx] for idx in remaining_component_indices]
            remaining_polygon = _normalize_polygon_vertices(_polygon_from_rects(remaining_component_rects), min_height)
            remaining_classification = _classify_orthogonal_polygon(remaining_polygon)
            largest = _largest_rect_in_union(remaining_component_rects)
            if not largest:
                continue
            area = largest["w"] * largest["h"]
            if (
                remaining_classification["rectangle_count"] > 0
                and largest["w"] >= min_width
                and largest["h"] >= min_height
                and area >= min_area
            ):
                rectangles.append({
                    "shape_type": "RECT",
                    "x": round(largest["x"], 2),
                    "y": round(largest["y"], 2),
                    "width": round(largest["w"], 2),
                    "height": round(largest["h"], 2),
                    "area": round(area, 2),
                    "source_vertex_count": remaining_classification["vertex_count"],
                })

    result = l_shapes + rectangles
    result.sort(key=lambda r: r["area"], reverse=True)
    return result
