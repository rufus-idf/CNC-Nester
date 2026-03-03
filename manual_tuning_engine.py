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
    sheet_w = float(layout["sheet_w"])
    sheet_h = float(layout["sheet_h"])

    estimated = ((sheet_w / step) + 1) * ((sheet_h / step) + 1)
    if estimated > 12000:
        scale = (estimated / 12000) ** 0.5
        step *= scale

    rows = []
    y = 0.0
    while y < sheet_h - 1e-9:
        x = 0.0
        while x < sheet_w - 1e-9:
            ok, reason = can_place_part_at(layout, sheet_index, part_id, x, y)
            rows.append({
                "x": float(round(x, 3)),
                "y": float(round(y, 3)),
                "x2": float(round(min(sheet_w, x + step), 3)),
                "y2": float(round(min(sheet_h, y + step), 3)),
                "is_legal": bool(ok),
                "reason": "Legal" if ok else reason,
            })
            x += step
        y += step
    return rows


def _cell_intersects(rect, x1, y1, x2, y2):
    return not (x2 <= rect["x"] or x1 >= rect["x2"] or y2 <= rect["y"] or y1 >= rect["y2"])


def compute_visual_guide_grid(layout, sheet_index, part_id, grid_step):
    sheet = layout["sheets"][sheet_index]
    step = max(1.0, float(grid_step))
    sheet_w = float(layout["sheet_w"])
    sheet_h = float(layout["sheet_h"])
    margin = float(layout["margin"])
    kerf = float(layout["kerf"])

    obstacles = []
    for p in sheet["parts"]:
        if p["id"] == part_id:
            continue
        obstacles.append(
            {
                "x": float(p["x"] - kerf),
                "y": float(p["y"] - kerf),
                "x2": float(p["x"] + p["w"] + kerf),
                "y2": float(p["y"] + p["h"] + kerf),
            }
        )

    rows = []
    y = 0.0
    while y < sheet_h - 1e-9:
        x = 0.0
        while x < sheet_w - 1e-9:
            x2 = min(sheet_w, x + step)
            y2 = min(sheet_h, y + step)

            in_margin = x >= margin and y >= margin and x2 <= sheet_w - margin and y2 <= sheet_h - margin
            blocked_obstacle = any(_cell_intersects(ob, x, y, x2, y2) for ob in obstacles)
            is_legal = in_margin and not blocked_obstacle

            reason = "Legal"
            if not in_margin:
                reason = "Out of sheet bounds (margin respected)."
            elif blocked_obstacle:
                reason = "Kerf clearance zone around another panel."

            rows.append(
                {
                    "x": float(round(x, 3)),
                    "y": float(round(y, 3)),
                    "x2": float(round(x2, 3)),
                    "y2": float(round(y2, 3)),
                    "is_legal": bool(is_legal),
                    "reason": reason,
                }
            )
            x += step
        y += step
    return rows
