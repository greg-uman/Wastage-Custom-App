import streamlit as st
import pandas as pd
from datetime import datetime
import os
import boto3
from io import BytesIO

# Set up AWS S3 client
s3_client = boto3.client('s3', aws_access_key_id='YOUR_AWS_ACCESS_KEY', aws_secret_access_key='YOUR_AWS_SECRET_KEY')
bucket_name = 'YOUR_BUCKET_NAME'
filename = "wastage_report.xlsx"

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

    # Department selection
    dept_options = ["Retail", "Medallion Club", "Functions", "Corporate Suites"]
    department = st.selectbox("🏢 Department", dept_options)

    # Outlet options based on selected department
    outlet_options = {
        "Retail": ["RET F 104", "RET B 105", "RET B 205"],
        "Medallion Club": ["Gallery", "Stokegrill", "Terrace"],
        "Functions": ["Victory Room", "Parker"],
        "Corporate Suites": ["suites 1", "suites 2", "suites 3"]
    }
    outlet = st.selectbox("📍 Outlet", outlet_options.get(department, []))

    # 5. Wastage
    has_wastage = st.radio("Any wastage today?", ["No", "Yes"], index=0)
    
    # If user toggles from "Yes" to "No", reset wastage inputs
    if has_wastage == "No":
        st.session_state.num_products = 0
        st.session_state.wastage_items = []

    # If "Yes", ask how many products
    if has_wastage == "Yes":
        # Safeguard: clamp the session_state value to be at least 1
        if st.session_state.num_products < 1:
            st.session_state.num_products = 1

        st.session_state.num_products = st.number_input(
            "Number of wasted products (Press Enter to go to next step)",
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
            # Save to S3
            save_to_s3(
                username=username,
                department=department,
                outlet=outlet,
                wastage_list=st.session_state.wastage_items
            )
        else:
            st.success("✅ No wastage reported, thank you!")
    
def save_to_s3(username, department, outlet, wastage_list):
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
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Download the existing Excel file from S3
    file_obj = s3_client.get_object(Bucket=bucket_name, Key=filename)
    df = pd.read_excel(file_obj['Body'])

    # Calculate next Entry ID
    if "Entry ID" in df.columns and not df["Entry ID"].empty:
        entry_id = df["Entry ID"].max() + 1
    else:
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

    # Append the new data to the existing DataFrame
    new_df = pd.DataFrame(rows_to_add, columns=COLUMN_ORDER)
    df = pd.concat([df, new_df], ignore_index=True)

    # Save the updated DataFrame to a BytesIO object
    excel_file = BytesIO()
    with pd.ExcelWriter(excel_file, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Wastage Report")
        writer.save()
    excel_file.seek(0)

    # Upload the updated file back to S3
    s3_client.put_object(Bucket=bucket_name, Key=filename, Body=excel_file)
    
    st.success(f"✅ Successfully saved {len(rows_to_add)} item(s) to {filename}!")
    st.balloons()

    # Reset session state
    st.session_state.num_products = 0
    st.session_state.wastage_items = []

if __name__ == "__main__":
    main()
