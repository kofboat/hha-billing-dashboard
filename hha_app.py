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

def parse_837_to_records(file_content):
    """Parses EDI 837 text into structured list."""
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
    
    # 1. SIDEBAR: FILTERS & UPLOADS
    with st.sidebar:
        st.header("Data Filters")
        show_all = st.checkbox("Show All Historical Data", value=False)
        date_range = None
        if not show_all:
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
                st.rerun()
            else:
                st.warning("All claims in this file are already in the database.")

    # 2. DATA RETRIEVAL
    expected_headers = ["claim_id", "patient_name", "mi", "service_date", "amount", "units", "hours"]
    data = sheet.get_all_records(expected_headers=expected_headers)
    
    if data:
        df = pd.DataFrame(data)
        df['service_date'] = pd.to_datetime(df['service_date'])
        
        # Calculate YTD (Current Year)
        ytd_total = df[df['service_date'].dt.year == datetime.now().year]['amount'].sum()

        # Apply Sidebar Filters
        if show_all:
            df_filtered = df
        elif date_range and len(date_range) == 2:
            start, end = date_range
            df_filtered = df[(df['service_date'].dt.date >= start) & (df['service_date'].dt.date <= end)]
        else:
            df_filtered = df

        # 3. TOP METRICS
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Period Revenue", f"${df_filtered['amount'].sum():,.2f}")
        m2.metric("Period Hours", f"{df_filtered['hours'].sum():.2f} hrs")
        m3.metric("YTD Total", f"${ytd_total:,.2f}")
        m4.metric("Total History", f"${df['amount'].sum():,.2f}")

        st.divider()

       # --- 4. MONTHLY REVENUE BUCKET CHART ---
st.subheader("📈 Monthly Revenue Trend")

if not df.empty:
    # Create a clean copy for the trend
    df_trend = df.copy()
    
    # 1. Force all dates to the first of the month
    # This creates the 'bucket'
    df_trend['month_start'] = df_trend['service_date'].dt.to_period('M').dt.to_timestamp()
    
    # 2. AGGREGATE: This is the missing step. 
    # We must sum the amounts so there is only ONE row per month.
    monthly_summary = df_trend.groupby('month_start')['amount'].sum().reset_index()
    
    # 3. Sort by date to ensure the line flows correctly
    monthly_summary = monthly_summary.sort_values('month_start')

    # 4. Create the line chart using the summarized data
    fig_trend = px.line(
        monthly_summary, 
        x='month_start', 
        y='amount', 
        markers=True, 
        line_shape="linear", # Using linear for clear bucket-to-bucket jumps
        template="plotly_white",
        labels={'amount': 'Total Revenue ($)', 'month_start': 'Month'},
        color_discrete_sequence=["#2ecc71"]
    )
    
    # Force X-axis to show month names clearly
    fig_trend.update_xaxes(dtick="M1", tickformat="%b %Y")
    
    st.plotly_chart(fig_trend, use_container_width=True) # 4. MONTHLY REVENUE BUCKET CHART
        st.subheader("📈 Monthly Revenue Trend")
        df_monthly = df.copy()
        df_monthly['month'] = df_monthly['service_date'].dt.to_period('M').dt.to_timestamp()
        monthly_revenue = df_monthly.groupby('month')['amount'].sum().reset_index()

        fig_trend = px.line(monthly_revenue, x='month', y='amount', markers=True, 
                            line_shape="spline", template="plotly_white",
                            color_discrete_sequence=["#2ecc71"])
        st.plotly_chart(fig_trend, use_container_width=True)

        # 5. PATIENT ANALYSIS
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("👥 Top 5 Patients by Revenue")
            top_5 = df_filtered.groupby("patient_name")["amount"].sum().nlargest(5).reset_index()
            fig_pie = px.pie(top_5, values='amount', names='patient_name', hole=0.4,
                             color_discrete_sequence=px.colors.sequential.Greens_r)
            st.plotly_chart(fig_pie, use_container_width=True)
        
        with col2:
            st.subheader("📊 Hours Billed by Patient")
            patient_hours = df_filtered.groupby("patient_name")["hours"].sum().reset_index()
            fig_bar = px.bar(patient_hours, x="patient_name", y="hours", 
                             template="plotly_white", color_discrete_sequence=["#27ae60"])
            st.plotly_chart(fig_bar, use_container_width=True)

        # 6. AUDIT LOG
        st.subheader("Full Billing Audit Log")
        st.dataframe(df_filtered.sort_values("service_date", ascending=False), use_container_width=True)

    else:
        st.info("The database is currently empty. Please upload an HHAExchange file.")

except Exception as e:
    st.error(f"Configuration or Data Error: {e}")
    st.info("Check your Google Sheet headers and Streamlit Secrets.")
