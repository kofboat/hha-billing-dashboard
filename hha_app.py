import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURATION & DATABASE ---
st.set_page_config(page_title="Comfort Hands Billing Portal", layout="wide")

def get_gsheet():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    client = gspread.authorize(creds)
    return client.open("HHA_Billing_History").sheet1

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
            claim_id, amount = p[1], float(p[2])
            service_date, units = "2026-01-01", 0
            for j in range(i+1, min(i+15, len(segments))):
                sub_p = segments[j].split('*')
                if sub_p[0] == 'DTP' and sub_p[1] == '472':
                    d = sub_p[3]
                    service_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                if sub_p[0] == 'SV1':
                    units = int(float(sub_p[4]))
            records.append([claim_id, curr_pat, curr_mi, service_date, amount, units, units * 0.25])
    return records

# --- MAIN APP LOGIC ---
st.title("🏥 Comfort Hands: Operations Dashboard")

try:
    sheet = get_gsheet()
    
    # 1. SIDEBAR
    with st.sidebar:
        st.header("Data Filters")
        show_all = st.checkbox("Show All Historical Data", value=False)
        date_range = None
        if not show_all:
            today = datetime.now().date()
            date_range = st.date_input("Select Date Range", value=(today - timedelta(days=30), today))

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
                st.rerun()

    # 2. DATA PROCESSING
    expected_columns = ["claim_id", "patient_name", "mi", "service_date", "amount", "units", "hours"]
    raw_data = sheet.get_all_records(expected_headers=expected_columns)
    
    if raw_data:
        df = pd.DataFrame(raw_data)
        df['service_date'] = pd.to_datetime(df['service_date']).dt.date
        
        # Filtering
        if show_all:
            df_filtered = df
        elif date_range and len(date_range) == 2:
            df_filtered = df[(df['service_date'] >= date_range[0]) & (df['service_date'] <= date_range[1])]
        else:
            df_filtered = df

        # 3. METRICS & CHARTS
        ytd_total = df[pd.to_datetime(df['service_date']).dt.year == datetime.now().year]['amount'].sum()
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Period Revenue", f"${df_filtered['amount'].sum():,.2f}")
        m2.metric("Period Hours", f"{df_filtered['hours'].sum():.2f} hrs")
        m3.metric("YTD Total", f"${ytd_total:,.2f}")
        m4.metric("Total History", f"${df['amount'].sum():,.2f}")

        st.subheader("📈 Monthly Revenue Trend")
        df_trend = df.copy()
        df_trend['month'] = pd.to_datetime(df_trend['service_date']).dt.to_period('M').dt.to_timestamp()
        fig = px.line(df_trend.groupby('month')['amount'].sum().reset_index(), x='month', y='amount', markers=True)
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("👥 Top 5 Patients by Revenue")
        top_5 = df_filtered.groupby("patient_name")["amount"].sum().nlargest(5).reset_index()
        st.plotly_chart(px.pie(top_5, values='amount', names='patient_name', hole=0.4), use_container_width=True)

    else:
        st.info("Upload a file to begin.")

except Exception as e:
    st.error(f"Dashboard Error: {e}")
