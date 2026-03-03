import json
from pathlib import Path

import streamlit.components.v1 as components

_FRONTEND_DIR = Path(__file__).parent / "frontend"
_component = components.declare_component("manual_tuning_canvas", path=str(_FRONTEND_DIR))


def manual_tuning_canvas(layout, selected_sheet_idx, selected_part_id, grid_rows, snap_enabled=False, snap_size=10.0, show_snap_grid=False, key=None):
    payload = {
        "layout": layout,
        "selected_sheet_idx": int(selected_sheet_idx),
        "selected_part_id": selected_part_id,
        "grid_rows": grid_rows,
        "snap_enabled": bool(snap_enabled),
        "snap_size": float(snap_size),
        "show_snap_grid": bool(show_snap_grid),
    }
    return _component(data=json.dumps(payload), key=key, default=None)
