from copy import deepcopy

from manual_layout import can_place


def find_part(layout, sheet_index, part_id):
    for part in layout["sheets"][sheet_index]["parts"]:
        if part["id"] == part_id:
            return part
    return None


def legal_bounds(layout, part):
    margin = float(layout["margin"])
    return {
        "x_min": margin,
        "y_min": margin,
        "x_max": float(layout["sheet_w"]) - margin - float(part["w"]),
        "y_max": float(layout["sheet_h"]) - margin - float(part["h"]),
    }


def can_place_part_at(layout, sheet_index, part_id, x, y):
    part = find_part(layout, sheet_index, part_id)
    if part is None:
        return False, "Part not found"
    sheet = layout["sheets"][sheet_index]
    rect = {"x": float(x), "y": float(y), "w": float(part["w"]), "h": float(part["h"])}
    return can_place(
        rect,
        sheet["parts"],
        part_id,
        float(layout["sheet_w"]),
        float(layout["sheet_h"]),
        float(layout["margin"]),
        float(layout["kerf"]),
    )


def move_part_to(layout, sheet_index, part_id, target_x, target_y):
    part = find_part(layout, sheet_index, part_id)
    if part is None:
        return layout, False, "Part not found"

    ok, msg = can_place_part_at(layout, sheet_index, part_id, target_x, target_y)
    if not ok:
        return layout, False, msg

    new_layout = deepcopy(layout)
    moving = find_part(new_layout, sheet_index, part_id)
    moving["x"] = float(target_x)
    moving["y"] = float(target_y)
    return new_layout, True, "Moved"


def compute_position_grid(layout, sheet_index, part_id, grid_step):
    part = find_part(layout, sheet_index, part_id)
    if part is None:
        return []

    step = max(1.0, float(grid_step))
    bounds = legal_bounds(layout, part)
    width = max(0.0, bounds["x_max"] - bounds["x_min"])
    height = max(0.0, bounds["y_max"] - bounds["y_min"])

    estimated = ((width / step) + 1) * ((height / step) + 1)
    if estimated > 12000:
        scale = (estimated / 12000) ** 0.5
        step *= scale

    rows = []
    y = bounds["y_min"]
    while y <= bounds["y_max"] + 1e-9:
        x = bounds["x_min"]
        while x <= bounds["x_max"] + 1e-9:
            ok, reason = can_place_part_at(layout, sheet_index, part_id, x, y)
            rows.append({
                "x": float(round(x, 3)),
                "y": float(round(y, 3)),
                "x2": float(round(x + step, 3)),
                "y2": float(round(y + step, 3)),
                "is_legal": bool(ok),
                "reason": "Legal" if ok else reason,
            })
            x += step
        y += step
    return rows
