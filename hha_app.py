import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURATION & DATABASE ---
st.set_page_config(page_title="Comfort Hands Billing Portal", layout="wide")

def get_gsheet():
    """Connects to Google Sheets using Streamlit Secrets."""
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    client = gspread.authorize(creds)
    return client.open("HHA_Billing_History").sheet1

# --- EDI 837 PARSER ---
def parse_837_to_records(file_content):
    segments = file_content.split('~')
    records = []
    curr_pat, curr_mi = "", ""

    for i, seg in enumerate(segments):
        p = seg.split('*')
        if not p or len(p) < 2: continue
        
        if p[0] == 'NM1' and p[1] == 'IL':
            curr_pat = f"{p[3]} {p[4]}"
            curr_mi = p[9] if len(p) > 9 else ""
        
        if p[0] == 'CLM':
            claim_id = p[1]
            amount = float(p[2])
            service_date = "2026-01-01"
            units = 0
            
            for j in range(i+1, min(i+15, len(segments))):
                sub_p = segments[j].split('*')
                if sub_p[0] == 'DTP' and sub_p[1] == '472':
                    d = sub_p[3]
                    service_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                if sub_p[0] == 'SV1':
                    units = int(float(sub_p[4]))
            
            hours = units * 0.25
            records.append([claim_id, curr_pat, curr_mi, service_date, amount, units, hours])
    return records

# --- APP UI START ---
st.title("🏥 Comfort Hands: Operations Dashboard")

# Initialize global variables
df = pd.DataFrame()
date_range = None

try:
    sheet = get_gsheet()
    
    # --- SIDEBAR: UPLOAD & FILTERS ---
    with st.sidebar:
        st.header("Data Filters")
        show_all = st.checkbox("Show All Historical Data", value=False)

        if not show_all:
            # FIX: Use datetime.now().date()
            today = datetime.now().date() 
            default_start = today - timedelta(days=30)
            date_range = st.date_input("Select Date Range", value=(default_start, today))

        st.divider()
        st.header("Upload Weekly Export")
        uploaded_file = st.file_uploader("Upload 837 .txt file", type=['txt'])

        if uploaded_file:
            content = uploaded_file.read().decode("utf-8")
            parsed_data = parse_837_to_records(content)
            existing_ids = sheet.col_values(1)
            unique_rows = [r for r in parsed_data if r[0] not in existing_ids]
            
            if unique_rows:
                sheet.append_rows(unique_rows)
                st.success(f"Synced {len(unique_rows)} new claims!")
                st.rerun() # Refresh to show new data
            else:
                st.warning("No new claims found.")

    # --- DATA PROCESSING ---
    expected_columns = ["claim_id", "patient_name", "mi", "service_date", "amount", "units", "hours"]
    raw_data = sheet.get_all_records(expected_headers=expected_columns)
    
    if raw_data:
        df = pd.DataFrame(raw_data)
        df['service_date'] = pd.to_datetime(df['service_date']).dt.date
        
        # Apply Filters
        if show_all:
            df_filtered = df
        elif date_range and len(date_range) == 2:
            df_filtered = df[(df['service_date'] >= date_range[0]) & (df['service_date'] <= date_range[1])]
        else:
            df_filtered = df

        # --- DASHBOARD METRICS ---
        if not df_filtered.empty:
            m1, m2, m3 = st.columns(3)
            m1.metric("Period Revenue", f"${df_filtered['amount'].sum():,.2f}")
            m2.metric("Period Hours", f"{df_filtered['hours'].sum():.2f} hrs")
            m3.metric("Total History", f"${df['amount'].sum():,.2f}")

            # Charts
            st.subheader("Billing Analysis")
            fig = px.bar(df_filtered.groupby("patient_name")["hours"].sum().reset_index(), 
                         x="patient_name", y="hours", color="hours", template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("Audit Log")
            st.dataframe(df_filtered.sort_values("service_date", ascending=False), use_container_width=True)
        else:
            st.info("No data found for the selected date range.")
    else:
        st.info("The database is currently empty. Please upload a file.")

except Exception as e:
    st.error(f"Error: {e}")
    st.info("Please check your Google Sheet headers and Streamlit Secrets.")
