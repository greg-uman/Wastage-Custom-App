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

# Set page config FIRST
st.set_page_config(page_title="Food Waste Reporting", page_icon="🍽️")

# AWS Configuration - Use environment variables
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
    if 'Outlet' in df.columns and 'Amount Wasted' in df.columns:
        outlet_summary = df.groupby('Outlet')['Amount Wasted'] \
            .agg(['count', 'sum']) \
            .rename(columns={'count': 'Incidents', 'sum': 'Total Wastage'}) \
            .sort_values('Total Wastage', ascending=False)
        analytics["Outlet Summary"] = outlet_summary
    
    # 2. Department Wastage Summary
    if 'Department' in df.columns and 'Amount Wasted' in df.columns:
        dept_summary = df.groupby('Department')['Amount Wasted'] \
            .agg(['count', 'sum']) \
            .rename(columns={'count': 'Incidents', 'sum': 'Total Wastage'}) \
            .sort_values('Total Wastage', ascending=False)
        analytics["Department Summary"] = dept_summary
    
    # 3. Product Wastage Summary
    if 'Product Name' in df.columns and 'Amount Wasted' in df.columns:
        product_summary = df.groupby('Product Name')['Amount Wasted'] \
            .agg(['count', 'sum']) \
            .rename(columns={'count': 'Incidents', 'sum': 'Total Wastage'}) \
            .sort_values('Total Wastage', ascending=False)
        analytics["Product Summary"] = product_summary
    
    # 4. Daily Wastage Trend
    if 'Timestamp' in df.columns and 'Amount Wasted' in df.columns:
        df['Date'] = pd.to_datetime(df['Timestamp']).dt.date
        daily_trend = df.groupby('Date')['Amount Wasted'].sum().reset_index()
        analytics["Daily Trend"] = daily_trend
    
    return analytics

def save_to_s3(s3_client, submitter_name, department, outlet, wastage_list):
    """Save data to S3 with enhanced Excel reporting"""
    COLUMN_ORDER = [
        "Entry ID",
        "Timestamp",
        "Submitter_Name",
        "Department",
        "Outlet",
        "Product Name",
        "Amount Wasted",
        "Notes"
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

        # Prepare new rows
        new_rows = [{
            "Entry ID": entry_id,
            "Timestamp": timestamp,
            "Submitter_Name": submitter_name,
            "Department": department,
            "Outlet": outlet,
            "Product Name": product,
            "Amount Wasted": amount,
            "Notes": ""  # Empty column for future notes
        } for product, amount in wastage_list]

        new_df = pd.DataFrame(new_rows, columns=COLUMN_ORDER)
        main_df = pd.concat([main_df, new_df], ignore_index=True)
        
        # Create analytics sheets
        analytics = create_analytics_sheets(main_df)

        # Save to in-memory Excel file with multiple sheets
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
            # Main data sheet with formatting
            main_df.to_excel(writer, sheet_name="Wastage Data", index=False)
            
            # Add analytics sheets
            for sheet_name, data in analytics.items():
                data.to_excel(writer, sheet_name=sheet_name)
                
            # Get workbook and worksheet objects for formatting
            workbook = writer.book
            worksheet = writer.sheets["Wastage Data"]
            
            # Formatting
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'top',
                'fg_color': '#4472C4',
                'font_color': 'white',
                'border': 1
            })
            
            # Write the column headers with defined format
            for col_num, value in enumerate(main_df.columns.values):
                worksheet.write(0, col_num, value, header_format)
            
            # Add conditional formatting for high wastage
            if 'Amount Wasted' in main_df.columns:
                amount_col = main_df.columns.get_loc('Amount Wasted')
                worksheet.conditional_format(1, amount_col, len(main_df), amount_col, {
                    'type': 'data_bar',
                    'bar_color': '#FF5555'
                })
            
            # Add charts to analytics sheets
            for sheet_name, data in analytics.items():
                if sheet_name in ["Outlet Summary", "Department Summary", "Product Summary"]:
                    chart_sheet = writer.sheets[sheet_name]
                    chart = workbook.add_chart({'type': 'column'})
                    
                    chart.add_series({
                        'name': f'{sheet_name}!$C$1',
                        'categories': f'{sheet_name}!$A$2:$A${len(data)+1}',
                        'values': f'{sheet_name}!$C$2:$C${len(data)+1}',
                    })
                    
                    chart.set_title({'name': f'Total Wastage by {sheet_name.split()[0]}'})
                    chart.set_x_axis({'name': sheet_name.split()[0]})
                    chart.set_y_axis({'name': 'Amount Wasted'})
                    
                    chart_sheet.insert_chart('E2', chart)

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
        st.session_state.num_products = 1
        st.session_state.confirmed_num = 1
        st.session_state.wastage_items = []
def main():
    # Initialize S3 client
    s3_client = initialize_s3_client()
    if not s3_client:
        return
    
    # Initialize session state
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
        "Retail": ["RET F 104", "RET B 105", "RET B 205"],
        "Medallion Club": ["Gallery", "Stokegrill", "Terrace"],
        "Functions": ["Victory Room", "Parker"],
        "Corporate Suites": ["suites 1", "suites 2", "suites 3"]
    }
    outlet = st.selectbox("📍 Outlet", outlet_options.get(department, []))

    # Wastage reporting
    has_wastage = st.radio("Any wastage today?", ["No", "Yes"], index=0)
    
    # Reset if toggled from Yes to No
    if has_wastage == "No":
        st.session_state.num_products = 1
        st.session_state.confirmed_num = 1
        st.session_state.wastage_items = []

    if has_wastage == "Yes":
        # Use a form to prevent immediate rerun on number change
        with st.form("product_count_form"):
            # Number input with separate confirmed state
            new_num = st.number_input(
                "Number of wasted products (Press Enter to confirm)",
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

def save_to_s3(s3_client, submitter_name, department, outlet, wastage_list):
    """Save data to S3 with proper error handling"""
    COLUMN_ORDER = [
        "Entry ID",
        "Timestamp",
        "Submitter_Name",
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
            "Submitter_Name": submitter_name,
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
        st.session_state.num_products = 1
        st.session_state.confirmed_num = 1
        st.session_state.wastage_items = []

if __name__ == "__main__":
    main()