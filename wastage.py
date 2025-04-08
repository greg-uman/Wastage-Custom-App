import streamlit as st
import pandas as pd
from datetime import datetime
import os
import boto3
from io import BytesIO
import logging
import xlsxwriter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 1. Set page config FIRST
st.set_page_config(page_title="Food Waste Reporting", page_icon="🍽️")

# 2. AWS Configuration - Use environment variables
AWS_ACCESS_KEY_ID = st.secrets["aws"]["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = st.secrets["aws"]["AWS_SECRET_ACCESS_KEY"]
AWS_REGION = os.environ.get('AWS_REGION', 'ap-southeast-2')
S3_BUCKET = os.environ.get('S3_BUCKET', 'my-food-waste-reports')
S3_FILE = "wastage_report.xlsx"

def initialize_s3_client():
    """Initialize S3 client with error handling"""
    try:
        return boto3.client(
            's3',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
    except Exception as e:
        logger.error(f"Failed to initialize S3 client: {str(e)}")
        st.error("Failed to initialize cloud storage connection")
        return None

def create_analytics_sheets(df):
    """Create additional analytical worksheets"""
    analytics = {}
    
    # 1. Outlet Wastage Summary
    outlet_summary = df.groupby('Outlet')['Amount Wasted'] \
        .agg(['count', 'sum']) \
        .rename(columns={'count': 'Incidents', 'sum': 'Total Wastage'}) \
        .sort_values('Total Wastage', ascending=False)
    analytics["Outlet Summary"] = outlet_summary
    
    # 2. Department Wastage Summary
    dept_summary = df.groupby('Department')['Amount Wasted'] \
        .agg(['count', 'sum']) \
        .rename(columns={'count': 'Incidents', 'sum': 'Total Wastage'}) \
        .sort_values('Total Wastage', ascending=False)
    analytics["Department Summary"] = dept_summary
    
    # 3. Product Wastage Summary
    product_summary = df.groupby('Product Name')['Amount Wasted'] \
        .agg(['count', 'sum']) \
        .rename(columns={'count': 'Incidents', 'sum': 'Total Wastage'}) \
        .sort_values('Total Wastage', ascending=False)
    analytics["Product Summary"] = product_summary
    
    return analytics

def main():
    # Initialize S3 client
    s3_client = initialize_s3_client()
    if not s3_client:
        return
    
    # 3. Maintain state across interactions
    if 'num_products' not in st.session_state:
        st.session_state.num_products = 0
    
    if 'wastage_items' not in st.session_state:
        st.session_state.wastage_items = []

    # 4. Page title
    st.title("🍽️ Food Waste Reporting")

    # 5. Basic user info
    submitter_name = st.text_input("👤 Your Name", value="")

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

    # 6. Wastage reporting
    has_wastage = st.radio("Any wastage today?", ["No", "Yes"], index=0)
    
    # Reset if toggled from Yes to No
    if has_wastage == "No":
        st.session_state.num_products = 0
        st.session_state.wastage_items = []

    if has_wastage == "Yes":
        # Safeguard minimum value
        if st.session_state.num_products < 1:
            st.session_state.num_products = 1

        st.session_state.num_products = st.number_input(
            "Number of wasted products (Press Enter to continue)",
            min_value=1, 
            max_value=50, 
            value=st.session_state.num_products
        )
        
        st.session_state.wastage_items = []
        for i in range(st.session_state.num_products):
            st.write(f"**Wasted Product #{i+1}**")
            product_name = st.text_input(f"Product Name #{i+1}", key=f"prod_name_{i}")
            amount = st.text_input(f"Amount Wasted #{i+1}", key=f"prod_amount_{i}")
            if product_name and amount:  # Only add if both fields have values
                st.session_state.wastage_items.append((product_name.strip(), amount.strip()))
    
    # 7. Submit button
    if st.button("🚀 Submit Report"):
        if not submitter_name:
            st.error("Please enter your name.")
            return

        if has_wastage == "Yes" and not st.session_state.wastage_items:
            st.error("Please enter all product details.")
            return

        try:
            if has_wastage == "Yes":
                save_to_s3(
                    s3_client=s3_client,
                    submitter_name=submitter_name,
                    department=department,
                    outlet=outlet,
                    wastage_list=st.session_state.wastage_items
                )
            else:
                st.success("✅ No wastage reported, thank you!")
        except Exception as e:
            logger.error(f"Submission error: {str(e)}")
            st.error("Failed to save report. Please try again.")

def save_to_s3(s3_client, submitter_name, department, outlet, wastage_list):
    """Save data to S3 with proper error handling"""
    COLUMN_ORDER = [
        "Entry ID",
        "Timestamp",
        "Submitter_Name",  # Corrected column name
        "Department",
        "Outlet",
        "Product Name",
        "Amount Wasted",
    ]
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Try to download existing file
        try:
            file_obj = s3_client.get_object(Bucket=S3_BUCKET, Key=S3_FILE)
            df = pd.read_excel(file_obj['Body'], sheet_name=None)
            main_df = df.get("Wastage Data", pd.DataFrame(columns=COLUMN_ORDER))
        except (s3_client.exceptions.NoSuchKey, KeyError):
            main_df = pd.DataFrame(columns=COLUMN_ORDER)
        except Exception as e:
            logger.error(f"Error reading existing file: {str(e)}")
            main_df = pd.DataFrame(columns=COLUMN_ORDER)

        # Calculate next Entry ID
        entry_id = main_df["Entry ID"].max() + 1 if "Entry ID" in main_df.columns and not main_df.empty else 1

        # Prepare new rows with CORRECT COLUMN NAMES
        new_rows = [{
            "Entry ID": entry_id,
            "Timestamp": timestamp,
            "Submitter_Name": submitter_name,  # Fixed key to match column name
            "Department": department,
            "Outlet": outlet,
            "Product Name": product,
            "Amount Wasted": amount
        } for product, amount in wastage_list]

        new_df = pd.DataFrame(new_rows, columns=COLUMN_ORDER)
        main_df = pd.concat([main_df, new_df], ignore_index=True)

        # Create analytics
        analytics = create_analytics_sheets(main_df)

        # Save to in-memory Excel file with multiple sheets
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
            # Main data sheet
            main_df.to_excel(writer, sheet_name="Wastage Data", index=False)
            
            # Analytics sheets
            for sheet_name, data in analytics.items():
                data.to_excel(writer, sheet_name=sheet_name)

        excel_buffer.seek(0)

        # Upload to S3
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=S3_FILE,
            Body=excel_buffer,
            ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
        st.success(f"✅ Successfully saved {len(new_rows)} item(s)!")
        st.balloons()

    except Exception as e:
        logger.error(f"S3 save error: {str(e)}")
        raise

    finally:
        # Reset session state
        st.session_state.num_products = 0
        st.session_state.wastage_items = []

if __name__ == "__main__":
    main()