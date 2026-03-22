import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="Comfort Hands Billing Portal", layout="wide")

def get_gsheet():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    client = gspread.authorize(creds)
    return client.open("HHA_Billing_History").sheet1

st.title("🏥 Comfort Hands: Operations Dashboard")

try:
    sheet = get_gsheet()
    
    # --- SIDEBAR: DATA IMPORT ---
    with st.sidebar:
        st.header("Import Data")
        uploaded_file = st.file_uploader("Upload HHA CSV Export", type=['csv'])
        
        if uploaded_file and st.button("🚀 Sync CSV to Database"):
            content = uploaded_file.getvalue().decode("utf-8").splitlines()
            # Automatically find where the actual data table starts
            header_idx = next((i for i, line in enumerate(content) if "GroupByText" in line), 0)
            
            uploaded_file.seek(0)
            csv_df = pd.read_csv(uploaded_file, skiprows=header_idx)
            
            # Universal Mapping (Visit_Date -> service_date)
            clean_csv = pd.DataFrame()
            clean_csv['claim_id'] = csv_df['Invoice_Number'].astype(str)
            clean_csv['patient_name'] = csv_df['Patient']
            clean_csv['caregiver'] = csv_df['Caregiver']
            clean_csv['service_date'] = pd.to_datetime(csv_df['Visit_Date']).dt.strftime('%Y-%m-%d')
            clean_csv['amount'] = csv_df['Billed_Amt']
            clean_csv['units'] = csv_df['Billed_Unit']
            clean_csv['hours'] = csv_df['Billed_Unit'] * 0.25
            clean_csv['contract'] = csv_df['Contract']
            
            # Update Headers in Google Sheet to prevent "Mismatch Error"
            target_headers = clean_csv.columns.tolist()
            sheet.update('A1', [target_headers])
            
            # Deduplicate
            existing_ids = sheet.col_values(1)
            to_add = clean_csv[~clean_csv['claim_id'].isin(existing_ids)].values.tolist()

            if to_add:
                sheet.append_rows(to_add)
                st.success(f"Successfully added {len(to_add)} records!")
                st.rerun()
            else:
                st.info("No new unique records found.")

        st.divider()
        st.header("Global Filters")
        show_all = st.checkbox("Show All History", value=False)
        today = datetime.now().date()
        date_range = st.date_input("Date Range", value=(today - timedelta(days=90), today))

    # --- DATA RETRIEVAL ---
    # We pull raw values to handle mismatched headers gracefully
    raw_data = sheet.get_all_values()
    
    if len(raw_data) > 1:
        df = pd.DataFrame(raw_data[1:], columns=raw_data[0])
        # Force all column names to be clean: lowercase and no spaces
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        
        # Convert data types
        df['service_date'] = pd.to_datetime(df['service_date'])
        for col in ['amount', 'hours', 'units']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # 1. APPLY FILTERS
        # Date Filter
        if not show_all and isinstance(date_range, tuple) and len(date_range) == 2:
            df = df[(df['service_date'].dt.date >= date_range[0]) & (df['service_date'].dt.date <= date_range[1])]
        
        # Contract Filter
        all_contracts = sorted(df['contract'].unique().tolist())
        selected_contracts = st.multiselect("Filter by Contract/Insurance", options=all_contracts, default=all_contracts)
        df = df[df['contract'].isin(selected_contracts)]

        # Search Bar
        search_query = st.text_input("🔍 Search Patient or Caregiver").lower()
        if search_query:
            df = df[
                df['patient_name'].str.lower().str.contains(search_query) | 
                df['caregiver'].str.lower().str.contains(search_query)
            ]

        # 2. METRICS
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Selected Revenue", f"${df['amount'].sum():,.2f}")
        m2.metric("Selected Hours", f"{df['hours'].sum():.2f}")
        m3.metric("Patients", df['patient_name'].nunique())
        m4.metric("Caregivers", df['caregiver'].nunique())

        # 3. VISUALS
        st.divider()
        
        # Monthly Trend
        st.subheader("📈 Revenue Trend")
        df_m = df.copy()
        df_m['month'] = df_m['service_date'].dt.to_period('M').dt.to_timestamp()
        monthly = df_m.groupby('month')['amount'].sum().reset_index()
        st.plotly_chart(px.line(monthly, x='month', y='amount', markers=True, template="plotly_white", color_discrete_sequence=["#2ecc71"]), use_container_width=True)
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("👥 Top Patients")
            top_p = df.groupby("patient_name")["amount"].sum().nlargest(10).reset_index()
            st.plotly_chart(px.pie(top_p, values='amount', names='patient_name', hole=0.4), use_container_width=True)
        with col2:
            st.subheader("👨‍⚕️ Caregiver Hours")
            top_c = df.groupby("caregiver")["hours"].sum().nlargest(10).reset_index()
            st.plotly_chart(px.bar(top_c, x='hours', y='caregiver', orientation='h', color_discrete_sequence=["#27ae60"]), use_container_width=True)

        # 4. AUDIT LOG
        st.subheader("Detailed Audit Log")
        st.dataframe(df.sort_values('service_date', ascending=False), use_container_width=True)

    else:
        st.info("Database is empty. Please upload an HHA CSV and click 'Sync'.")

except Exception as e:
    st.error(f"System Error: {e}")
