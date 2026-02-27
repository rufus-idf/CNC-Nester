import copy
import hashlib
import io
import json
import zipfile

import ezdxf
import altair as alt
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection

from manual_layout import initialize_layout_from_packer, move_part, rotate_part_90
from nest_storage import build_nest_payload, build_sheet_boring_points, create_cix_zip, nest_file_to_payload, parse_nest_payload, payload_to_dxf
from nesting_engine import run_selco_nesting, run_smart_nesting
from panel_utils import normalize_panels
from offcut_utils import calculate_sheet_offcuts, build_sheet_usage_heatmap

# --- PAGE CONFIG ---
st.set_page_config(page_title="CNC Nester Pro", layout="wide")

# --- SESSION STATE ---
if 'panels' not in st.session_state:
    st.session_state['panels'] = []
if 'sheet_w' not in st.session_state:
    st.session_state.sheet_w = 2440.0
if 'sheet_h' not in st.session_state:
    st.session_state.sheet_h = 1220.0
if 'kerf' not in st.session_state:
    st.session_state.kerf = 6.0
if 'margin' not in st.session_state:
    st.session_state.margin = 10.0
if 'machine_type' not in st.session_state:
    st.session_state.machine_type = 'Flat Bed'
if 'manual_layout' not in st.session_state:
    st.session_state.manual_layout = None
if 'manual_layout_draft' not in st.session_state:
    st.session_state.manual_layout_draft = None
if 'show_manual_tuning' not in st.session_state:
    st.session_state.show_manual_tuning = False
if 'last_packer' not in st.session_state:
    st.session_state.last_packer = None
if 'manual_selected_part_id' not in st.session_state:
    st.session_state.manual_selected_part_id = None
if 'manual_part_select' not in st.session_state:
    st.session_state.manual_part_select = None
if 'manual_notice' not in st.session_state:
    st.session_state.manual_notice = None
if 'cix_preview' not in st.session_state:
    st.session_state.cix_preview = None
if 'last_sheet_preset_applied' not in st.session_state:
    st.session_state.last_sheet_preset_applied = "Custom"


SHEET_PRESETS = {
    "MDF (2800 x 2070)": (2800.0, 2070.0),
    "Ply (3050 x 1220)": (3050.0, 1220.0),
}


def apply_pending_loaded_nest():
    pending = st.session_state.pop("pending_loaded_nest", None)
    if pending is None:
        return

    st.session_state.sheet_w = pending["sheet_w"]
    st.session_state.sheet_h = pending["sheet_h"]
    st.session_state.kerf = pending["kerf"]
    st.session_state.margin = pending["margin"]
    st.session_state["panels"] = pending["panels"]
    st.session_state["loaded_nest_name"] = pending["nest_name"]
    st.session_state.machine_type = pending.get("machine_type", "Flat Bed")
    st.session_state.manual_layout = pending.get("manual_layout")
    st.session_state.cix_preview = pending.get("cix_preview")
    st.session_state.manual_layout_draft = None
    st.session_state.sheet_preset = infer_sheet_preset(pending["sheet_w"], pending["sheet_h"])
    st.session_state.last_sheet_preset_applied = st.session_state.sheet_preset


# --- HELPERS ---


def add_panel(w, l, q, label, grain, mat):
    row = {
        "Label": label, "Width": w, "Length": l, "Qty": q,
        "Grain?": grain, "Material": mat
    }
    st.session_state['panels'].append(row)


def clear_data():
    st.session_state['panels'] = []
    st.session_state.manual_layout = None
    st.session_state.manual_layout_draft = None
    st.session_state.last_packer = None
    st.session_state.cix_preview = None


@st.cache_data(ttl=120)
def load_gsheets_catalog():
    conn = st.connection("gsheets", type=GSheetsConnection)
    return conn.read()


def create_dxf_zip(packer, sheet_w, sheet_h, margin, kerf):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for i, bin in enumerate(packer):
            doc = ezdxf.new()
            msp = doc.modelspace()
            doc.layers.new(name='SHEET_BOUNDARY', dxfattribs={'color': 1})
            doc.layers.new(name='CUT_LINES', dxfattribs={'color': 3})
            doc.layers.new(name='LABELS', dxfattribs={'color': 7})

            msp.add_lwpolyline([(0, 0), (sheet_w, 0), (sheet_w, sheet_h), (0, sheet_h), (0, 0)], dxfattribs={'layer': 'SHEET_BOUNDARY'})

            for rect in bin:
                x = rect.x + margin
                y = rect.y + margin
                w = rect.width - kerf
                h = rect.height - kerf
                points = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
                msp.add_lwpolyline(points, dxfattribs={'layer': 'CUT_LINES'})
                label_text = str(rect.rid) if rect.rid else "Part"
                msp.add_text(label_text, dxfattribs={'layer': 'LABELS', 'height': 20}).set_placement((x + w / 2, y + h / 2), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
                size_text = f"{int(w)}x{int(h)}"
                msp.add_text(size_text, dxfattribs={'layer': 'LABELS', 'height': 15}).set_placement((x + w / 2, y + h / 2 - 25), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
            dxf_io = io.StringIO()
            doc.write(dxf_io)
            zip_file.writestr(f"Sheet_{i + 1}.dxf", dxf_io.getvalue())
    return zip_buffer.getvalue()


def infer_sheet_preset(sheet_w, sheet_h):
    for preset, dims in SHEET_PRESETS.items():
        if (sheet_w, sheet_h) == dims:
            return preset
    return "Custom"


def sync_sheet_dims_from_preset():
    preset = st.session_state.get("sheet_preset", "Custom")
    if st.session_state.get("last_sheet_preset_applied") == preset:
        return

    dims = SHEET_PRESETS.get(preset)
    if dims is not None:
        st.session_state.sheet_w, st.session_state.sheet_h = dims

    st.session_state.last_sheet_preset_applied = preset


def draw_layout_sheet(layout, selected_sheet_idx, tooling_map=None, template_preview=None):
    selected_sheet = layout["sheets"][selected_sheet_idx]
    fig, ax = plt.subplots(figsize=(3.75, 2.25))
    ax.set_xlim(0, layout["sheet_w"])
    ax.set_ylim(0, layout["sheet_h"])
    ax.set_aspect('equal')
    ax.axis('off')
    ax.add_patch(patches.Rectangle((0, 0), layout["sheet_w"], layout["sheet_h"], fc='#eef5ff', ec='#333'))
    ax.add_patch(patches.Rectangle((layout["margin"], layout["margin"]), layout["sheet_w"] - 2 * layout["margin"], layout["sheet_h"] - 2 * layout["margin"], ec='red', ls='--', fc='none'))

    for part in selected_sheet["parts"]:
        fc = '#5a7' if part.get('rotated') else '#6fa8dc'
        ax.add_patch(patches.Rectangle((part["x"], part["y"]), part["w"], part["h"], fc=fc, ec='#222'))
        ax.text(part["x"] + part["w"] / 2, part["y"] + part["h"] / 2, f"{part['rid']}\n{int(part['w'])}x{int(part['h'])}", ha='center', va='center', fontsize=7)

    boring_points = build_sheet_boring_points(selected_sheet.get("parts", []), tooling_map, template_preview)
    if boring_points:
        ax.scatter([p["x"] for p in boring_points], [p["y"] for p in boring_points], c='#d32f2f', s=28, marker='o', edgecolors='white', linewidths=0.6, zorder=4)
        ax.text(layout["margin"], layout["sheet_h"] - layout["margin"] - 25, f"Borings: {len(boring_points)}", color='#b71c1c', fontsize=8, ha='left', va='top')

    st.pyplot(fig)


def draw_interactive_layout(layout, selected_sheet_idx, selected_part_id):
    selected_sheet = layout["sheets"][selected_sheet_idx]
    part_ids = [p["id"] for p in selected_sheet["parts"]]

    # Keep geometry accurate by preserving sheet aspect ratio in a bounded viewport.
    max_plot_w = 1200
    max_plot_h = 560
    scale = min(max_plot_w / layout["sheet_w"], max_plot_h / layout["sheet_h"])
    plot_w = max(600, int(layout["sheet_w"] * scale))
    plot_h = max(260, int(layout["sheet_h"] * scale))

    rows = [
        {
            "part_id": "__sheet__",
            "kind": "sheet",
            "x": 0.0,
            "x2": float(layout["sheet_w"]),
            "y": 0.0,
            "y2": float(layout["sheet_h"]),
            "label": "Sheet",
            "dims": f"{int(layout['sheet_w'])}x{int(layout['sheet_h'])}",
            "display_color": "#eef5ff",
            "stroke_color": "#333",
            "base_stroke": 2,
        },
        {
            "part_id": "__margin__",
            "kind": "margin",
            "x": float(layout["margin"]),
            "x2": float(layout["sheet_w"] - layout["margin"]),
            "y": float(layout["margin"]),
            "y2": float(layout["sheet_h"] - layout["margin"]),
            "label": "Margin",
            "dims": "",
            "display_color": "rgba(0,0,0,0)",
            "stroke_color": "#cc0000",
            "base_stroke": 2,
        },
    ]

    for part in selected_sheet["parts"]:
        rows.append({
            "part_id": part["id"],
            "kind": "part",
            "x": float(part["x"]),
            "x2": float(part["x"] + part["w"]),
            "y": float(part["y"]),
            "y2": float(part["y"] + part["h"]),
            "label": part["rid"],
            "dims": f"{int(part['w'])}x{int(part['h'])}",
            "display_color": "#f39c12" if part["id"] == selected_part_id else ("#2e7d32" if part.get("rotated") else "#4a90e2"),
            "stroke_color": "#222",
            "base_stroke": 1,
        })

    chart_df = pd.DataFrame(rows)
    selector = alt.selection_point(fields=["part_id"], name="part_pick")

    chart = (
        alt.Chart(chart_df)
        .mark_rect()
        .encode(
            x=alt.X("x:Q", scale=alt.Scale(domain=[0, layout["sheet_w"]]), axis=None),
            x2="x2:Q",
            y=alt.Y("y:Q", scale=alt.Scale(domain=[0, layout["sheet_h"]]), axis=None),
            y2="y2:Q",
            color=alt.Color("display_color:N", scale=None, legend=None),
            stroke=alt.Color("stroke_color:N", scale=None, legend=None),
            strokeWidth=alt.condition(
                selector,
                alt.value(4),
                alt.value(1),
            ),
            tooltip=["label:N", "dims:N", "part_id:N"],
        )
        .add_params(selector)
        .properties(width=plot_w, height=plot_h)
    )

    event = st.altair_chart(chart, width="content", on_select="rerun", selection_mode="part_pick")
    st.caption("Tip: click any panel in the diagram to select it for nudging/rotation.")

    selected = None
    if isinstance(event, dict):
        selection = event.get("selection", {})
        picked = selection.get("part_pick", [])
        if isinstance(picked, list) and picked:
            selected = picked[0].get("part_id")
        elif isinstance(picked, dict):
            ids = picked.get("part_id")
            if isinstance(ids, list) and ids:
                selected = ids[0]

    if selected not in part_ids:
        return None
    return selected




def draw_cix_preview(cix_preview):
    if not cix_preview:
        return

    panel_w = float(cix_preview.get("panel_width", 0.0))
    panel_h = float(cix_preview.get("panel_length", 0.0))
    if panel_w <= 0 or panel_h <= 0:
        return

    borings = cix_preview.get("borings", [])
    segments = cix_preview.get("toolpath_segments", [])

    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.set_xlim(0, panel_w)
    ax.set_ylim(0, panel_h)
    ax.set_aspect('equal')
    ax.add_patch(patches.Rectangle((0, 0), panel_w, panel_h, fc='#f5f9ff', ec='#1f2937', lw=1.5))

    for seg in segments:
        ax.plot([seg["x1"], seg["x2"]], [seg["y1"], seg["y2"]], color='#2563eb', linewidth=1.8)

    boring_legend_entries = []
    if borings:
        tool_groups = {}
        for boring in borings:
            tool_name = str(boring.get("tool") or "UNKNOWN")
            tool_groups.setdefault(tool_name, []).append(boring)

        palette = [
            '#dc2626', '#16a34a', '#f59e0b', '#9333ea', '#0ea5e9',
            '#e11d48', '#84cc16', '#f97316', '#06b6d4', '#a855f7'
        ]

        for idx, (tool_name, grouped_borings) in enumerate(sorted(tool_groups.items())):
            xs = [b["x"] for b in grouped_borings]
            ys = [b["y"] for b in grouped_borings]
            color = palette[idx % len(palette)]
            ax.scatter(
                xs,
                ys,
                c=color,
                s=48,
                marker='o',
                edgecolors='white',
                linewidths=0.8,
                zorder=3,
                label=f"{tool_name} ({len(grouped_borings)})",
            )
            boring_legend_entries.append(f"{tool_name}: {len(grouped_borings)}")

        if tool_groups:
            ax.legend(loc='upper right', fontsize=8, frameon=True)

    ax.set_title('CIX Machining Preview (Blue = route/toolpath, colors = boring tool type)')
    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')
    st.pyplot(fig)

    thickness = float(cix_preview.get("panel_thickness", 0.0))
    detail = f" | {'; '.join(boring_legend_entries)}" if boring_legend_entries else ""
    st.caption(
        f"Detected: {len(segments)} toolpath segment(s), {len(borings)} boring operation(s), thickness {thickness:g} mm{detail}"
    )


@st.dialog("Manual Nesting Tuning", width="large")
def manual_tuning_dialog():
    st.markdown(
        """
        <style>
        div[data-testid="stDialog"] {
            width: 100vw !important;
            max-width: 100vw !important;
        }
        div[data-testid="stDialog"] > div {
            width: 100vw !important;
            max-width: 100vw !important;
            height: 100vh !important;
            max-height: 100vh !important;
            margin: 0 !important;
            border-radius: 0 !important;
            inset: 0 !important;
            left: 0 !important;
            right: 0 !important;
            transform: none !important;
        }
        div[data-testid="stDialog"] [data-testid="stDialogContent"] {
            max-height: 100vh !important;
            overflow: auto !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    layout = st.session_state.manual_layout_draft
    if not layout or not layout.get("sheets"):
        st.session_state.show_manual_tuning = False
        st.session_state.manual_layout_draft = None
        if "manual_part_select" in st.session_state:
            del st.session_state["manual_part_select"]
        return

    editable_sheets = [
        (idx, s)
        for idx, s in enumerate(layout["sheets"])
        if s.get("parts")
    ]
    if not editable_sheets:
        st.warning("No parts available to tune.")
        if st.button("Close"):
            st.session_state.show_manual_tuning = False
            st.session_state.manual_layout_draft = None
            st.rerun()
        return

    sheet_choices = [f"Sheet {sheet['sheet_index'] + 1}" for _, sheet in editable_sheets]
    selected_sheet_label = st.selectbox("Manual Sheet", sheet_choices, key="manual_sheet_select")
    selected_sheet_option = sheet_choices.index(selected_sheet_label)
    selected_sheet_idx, selected_sheet = editable_sheets[selected_sheet_option]

    part_ids = [p["id"] for p in selected_sheet["parts"]]
    part_label_map = {p["id"]: f"{p['rid']} ({int(p['w'])}x{int(p['h'])})" for p in selected_sheet["parts"]}
    part_by_id = {p["id"]: p for p in selected_sheet["parts"]}

    notice = st.session_state.pop("manual_notice", None)
    if notice:
        level, msg = notice
        if level == "error":
            st.toast(msg, icon="⚠️")
        else:
            st.toast(msg, icon="✅")

    if st.session_state.manual_selected_part_id not in part_ids:
        st.session_state.manual_selected_part_id = part_ids[0]

    clicked_part_id = draw_interactive_layout(layout, selected_sheet_idx, st.session_state.manual_selected_part_id)
    if clicked_part_id in part_ids and clicked_part_id != st.session_state.manual_selected_part_id:
        st.session_state.manual_selected_part_id = clicked_part_id
        st.session_state.manual_part_select = clicked_part_id
        st.rerun()

    if st.session_state.get("manual_part_select") not in part_ids:
        st.session_state.manual_part_select = st.session_state.manual_selected_part_id

    selected_part_id = st.selectbox(
        "Part to move/rotate",
        options=part_ids,
        index=part_ids.index(st.session_state.manual_selected_part_id),
        format_func=lambda pid: part_label_map[pid],
        key="manual_part_select",
    )
    st.session_state.manual_selected_part_id = selected_part_id

    selected_part = part_by_id[selected_part_id]
    st.caption(
        f"Selected: {selected_part['rid']} | X={selected_part['x']:.1f}, Y={selected_part['y']:.1f}, "
        f"W={selected_part['w']:.1f}, H={selected_part['h']:.1f}, Rotated={'Yes' if selected_part.get('rotated') else 'No'}"
    )

    c_snap, c_nudge = st.columns([1, 2])
    snap_mode = c_snap.radio("Step preset", options=[1.0, 5.0, 10.0, 25.0], horizontal=True, format_func=lambda v: f"{int(v)} mm", key="manual_step_preset")
    nudge = c_nudge.number_input("Move step (mm)", min_value=1.0, value=float(snap_mode), step=1.0, key="manual_nudge")

    c1, c2, c3, c4, c5 = st.columns(5)
    move_up = c1.button("⬆️ Up")
    move_left = c2.button("⬅️ Left")
    move_right = c3.button("➡️ Right")
    move_down = c4.button("⬇️ Down")
    rotate = c5.button("🔄 Rotate 90°")

    if move_up:
        st.session_state.manual_layout_draft, ok, msg = move_part(layout, selected_sheet_idx, selected_part_id, 0, nudge)
        st.session_state.manual_notice = ("success" if ok else "error", msg)
        st.rerun()
    if move_left:
        st.session_state.manual_layout_draft, ok, msg = move_part(layout, selected_sheet_idx, selected_part_id, -nudge, 0)
        st.session_state.manual_notice = ("success" if ok else "error", msg)
        st.rerun()
    if move_right:
        st.session_state.manual_layout_draft, ok, msg = move_part(layout, selected_sheet_idx, selected_part_id, nudge, 0)
        st.session_state.manual_notice = ("success" if ok else "error", msg)
        st.rerun()
    if move_down:
        st.session_state.manual_layout_draft, ok, msg = move_part(layout, selected_sheet_idx, selected_part_id, 0, -nudge)
        st.session_state.manual_notice = ("success" if ok else "error", msg)
        st.rerun()
    if rotate:
        st.session_state.manual_layout_draft, ok, msg = rotate_part_90(layout, selected_sheet_idx, selected_part_id)
        st.session_state.manual_notice = ("success" if ok else "error", msg)
        st.rerun()

    st.markdown("##### Move to exact position")
    x_col, y_col, go_col = st.columns([2, 2, 1])
    target_x = x_col.number_input("Target X", value=float(selected_part["x"]), step=1.0, key=f"manual_target_x_{selected_part_id}")
    target_y = y_col.number_input("Target Y", value=float(selected_part["y"]), step=1.0, key=f"manual_target_y_{selected_part_id}")
    move_to = go_col.button("Move")

    if move_to:
        dx = float(target_x) - float(selected_part["x"])
        dy = float(target_y) - float(selected_part["y"])
        st.session_state.manual_layout_draft, ok, msg = move_part(layout, selected_sheet_idx, selected_part_id, dx, dy)
        st.session_state.manual_notice = ("success" if ok else "error", msg)
        st.rerun()

    d1, d2, d3 = st.columns(3)
    if d1.button("Apply to Nest", type="primary"):
        st.session_state.manual_layout = copy.deepcopy(st.session_state.manual_layout_draft)
        st.session_state.show_manual_tuning = False
        st.success("Manual tuning applied to current nest.")
        st.rerun()
    if d2.button("Reset Draft"):
        st.session_state.manual_layout_draft = copy.deepcopy(st.session_state.manual_layout)
        st.session_state.manual_notice = ("success", "Draft reset to current nest layout")
        st.rerun()
    if d3.button("Cancel"):
        st.session_state.show_manual_tuning = False
        st.session_state.manual_layout_draft = None
        if "manual_part_select" in st.session_state:
            del st.session_state["manual_part_select"]
        st.rerun()


apply_pending_loaded_nest()

# --- MAIN PAGE ---
st.title("🪚 CNC Nester Pro (Robust)")

st.sidebar.header("⚙️ Machine Settings")
MACHINE_TYPE = st.sidebar.selectbox("Machine Type", ["Flat Bed", "Selco"], key="machine_type")
st.sidebar.selectbox("Select Sheet Size", ["Custom", "MDF (2800 x 2070)", "Ply (3050 x 1220)"], index=0, key="sheet_preset")
sync_sheet_dims_from_preset()
SHEET_W = st.sidebar.number_input("Sheet Width", key="sheet_w", step=10.0)
SHEET_H = st.sidebar.number_input("Sheet Height", key="sheet_h", step=10.0)
KERF = st.sidebar.number_input("Kerf", key="kerf")
MARGIN = st.sidebar.number_input("Margin", key="margin")

input_tab, result_tab, heat_tab = st.tabs(["1️⃣ Input", "2️⃣ Nested Results", "3️⃣ Heat Map & Offcuts"])

with input_tab:
    st.markdown("### Load Nest")
    uploaded_nest = st.file_uploader("📂 Load Nest", type=["dxf", "cix"], accept_multiple_files=False)

    loaded_nest_name = st.session_state.pop("loaded_nest_name", None)
    if loaded_nest_name:
        st.success(f"Loaded nest: {loaded_nest_name}")

    if uploaded_nest is None:
        st.session_state.pop("last_loaded_nest_signature", None)
    else:
        file_bytes = uploaded_nest.getvalue()
        upload_signature = f"{uploaded_nest.name}:{len(file_bytes)}:{hashlib.md5(file_bytes).hexdigest()}"
        if st.session_state.get("last_loaded_nest_signature") != upload_signature:
            try:
                payload = nest_file_to_payload(uploaded_nest.name, file_bytes)
                loaded = parse_nest_payload(payload)
                st.session_state["pending_loaded_nest"] = loaded
                st.session_state["last_loaded_nest_signature"] = upload_signature
                st.rerun()
            except Exception as e:
                st.error(f"Failed to load nest file: {e}")

    st.write("---")
    st.subheader("Input")
    input_tabs = st.tabs(["☁️ G-Sheets", "Manual"])

    with input_tabs[0]:
        if st.button("🔄 Refresh"):
            st.cache_data.clear()
        try:
            df = load_gsheets_catalog()
            cols = ["Product Name", "Panel Name", "Material", "Length (mm)", "Width (mm)", "Qty Per Unit"]
            if all(c in df.columns for c in cols):
                prods = df["Product Name"].dropna().unique()
                sel_prod = st.selectbox("Product", prods)
                qty = st.number_input("Build Qty", 1, 1000, 1)
                mats = df[df["Product Name"] == sel_prod]["Material"].unique()
                sel_mats = st.multiselect("Material", mats, default=mats)

                subset = df[(df["Product Name"] == sel_prod) & (df["Material"].isin(sel_mats))]

                filtered_count = 0
                if not subset.empty:
                    include_mask = pd.Series(True, index=subset.index)

                    # Primary rule: Material column explicitly marked as Component.
                    material_values = subset["Material"].fillna("").astype(str).str.strip().str.lower()
                    include_mask &= material_values != "component"

                    # Safety rule: component rows generally have no panel dimensions.
                    length_values = pd.to_numeric(subset["Length (mm)"], errors="coerce")
                    width_values = pd.to_numeric(subset["Width (mm)"], errors="coerce")
                    include_mask &= length_values.notna() & width_values.notna()

                    filtered_count = int((~include_mask).sum())
                    subset = subset[include_mask]

                prev_cols = ["Panel Name", "Material", "Qty Per Unit", "Length (mm)", "Width (mm)"]
                if "Shopify SKU" in df.columns:
                    prev_cols.insert(0, "Shopify SKU")
                st.dataframe(subset[prev_cols], hide_index=True)
                if filtered_count:
                    st.caption(f"Excluded {filtered_count} component row(s) from import.")

                if st.button("➕ Add Product"):
                    c = 0
                    for _, r in subset.iterrows():
                        add_panel(float(r["Width (mm)"]), float(r["Length (mm)"]), int(r["Qty Per Unit"]) * qty, r["Panel Name"], False, r["Material"])
                        c += 1
                    if c:
                        st.success(f"Added {c} items")
            else:
                st.error(f"Missing headers. Needed: {cols}")
        except Exception as e:
            st.warning(f"Connection error: {e}")

    with input_tabs[1]:
        with st.form("man"):
            c1, c2 = st.columns(2)
            w = c1.number_input("W", step=10.0)
            l = c2.number_input("L", step=10.0)
            c3, c4 = st.columns(2)
            q = c3.number_input("Qty", 1, 100, 1)
            g = c4.checkbox("Grain? (Fixed)")
            lbl = st.text_input("Label", "Part")
            if st.form_submit_button("Add"):
                add_panel(w, l, q, lbl, g, "Manual")
                st.success("Added")

    if st.session_state['panels']:
        st.write("---")
        st.markdown("### Panel List")
        st.caption("Use the row editor below to reliably save Qty/Width/Length/Grain changes.")

        st.session_state['panels'] = normalize_panels(st.session_state['panels'])
        st.dataframe(pd.DataFrame(st.session_state['panels']), hide_index=True, width="stretch")

        row_options = [f"{i + 1}: {p['Label']}" for i, p in enumerate(st.session_state['panels'])]
        selected_label = st.selectbox("Select panel row to edit", options=row_options)
        selected_idx = row_options.index(selected_label)
        selected = st.session_state['panels'][selected_idx]

        with st.form(f"edit_row_{selected_idx}"):
            e1, e2 = st.columns(2)
            label = e1.text_input("Label", value=str(selected.get("Label", "Part")))
            material = e2.text_input("Material", value=str(selected.get("Material", "Manual")))

            e3, e4, e5 = st.columns(3)
            width = e3.number_input("Width", min_value=0.0, value=float(selected.get("Width", 0.0)), step=1.0)
            length = e4.number_input("Length", min_value=0.0, value=float(selected.get("Length", 0.0)), step=1.0)
            qty = e5.number_input("Qty", min_value=1, value=int(selected.get("Qty", 1)), step=1)

            grain = st.checkbox("Grain? (Fixed)", value=bool(selected.get("Grain?", False)))

            b1, b2, b3 = st.columns(3)
            save_row = b1.form_submit_button("💾 Save Row", type="primary")
            swap_row = b2.form_submit_button("🔄 Swap L↔W")
            delete_row = b3.form_submit_button("🗑️ Delete Row")

        if save_row:
            st.session_state['panels'][selected_idx] = {
                "Label": label,
                "Width": width,
                "Length": length,
                "Qty": qty,
                "Grain?": grain,
                "Material": material,
            }
            st.session_state['panels'] = normalize_panels(st.session_state['panels'])
            st.success("Row saved")
            st.rerun()

        if swap_row:
            st.session_state['panels'][selected_idx] = {
                "Label": label,
                "Width": length,
                "Length": width,
                "Qty": qty,
                "Grain?": grain,
                "Material": material,
            }
            st.session_state['panels'] = normalize_panels(st.session_state['panels'])
            st.success("Width and Length swapped")
            st.rerun()

        if delete_row:
            del st.session_state['panels'][selected_idx]
            st.success("Row deleted")
            st.rerun()

        if st.button("🗑️ Clear All Panels"):
            clear_data()
            st.rerun()

    st.write("---")
    if st.button("🚀 RUN SMART NESTING", type="primary", use_container_width=True):
        if not st.session_state['panels']:
            st.warning("Empty.")
        else:
            if MACHINE_TYPE == "Selco":
                packer = run_selco_nesting(st.session_state['panels'], SHEET_W, SHEET_H, MARGIN, KERF)
            else:
                packer = run_smart_nesting(st.session_state['panels'], SHEET_W, SHEET_H, MARGIN, KERF)
            st.session_state.last_packer = packer

            total_input = sum(p['Qty'] for p in st.session_state['panels'])
            total_packed = len(packer.rect_list()) if packer else 0

            if total_packed < total_input:
                missing = total_input - total_packed
                st.error(f"⚠️ CRITICAL WARNING: {missing} panels could not fit on the sheets! Check your Sheet Size or Panel Dimensions.")
            else:
                st.success(f"Success! All {total_packed} panels nested on {len(packer)} Sheets.")

            st.session_state.manual_layout = initialize_layout_from_packer(packer, MARGIN, KERF, SHEET_W, SHEET_H)
            st.session_state.manual_layout_draft = None

with result_tab:
    st.subheader("Nested Results")
    if st.session_state.cix_preview:
        st.markdown("### CIX Machining Preview")
        draw_cix_preview(st.session_state.cix_preview)

    export_col0, export_col1, export_col2, export_col3 = st.columns([2, 1, 1, 1])
    with export_col0:
        nest_name = st.text_input("Nest Name", value="My Nest", key="nest_name_results")
    with export_col1:
        save_payload = build_nest_payload(
            nest_name,
            st.session_state.sheet_w,
            st.session_state.sheet_h,
            st.session_state.margin,
            st.session_state.kerf,
            st.session_state['panels'],
            st.session_state.manual_layout,
            st.session_state.machine_type,
        )
        st.download_button(
            "💾 Save Nest",
            data=payload_to_dxf(save_payload),
            file_name=f"{nest_name.strip().replace(' ', '_') or 'nest'}.dxf",
            mime="application/dxf",
            type="secondary",
            use_container_width=True,
        )
    with export_col2:
        if st.session_state.last_packer:
            dxf = create_dxf_zip(st.session_state.last_packer, st.session_state.sheet_w, st.session_state.sheet_h, st.session_state.margin, st.session_state.kerf)
            st.download_button("💾 DXF", dxf, "nest.zip", "application/zip", type="secondary", use_container_width=True)
    with export_col3:
        if st.session_state.manual_layout and st.session_state.manual_layout.get("sheets"):
            cix_zip = create_cix_zip(st.session_state.manual_layout, st.session_state.cix_preview)
            st.download_button("💾 CIX Programs", cix_zip, "nest_cix.zip", "application/zip", type="secondary", use_container_width=True)

    if st.session_state.manual_layout and st.session_state.manual_layout.get("sheets"):
        preview_sheets = [
            (idx, sheet)
            for idx, sheet in enumerate(st.session_state.manual_layout["sheets"])
            if sheet.get("parts")
        ]

        if not preview_sheets:
            st.warning("No previewable sheets were generated.")
        else:
            sheet_choices = [f"Sheet {sheet['sheet_index'] + 1}" for _, sheet in preview_sheets]
            preview_sheet_label = st.selectbox("Preview Sheet", sheet_choices, key="preview_sheet_select_results")
            preview_sheet_idx = sheet_choices.index(preview_sheet_label)
            actual_sheet_idx = preview_sheets[preview_sheet_idx][0]
            draw_layout_sheet(st.session_state.manual_layout, actual_sheet_idx, template_preview=st.session_state.cix_preview)

        if st.session_state.machine_type == "Flat Bed":
            action_col1, action_col2 = st.columns([1, 2])
            with action_col1:
                if st.button("Manual Nesting Tuning"):
                    st.session_state.manual_layout_draft = copy.deepcopy(st.session_state.manual_layout)
                    first_non_empty_parts = []
                    for sheet in st.session_state.manual_layout_draft["sheets"]:
                        if sheet.get("parts"):
                            first_non_empty_parts = sheet["parts"]
                            break
                    st.session_state.manual_selected_part_id = first_non_empty_parts[0]["id"] if first_non_empty_parts else None
                    st.session_state.manual_part_select = st.session_state.manual_selected_part_id
                    st.session_state.show_manual_tuning = True
                    st.rerun()
            with action_col2:
                st.caption("Manual tuning opens in a popup. Click 'Apply to Nest' to commit your changes.")
        else:
            st.caption("Selco mode: sheet preview only (manual tuning is disabled).")
    else:
        st.info("Run nesting from the Input tab to view results.")

with heat_tab:
    st.subheader("Heat Map & Offcut Summary")
    if st.session_state.manual_layout and st.session_state.manual_layout.get("sheets"):
        preview_sheets = [
            (idx, sheet)
            for idx, sheet in enumerate(st.session_state.manual_layout["sheets"])
            if sheet.get("parts")
        ]
        if not preview_sheets:
            st.warning("No previewable sheets were generated.")
        else:
            sheet_choices = [f"Sheet {sheet['sheet_index'] + 1}" for _, sheet in preview_sheets]
            heat_sheet_label = st.selectbox("Sheet for Analysis", sheet_choices, key="preview_sheet_select_heat")
            heat_sheet_idx = sheet_choices.index(heat_sheet_label)
            actual_sheet_idx = preview_sheets[heat_sheet_idx][0]
            selected_sheet = st.session_state.manual_layout["sheets"][actual_sheet_idx]

            min_offcut_w = st.number_input("Min offcut width (mm)", min_value=0.0, value=120.0, step=10.0, key="min_offcut_w")
            min_offcut_h = st.number_input("Min offcut height (mm)", min_value=0.0, value=120.0, step=10.0, key="min_offcut_h")
            min_offcut_area = st.number_input("Min offcut area (mm²)", min_value=0.0, value=25000.0, step=1000.0, key="min_offcut_area")

            offcuts = calculate_sheet_offcuts(
                st.session_state.manual_layout,
                selected_sheet,
                min_width=min_offcut_w,
                min_height=min_offcut_h,
                min_area=min_offcut_area,
            )

            metrics_col1, metrics_col2, metrics_col3 = st.columns(3)
            metrics_col1.metric("Utilization", f"{offcuts['utilization_pct']}%")
            metrics_col2.metric("Used area", f"{(offcuts['used_area'] / 1_000_000):.2f} m²")
            metrics_col3.metric("Waste area", f"{(offcuts['waste_area'] / 1_000_000):.2f} m²")

            if offcuts["reusable_offcuts"]:
                st.caption(f"Reusable offcuts found: {len(offcuts['reusable_offcuts'])}")
                st.dataframe(pd.DataFrame(offcuts["reusable_offcuts"]), hide_index=True, width="stretch")
            else:
                st.caption("No reusable offcuts match current filter thresholds.")

            st.markdown("#### Sheet Usage Heat Map")
            heat_cell = st.number_input("Heat map cell size (mm)", min_value=25.0, value=150.0, step=25.0, key="heatmap_cell_size")
            heat_rows = build_sheet_usage_heatmap(st.session_state.manual_layout, selected_sheet, cell_size=heat_cell)
            if heat_rows:
                heat_df = pd.DataFrame(heat_rows)
                heat_chart = (
                    alt.Chart(heat_df)
                    .mark_rect()
                    .encode(
                        x=alt.X("x:Q", title="X (mm)"),
                        x2="x2:Q",
                        y=alt.Y("y:Q", title="Y (mm)"),
                        y2="y2:Q",
                        color=alt.Color("usage_pct:Q", title="Usage %", scale=alt.Scale(scheme="yelloworangered", domain=[0, 100])),
                        tooltip=[
                            alt.Tooltip("x:Q", title="X"),
                            alt.Tooltip("y:Q", title="Y"),
                            alt.Tooltip("usage_pct:Q", title="Usage %"),
                            alt.Tooltip("used_area:Q", title="Used area"),
                            alt.Tooltip("cell_area:Q", title="Cell area"),
                        ],
                    )
                    .properties(height=360)
                )
                st.altair_chart(heat_chart, width="stretch")
                st.caption("Darker cells are more heavily used by parts; lighter cells indicate likely reclaimable space.")
    else:
        st.info("Run nesting from the Input tab to generate offcut and heat map analytics.")

if st.session_state.show_manual_tuning and st.session_state.manual_layout_draft:
    manual_tuning_dialog()
