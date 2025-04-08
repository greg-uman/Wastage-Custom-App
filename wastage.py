import streamlit as st
import pandas as pd
from datetime import datetime
import os
import boto3
from io import BytesIO
import logging
import xlsxwriter
import qrcode
from PIL import Image
import io

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set page config FIRST
st.set_page_config(page_title="Food Waste Reporting", page_icon="🍽️")

# AWS Configuration - Use environment variables
AWS_ACCESS_KEY_ID = st.secrets["aws"]["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = st.secrets["aws"]["AWS_SECRET_ACCESS_KEY"]
AWS_REGION = os.environ.get('AWS_REGION', 'ap-southeast-2')
S3_BUCKET = os.environ.get('S3_BUCKET', 'my-food-waste-reports')
S3_FILE = "wastage_report.xlsx"

def generate_qr(url, box_size=10):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white")

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
    
    # Maintain state across interactions
    if 'num_products' not in st.session_state:
        st.session_state.num_products = 1  # Default to 1
        st.session_state.confirmed_num = 1
    
    if 'wastage_items' not in st.session_state:
        st.session_state.wastage_items = []

    # Page title
    st.title("🍽️ Food Waste Reporting")

    # Basic user info
    submitter_name = st.text_input("👤 Your Name", value="")

    # Department selection
    dept_options = ["Retail", "Medallion Club", "Functions", "Corporate Suites"]
    department = st.selectbox("🏢 Department", dept_options)

    # Outlet options based on selected department
    outlet_options = {
        "Retail":[
            "RET B 108",
            "RET B 121",
            "RET B 128 - THE RUNNER",
            "RET B 134",
            "RET B 147 - JOHNNY WALKER",
            "RET B 207",
            "RET B 218",
            "RET B 229",
            "RET B 232",
            "RET B 236",
            "RET B 241",
            "RET B 244",
            "RET B 305 4 Pines",
            "RET B 309",
            "RET B 317",
            "RET B 324",
            "RET B 329",
            "RET B 333",
            "RET B 340",
            "RET B 342",
            "RET B 348",
            "RET B 305",
            "RET B 345",
            "RET B 235 - CRAFT",
            "RET B 238 - PERONI",
            "RET B 335 - ALFREDS",
            "RET B 338 - EDWARDS",
            "Spare Location 1260",
            "View Bar",
            "RET B 102",
            "RET C 106",
            "RET C 118",
            "RET C 130",
            "RET C 143",
            "RET C 243",
            "RET C 305",
            "RET C 320",
            "RET C 329",
            "RET C 344",
            "RET F 104",
            "RET F 118 - RUNNER",
            "RET F 118 - Hot Dog Cart",
            "RET F 131",
            "RET F 145",
            "RET F 205",
            "RET F 220",
            "RET F 231",
            "RET F 242",
            "RET F 305",
            "RET F 320",
            "Ret F 329",  # Note: lowercase 't' preserved as in original
            "RET F 344",
            "RET F 135 - 8 BIT",
            "RET F 234",
            "RET F 239",
            "RET F 336",
            "RET F 337",
            "RET F 102 - 8 BIT",
            "RET F 101 - EARL"
        ],
        "Medallion Club": ["Gallery", "Stokegrill", "Terrace", "Altis", "Sportsbar", "Lee Ho Fook"],
        "Functions": ["Victory Room", "Parker"],
        "Corporate Suites":[f"Suites {i}" for i in range(1, 66)]
    }
    outlet = st.selectbox("📍 Outlet", outlet_options.get(department, []))

    # Wastage reporting
    has_wastage = st.radio("Any wastage today?", ["No", "Yes"], index=0)
    
    # Reset if toggled from Yes to No
    if has_wastage == "Yes":
        # Safeguard minimum value
        if st.session_state.num_products < 1:
            st.session_state.num_products = 1

        with st.form("product_count_form", enter_to_submit = False):
            # Number input with separate confirmed state
            new_num = st.number_input(
                "Number of wasted products (Enter number of products, then press the confirm button)",
                min_value=1, 
                max_value=50, 
                value=st.session_state.confirmed_num,
                key="num_products_input"
            )
             
            # Only update the confirmed number when form is submitted
            if st.form_submit_button("Confirm Count"):
                st.session_state.confirmed_num = new_num
                st.session_state.num_products = new_num
                st.rerun()
        # Display product inputs based on confirmed number
        st.session_state.wastage_items = []
        for i in range(st.session_state.confirmed_num):
            st.write(f"**Wasted Product #{i+1}**")
            product_name = st.text_input(f"Product Name #{i+1}", key=f"prod_name_{i}")
            amount = st.text_input(f"Amount Wasted #{i+1}", key=f"prod_amount_{i}")
            if product_name and amount:  # Only add if both fields have values
                st.session_state.wastage_items.append((product_name.strip(), amount.strip()))
    
    # Submit button
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

    # Add QR section (sidebar or new tab)
    with st.sidebar:
        st.header("Mobile Access")
        app_url = "https://wastage-custom-app-be349qwejau7lcfqyqqkny.streamlit.app/"
        
        # Preview
        qr_img = generate_qr(app_url, box_size=6)
        img_bytes = io.BytesIO()
        qr_img.save(img_bytes, format="PNG")
        st.image(img_bytes, caption="Scan with phone camera")
        
        # Download
        st.download_button(
            label="Download QR (PNG)",
            data=img_bytes.getvalue(),
            file_name="wastage_qr.png",
            mime="image/png"
        )

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
