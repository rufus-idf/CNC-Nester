# Offcut Stock in Google Sheets: Shape-Aware Data Model and App Flow

This document proposes a practical way to store offcuts in Google Sheets so the app can:

1. Save offcuts from a completed nest.
2. Keep true shape information (rectangle, L, C, polygon).
3. Let users select offcuts from stock and view shape + size before reuse.

## 1) Spreadsheet Layout

Use one Google Spreadsheet with **four tabs**.

## 1.1 `offcut_inventory` (master stock list)
One row per offcut item in stock.

Required columns:

- `offcut_id` (string, unique; e.g. `OC-2026-000123`)
- `status` (`IN_STOCK`, `RESERVED`, `USED`, `SCRAPPED`)
- `material` (e.g. `MDF`, `Birch Ply`)
- `thickness_mm` (number)
- `grade` (optional)
- `sheet_origin_job` (job / nest identifier)
- `sheet_origin_index` (number)
- `captured_at_utc` (ISO timestamp)
- `shape_type` (`RECT`, `L`, `C`, `POLYGON`)
- `area_mm2` (number)
- `bbox_w_mm` (number)
- `bbox_h_mm` (number)
- `min_internal_width_mm` (number; useful for non-rectangles)
- `usable_score` (0..100 optional heuristic)
- `location` (rack/bin label)
- `preview_ref` (pointer to preview entry)
- `shape_ref` (pointer to geometry row)
- `notes`

Why: keeps filtering/search very fast and gives enough dimensions for table-style stock views.

## 1.2 `offcut_shapes` (geometry payload)
One row per offcut geometry.

Required columns:

- `shape_ref` (unique)
- `offcut_id`
- `coord_unit` (`mm`)
- `bbox_x_mm`
- `bbox_y_mm`
- `vertices_json` (JSON array of points in order)
- `holes_json` (JSON array for inner voids; empty `[]` if none)
- `version`

Recommended JSON structure:

- `vertices_json`: `[[0,0],[800,0],[800,200],[300,200],[300,700],[0,700]]`
- `holes_json`: `[]`

Why: this preserves true shape (L/C/other) and is app-renderable.

## 1.3 `offcut_events` (audit trail)
Append-only log of stock actions.

Columns:

- `event_id`
- `offcut_id`
- `event_type` (`CREATED`, `RESERVED`, `RELEASED`, `CONSUMED`, `SCRAPPED`, `EDITED`)
- `event_at_utc`
- `job_id`
- `user`
- `payload_json`

Why: supports traceability and rollback-style diagnostics.

## 1.4 `offcut_previews` (optional lightweight render metadata)
Columns:

- `preview_ref`
- `offcut_id`
- `svg_path_data` (or compact polyline)
- `scale_hint`
- `updated_at_utc`

Why: app can render quickly without parsing full geometry every time.

---

## 2) Shape + Size Representation Rules

To keep this robust:

- Store **true boundary vertices** for every offcut in `offcut_shapes`.
- Also store **derived dimensions** in `offcut_inventory`:
  - area,
  - bounding box width/height,
  - min internal width.

This gives both:

- engineering truth (geometry), and
- operator usability (quick dimensions/filtering).

For `RECT`, vertices still get stored (4-point polygon) so all shapes are handled consistently.

---

## 3) App Workflow (No code yet)

## 3.1 Save offcuts after nesting
When a nest completes:

1. Build offcut regions (including non-rectangles).
2. For each offcut passing your keep rules:
   - create `offcut_id`,
   - write one row to `offcut_inventory`,
   - write one row to `offcut_shapes`,
   - append `CREATED` event in `offcut_events`.

## 3.2 Stock browser in app
The app reads `offcut_inventory` for fast list views with filters:

- material,
- thickness,
- minimum area,
- minimum bbox size,
- shape type,
- status.

On selection:

- fetch matching `offcut_shapes` row,
- render the polygon preview,
- show key dimensions/metadata.

## 3.3 Consume or reserve offcuts
When user chooses an offcut for a job:

- set `status` to `RESERVED` or `USED`,
- append corresponding row to `offcut_events`.

This avoids deleting data and preserves stock history.

---

## 4) Suggested Minimum Columns for Immediate Start

If you want to start lean, begin with these:

- `offcut_inventory`: `offcut_id`, `status`, `material`, `thickness_mm`, `shape_type`, `area_mm2`, `bbox_w_mm`, `bbox_h_mm`, `shape_ref`, `captured_at_utc`
- `offcut_shapes`: `shape_ref`, `offcut_id`, `vertices_json`, `holes_json`

Then add events/location once workflow stabilizes.

---

## 5) Data Validation in Google Sheets

Recommended validations:

- `status` dropdown: `IN_STOCK, RESERVED, USED, SCRAPPED`
- `shape_type` dropdown: `RECT, L, C, POLYGON`
- Numeric columns must be `>= 0`
- `offcut_id` unique (enforced by app before write)

Also freeze header row and use filter views for shop-floor operators.

---

## 6) Practical Notes

- Google Sheets is good for moderate volume and visibility.
- For high write rates / concurrent edits, add conflict checks (row version or last-updated timestamp).
- Keep geometry in JSON to avoid column explosion and preserve arbitrary shape complexity.
- Precompute lightweight preview data for smoother UI list browsing.

---

## 7) Outcome

With this format, the app can reliably:

- save offcuts from nests,
- retain true L/C/polygon shape,
- show shape + dimensions in stock selection,
- track lifecycle from creation to consumption.

---

## 8) Concrete Example: Saving an L-Shaped Offcut

Example L offcut dimensions (in mm):

- Overall bounding box: `800 x 700`
- Shape footprint points (clockwise):
  `[[0,0],[800,0],[800,200],[300,200],[300,700],[0,700]]`

This represents an L profile where the top-right inner corner is cut out.

### 8.1 Row in `offcut_inventory`

| offcut_id | status | material | thickness_mm | sheet_origin_job | sheet_origin_index | captured_at_utc | shape_type | area_mm2 | bbox_w_mm | bbox_h_mm | min_internal_width_mm | location | preview_ref | shape_ref |
|---|---|---|---:|---|---:|---|---|---:|---:|---:|---:|---|---|---|
| OC-2026-000123 | IN_STOCK | Birch Ply | 18 | JOB-2026-0412 | 2 | 2026-04-12T14:33:09Z | L | 350000 | 800 | 700 | 200 | Rack-A3 | PV-2026-00991 | SH-2026-00991 |

Area check for the above shape:

- Outer rectangle area: `800 * 700 = 560000`
- Cut-out rectangle area: `500 * 420 = 210000`
- Net L area: `560000 - 210000 = 350000 mm²`

### 8.2 Matching row in `offcut_shapes`

| shape_ref | offcut_id | coord_unit | bbox_x_mm | bbox_y_mm | vertices_json | holes_json | version |
|---|---|---|---:|---:|---|---|---:|
| SH-2026-00991 | OC-2026-000123 | mm | 0 | 0 | [[0,0],[800,0],[800,200],[300,200],[300,700],[0,700]] | [] | 1 |

### 8.3 Optional row in `offcut_previews`

| preview_ref | offcut_id | svg_path_data | scale_hint | updated_at_utc |
|---|---|---|---|---|
| PV-2026-00991 | OC-2026-000123 | M0 0 L800 0 L800 200 L300 200 L300 700 L0 700 Z | 1:1 mm | 2026-04-12T14:33:10Z |

### 8.4 What the app does with this

- Stock list view reads `offcut_inventory` and shows `shape_type = L`, area, and bbox dimensions.
- On row click, app loads `offcut_shapes.vertices_json` and renders the exact L outline.
- If reserved/used, app updates status and logs an event in `offcut_events`.
