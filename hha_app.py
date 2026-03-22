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
    
    # --- SIDEBAR: FILTERS & UPLOAD ---
    with st.sidebar:
        st.header("Data Filters")
        show_all = st.checkbox("Show All Historical Data", value=False)
        today = datetime.now().date()
        date_selection = st.date_input("Select Date Range", value=(today - timedelta(days=90), today))
        
        st.divider()
        st.header("Import Data")
        uploaded_file = st.file_uploader("Upload HHA CSV Export", type=['csv'])
        
        if uploaded_file and st.button("🚀 Sync CSV to Database"):
            csv_df = pd.read_csv(uploaded_file)
            
            # Map HHAExchange Headers to Dashboard Schema
            clean_csv = pd.DataFrame()
            clean_csv['claim_id'] = csv_df['Invoice_Number'].astype(str)
            clean_csv['patient_name'] = csv_df['Patient']
            clean_csv['mi'] = "" 
            clean_csv['service_date'] = pd.to_datetime(csv_df['Visit_Date']).dt.strftime('%Y-%m-%d')
            clean_csv['amount'] = csv_df['Billed_Amt']
            clean_csv['units'] = csv_df['Billed_Unit']
            clean_csv['hours'] = csv_df['Billed_Unit'] * 0.25
            
            # Deduplication
            existing_ids = sheet.col_values(1)
            to_add = clean_csv[~clean_csv['claim_id'].isin(existing_ids)].values.tolist()

            if to_add:
                sheet.append_rows(to_add)
                st.success(f"Added {len(to_add)} records!")
                st.rerun()
            else:
                st.info("No new unique records found.")

    # --- DATA RETRIEVAL ---
    # We pull all data and clean headers manually to prevent the 'Application Error'
    raw_records = sheet.get_all_records()
    
    if raw_records:
        df = pd.DataFrame(raw_records)
        df.columns = [c.strip() for c in df.columns] # Remove hidden spaces
        df['service_date'] = pd.to_datetime(df['service_date'])
        
        # Filtering
        if show_all:
            df_filtered = df
        elif isinstance(date_selection, tuple) and len(date_selection) == 2:
            start, end = date_selection
            df_filtered = df[(df['service_date'].dt.date >= start) & (df['service_date'].dt.date <= end)]
        else:
            df_filtered = df

        # --- METRICS ---
        ytd_val = df[df['service_date'].dt.year == datetime.now().year]['amount'].sum()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Period Revenue", f"${df_filtered['amount'].sum():,.2f}")
        m2.metric("Period Hours", f"{df_filtered['hours'].sum():.2f} hrs")
        m3.metric("YTD Total", f"${ytd_val:,.2f}")
        m4.metric("Total History", f"${df['amount'].sum():,.2f}")

        # --- VISUALS ---
        st.divider()
        st.subheader("📈 Monthly Revenue Trend")
        df_m = df.copy()
        df_m['month'] = df_m['service_date'].dt.to_period('M').dt.to_timestamp()
        monthly_summary = df_m.groupby('month')['amount'].sum().reset_index()
        
        fig = px.line(monthly_summary, x='month', y='amount', markers=True, template="plotly_white", color_discrete_sequence=["#2ecc71"])
        fig.update_xaxes(dtick="M1", tickformat="%b %Y")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("👥 Top 5 Patients by Revenue")
        top_5 = df_filtered.groupby("patient_name")["amount"].sum().nlargest(5).reset_index()
        st.plotly_chart(px.pie(top_5, values='amount', names='patient_name', hole=0.4, color_discrete_sequence=px.colors.sequential.Greens_r), use_container_width=True)

    else:
        st.warning("Database is empty. Upload a CSV to begin.")

except Exception as e:
    st.error(f"System Error: {e}")
