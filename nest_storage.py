import json
from datetime import datetime

from nesting_engine import run_smart_nesting
from panel_utils import normalize_panels


def build_nest_payload(nest_name, sheet_w, sheet_h, margin, kerf, panels):
    normalized_panels = normalize_panels(panels)
    payload = {
        "version": 1,
        "nest_name": nest_name,
        "saved_at": datetime.utcnow().isoformat() + "Z",
        "settings": {
            "sheet_w": float(sheet_w),
            "sheet_h": float(sheet_h),
            "margin": float(margin),
            "kerf": float(kerf),
        },
        "panels": normalized_panels,
        "packed_sheets": [],
    }

    packer = run_smart_nesting(normalized_panels, sheet_w, sheet_h, margin, kerf)
    if packer:
        for sheet_index, bin in enumerate(packer):
            rects = []
            for rect in bin:
                rects.append({
                    "x": float(rect.x),
                    "y": float(rect.y),
                    "width": float(rect.width),
                    "height": float(rect.height),
                    "rid": str(rect.rid) if rect.rid else "Part",
                })
            payload["packed_sheets"].append({
                "sheet_index": sheet_index,
                "rects": rects,
            })
    return payload


def parse_nest_payload(payload):
    settings = payload.get("settings", {})
    return {
        "sheet_w": float(settings.get("sheet_w", 2440.0)),
        "sheet_h": float(settings.get("sheet_h", 1220.0)),
        "kerf": float(settings.get("kerf", 6.0)),
        "margin": float(settings.get("margin", 10.0)),
        "panels": normalize_panels(payload.get("panels", [])),
        "nest_name": str(payload.get("nest_name", "Untitled")),
    }


def payload_to_json(payload):
    return json.dumps(payload, indent=2)
