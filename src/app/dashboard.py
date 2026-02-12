import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

# Use same DB URL you used in models.py
DB_URL = "postgresql+psycopg://events:events@127.0.0.1:5432/events"
engine = create_engine(DB_URL)

st.set_page_config(page_title="Charlottesville Events Dashboard", layout="wide")

st.title("Charlottesville Events Dashboard")

# --- KPIs ---
total_events = pd.read_sql("SELECT COUNT(*) AS cnt FROM event_records;", engine)["cnt"][0]
st.metric("Total events in DB", int(total_events))

# --- Category breakdown ---
st.subheader("Events by Category")
cat_df = pd.read_sql("""
    SELECT COALESCE(event_category, 'Unknown') AS category, COUNT(*) AS count
    FROM event_records
    GROUP BY 1
    ORDER BY count DESC;
""", engine)

st.dataframe(cat_df, use_container_width=True)
st.bar_chart(cat_df.set_index("category"))

# --- Recent events table ---
st.subheader("Sample events")
events_df = pd.read_sql("""
    SELECT *
    FROM event_records
    ORDER BY start_date NULLS LAST;
""", engine)

st.dataframe(events_df, use_container_width=True)
