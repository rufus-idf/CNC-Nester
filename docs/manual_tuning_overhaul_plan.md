# Manual Nesting Tuning Overhaul Plan

## Why an overhaul is justified
The current manual tuning dialog relies on click-to-select + button nudges and does not provide drag interactions, explicit movement envelopes, or robust visual validation of legal/illegal placement zones. It also mixes rendering and editing rules directly in `app.py`, which makes iteration risky and slow.

## Current state (what we already have)
- Accurate sheet/panel dimensions are already represented in a common layout model (`sheet_w`, `sheet_h`, `margin`, `kerf`, `sheets[].parts[]`) and validated through collision/bounds checks in `manual_layout.py`.
- Panel selection already works through both chart click and dropdown in the existing dialog.
- Manual nudge controls (up/down/left/right with step size) already exist and should be preserved.
- An exact coordinate move control exists today, but can be removed/de-emphasized for this phase.

## Target v1 outcomes (aligned to your 4 requirements)
1. Accurate, to-scale sheet preview with panels.
2. Dual selection: click panel in canvas OR pick from list.
3. Drag-to-move with live legal/illegal placement feedback:
   - Green overlays = legal destination region.
   - Red overlays = illegal (margin or kerf violations).
4. Preserve directional move controls with configurable step distance.

## First steps (recommended sequence)

### 1) Freeze behavior with tests before UI rewrite
Create/expand tests around placement rules so UI rewrites cannot break geometry logic:
- Bounds checks with margin.
- Kerf clearance between parts.
- Rotation validity at edges and near neighbors.
- Incremental nudge movement behavior.

### 2) Split layout engine from Streamlit UI
Move all manual-edit geometry logic into a dedicated module (e.g., `manual_tuning_engine.py`) with pure functions:
- `can_place(part, x, y, layout)`
- `move_part_to(layout, sheet_idx, part_id, x, y)`
- `compute_allowed_region(layout, sheet_idx, part_id)`
- `compute_blocked_regions(layout, sheet_idx, part_id)`

This gives one trusted source for both drag/drop validation and button nudges.

### 3) Replace current Altair interaction layer for editing
Keep Altair for static charts if needed, but use a true drag-capable canvas component for manual tuning (for example, a Streamlit custom component with Konva/Fabric/React Flow or another drag-friendly canvas):
- Render sheet and margin rectangles to scale.
- Render panel rectangles with IDs and dimensions.
- Emit events: `select_part`, `drag_start`, `drag_move`, `drag_end`.
- Snap drag to millimeter grid if desired (optional toggle).

### 4) Implement movement envelope visualization
When a part is selected:
- Compute legal range from sheet margin first (`x_min/x_max`, `y_min/y_max`).
- Subtract disallowed zones caused by kerf-expanded footprints of other panels.
- Visualize:
  - Green translucent area where top-left of selected part can legally move.
  - Red translucent overlays where movement would violate margin/kerf.
- During drag, preview candidate position and validity in real time.

### 5) Keep and rewire manual nudge controls
Retain current step presets and arrow controls, but route through the same engine function used by dragging (`move_part_to` / `move_part_by`). This guarantees consistent behavior between drag and buttons.

### 6) Tighten UX and reliability details
- Add optimistic movement preview + immediate rollback when invalid.
- Keep selected part highlighted after rerenders.
- Add concise status text: `Valid move`, `Blocked by kerf near PANEL_12`, `Out of margin`.
- Preserve undo scope for the dialog draft (at least single-step undo; multi-step optional).

## Suggested implementation phases

### Phase A (1–2 days)
- Extract engine module.
- Add test coverage for geometry + movement APIs.
- Keep existing UI wired to new engine.

### Phase B (2–4 days)
- Build new drag-capable manual tuning canvas.
- Support click/dropdown selection parity.
- Maintain existing nudge controls.

### Phase C (2–3 days)
- Add green/red allowed-area overlays.
- Add drag preview + conflict reason messages.
- Polish performance for dense nests.

## Definition of done (v1)
- Users can reliably select any part by clicking or list.
- Users can drag parts with immediate valid/invalid visual feedback.
- No move is committed if it breaches margin or kerf.
- Arrow-step movement still works and uses identical rules.
- Sheet preview remains geometrically accurate to configured dimensions.

## Architecture note
A clean overhaul is reasonable here: keep the existing data model and validation concepts, but replace the editing UI with a dedicated interactive layer and a tested geometry engine. This avoids incremental hacks in the current dialog and gives a stable platform for future features (snap lines, alignment tools, constrained rotate, auto-pack assist).
