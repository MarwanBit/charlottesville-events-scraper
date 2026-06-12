import pandas as pd
import streamlit as st
import altair as alt

from src.app.models import engine as _lazy_engine

st.set_page_config(page_title="Charlottesville Events Dashboard", layout="wide")

# Exceedingly large text for readability (e.g. when pasting into Google Docs)
st.markdown(
    """
    <style>
    /* Main title */
    h1 { font-size: 3.5rem !important; }
    /* Subheaders */
    h2, h3 { font-size: 2.5rem !important; }
    /* Body and captions */
    .stMarkdown p, .stCaption { font-size: 1.5rem !important; }
    /* Metric value and label */
    [data-testid="stMetricValue"] { font-size: 2.75rem !important; }
    [data-testid="stMetricLabel"] { font-size: 1.5rem !important; }
    /* Dataframes */
    .stDataFrame { font-size: 1.25rem !important; }
    .stDataFrame td, .stDataFrame th { font-size: 1.25rem !important; padding: 0.75rem !important; }
    /* Buttons */
    .stButton button { font-size: 1.25rem !important; padding: 0.6rem 1.2rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Charlottesville Events Dashboard")


def is_missing(series):
    if series.dtype == object or str(series.dtype) == "object":
        return series.isna() | (series.astype(str).str.strip() == "")
    return series.isna()


# Resolve the real SQLAlchemy engine from the lazy wrapper.
_engine = _lazy_engine._get_engine()

# --- KPIs ---
total_events = pd.read_sql("SELECT COUNT(*) AS cnt FROM event_records;", _engine)["cnt"][0]
st.metric("Total events in DB", int(total_events))

# --- Null rate ---
'''
events_df = pd.read_sql("SELECT * FROM event_records;", _engine)
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
'''

# --- Category breakdown ---
st.subheader("Events by Category")
cat_df = pd.read_sql("""
    SELECT COALESCE(event_category, 'Unknown') AS category, COUNT(*) AS count
    FROM event_records
    GROUP BY 1
    ORDER BY count DESC;
""", _engine)

st.dataframe(cat_df, use_container_width=True)
st.bar_chart(cat_df.set_index("category"))

# --- Website data completeness (computed in pandas, matching the SQL logic) ---
st.subheader("Usable events by website")

websites = [
    "visitcharlottesville.org",
    "washington.org",
    "visitma.com",
    "enjoyillinois.com",
    "exploregeorgia.org",
    "texastimetravel.com",
    "visitarizona.com",
]

events_df = pd.read_sql("SELECT * FROM event_records;", _engine)

usable_mask = (
    events_df["start_date"].notna() & (events_df["start_date"].astype(str).str.strip() != "") &
    events_df["end_date"].notna() & (events_df["end_date"].astype(str).str.strip() != "") &
    events_df["start_time"].notna() & (events_df["start_time"].astype(str).str.strip() != "") &
    events_df["end_time"].notna() & (events_df["end_time"].astype(str).str.strip() != "") &
    events_df["address"].notna() & (events_df["address"].astype(str).str.strip() != "")
)

events_df = events_df.copy()
events_df["is_usable"] = usable_mask

rows = []
for site in websites:
    mask = events_df["event_link"].astype(str).str.contains(site, na=False)
    subset = events_df[mask]
    total_events_site = len(subset)
    if total_events_site == 0:
        total_usable_site = 0
        usable_pct_site = 0.0
    else:
        total_usable_site = int(subset["is_usable"].sum())
        usable_pct_site = total_usable_site * 100.0 / total_events_site
    rows.append(
        {
            "website_name": site,
            "total_usable_events": total_usable_site,
            "total_events": total_events_site,
            "usable_percentage": usable_pct_site,
        }
    )

website_df = pd.DataFrame(rows)
website_df = website_df.sort_values(
    by=["usable_percentage", "total_events"], ascending=[False, False]
)

st.dataframe(website_df, use_container_width=True)

st.caption("Usable events require non-empty dates, times, and address.")

st.subheader("Usable percentage by website")

percentage_chart = (
    alt.Chart(website_df)
    .mark_bar()
    .encode(
        x=alt.X("website_name:N", title="Website"),
        y=alt.Y("usable_percentage:Q", title="Usable events (%)"),
        color=alt.Color("website_name:N", legend=alt.Legend(title="Website")),
        tooltip=[
            alt.Tooltip("website_name:N", title="Website"),
            alt.Tooltip("usable_percentage:Q", title="Usable %", format=".1f"),
            alt.Tooltip("total_usable_events:Q", title="Usable events"),
            alt.Tooltip("total_events:Q", title="Total events"),
        ],
    )
    .properties(height=480, width="container")
    .configure_axis(labelFontSize=22, titleFontSize=26)
    .configure_legend(labelFontSize=22, titleFontSize=26)
)

st.altair_chart(percentage_chart, use_container_width=True)

st.subheader("Total vs usable events by website")

totals_long = website_df.melt(
    id_vars="website_name",
    value_vars=["total_events", "total_usable_events"],
    var_name="metric",
    value_name="events",
)

totals_chart = (
    alt.Chart(totals_long)
    .mark_bar()
    .encode(
        x=alt.X("website_name:N", title="Website"),
        y=alt.Y("events:Q", title="Number of events"),
        color=alt.Color(
            "metric:N",
            legend=alt.Legend(title="Metric", labelExpr="datum.label == 'total_usable_events' ? 'Usable events' : 'Total events'"),
        ),
        tooltip=[
            alt.Tooltip("website_name:N", title="Website"),
            alt.Tooltip("metric:N", title="Metric"),
            alt.Tooltip("events:Q", title="Events"),
        ],
    )
    .properties(height=480, width="container")
    .configure_axis(labelFontSize=22, titleFontSize=26)
    .configure_legend(labelFontSize=22, titleFontSize=26)
)

st.altair_chart(totals_chart, use_container_width=True)

csv_bytes = website_df.to_csv(index=False).encode("utf-8")
st.download_button(
    "Download website metrics (CSV)",
    data=csv_bytes,
    file_name="website_usable_events_by_website.csv",
    mime="text/csv",
)

# --- Recent events table ---
st.subheader("Sample events")
events_df = pd.read_sql("""
    SELECT *
    FROM event_records
    ORDER BY start_date NULLS LAST;
""", _engine)

st.dataframe(events_df, use_container_width=True)
