import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import io
import csv
from rectpack import newPacker, PackingMode, MaxRectsBl

# --- PAGE CONFIG ---
st.set_page_config(page_title="CNC Nester Pro", layout="wide")

# --- SESSION STATE ---
if 'panels' not in st.session_state:
    st.session_state['panels'] = []

# --- LOGIC ---
def add_panel(w, l, q, label, rot):
    # Add to session state
    st.session_state['panels'].append({
        "Width": w, "Length": l, "Qty": q, "Label": label, "Rot": rot
    })

def clear_data():
    st.session_state['panels'] = []

# --- SIDEBAR: SETTINGS ---
st.sidebar.header("⚙️ Machine Settings")
SHEET_W = st.sidebar.number_input("Sheet Width (mm)", value=2800)
SHEET_H = st.sidebar.number_input("Sheet Height (mm)", value=2070)
KERF = st.sidebar.number_input("Kerf / Blade (mm)", value=6.0)
MARGIN = st.sidebar.number_input("Safety Margin (mm)", value=10.0)

# --- MAIN PAGE ---
st.title("🪚 CNC Nester Pro (Production Edition)")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("1. Input Panels")
    
    # Tabs
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
            
            submitted = st.form_submit_button("➕ Add Panel")
            if submitted:
                add_panel(w, l, q, label, rot)
                st.success(f"Added {q}x {label}")

    with tab2:
        st.info("Paste the breakdown for **1 Single Product** below.")
        
        # NEW: Product Multiplier
        product_qty = st.number_input("How many Products are you building?", min_value=1, value=1, step=1)
        
        paste_data = st.text_area("Paste Excel Data (Width, Length, Qty per Product)")
        
        if st.button("🚀 Calculate & Add All Panels"):
            try:
                f = io.StringIO(paste_data)
                reader = csv.DictReader(f, delimiter='\t')
                
                # Clean headers
                if reader.fieldnames:
                    reader.fieldnames = [n.strip() for n in reader.fieldnames]
                
                col_map = {}
                for field in reader.fieldnames or []:
                    lf = field.lower()
                    if "width" in lf: col_map['width'] = field
                    if "length" in lf: col_map['length'] = field
                    if "qty" in lf or "quantity" in lf: col_map['qty'] = field
                    if "panel name" in lf: col_map['name'] = field
                
                if not all(k in col_map for k in ('width', 'length', 'qty')):
                    st.error("Could not find 'Width', 'Length' or 'Qty' columns in headers.")
                else:
                    count = 0
                    for row in reader:
                        try:
                            w_val = float(row[col_map['width']])
                            l_val = float(row[col_map['length']])
                            
                            # THE MAGIC: Multiply Unit Qty by Product Qty
                            unit_qty = int(row[col_map['qty']])
                            total_qty = unit_qty * product_qty
                            
                            name_val = row.get(col_map.get('name', ''), "Part")
                            
                            add_panel(w_val, l_val, total_qty, name_val, True)
                            count += 1
                        except ValueError:
                            continue
                    
                    if count > 0:
                        st.success(f"Successfully added panels for {product_qty} products! ({count} unique parts loaded)")
                    else:
                        st.warning("No valid rows found.")
                        
            except Exception as e:
                st.error(f"Error parsing data: {e}")

    # Show Current List
    if st.session_state['panels']:
        st.write("---")
        st.subheader("Total Cut List")
        df = pd.DataFrame(st.session_state['panels'])
        st.dataframe(df, use_container_width=True)
        
        if st.button("🗑️ Clear List"):
            clear_data()
            st.rerun()

with col2:
    st.subheader("2. Visualization")
    
    if st.button("🚀 RUN NESTING CALCULATION", type="primary", use_container_width=True):
        if not st.session_state['panels']:
            st.warning("Add some panels first!")
        else:
            packer = newPacker(mode=PackingMode.Offline, pack_algo=MaxRectsBl, rotation=True)
            
            usable_w = SHEET_W - (MARGIN * 2)
            usable_h = SHEET_H - (MARGIN * 2)
            
            # Add rectangles
            total_qty = 0
            for p in st.session_state['panels']:
                for _ in range(p['Qty']):
                    packer.add_rect(p['Width'] + KERF, p['Length'] + KERF, rid=p['Label'])
                    total_qty += 1
            
            # Add first bin
            packer.add_bin(usable_w, usable_h)
            packer.pack()
            
            # Add more bins loop
            max_safety = 300
            
            def count_packed():
                return sum(len(b) for b in packer)

            while count_packed() < total_qty:
                 if len(packer) > max_safety:
                     st.error("Too many sheets needed (over 300)!")
                     break
                 packer.add_bin(usable_w, usable_h)
                 packer.pack()

            # --- DISPLAY RESULTS ---
            st.success(f"Total Sheets Required: {len(packer)}")
            st.info(f"Total Panels Nested: {total_qty}")
            
            sheet_tabs = st.tabs([f"Sheet {i+1}" for i in range(len(packer))])
            
            for i, bin in enumerate(packer):
                with sheet_tabs[i]:
                    fig, ax = plt.subplots(figsize=(10, 5))
                    ax.set_xlim(0, SHEET_W)
                    ax.set_ylim(0, SHEET_H)
                    ax.set_aspect('equal')
                    ax.axis('off')

                    # Draw Sheet
                    ax.add_patch(patches.Rectangle((0, 0), SHEET_W, SHEET_H, edgecolor='#333', facecolor='#f4f4f4'))
                    # Draw Margin
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

