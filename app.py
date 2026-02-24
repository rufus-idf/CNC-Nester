import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import io
import csv
import zipfile
import json
import ezdxf
from streamlit_gsheets import GSheetsConnection
from nesting_engine import run_smart_nesting
from panel_utils import normalize_panels
from nest_storage import build_nest_payload, parse_nest_payload, payload_to_json

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


# --- HELPERS ---
def add_panel(w, l, q, label, grain, mat):
    st.session_state['panels'].append({
        "Label": label, "Width": w, "Length": l, "Qty": q,
        "Grain?": grain, "Material": mat
    })


def clear_data():
    st.session_state['panels'] = []


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


def update_sheet_dims():
    preset = st.session_state.sheet_preset
    if preset == "MDF (2800 x 2070)":
        st.session_state.sheet_w = 2800.0
        st.session_state.sheet_h = 2070.0
    elif preset == "Ply (3050 x 1220)":
        st.session_state.sheet_w = 3050.0
        st.session_state.sheet_h = 1220.0


# --- SIDEBAR ---
st.sidebar.header("⚙️ Machine Settings")
st.sidebar.selectbox("Select Sheet Size", ["Custom", "MDF (2800 x 2070)", "Ply (3050 x 1220)"], index=0, key="sheet_preset", on_change=update_sheet_dims)
SHEET_W = st.sidebar.number_input("Sheet Width", key="sheet_w", step=10.0)
SHEET_H = st.sidebar.number_input("Sheet Height", key="sheet_h", step=10.0)
KERF = st.sidebar.number_input("Kerf", key="kerf")
MARGIN = st.sidebar.number_input("Margin", key="margin")

# --- MAIN PAGE ---
st.title("🪚 CNC Nester Pro (Robust)")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("1. Input")
    tab1, tab2, tab3 = st.tabs(["☁️ G-Sheets", "Manual", "Paste"])

    with tab1:
        if st.button("🔄 Refresh"):
            st.cache_data.clear()
        try:
            conn = st.connection("gsheets", type=GSheetsConnection)
            df = conn.read()
            cols = ["Product Name", "Panel Name", "Material", "Length (mm)", "Width (mm)", "Qty Per Unit"]
            if all(c in df.columns for c in cols):
                prods = df["Product Name"].dropna().unique()
                sel_prod = st.selectbox("Product", prods)
                qty = st.number_input("Build Qty", 1, 1000, 1)
                mats = df[df["Product Name"] == sel_prod]["Material"].unique()
                sel_mats = st.multiselect("Material", mats, default=mats)

                subset = df[(df["Product Name"] == sel_prod) & (df["Material"].isin(sel_mats))]

                prev_cols = ["Panel Name", "Material", "Qty Per Unit", "Length (mm)", "Width (mm)"]
                if "Shopify SKU" in df.columns:
                    prev_cols.insert(0, "Shopify SKU")
                st.dataframe(subset[prev_cols], hide_index=True)

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

    with tab2:
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

    with tab3:
        pq = st.number_input("Prod Multi", 1)
        mf = st.text_input("Mat Filter")
        txt = st.text_area("Paste (Name|Mat|Qty|Len|Wid)")
        if st.button("Process"):
            try:
                f = io.StringIO(txt)
                rdr = csv.reader(f, delimiter='\t')
                c = 0
                for r in rdr:
                    if len(r) >= 5 and (mf.lower() in r[1].lower()):
                        add_panel(float(r[4]), float(r[3]), int(r[2]) * pq, r[0], False, r[1])
                        c += 1
                st.success(f"Added {c}")
            except Exception:
                st.error("Error")

    st.write("---")
    st.markdown("### Save / Load Nest")
    nest_name = st.text_input("Nest Name", value="My Nest")

    save_payload = build_nest_payload(nest_name, SHEET_W, SHEET_H, MARGIN, KERF, st.session_state['panels'])
    st.download_button(
        "💾 Save Nest",
        data=payload_to_json(save_payload),
        file_name=f"{nest_name.strip().replace(' ', '_') or 'nest'}.json",
        mime="application/json",
        type="secondary",
    )

    uploaded_nest = st.file_uploader("📂 Load Nest", type=["json"], accept_multiple_files=False)
    if uploaded_nest is not None:
        try:
            payload = json.loads(uploaded_nest.read().decode("utf-8"))
            loaded = parse_nest_payload(payload)
            st.session_state.sheet_w = loaded["sheet_w"]
            st.session_state.sheet_h = loaded["sheet_h"]
            st.session_state.kerf = loaded["kerf"]
            st.session_state.margin = loaded["margin"]
            st.session_state["panels"] = loaded["panels"]
            st.success(f"Loaded nest: {loaded['nest_name']}")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to load nest file: {e}")

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

with col2:
    st.subheader("2. Result")
    if st.button("🚀 RUN SMART NESTING", type="primary"):
        if not st.session_state['panels']:
            st.warning("Empty.")
        else:
            packer = run_smart_nesting(st.session_state['panels'], SHEET_W, SHEET_H, MARGIN, KERF)

            total_input = sum(p['Qty'] for p in st.session_state['panels'])
            total_packed = len(packer.rect_list()) if packer else 0

            if total_packed < total_input:
                missing = total_input - total_packed
                st.error(f"⚠️ CRITICAL WARNING: {missing} panels could not fit on the sheets! Check your Sheet Size or Panel Dimensions.")
            else:
                st.success(f"Success! All {total_packed} panels nested on {len(packer)} Sheets.")

            dxf = create_dxf_zip(packer, SHEET_W, SHEET_H, MARGIN, KERF)
            st.download_button("💾 DXF", dxf, "nest.zip", "application/zip", type="secondary")

            tabs = st.tabs([f"Sheet {i + 1}" for i in range(len(packer))])
            for i, bin in enumerate(packer):
                with tabs[i]:
                    fig, ax = plt.subplots(figsize=(10, 6))
                    ax.set_xlim(0, SHEET_W)
                    ax.set_ylim(0, SHEET_H)
                    ax.set_aspect('equal')
                    ax.axis('off')
                    ax.add_patch(patches.Rectangle((0, 0), SHEET_W, SHEET_H, fc='#f4f4f4', ec='#333'))
                    ax.add_patch(patches.Rectangle((MARGIN, MARGIN), SHEET_W - 2 * MARGIN, SHEET_H - 2 * MARGIN, ec='red', ls='--', fc='none'))

                    for r in bin:
                        x = r.x + MARGIN
                        y = r.y + MARGIN
                        w = r.width - KERF
                        h = r.height - KERF
                        fc = '#8b4513' if "(G)" in str(r.rid) else '#d2b48c'
                        ax.add_patch(patches.Rectangle((x, y), w, h, fc=fc, ec='#222'))
                        ax.text(x + w / 2, y + h / 2, f"{r.rid}\n{int(w)}x{int(h)}", ha='center', va='center', fontsize=8 if w > 100 else 6, color='white' if fc == '#8b4513' else 'black')
                    st.pyplot(fig)
