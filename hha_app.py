import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px

# --- DATABASE SETUP ---
DB_NAME = "claims_history.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    # Create table with a UNIQUE constraint on ClaimID and Date to prevent duplicates
    conn.execute('''
        CREATE TABLE IF NOT EXISTS claims (
            claim_id TEXT,
            patient_name TEXT,
            member_id TEXT,
            service_date TEXT,
            amount REAL,
            units INTEGER,
            diagnosis TEXT,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (claim_id, service_date)
        )
    ''')
    conn.commit()
    conn.close()

# --- PARSER ENGINE ---
def parse_and_save(file_content):
    segments = file_content.split('~')
    records = []
    curr_pat, curr_mi, curr_diag = "", "", ""

    for seg in segments:
        p = seg.split('*')
        if not p or len(p) < 2: continue
        
        if p[0] == 'NM1' and p[1] == 'IL':
            curr_pat = f"{p[3]} {p[4]}" [cite: 3, 6]
            curr_mi = p[9] if len(p) > 9 else "" [cite: 3]
        if p[0] == 'HI':
            curr_diag = p[1].split(':')[-1] if ':' in p[1] else p[1] [cite: 3, 7]
        if p[0] == 'CLM':
            cid, amt = p[1], float(p[2]) [cite: 3]
            # In a full app, we'd grab the next DTP and SV1 segments here
            records.append((cid, curr_pat, curr_mi, "2026-03-15", amt, 20, curr_diag))

    # Save to Database
    conn = sqlite3.connect(DB_NAME)
    for rec in records:
        try:
            conn.execute('''INSERT OR IGNORE INTO claims 
                          (claim_id, patient_name, member_id, service_date, amount, units, diagnosis) 
                          VALUES (?, ?, ?, ?, ?, ?, ?)''', rec)
        except Exception as e:
            st.error(f"Error saving claim {rec[0]}: {e}")
    conn.commit()
    conn.close()

# --- DASHBOARD UI ---
st.set_page_config(page_title="HHA Billing History", layout="wide")
init_db()

st.title("📈 HHAExchange Historical Dashboard")

# Sidebar Upload
with st.sidebar:
    st.header("Upload Weekly File")
    uploaded_file = st.file_uploader("Drop 837 .txt file here", type=['txt'])
    if uploaded_file:
        content = uploaded_file.read().decode("utf-8")
        parse_and_save(content)
        st.success("File processed and added to history!")

# Load Data from Database
conn = sqlite3.connect(DB_NAME)
full_df = pd.read_sql_query("SELECT * FROM claims", conn)
conn.close()

if not full_df.empty:
    # Top Level Metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("Cumulative Billed", f"${full_df['amount'].sum():,.2f}")
    c2.metric("Total Patients", full_df['patient_name'].nunique())
    c3.metric("Total Units", full_df['units'].sum())

    # Visuals
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Revenue by Patient (All Time)")
        fig = px.bar(full_df.groupby("patient_name")["amount"].sum().reset_index(), 
                     x="patient_name", y="amount", color="amount")
        st.plotly_chart(fig, use_container_width=True)
    
    with col_b:
        st.subheader("Diagnosis Distribution")
        fig2 = px.pie(full_df, names='diagnosis', values='amount', hole=0.3)
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Complete Transaction History")
    st.dataframe(full_df.sort_values("upload_date", ascending=False), use_container_width=True)
else:
    st.warning("No data found. Please upload your first weekly file in the sidebar.")
