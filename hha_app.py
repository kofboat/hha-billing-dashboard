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
    # Ensure your Google Sheet is named exactly this
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
            default_start = today - timedelta(days=90) # Default to last quarter
            date_range = st.date_input("Select Date Range", value=(default_start, today))

        st.divider()
        st.header("Import Data")
        
        # Support both file types
        uploaded_file = st.file_uploader("Upload 837 (.txt) or HHA Export (.csv)", type=['txt', 'csv'])
        
        if uploaded_file:
            unique_rows = []
            existing_ids = sheet.col_values(1)
            
            # HANDLE CSV (HHAExchange Export)
            if uploaded_file.name.endswith('.csv'):
                csv_df = pd.read_csv(uploaded_file)
                # Map CSV columns to our schema
                cleaned_csv = pd.DataFrame()
                cleaned_csv['claim_id'] = csv_df['Invoice_Number'].astype(str)
                cleaned_csv['patient_name'] = csv_df['Patient']
                cleaned_csv['mi'] = ""
                cleaned_csv['service_date'] = pd.to_datetime(csv_df['Visit_Date']).dt.strftime('%Y-%m-%d')
                cleaned_csv['amount'] = csv_df['Billed_Amt']
                cleaned_csv['units'] = csv_df['Billed_Unit']
                cleaned_csv['hours'] = csv_df['Billed_Unit'] * 0.25
                
                unique_rows = cleaned_csv[~cleaned_csv['claim_id'].isin(existing_ids)].values.tolist()

            # HANDLE TXT (837 EDI)
            else:
                content = uploaded_file.read().decode("utf-8")
                parsed_data = parse_837_to_records(content)
                unique_rows = [r for r in parsed_data if r[0] not in existing_ids]

            if unique_rows:
                sheet.append_rows(unique_rows)
                st.success(f"Successfully added {len(unique_rows)} new records!")
                st.rerun()
            else:
                st.warning("All records in this file already exist in the database.")

    # 2. DATA RETRIEVAL & PROCESSING
    expected_headers = ["claim_id", "patient_name", "mi", "service_date", "amount", "units", "hours"]
    raw_data = sheet.get_all_records(expected_headers=expected_headers)
    
    if raw_data:
        df = pd.DataFrame(raw_data)
        df['service_date'] = pd.to_datetime(df['service_date'])
        
        # Filtering Logic
        if show_all:
            df_filtered = df
        elif date_range and len(date_range) == 2:
            start, end = date_range
            df_filtered = df[(df['service_date'].dt.date >= start) & (df['service_date'].dt.date <= end)]
        else:
            df_filtered = df

        # 3. TOP METRICS
        ytd_total = df[df['service_date'].dt.year == datetime.now().year]['amount'].sum()
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Period Revenue", f"${df_filtered['amount'].sum():,.2f}")
        m2.metric("Period Hours", f"{df_filtered['hours'].sum():.2f} hrs")
        m3.metric("YTD Total", f"${ytd_total:,.2f}")
        m4.metric("Total History", f"${df['amount'].sum():,.2f}")

        st.divider()

        # 4. MONTHLY REVENUE TREND (Forced Grouping)
        st.subheader("📈 Monthly Revenue Trend")
        df_monthly = df.copy()
        df_monthly['month'] = df_monthly['service_date'].dt.to_period('M').dt.to_timestamp()
        # Group by month and sum amounts to ensure one bucket per month
        monthly_summary = df_monthly.groupby('month')['amount'].sum().reset_index().sort_values('month')

        fig_trend = px.line(monthly_summary, x='month', y='amount', markers=True, 
                            line_shape="spline", template="plotly_white",
                            color_discrete_sequence=["#2ecc71"])
        fig_trend.update_xaxes(dtick="M1", tickformat="%b %Y")
        st.plotly_chart(fig_trend, use_container_width=True)

        # 5. PATIENT ANALYSIS
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("👥 Top 5 Patients by Revenue")
            top_5 = df_filtered.groupby("patient_name")["amount"].sum().nlargest(5).reset_index()
            fig_pie = px.pie(top_5, values='amount', names='patient_name', hole=0.4,
                             color_discrete_sequence=px.colors.sequential.Greens_r)
            st.plotly_chart(fig_pie, use_container_width=True)
        with c2:
            st.subheader("📊 Hours Billed by Patient")
            patient_hours = df_filtered.groupby("patient_name")["hours"].sum().reset_index()
            fig_bar = px.bar(patient_hours, x="patient_name", y="hours", template="plotly_white",
                             color_discrete_sequence=["#27ae60"])
            st.plotly_chart(fig_bar, use_container_width=True)

        # 6. AUDIT LOG
        st.subheader("Full Billing Audit Log")
        st.dataframe(df_filtered.sort_values("service_date", ascending=False), use_container_width=True)

    else:
        st.info("The database is currently empty. Please upload a file to begin.")

except Exception as e:
    st.error(f"Application Error: {e}")
    st.info("Please verify your Google Sheet headers and Streamlit Secrets configuration.")
