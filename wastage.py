import streamlit as st
import pandas as pd
from datetime import datetime
import os
import boto3
from io import BytesIO
import logging

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
        if not username:
            st.error("Please enter your name.")
            return

        if has_wastage == "Yes" and not st.session_state.wastage_items:
            st.error("Please enter all product details.")
            return

        try:
            if has_wastage == "Yes":
                save_to_s3(
                    s3_client=s3_client,
                    username=username,
                    department=department,
                    outlet=outlet,
                    wastage_list=st.session_state.wastage_items
                )
            else:
                st.success("✅ No wastage reported, thank you!")
        except Exception as e:
            logger.error(f"Submission error: {str(e)}")
            st.error("Failed to save report. Please try again.")

def save_to_s3(s3_client, username, department, outlet, wastage_list):
    """Save data to S3 with proper error handling"""
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

    try:
        # Try to download existing file
        try:
            file_obj = s3_client.get_object(Bucket=S3_BUCKET, Key=S3_FILE)
            df = pd.read_excel(file_obj['Body'])
        except s3_client.exceptions.NoSuchKey:
            df = pd.DataFrame(columns=COLUMN_ORDER)
        except Exception as e:
            logger.error(f"Error reading existing file: {str(e)}")
            df = pd.DataFrame(columns=COLUMN_ORDER)

        # Calculate next Entry ID
        entry_id = df["Entry ID"].max() + 1 if "Entry ID" in df.columns and not df.empty else 1

        # Prepare new rows
        new_rows = [{
            "Entry ID": entry_id,
            "Timestamp": timestamp,
            "Username": username,
            "Department": department,
            "Outlet": outlet,
            "Product Name": product,
            "Amount Wasted": amount
        } for product, amount in wastage_list]

        new_df = pd.DataFrame(new_rows, columns=COLUMN_ORDER)
        df = pd.concat([df, new_df], ignore_index=True)

        # Save to in-memory Excel file
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False)
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