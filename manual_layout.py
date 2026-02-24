from copy import deepcopy


def _too_close(a, b, clearance):
    return not (
        a["x"] + a["w"] + clearance <= b["x"]
        or b["x"] + b["w"] + clearance <= a["x"]
        or a["y"] + a["h"] + clearance <= b["y"]
        or b["y"] + b["h"] + clearance <= a["y"]
    )


def _in_bounds(rect, sheet_w, sheet_h, margin):
    return (
        rect["x"] >= margin
        and rect["y"] >= margin
        and rect["x"] + rect["w"] <= sheet_w - margin
        and rect["y"] + rect["h"] <= sheet_h - margin
    )


def can_place(rect, parts, part_id, sheet_w, sheet_h, margin, kerf):
    if not _in_bounds(rect, sheet_w, sheet_h, margin):
        return False, "Out of sheet bounds (margin respected)."

    for p in parts:
        if p["id"] == part_id:
            continue
        other = {"x": p["x"], "y": p["y"], "w": p["w"], "h": p["h"]}
        if _too_close(rect, other, kerf):
            return False, f"Too close to {p['rid']} (kerf clearance violation)."
    return True, "OK"


def initialize_layout_from_packer(packer, margin, kerf, sheet_w, sheet_h):
    sheets = []
    for sheet_index, bin in enumerate(packer):
        parts = []
        for i, rect in enumerate(bin):
            parts.append(
                {
                    "id": f"S{sheet_index+1}-P{i+1}",
                    "rid": str(rect.rid) if rect.rid else f"Part {i+1}",
                    "x": float(rect.x + margin),
                    "y": float(rect.y + margin),
                    "w": float(rect.width - kerf),
                    "h": float(rect.height - kerf),
                    "rotated": False,
                }
            )
        sheets.append({"sheet_index": sheet_index, "parts": parts})

    return {
        "sheet_w": float(sheet_w),
        "sheet_h": float(sheet_h),
        "margin": float(margin),
        "kerf": float(kerf),
        "sheets": sheets,
    }


def move_part(layout, sheet_index, part_id, dx, dy):
    new_layout = deepcopy(layout)
    sheet = new_layout["sheets"][sheet_index]
    for p in sheet["parts"]:
        if p["id"] == part_id:
            candidate = {"x": p["x"] + dx, "y": p["y"] + dy, "w": p["w"], "h": p["h"]}
            ok, msg = can_place(
                candidate,
                sheet["parts"],
                part_id,
                new_layout["sheet_w"],
                new_layout["sheet_h"],
                new_layout["margin"],
                new_layout["kerf"],
            )
            if not ok:
                return layout, False, msg
            p["x"] = candidate["x"]
            p["y"] = candidate["y"]
            return new_layout, True, "Moved"
    return layout, False, "Part not found"


def rotate_part_90(layout, sheet_index, part_id):
    new_layout = deepcopy(layout)
    sheet = new_layout["sheets"][sheet_index]
    for p in sheet["parts"]:
        if p["id"] == part_id:
            candidate = {"x": p["x"], "y": p["y"], "w": p["h"], "h": p["w"]}
            ok, msg = can_place(
                candidate,
                sheet["parts"],
                part_id,
                new_layout["sheet_w"],
                new_layout["sheet_h"],
                new_layout["margin"],
                new_layout["kerf"],
            )
            if not ok:
                return layout, False, msg
            p["w"], p["h"] = p["h"], p["w"]
            p["rotated"] = not p.get("rotated", False)
            return new_layout, True, "Rotated"
    return layout, False, "Part not found"
