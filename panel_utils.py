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


def normalize_panels(panels):
    normalized = []
    for p in panels:
        row = dict(p)
        row["Grain?"] = coerce_bool(row.get("Grain?", False))
        normalized.append(row)
    return normalized
