import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import io
import csv
import zipfile
import ezdxf
from rectpack import newPacker, PackingMode, MaxRectsBl, MaxRectsBssf, MaxRectsBaf
from streamlit_gsheets import GSheetsConnection

# --- PAGE CONFIG ---
st.set_page_config(page_title="CNC Nester Pro", layout="wide")

# --- SESSION STATE ---
if 'panels' not in st.session_state:
    st.session_state['panels'] = []
if 'sheet_w' not in st.session_state:
    st.session_state.sheet_w = 2440.0
if 'sheet_h' not in st.session_state:
    st.session_state.sheet_h = 1220.0

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
                points = [(x, y), (x+w, y), (x+w, y+h), (x, y+h), (x, y)]
                msp.add_lwpolyline(points, dxfattribs={'layer': 'CUT_LINES'})
                label_text = str(rect.rid) if rect.rid else "Part"
                msp.add_text(label_text, dxfattribs={'layer': 'LABELS', 'height': 20}).set_placement((x + w/2, y + h/2), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
                size_text = f"{int(w)}x{int(h)}"
                msp.add_text(size_text, dxfattribs={'layer': 'LABELS', 'height': 15}).set_placement((x + w/2, y + h/2 - 25), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
            dxf_io = io.StringIO()
            doc.write(dxf_io)
            zip_file.writestr(f"Sheet_{i+1}.dxf", dxf_io.getvalue())
    return zip_buffer.getvalue()

def update_sheet_dims():
    preset = st.session_state.sheet_preset
    if preset == "MDF (2800 x 2070)":
        st.session_state.sheet_w = 2800.0
        st.session_state.sheet_h = 2070.0
    elif preset == "Ply (3050 x 1220)":
        st.session_state.sheet_w = 3050.0
        st.session_state.sheet_h = 1220.0

# --- ROBUST SOLVER ENGINE ---
def solve_packer(panels, sheet_w, sheet_h, margin, kerf, rotate_flexible_panels=False):
    """
    Runs one specific rotation strategy.
    Returns: (packer_object, items_packed_count, num_sheets)
    """
    usable_w = sheet_w - (margin * 2)
    usable_h = sheet_h - (margin * 2)
    
    # We test 3 packing algorithms for this strategy
    algos = [MaxRectsBl, MaxRectsBssf, MaxRectsBaf]
    
    best_algo_packer = None
    best_algo_items = -1
    best_algo_sheets = float('inf')
    
    # Calculate total expected items for safety loop
    total_input_items = sum(p['Qty'] for p in panels)
    
    for algo in algos:
        packer = newPacker(mode=PackingMode.Offline, pack_algo=algo, rotation=False)
        
        # ADD RECTANGLES
        for p in panels:
            for _ in range(p['Qty']):
                p_w = p['Width']
                p_l = p['Length']
                grain = p['Grain?']
                rid_label = f"{p['Label']}{'(G)' if grain else ''}"
                
                real_w = p_w + kerf
                real_l = p_l + kerf
                
                # APPLY ROTATION STRATEGY
                if grain:
                    # Locked Grain: Must use input dims
                    packer.add_rect(real_w, real_l, rid=rid_label)
                else:
                    if rotate_flexible_panels:
                        # Strategy B: Force Rotate
                        packer.add_rect(real_l, real_w, rid=rid_label)
                    else:
                        # Strategy A: Keep Original
                        packer.add_rect(real_w, real_l, rid=rid_label)

        # ADD BINS (Dynamic safety limit)
        # We add enough bins to cover worst case (1 item per sheet + buffer)
        safety_bins = max(300, total_input_items + 50)
        for _ in range(safety_bins):
            packer.add_bin(usable_w, usable_h)

        packer.pack()
        
        # SCORING THE ALGO
        items_packed = len(packer.rect_list())
        sheets_used = len(packer)
        
        # PRIORITIZE MAX ITEMS, THEN MIN SHEETS
        if items_packed > best_algo_items:
            best_algo_packer = packer
            best_algo_items = items_packed
            best_algo_sheets = sheets_used
        elif items_packed == best_algo_items:
            if sheets_used < best_algo_sheets:
                best_algo_packer = packer
                best_algo_sheets = sheets_used
    
    return best_algo_packer

def run_smart_nesting(panels, sheet_w, sheet_h, margin, kerf):
    # RUN SIMULATION A (Standard)
    packer_a = solve_packer(panels, sheet_w, sheet_h, margin, kerf, False)
    items_a = len(packer_a.rect_list()) if packer_a else 0
    sheets_a = len(packer_a) if packer_a else float('inf')

    # RUN SIMULATION B (Rotated 90)
    packer_b = solve_packer(panels, sheet_w, sheet_h, margin, kerf, True)
    items_b = len(packer_b.rect_list()) if packer_b else 0
    sheets_b = len(packer_b) if packer_b else float('inf')
    
    # COMPARE SIMULATIONS
    # 1. Who packed more items? (The most critical check!)
    if items_b > items_a:
        return packer_b
    elif items_a > items_b:
        return packer_a
    else:
        # 2. If tied on items, who used fewer sheets?
        if sheets_b < sheets_a:
            return packer_b
        else:
            return packer_a

# --- SIDEBAR ---
st.sidebar.header("⚙️ Machine Settings")
st.sidebar.selectbox("Select Sheet Size", ["Custom", "MDF (2800 x 2070)", "Ply (3050 x 1220)"], index=0, key="sheet_preset", on_change=update_sheet_dims)
SHEET_W = st.sidebar.number_input("Sheet Width", key="sheet_w", step=10.0)
SHEET_H = st.sidebar.number_input("Sheet Height", key="sheet_h", step=10.0)
KERF = st.sidebar.number_input("Kerf", value=6.0)
MARGIN = st.sidebar.number_input("Margin", value=10.0)

# --- MAIN PAGE ---
st.title("🪚 CNC Nester Pro (Robust)")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("1. Input")
    tab1, tab2, tab3 = st.tabs(["☁️ G-Sheets", "Manual", "Paste"])
    
    with tab1:
        if st.button("🔄 Refresh"): st.cache_data.clear()
        try:
            conn = st.connection("gsheets", type=GSheetsConnection)
            df = conn.read()
            cols = ["Product Name", "Panel Name", "Material", "Length (mm)", "Width (mm)", "Qty Per Unit"]
            if all(c in df.columns for c in cols):
                prods = df["Product Name"].dropna().unique()
                sel_prod = st.selectbox("Product", prods)
                qty = st.number_input("Build Qty", 1, 1000, 1)
                mats = df[df["Product Name"]==sel_prod]["Material"].unique()
                sel_mats = st.multiselect("Material", mats, default=mats)
                
                subset = df[(df["Product Name"]==sel_prod) & (df["Material"].isin(sel_mats))]
                
                prev_cols = ["Panel Name", "Material", "Qty Per Unit", "Length (mm)", "Width (mm)"]
                if "Shopify SKU" in df.columns: prev_cols.insert(0, "Shopify SKU")
                st.dataframe(subset[prev_cols], hide_index=True)
                
                if st.button("➕ Add Product"):
                    c=0
                    for i,r in subset.iterrows():
                        add_panel(float(r["Width (mm)"]), float(r["Length (mm)"]), int(r["Qty Per Unit"])*qty, r["Panel Name"], False, r["Material"])
                        c+=1
                    if c: st.success(f"Added {c} items")
            else: st.error(f"Missing headers. Needed: {cols}")
        except Exception as e: st.warning(f"Connection error: {e}")

    with tab2:
        with st.form("man"):
            c1,c2 = st.columns(2)
            w=c1.number_input("W", step=10.0); l=c2.number_input("L", step=10.0)
            c3,c4 = st.columns(2)
            q=c3.number_input("Qty", 1, 100, 1); g=c4.checkbox("Grain? (Fixed)")
            lbl=st.text_input("Label", "Part")
            if st.form_submit_button("Add"):
                add_panel(w,l,q,lbl,g,"Manual")
                st.success("Added")

    with tab3:
        pq = st.number_input("Prod Multi", 1); mf = st.text_input("Mat Filter")
        txt = st.text_area("Paste (Name|Mat|Qty|Len|Wid)")
        if st.button("Process"):
            try:
                f=io.StringIO(txt); rdr=csv.reader(f, delimiter='\t')
                c=0
                for r in rdr:
                    if len(r)>=5 and (mf.lower() in r[1].lower()):
                        add_panel(float(r[4]), float(r[3]), int(r[2])*pq, r[0], False, r[1])
                        c+=1
                st.success(f"Added {c}")
            except: st.error("Error")

    if st.session_state['panels']:
        st.write("---")
        df_ed = pd.DataFrame(st.session_state['panels'])
        edited = st.data_editor(df_ed, use_container_width=True, num_rows="dynamic", hide_index=True,
                                column_config={"Grain?": st.column_config.CheckboxColumn("Grain?", default=False)})
        st.session_state['panels'] = edited.to_dict('records')
        if st.button("🗑️ Clear"): clear_data(); st.rerun()

with col2:
    st.subheader("2. Result")
    if st.button("🚀 RUN SMART NESTING", type="primary"):
        if not st.session_state['panels']: st.warning("Empty.")
        else:
            # RUN NESTING
            packer = run_smart_nesting(st.session_state['panels'], SHEET_W, SHEET_H, MARGIN, KERF)
            
            # CHECK FOR MISSING ITEMS
            total_input = sum(p['Qty'] for p in st.session_state['panels'])
            total_packed = len(packer.rect_list()) if packer else 0
            
            if total_packed < total_input:
                missing = total_input - total_packed
                st.error(f"⚠️ CRITICAL WARNING: {missing} panels could not fit on the sheets! Check your Sheet Size or Panel Dimensions.")
            else:
                st.success(f"Success! All {total_packed} panels nested on {len(packer)} Sheets.")
            
            dxf = create_dxf_zip(packer, SHEET_W, SHEET_H, MARGIN, KERF)
            st.download_button("💾 DXF", dxf, "nest.zip", "application/zip", type="secondary")

            tabs = st.tabs([f"Sheet {i+1}" for i in range(len(packer))])
            for i, bin in enumerate(packer):
                with tabs[i]:
                    fig, ax = plt.subplots(figsize=(10, 6))
                    ax.set_xlim(0, SHEET_W); ax.set_ylim(0, SHEET_H); ax.set_aspect('equal'); ax.axis('off')
                    ax.add_patch(patches.Rectangle((0,0), SHEET_W, SHEET_H, fc='#f4f4f4', ec='#333'))
                    ax.add_patch(patches.Rectangle((MARGIN,MARGIN), SHEET_W-2*MARGIN, SHEET_H-2*MARGIN, ec='red', ls='--', fc='none'))
                    
                    for r in bin:
                        x=r.x+MARGIN; y=r.y+MARGIN; w=r.width-KERF; h=r.height-KERF
                        fc = '#8b4513' if "(G)" in str(r.rid) else '#d2b48c'
                        ax.add_patch(patches.Rectangle((x,y), w, h, fc=fc, ec='#222'))
                        ax.text(x+w/2, y+h/2, f"{r.rid}\n{int(w)}x{int(h)}", ha='center', va='center', fontsize=8 if w>100 else 6, color='white' if fc=='#8b4513' else 'black')
                    st.pyplot(fig)
