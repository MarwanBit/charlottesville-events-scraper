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

# --- Null rate ---
# Treat null and empty string as missing
events_df = pd.read_sql("SELECT * FROM event_records;", engine)
def is_missing(series):
    if series.dtype == object or str(series.dtype) == "object":
        return series.isna() | (series.astype(str).str.strip() == "")
    return series.isna()

missing = events_df.apply(is_missing)

st.subheader("Null/empty rate by column (%)")
missing_by_col = (missing.sum() / len(events_df) * 100).round(1).sort_values(ascending=False)
missing_by_col = missing_by_col[missing_by_col > 0].reset_index()
missing_by_col.columns = ["column", "null_empty_pct"]
if len(missing_by_col) > 0:
    st.dataframe(missing_by_col, use_container_width=True)
    st.bar_chart(missing_by_col.set_index("column"))
else:
    st.caption("No null or empty values in any column.")

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
