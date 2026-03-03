const canvas = document.getElementById('canvas');
      const ctx = canvas.getContext('2d');
      let state = null;
      let drag = null;
      let measure = { start: null, end: null, clearSeq: 0 };
      const DRAG_THRESHOLD_PX = 6;
const MEASURE_SNAP_PX = 10;

      function postToStreamlit(type, payload = {}) {
        window.parent.postMessage(
          {
            isStreamlitMessage: true,
            type,
            ...payload,
          },
          "*"
        );
      }

      function emit(payload) {
        postToStreamlit("streamlit:setComponentValue", {
          value: { ...payload, event_id: `${Date.now()}-${Math.random()}` },
        });
      }

      function toPx(x, y) {
        const s = state.scale;
        return { x: x * s, y: canvas.height - y * s };
      }

      function fromPx(px, py) {
        const s = state.scale;
        return { x: px / s, y: (canvas.height - py) / s };
      }

      function clampToSheet(part, x, y) {
        const minX = state.margin;
        const minY = state.margin;
        const maxX = state.sheetW - state.margin - part.w;
        const maxY = state.sheetH - state.margin - part.h;
        return {
          x: Math.max(minX, Math.min(maxX, x)),
          y: Math.max(minY, Math.min(maxY, y)),
        };
      }

      
function snapAxis(value, spacing, origin) {
  return Math.round((value - origin) / spacing) * spacing + origin;
}

function applySnap(part, x, y) {
  if (!state.snapEnabled) return { x, y };
  const spacing = Math.max(1, state.snapSize || 1);
  const sx = snapAxis(x, spacing, state.margin);
  const sy = snapAxis(y, spacing, state.margin);
  return clampToSheet(part, sx, sy);
}

function drawSnapGrid() {
  if (!state.showSnapGrid) return;
  const spacing = Math.max(1, state.snapSize || 1);
  ctx.strokeStyle = 'rgba(130,130,130,0.25)';
  ctx.lineWidth = 1;

  for (let x = state.margin; x <= state.sheetW - state.margin + 1e-6; x += spacing) {
    const p1 = toPx(x, state.margin);
    const p2 = toPx(x, state.sheetH - state.margin);
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);
    ctx.stroke();
  }

  for (let y = state.margin; y <= state.sheetH - state.margin + 1e-6; y += spacing) {
    const p1 = toPx(state.margin, y);
    const p2 = toPx(state.sheetW - state.margin, y);
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);
    ctx.stroke();
  }
}


function rangesOverlap(a1, a2, b1, b2) {
  return Math.min(a2, b2) - Math.max(a1, b1) > 0;
}

function findAlignmentSnap(part, x, y) {
  if (!state.alignSnapEnabled) return null;
  const tol = Math.max(0.1, state.alignSnapTolerance || 0);
  let best = null;

  for (const other of state.parts) {
    if (other.id === part.id) continue;

    const xCandidates = [
      { v: other.x, kind: 'left-left' },
      { v: other.x + other.w - part.w, kind: 'right-right' },
      { v: other.x - part.w, kind: 'right-left' },
      { v: other.x + other.w, kind: 'left-right' },
      { v: other.x - state.kerf - part.w, kind: 'kerf-left' },
      { v: other.x + other.w + state.kerf, kind: 'kerf-right' },
    ];

    for (const c of xCandidates) {
      const d = Math.abs(x - c.v);
      if (d > tol) continue;
      if (!rangesOverlap(y, y + part.h, other.y, other.y + other.h)) continue;
      if (!best || d < best.distance) best = { axis: 'x', value: c.v, distance: d, kind: c.kind };
    }

    const yCandidates = [
      { v: other.y, kind: 'bottom-bottom' },
      { v: other.y + other.h - part.h, kind: 'top-top' },
      { v: other.y - part.h, kind: 'top-bottom' },
      { v: other.y + other.h, kind: 'bottom-top' },
      { v: other.y - state.kerf - part.h, kind: 'kerf-bottom' },
      { v: other.y + other.h + state.kerf, kind: 'kerf-top' },
    ];

    for (const c of yCandidates) {
      const d = Math.abs(y - c.v);
      if (d > tol) continue;
      if (!rangesOverlap(x, x + part.w, other.x, other.x + other.w)) continue;
      if (!best || d < best.distance) best = { axis: 'y', value: c.v, distance: d, kind: c.kind };
    }
  }

  return best;
}

function findKerfSuggestion(part, x, y) {
  if (!state.kerfPromptEnabled) return null;
  const threshold = Math.max(0.1, state.kerfPromptThreshold || 0);
  let best = null;

  for (const other of state.parts) {
    if (other.id === part.id) continue;

    const xCandidates = [other.x - state.kerf - part.w, other.x + other.w + state.kerf];
    for (const v of xCandidates) {
      const d = Math.abs(x - v);
      if (d > threshold) continue;
      if (!rangesOverlap(y, y + part.h, other.y, other.y + other.h)) continue;
      if (!best || d < best.distance) best = { x: v, y, distance: d };
    }

    const yCandidates = [other.y - state.kerf - part.h, other.y + other.h + state.kerf];
    for (const v of yCandidates) {
      const d = Math.abs(y - v);
      if (d > threshold) continue;
      if (!rangesOverlap(x, x + part.w, other.x, other.x + other.w)) continue;
      if (!best || d < best.distance) best = { x, y: v, distance: d };
    }
  }

  return best;
}


function distance(a, b) {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

function nearestPointOnSegment(p, a, b) {
  const abx = b.x - a.x;
  const aby = b.y - a.y;
  const apx = p.x - a.x;
  const apy = p.y - a.y;
  const ab2 = abx * abx + aby * aby;
  if (ab2 <= 1e-9) return { x: a.x, y: a.y };
  let t = (apx * abx + apy * aby) / ab2;
  t = Math.max(0, Math.min(1, t));
  return { x: a.x + abx * t, y: a.y + aby * t };
}

function getMeasureSnapPoint(world) {
  const toleranceMm = MEASURE_SNAP_PX / state.scale;
  let best = null;

  for (const part of state.parts) {
    const corners = [
      { x: part.x, y: part.y },
      { x: part.x + part.w, y: part.y },
      { x: part.x + part.w, y: part.y + part.h },
      { x: part.x, y: part.y + part.h },
    ];

    for (const c of corners) {
      const d = distance(world, c);
      if (d <= toleranceMm && (!best || d < best.d)) best = { p: c, d };
    }

    const edges = [
      [corners[0], corners[1]],
      [corners[1], corners[2]],
      [corners[2], corners[3]],
      [corners[3], corners[0]],
    ];
    for (const [a, b] of edges) {
      const q = nearestPointOnSegment(world, a, b);
      const d = distance(world, q);
      if (d <= toleranceMm && (!best || d < best.d)) best = { p: q, d };
    }
  }

  return best ? best.p : world;
}

function drawRect(x, y, w, h, fill, stroke, lineWidth=1) {
        const p1 = toPx(x, y);
        const p2 = toPx(x + w, y + h);
        const left = p1.x;
        const top = p2.y;
        const width = p2.x - p1.x;
        const height = p1.y - p2.y;
        if (fill) {
          ctx.fillStyle = fill;
          ctx.fillRect(left, top, width, height);
        }
        if (stroke) {
          ctx.strokeStyle = stroke;
          ctx.lineWidth = lineWidth;
          ctx.strokeRect(left, top, width, height);
        }
      }

      function render() {
        if (!state) return;
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        for (const cell of state.gridRows) {
          drawRect(cell.x, cell.y, cell.x2 - cell.x, cell.y2 - cell.y, cell.is_legal ? 'rgba(102, 187, 106, 0.32)' : 'rgba(239, 83, 80, 0.36)', null);
        }

        drawRect(0, 0, state.sheetW, state.sheetH, null, '#333', 2);
        drawRect(state.margin, state.margin, state.sheetW - 2*state.margin, state.sheetH - 2*state.margin, null, '#cc0000', 1);
        drawSnapGrid();
        drawMeasureOverlay();

        for (const part of state.parts) {
          const isSelected = part.id === state.selectedPartId;
          drawRect(part.x, part.y, part.w, part.h, isSelected ? '#f39c12' : '#4a90e2', '#222', isSelected ? 3 : 1);
          const c = toPx(part.x + part.w/2, part.y + part.h/2);
          ctx.fillStyle = '#111';
          ctx.font = '12px Arial';
          ctx.textAlign = 'center';
          ctx.fillText(part.rid, c.x, c.y);
        }
      }

      
function drawMeasureOverlay() {
  if (!state.measureEnabled) return;
  if (!measure.start) return;

  const p1 = toPx(measure.start.x, measure.start.y);
  const p2 = measure.end ? toPx(measure.end.x, measure.end.y) : p1;
  ctx.strokeStyle = 'rgba(33, 150, 243, 0.95)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(p1.x, p1.y);
  ctx.lineTo(p2.x, p2.y);
  ctx.stroke();

  ctx.fillStyle = '#1565c0';
  ctx.font = '12px Arial';
  const dx = (measure.end ? measure.end.x : measure.start.x) - measure.start.x;
  const dy = (measure.end ? measure.end.y : measure.start.y) - measure.start.y;
  const dist = Math.sqrt(dx * dx + dy * dy);
  const cx = (p1.x + p2.x) / 2;
  const cy = (p1.y + p2.y) / 2;
  ctx.fillText(`${dist.toFixed(1)} mm`, cx + 8, cy - 8);
}

function pickPart(mx, my) {
        const p = fromPx(mx, my);
        for (let i = state.parts.length - 1; i >= 0; i--) {
          const part = state.parts[i];
          if (p.x >= part.x && p.x <= part.x + part.w && p.y >= part.y && p.y <= part.y + part.h) {
            return { part, p };
          }
        }
        return { part: null, p };
      }

      canvas.addEventListener('mousedown', (e) => {
        if (!state) return;
        const rect = canvas.getBoundingClientRect();
        const mx = (e.clientX - rect.left) * (canvas.width / rect.width);
        const my = (e.clientY - rect.top) * (canvas.height / rect.height);
        const world = fromPx(mx, my);

        if (state.measureEnabled) {
          const snappedPoint = getMeasureSnapPoint(world);
          if (!measure.start || (measure.start && measure.end)) {
            measure.start = { x: snappedPoint.x, y: snappedPoint.y };
            measure.end = null;
          } else {
            measure.end = { x: snappedPoint.x, y: snappedPoint.y };
            const dx = measure.end.x - measure.start.x;
            const dy = measure.end.y - measure.start.y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            emit({ type: 'measure_update', x1: measure.start.x, y1: measure.start.y, x2: measure.end.x, y2: measure.end.y, distance: dist });
          }
          render();
          return;
        }

        const { part, p } = pickPart(mx, my);
        if (!part) return;

        drag = {
          partId: part.id,
          startMouseX: mx,
          startMouseY: my,
          offsetX: p.x - part.x,
          offsetY: p.y - part.y,
          dragged: false,
          snappedByAlign: false,
        };
      });

      canvas.addEventListener('mousemove', (e) => {
        if (!drag || !state) return;
        const rect = canvas.getBoundingClientRect();
        const mx = (e.clientX - rect.left) * (canvas.width / rect.width);
        const my = (e.clientY - rect.top) * (canvas.height / rect.height);

        const dx = mx - drag.startMouseX;
        const dy = my - drag.startMouseY;
        if (!drag.dragged && (Math.abs(dx) > DRAG_THRESHOLD_PX || Math.abs(dy) > DRAG_THRESHOLD_PX)) {
          drag.dragged = true;
        }

        if (!drag.dragged) return;

        const p = fromPx(mx, my);
        const moving = state.parts.find(pp => pp.id === drag.partId);
        if (!moving) return;
        const clamped = clampToSheet(moving, p.x - drag.offsetX, p.y - drag.offsetY);
        let candidateX = clamped.x;
        let candidateY = clamped.y;
        drag.snappedByAlign = false;

        const align = findAlignmentSnap(moving, candidateX, candidateY);
        if (align) {
          if (align.axis === 'x') candidateX = align.value;
          if (align.axis === 'y') candidateY = align.value;
          drag.snappedByAlign = true;
        }

        const snapped = applySnap(moving, candidateX, candidateY);
        moving.x = snapped.x;
        moving.y = snapped.y;
        render();
      });

      canvas.addEventListener('mouseup', () => {
        if (!drag || !state) return;
        const moved = state.parts.find(pp => pp.id === drag.partId);

        if (drag.dragged) {
          if (!drag.snappedByAlign) {
            const suggestion = findKerfSuggestion(moved, moved.x, moved.y);
            if (suggestion) {
              emit({ type: 'suggest_snap', part_id: drag.partId, x: suggestion.x, y: suggestion.y, gap: suggestion.distance });
              drag = null;
              return;
            }
          }
          emit({ type: 'move', part_id: drag.partId, x: moved.x, y: moved.y });
        } else {
          emit({ type: 'select', part_id: drag.partId });
        }

        drag = null;
      });

      function onRender(event) {
        const msg = event.data || {};
        if (msg.type !== "streamlit:render") return;
        const args = msg.args || {};
        const payload = JSON.parse(args.data);
        const layout = payload.layout;
        const sheet = layout.sheets[payload.selected_sheet_idx];

        const maxW = 1200;
        const maxH = 560;
        const scale = Math.min(maxW / layout.sheet_w, maxH / layout.sheet_h);
        canvas.width = Math.max(600, Math.floor(layout.sheet_w * scale));
        canvas.height = Math.max(260, Math.floor(layout.sheet_h * scale));

        state = {
          sheetW: layout.sheet_w,
          sheetH: layout.sheet_h,
          margin: layout.margin,
          selectedPartId: payload.selected_part_id,
          parts: JSON.parse(JSON.stringify(sheet.parts)),
          gridRows: payload.grid_rows || [],
          snapEnabled: Boolean(payload.snap_enabled),
          snapSize: Number(payload.snap_size || 10),
          showSnapGrid: Boolean(payload.show_snap_grid),
          alignSnapEnabled: Boolean(payload.align_snap_enabled),
          alignSnapTolerance: Number(payload.align_snap_tolerance || 4),
          kerfPromptEnabled: Boolean(payload.kerf_prompt_enabled),
          kerfPromptThreshold: Number(payload.kerf_prompt_threshold || 12),
          kerf: Number(layout.kerf || 0),
          measureEnabled: Boolean(payload.measure_enabled),
          measureClearSeq: Number(payload.measure_clear_seq || 0),
          scale,
        };

        if (measure.clearSeq !== state.measureClearSeq) {
          measure = { start: null, end: null, clearSeq: state.measureClearSeq };
        }
        if (!state.measureEnabled) {
          measure = { start: null, end: null, clearSeq: state.measureClearSeq };
        }

        render();
        postToStreamlit("streamlit:setFrameHeight", { height: document.body.scrollHeight + 12 });
      }

      window.addEventListener("message", onRender);
      postToStreamlit("streamlit:componentReady", { apiVersion: 1 });
