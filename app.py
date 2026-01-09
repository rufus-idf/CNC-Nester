import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import io
import csv
import zipfile
import ezdxf
from rectpack import newPacker, PackingMode, MaxRectsBl

# --- PAGE CONFIG ---
st.set_page_config(page_title="CNC Nester Pro", layout="wide")

# --- SESSION STATE ---
if 'panels' not in st.session_state:
    st.session_state['panels'] = []

# --- HELPER FUNCTIONS ---
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

# --- SIDEBAR: SETTINGS ---
st.sidebar.header("⚙️ Machine Settings")
SHEET_W = st.sidebar.number_input("Sheet Width (mm)", value=2800.0)
SHEET_H = st.sidebar.number_input("Sheet Height (mm)", value=2070.0)
KERF = st.sidebar.number_input("Kerf / Blade (mm)", value=6.0)
MARGIN = st.sidebar.number_input("Safety Margin (mm)", value=10.0)

# --- MAIN PAGE ---
st.title("🪚 CNC Nester Pro (Product Import Edition)")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("1. Input Panels")
    
    tab1, tab2 = st.tabs(["Manual Entry", "Add Product Panels"])
    
    with tab1:
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

    with tab2:
        st.info("Paste Excel Data (No Headers): **Name | Material | Qty | Length | Width**")
        
        # Product Multiplier
        product_qty = st.number_input("How many Products are you building?", min_value=1, value=1, step=1)
        
        # Material Filter (Optional)
        mat_filter = st.text_input("Filter Material (e.g. 'Oak' or leave empty for all)", value="")
        
        paste_data = st.text_area("Paste Data Here")
        
        if st.button("🚀 Process & Add Panels"):
            if not paste_data.strip():
                st.warning("Paste box is empty.")
            else:
                try:
                    # Parse assuming TAB delimiters (Excel default)
                    # We use csv.reader instead of DictReader since there are no headers
                    f = io.StringIO(paste_data)
                    reader = csv.reader(f, delimiter='\t')
                    
                    count = 0
                    skipped = 0
                    
                    for row in reader:
                        # Skip empty rows
                        if not row or len(row) < 5:
                            continue
                            
                        # MAPPING:
                        # Col 0: Name
                        # Col 1: Material
                        # Col 2: Qty
                        # Col 3: Length
                        # Col 4: Width
                        
                        try:
                            name_val = row[0].strip()
                            mat_val = row[1].strip()
                            unit_qty = int(row[2])
                            l_val = float(row[3]) # Your data had Length in col 3
                            w_val = float(row[4]) # Your data had Width in col 4
                            
                            # Filter Logic
                            if mat_filter.lower() in mat_val.lower():
                                total_qty = unit_qty * product_qty
                                add_panel(w_val, l_val, total_qty, name_val, True, mat_val)
                                count += 1
                            else:
                                skipped += 1
                                
                        except ValueError:
                            # Skip rows that have text instead of numbers in size cols
                            continue

                    if count > 0:
                        st.success(f"Imported {count} panels! (Skipped {skipped} due to material filter)")
                    else:
                        st.warning("No panels imported. Check your filter or paste format.")
                        
                except Exception as e:
                    st.error(f"Error reading data: {e}")

    if st.session_state['panels']:
        st.write("---")
        st.subheader("Current Cut List")
        st.dataframe(pd.DataFrame(st.session_state['panels']), use_container_width=True)
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

