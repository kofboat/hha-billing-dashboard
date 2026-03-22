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
    # Ensure your Google Sheet is named exactly this and shared with the client_email
    return client.open("HHA_Billing_History").sheet1

# --- EDI 837 PARSER ---
def parse_837_to_records(file_content):
    segments = file_content.split('~')
    records = []
    curr_pat, curr_mi = "", ""

    for i, seg in enumerate(segments):
        p = seg.split('*')
        if not p or len(p) < 2: continue
        
        # 1. Capture Patient Info (NM1*IL)
        if p[0] == 'NM1' and p[1] == 'IL':
            curr_pat = f"{p[3]} {p[4]}"
            curr_mi = p[9] if len(p) > 9 else ""
        
        # 2. Capture Claim (CLM)
        if p[0] == 'CLM':
            claim_id = p[1]
            amount = float(p[2])
            
            # 3. Look ahead for Date (DTP*472) and Units (SV1)
            service_date = "2026-01-01"
            units = 0
            
            # Scan next 15 segments for date and unit details
            for j in range(i+1, min(i+15, len(segments))):
                sub_p = segments[j].split('*')
                if sub_p[0] == 'DTP' and sub_p[1] == '472':
                    d = sub_p[3]
                    service_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                if sub_p[0] == 'SV1':
                    units = int(float(sub_p[4]))
            
            # Hours conversion: 1 unit = 15 mins (0.25 hours)
            hours = units * 0.25
            
            records.append([
                claim_id, curr_pat, curr_mi, service_date, amount, units, hours
            ])
    return records

# --- APP UI ---
st.title("🏥 Comfort Hands: Weekly Operations Dashboard")

try:
    sheet = get_gsheet()
    
    # --- SIDEBAR: UPLOAD ---
    with st.sidebar:
        st.header("Upload Weekly Export")
        uploaded_file = st.file_uploader("Upload 837 .txt file from HHAExchange", type=['txt'])
        
        if uploaded_file:
            content = uploaded_file.read().decode("utf-8")
            parsed_data = parse_837_to_records(content)
            
            # Prevent Duplicates
            existing_ids = sheet.col_values(1)
            unique_rows = [r for r in parsed_data if r[0] not in existing_ids]
            
            if unique_rows:
                sheet.append_rows(unique_rows)
                st.success(f"Successfully synced {len(unique_rows)} new claims.")
            else:
                st.warning("All claims in this file are already in the database.")

    
# --- DATA PROCESSING ---
    try:
        # 1. Define the exact headers expected in Row 1 of the Google Sheet
        expected_columns = [
            "claim_id", "patient_name", "mi", "service_date", 
            "amount", "units", "hours"
        ]
        
        # 2. Fetch data and validate headers simultaneously
        data = sheet.get_all_records(expected_headers=expected_columns)
        
        # 3. Add a "Last Synced" notice for the user
        st.sidebar.caption(f"Last synced: {datetime.now().strftime('%I:%M %p')}")

    except Exception as e:
        st.error("🚨 **Data Format Error**")
        st.info(f"The Google Sheet headers must match: `{', '.join(expected_columns)}`")
        st.stop() # Prevents further errors in the metrics section below
        if data:
            df = pd.DataFrame(data)
            df['service_date'] = pd.to_datetime(df['service_date'])
        
        # --- TOP METRICS (Week-over-Week) ---
        latest_date = df['service_date'].max()
        this_week = df[df['service_date'] > (latest_date - timedelta(days=7))]
        prev_week = df[(df['service_date'] <= (latest_date - timedelta(days=7))) & 
                       (df['service_date'] > (latest_date - timedelta(days=14)))]
        
        rev_now = this_week['amount'].sum()
        rev_prev = prev_week['amount'].sum()
        wow_change = ((rev_now - rev_prev) / rev_prev * 100) if rev_prev > 0 else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("Current Weekly Revenue", f"${rev_now:,.2f}", f"{wow_change:.1f}% WoW")
        m2.metric("Weekly Hours Billed", f"{this_week['hours'].sum():.2f} hrs")
        m3.metric("Total History Billed", f"${df['amount'].sum():,.2f}")

        # --- UNUSUAL ACTIVITY ALERTS ---
        st.divider()
        st.subheader("⚠️ Unusual Activity Alerts")
        baselines = df.groupby("patient_name")["hours"].mean()
        alerts = []
        for _, row in this_week.iterrows():
            if row['hours'] < (baselines[row['patient_name']] * 0.8):
                alerts.append(f"**LOW HOURS**: {row['patient_name']} - {row['hours']} hrs on {row['service_date'].date()} (Avg: {baselines[row['patient_name']]:.1f})")
        
        if alerts:
            for a in alerts: st.error(a)
        else:
            st.success("No unusual activity detected in the current period.")

        # --- VISUALS ---
        col_left, col_right = st.columns(2)
        
        with col_left:
            st.subheader("Total Hours per Patient")
            fig_hours = px.bar(df.groupby("patient_name")["hours"].sum().reset_index(), 
                               x="patient_name", y="hours", color="hours", template="plotly_white")
            st.plotly_chart(fig_hours, use_container_width=True)

        with col_right:
            st.subheader("📍 Patient Service Map")
            # Static coordinates for Atlantic County service areas
            geo_map = {
                "Atlantic City": [39.3643, -74.4229],
                "Mays Landing": [39.4523, -74.7277],
                "Galloway": [39.4482, -74.4510],
                "Tuckerton": [39.6032, -74.3407],
                "Hammonton": [39.6354, -74.8027]
            }
            # Add simple mapping logic or coordinates to your DF here
            st.map(pd.DataFrame({'lat': [39.36, 39.45, 39.44], 'lon': [-74.42, -74.72, -74.45]}))

        st.subheader("Full Billing Audit Log")
        st.dataframe(df.sort_values("service_date", ascending=False), use_container_width=True)

    else:
        st.info("Dashboard is empty. Please upload an HHAExchange file to begin.")

except Exception as e:
    st.error(f"Configuration Error: {e}")
    st.info("Check your Streamlit Secrets and Google Sheet sharing settings.")
