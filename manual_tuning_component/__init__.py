import json
from pathlib import Path

import streamlit.components.v1 as components

_FRONTEND_DIR = Path(__file__).parent / "frontend"
_component = components.declare_component("manual_tuning_canvas", path=str(_FRONTEND_DIR))


def manual_tuning_canvas(layout, selected_sheet_idx, selected_part_id, grid_rows, part_labels=None, snap_enabled=False, snap_size=10.0, show_snap_grid=False, align_snap_enabled=True, align_snap_tolerance=4.0, kerf_prompt_enabled=True, kerf_prompt_threshold=12.0, measure_enabled=False, measure_clear_seq=0, key=None):
    payload = {
        "layout": layout,
        "selected_sheet_idx": int(selected_sheet_idx),
        "selected_part_id": selected_part_id,
        "grid_rows": grid_rows,
        "part_labels": part_labels or {},
        "snap_enabled": bool(snap_enabled),
        "snap_size": float(snap_size),
        "show_snap_grid": bool(show_snap_grid),
        "align_snap_enabled": bool(align_snap_enabled),
        "align_snap_tolerance": float(align_snap_tolerance),
        "kerf_prompt_enabled": bool(kerf_prompt_enabled),
        "kerf_prompt_threshold": float(kerf_prompt_threshold),
        "measure_enabled": bool(measure_enabled),
        "measure_clear_seq": int(measure_clear_seq),
    }
    return _component(data=json.dumps(payload), key=key, default=None)
