import streamlit as st
import pandas as pd
from datetime import datetime
import os

# 1. Set page config FIRST
st.set_page_config(page_title="Food Waste Reporting", page_icon="🍽️")

def main():
    # 2. Maintain state across interactions
    if 'num_products' not in st.session_state:
        st.session_state.num_products = 0
    
    if 'wastage_items' not in st.session_state:
        st.session_state.wastage_items = []

    # 3. Page title
    st.title("🍽️ Food Waste Reporting")

    # 4. Basic user info
    username = st.text_input("👤 Your Name", value="")
    department = st.selectbox("🏢 Department", ["Bakery", "Kitchen", "Bar", "Other"])
    outlet = st.selectbox("📍 Outlet", ["Main Counter", "Kiosk 1", "Kiosk 2", "Mobile Unit"])

    # 5. Wastage
    has_wastage = st.radio("Any wastage today?", ["No", "Yes"], index=0)
    
    # If user toggles from "Yes" to "No", reset wastage inputs
    if has_wastage == "No":
        st.session_state.num_products = 0
        st.session_state.wastage_items = []
    # Initialize to 0 if not present
    if 'num_products' not in st.session_state:
        st.session_state.num_products = 0
    # If "Yes", ask how many products
    if has_wastage == "Yes":
    # Safeguard: clamp the session_state value to be at least 1
        if st.session_state.num_products < 1:
            st.session_state.num_products = 1

        st.session_state.num_products = st.number_input(
            "Number of wasted products",
            min_value=1, 
            max_value=50, 
            value=st.session_state.num_products
    )
        # Display input fields for each product
        st.session_state.wastage_items = []
        for i in range(st.session_state.num_products):
            st.write(f"**Wasted Product #{i+1}**")
            product_name = st.text_input(f"Product Name #{i+1}", key=f"prod_name_{i}")
            amount = st.text_input(f"Amount Wasted #{i+1}", key=f"prod_amount_{i}")
            st.session_state.wastage_items.append((product_name, amount))
    
    # 6. Submit button
    if st.button("🚀 Submit Report"):
        # Basic validation
        if not username:
            st.error("Please enter your name.")
            return

        if has_wastage == "Yes" and st.session_state.num_products > 0:
            # Save to Excel
            save_to_excel(
                username=username,
                department=department,
                outlet=outlet,
                wastage_list=st.session_state.wastage_items
            )
        else:
            st.success("✅ No wastage reported, thank you!")
    
def save_to_excel(username, department, outlet, wastage_list):
    # Desired column order
    COLUMN_ORDER = [
        "Entry ID",
        "Timestamp",
        "Username",
        "Department",
        "Outlet",
        "Product Name",
        "Amount Wasted",
    ]
    
    filename = "wastage_report.xlsx"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Load or create DataFrame with correct columns
    if os.path.exists(filename):
        df = pd.read_excel(filename)
        # Enforce column order if columns already exist
        if all(col in df.columns for col in COLUMN_ORDER):
            df = df[COLUMN_ORDER]
        else:
            # If the Excel has different columns, just re-create for simplicity
            df = pd.DataFrame(columns=COLUMN_ORDER)
        # Calculate next Entry ID
        if "Entry ID" in df.columns and not df["Entry ID"].empty:
            entry_id = df["Entry ID"].max() + 1
        else:
            entry_id = 1
    else:
        # No file yet, create empty with correct columns
        df = pd.DataFrame(columns=COLUMN_ORDER)
        entry_id = 1

    # Build new rows
    rows_to_add = []
    for product, amount in wastage_list:
        rows_to_add.append({
            "Entry ID": entry_id,
            "Timestamp": timestamp,
            "Username": username,
            "Department": department,
            "Outlet": outlet,
            "Product Name": product.strip() if product else "",
            "Amount Wasted": amount.strip() if amount else "",
        })

    # Only append if we have items
    if rows_to_add:
        new_df = pd.DataFrame(rows_to_add, columns=COLUMN_ORDER)
        df = pd.concat([df, new_df], ignore_index=True)
        df.to_excel(filename, index=False)

        st.success(f"✅ Successfully saved {len(rows_to_add)} item(s) to {filename}!")
        st.balloons()
        # Reset
        st.session_state.num_products = 0
        st.session_state.wastage_items = []
    else:
        st.success("✅ No wastage details entered. Nothing to save.")

if __name__ == "__main__":
    main()
