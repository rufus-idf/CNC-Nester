TRUTHY_VALUES = {"1", "true", "t", "yes", "y", "on"}
FALSY_VALUES = {"0", "false", "f", "no", "n", "off", ""}


def coerce_bool(value):
    """Safely coerce mixed UI/import values to bool without bool('False') bugs."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in TRUTHY_VALUES:
            return True
        if normalized in FALSY_VALUES:
            return False
    return False


def _coerce_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value, default=1):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def normalize_panels(panels):
    normalized = []
    for p in panels:
        row = dict(p)
        row["Label"] = str(row.get("Label", "Part"))
        row["Width"] = _coerce_float(row.get("Width", 0.0), default=0.0)
        row["Length"] = _coerce_float(row.get("Length", 0.0), default=0.0)
        row["Qty"] = max(1, _coerce_int(row.get("Qty", 1), default=1))
        row["Grain?"] = coerce_bool(row.get("Grain?", False))
        row["Material"] = str(row.get("Material", "Manual"))
        normalized_row = {
            "Label": row["Label"],
            "Width": row["Width"],
            "Length": row["Length"],
            "Qty": row["Qty"],
            "Grain?": row["Grain?"],
            "Material": row["Material"],
        }
        if "Tooling" in row and row["Tooling"] is not None:
            normalized_row["Tooling"] = row["Tooling"]
        normalized.append(normalized_row)
    return normalized


def panels_to_editor_rows(panels):
    rows = []
    for panel in normalize_panels(panels):
        row = dict(panel)
        row["Swap L↔W"] = False
        rows.append(row)
    return rows


def apply_editor_rows(edited_rows):
    rows = []
    for raw in edited_rows:
        row = dict(raw)
        if coerce_bool(row.get("Swap L↔W", False)):
            width = row.get("Width", 0.0)
            row["Width"] = row.get("Length", 0.0)
            row["Length"] = width
        row["Swap L↔W"] = False
        rows.append(row)

    normalized_panels = normalize_panels(rows)
    return normalized_panels, panels_to_editor_rows(normalized_panels)
