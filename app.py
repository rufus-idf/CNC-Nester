import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import io
import csv
import zipfile
import ezdxf
from rectpack import newPacker, PackingMode, MaxRectsBl
from streamlit_gsheets import GSheetsConnection

# --- PAGE CONFIG ---
st.set_page_config(page_title="CNC Nester Pro", layout="wide")

# --- SESSION STATE INITIALIZATION ---
if 'panels' not in st.session_state:
    st.session_state['panels'] = []

# Initialize Sheet Dimension State if not present
if 'sheet_w' not in st.session_state:
    st.session_state.sheet_w = 2440.0
if 'sheet_h' not in st.session_state:
    st.session_state.sheet_h = 1220.0

# --- LOGIC FUNCTIONS ---
def add_panel(w, l, q, label, rot, mat):
    st.session_state['panels'].append({
        "Width": w, "Length": l, "Qty": q, "Label": label, "Rot": rot, "Material": mat
    })

def clear_data():
    st.session_state['panels'] = []

def create_dxf_zip(packer, sheet_w, sheet_h, margin, kerf):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for i, bin in enumerate(packer):
            doc = ezdxf.new()
            msp = doc.modelspace()
            
            # Layers
            doc.layers.new(name='SHEET_BOUNDARY', dxfattribs={'color': 1}) 
            doc.layers.new(name='CUT_LINES', dxfattribs={'color': 3})      
            doc.layers.new(name='LABELS', dxfattribs={'color': 7})         

            # Boundary
            msp.add_lwpolyline([(0, 0), (sheet_w, 0), (sheet_w, sheet_h), (0, sheet_h), (0, 0)], dxfattribs={'layer': 'SHEET_BOUNDARY'})
            
            # Panels
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

# --- CALLBACK FOR PRESETS ---
def update_sheet_dims():
    preset = st.session_state.sheet_preset
    if preset == "MDF (2800 x 2070)":
        st.session_state.sheet_w = 2800.0
        st.session_state.sheet_h = 2070.0
    elif preset == "Ply (3050 x 1220)":
        st.session_state.sheet_w = 3050.0
        st.session_state.sheet_h = 1220.0
    # If Custom, we leave values as they are

# --- SIDEBAR: SETTINGS ---
st.sidebar.header("⚙️ Machine Settings")

# 1. Preset Dropdown
st.sidebar.selectbox(
    "Select Sheet Size",
    options=["Custom", "MDF (2800 x 2070)", "Ply (3050 x 1220)"],
    index=0,
    key="sheet_preset",
    on_change=update_sheet_dims
)

# 2. Dimensions (Linked to session state)
SHEET_W = st.sidebar.number_input("Sheet Width (mm)", key="sheet_w", step=10.0)
SHEET_H = st.sidebar.number_input("Sheet Height (mm)", key="sheet_h", step=10.0)

# 3. Other Settings
KERF = st.sidebar.number_input("Kerf / Blade (mm)", value=6.0)
MARGIN = st.sidebar.number_input("Safety Margin (mm)", value=10.0)


# --- MAIN PAGE ---
st.title("🪚 CNC Nester Pro (Google Sheets + Presets)")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("1. Input Panels")
    
    tab1, tab2, tab3 = st.tabs(["☁️ Load from Google Sheet", "Manual Entry", "Paste Data"])
    
    # --- TAB 1: GOOGLE SHEETS ---
    with tab1:
        st.info("Connects to your Master Product Sheet")
        if st.button("🔄 Refresh Data from Google"):
            st.cache_data.clear()
            
        try:
            conn = st.connection("gsheets", type=GSheetsConnection)
            df = conn.read()
            
            required_cols = ["Product Name", "Panel Name", "Material", "Length (mm)", "Width (mm)", "Qty Per Unit"]
            missing = [c for c in required_cols if c not in df.columns]
            
            if missing:
                st.error(f"Missing columns: {missing}")
            else:
                unique_products = df["Product Name"].dropna().unique()
                selected_product = st.selectbox("Select Product to Build", unique_products)
                
                build_qty = st.number_input("How many do you want to build?", min_value=1, value=1)
                
                unique_mats = df[df["Product Name"] == selected_product]["Material"].unique()
                selected_mat_filter = st.multiselect("Filter Material (Optional)", unique_mats, default=unique_mats)
                
                subset = df[
                    (df["Product Name"] == selected_product) & 
                    (df["Material"].isin(selected_mat_filter))
                ]
                
                st.caption(f"Found {len(subset)} panel types.")
                
                # Show SKU if exists
                preview_cols = ["Panel Name", "Material", "Qty Per Unit", "Length (mm)", "Width (mm)"]
                if "Shopify SKU" in df.columns:
                    preview_cols.insert(0, "Shopify SKU")
                    
                st.dataframe(subset[preview_cols], hide_index=True)
                
                if st.button("➕ Add Product to Nest", type="primary"):
                    count = 0
                    for index, row in subset.iterrows():
                        try:
                            p_name = row["Panel Name"]
                            p_mat = row["Material"]
                            p_len = float(row["Length (mm)"])
                            p_wid = float(row["Width (mm)"])
                            p_unit_qty = int(row["Qty Per Unit"])
                            
                            total_qty = p_unit_qty * build_qty
                            
                            add_panel(p_wid, p_len, total_qty, p_name, True, p_mat)
                            count += 1
                        except Exception as e:
                            st.error(f"Error reading row {index}: {e}")
                    
                    if count > 0:
                        st.success(f"Added {count} parts to Cut List!")

        except Exception as e:
            st.warning("Could not connect to Google Sheets.")
            st.error(f"Error: {e}")

    # --- TAB 2: MANUAL ---
    with tab2:
        with st.form("add_panel_form"):
            c1, c2 = st.columns(2)
            w = c1.number_input("Width", min_value=1.0, step=10.0)
            l = c2.number_input("Length", min_value=1.0, step=10.0)
            c3, c4 = st.columns(2)
            q = c3.number_input("Qty", min_value=1, value=1, step=1)
            rot = c4.checkbox("Allow Rotation?", value=True)
            label = st.text_input("Label", value="Part")
            
            if st.form_submit_button("➕ Add Panel"):
                add_panel(w, l, q, label, rot, "Manual")
                st.success(f"Added {q}x {label}")

    # --- TAB 3: PASTE ---
    with tab3:
        st.info("Paste Data (No Headers): Name | Material | Qty | Length | Width")
        product_qty = st.number_input("Multiplier (Products)", min_value=1, value=1)
        mat_filter = st.text_input("Filter Material", value="")
        paste_data = st.text_area("Paste Data Here")
        
        if st.button("🚀 Process Paste"):
            if not paste_data.strip():
                st.warning("Empty.")
            else:
                try:
                    f = io.StringIO(paste_data)
                    reader = csv.reader(f, delimiter='\t')
                    count = 0
                    for row in reader:
                        if not row or len(row) < 5: continue
                        try:
                            name_val = row[0].strip()
                            mat_val = row[1].strip()
                            unit_qty = int(row[2])
                            l_val = float(row[3]) 
                            w_val = float(row[4]) 
                            
                            if mat_filter.lower() in mat_val.lower():
                                total_qty = unit_qty * product_qty
                                add_panel(w_val, l_val, total_qty, name_val, True, mat_val)
                                count += 1
                        except ValueError: continue

                    if count > 0: st.success(f"Imported {count} panels!")
                except Exception as e: st.error(f"Error: {e}")

    # --- CURRENT LIST ---
    if st.session_state['panels']:
        st.write("---")
        st.subheader("Current Cut List")
        df_disp = pd.DataFrame(st.session_state['panels'])
        st.dataframe(df_disp, use_container_width=True)
        if st.button("🗑️ Clear List"):
            clear_data()
            st.rerun()

with col2:
    st.subheader("2. Visualization & Export")
    
    if st.button("🚀 RUN NESTING & GENERATE DXF", type="primary", use_container_width=True):
        if not st.session_state['panels']:
            st.warning("Add panels first.")
        else:
            packer = newPacker(mode=PackingMode.Offline, pack_algo=MaxRectsBl, rotation=True)
            usable_w = SHEET_W - (MARGIN * 2)
            usable_h = SHEET_H - (MARGIN * 2)
            
            total_qty = 0
            for p in st.session_state['panels']:
                for _ in range(p['Qty']):
                    packer.add_rect(p['Width'] + KERF, p['Length'] + KERF, rid=p['Label'])
                    total_qty += 1
            
            packer.add_bin(usable_w, usable_h)
            packer.pack()
            
            max_s = 300
            while sum(len(b) for b in packer) < total_qty:
                 if len(packer) > max_s: break
                 packer.add_bin(usable_w, usable_h)
                 packer.pack()

            st.success(f"Total Sheets: {len(packer)}")
            
            dxf_zip = create_dxf_zip(packer, SHEET_W, SHEET_H, MARGIN, KERF)
            st.download_button(
                label="💾 DOWNLOAD DXF FILES (ZIP)",
                data=dxf_zip,
                file_name="nesting_results.zip",
                mime="application/zip",
                type="secondary"
            )

            sheet_tabs = st.tabs([f"Sheet {i+1}" for i in range(len(packer))])
            for i, bin in enumerate(packer):
                with sheet_tabs[i]:
                    fig, ax = plt.subplots(figsize=(10, 5))
                    ax.set_xlim(0, SHEET_W)
                    ax.set_ylim(0, SHEET_H)
                    ax.set_aspect('equal')
                    ax.axis('off')
                    
                    ax.add_patch(patches.Rectangle((0, 0), SHEET_W, SHEET_H, edgecolor='#333', facecolor='#f4f4f4'))
                    ax.add_patch(patches.Rectangle((MARGIN, MARGIN), SHEET_W-2*MARGIN, SHEET_H-2*MARGIN, edgecolor='red', linestyle='--', facecolor='none'))

                    for rect in bin:
                        x = rect.x + MARGIN
                        y = rect.y + MARGIN
                        w = rect.width - KERF
                        h = rect.height - KERF
                        ax.add_patch(patches.Rectangle((x, y), w, h, edgecolor='#222', facecolor='#d2b48c'))
                        font_s = 8 if w > 100 else 6
                        ax.text(x + w/2, y + h/2, f"{rect.rid}\n{int(w)}x{int(h)}", ha='center', va='center', fontsize=font_s)
                    
                    st.pyplot(fig)
