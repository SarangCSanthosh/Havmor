# app.py
"""
Temperature Monitoring Dashboard
(Fixed: TODAY panel now uses original Excel date — BaseDate)
(Updated: Reads live data directly from Google Sheets)
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, time
import plotly.graph_objects as go

# -------------------------------
# CONFIG
# -------------------------------
st.set_page_config(layout="wide", page_title="Temperature Monitoring Dashboard")
st.title("❄ Temperature Monitoring — Channel Performance Dashboard")

DESIRED_MIN = -25
DESIRED_MAX = -10

# GOOGLE SHEET URL
gsheet_url = "https://docs.google.com/spreadsheets/d/1VxXJUP-tFMU1UaXNmBXut_wk5FQZ-SB-/export?format=xlsx"

# -------------------------------
# LOAD & TRANSFORM FUNCTION
# -------------------------------
@st.cache_data
def load_all_channels(url):
    xls = pd.ExcelFile(url)
    real_sheets = xls.sheet_names
    clean_sheets = [s.strip() for s in real_sheets]
    sheet_map = dict(zip(clean_sheets, real_sheets))

    channels = {}

    for clean in clean_sheets:
        real = sheet_map[clean]
        df = pd.read_excel(url, sheet_name=real, header=3)
        df = df.dropna(axis=1, how="all")

        df_long = df.melt(id_vars=["Date"], var_name="Hour", value_name="Temperature")
        df_long = df_long.dropna(subset=["Date", "Temperature"])

        df_long["Channel"] = clean
        df_long["Date"] = pd.to_datetime(df_long["Date"], errors="coerce")

        # BaseDate = original real date
        df_long["BaseDate"] = df_long["Date"].dt.date

        # ---- HOUR CLEANING ----
        df_long["Hour"] = df_long["Hour"].astype(str).str.strip()
        df_long["Hour"] = df_long["Hour"].str.extract(r"(\d+)")
        df_long["Hour_int"] = pd.to_numeric(df_long["Hour"], errors="coerce")

        df_long = df_long.dropna(subset=["Hour_int"])
        df_long["Hour_int"] = df_long["Hour_int"].astype(int)

        # ---- TIMESTAMP FIX ----
        timestamps = []
        for _, r in df_long.iterrows():
            base = r["BaseDate"]
            h = int(r["Hour_int"])

            if h == 24:
                ts = datetime.combine(base, time(23, 59))
            else:
                ts = datetime.combine(base, time(h, 0))

            timestamps.append(ts)

        df_long["Timestamp"] = pd.to_datetime(timestamps)

        # Extra columns
        df_long["Date_only"] = df_long["Timestamp"].dt.date
        df_long["MonthPeriod"] = df_long["Timestamp"].dt.to_period("M")
        df_long["ISO_Week"] = df_long["Timestamp"].dt.isocalendar().week
        df_long["Year"] = df_long["Timestamp"].dt.isocalendar().year

        df_long["Temperature"] = pd.to_numeric(df_long["Temperature"], errors="coerce")
        df_long = df_long.dropna(subset=["Temperature"])

        channels[clean] = df_long

    return channels


# Load channels
channels = load_all_channels(gsheet_url)

# --------------------------------
# SIDEBAR YEAR FILTER
# --------------------------------
st.sidebar.header("Filters")

all_years = sorted({int(y) for df in channels.values() for y in df["Year"].unique()})
current_year = date.today().year
default_index = all_years.index(current_year) if current_year in all_years else 0

selected_year = st.sidebar.selectbox("Select Year", options=all_years, index=default_index)

channels = {
    ch: df[df["Year"] == selected_year]
    for ch, df in channels.items()
    if not df[df["Year"] == selected_year].empty
}

channel_names = list(channels.keys())

if not channel_names:
    st.warning(f"No data available for year {selected_year}.")
    st.stop()

# ---------------------------------------------
# DONUT KPI
# ---------------------------------------------
def donut_kpi(channel_name, df_channel, color="#2ca02c"):
    total = len(df_channel)
    safe_count = df_channel["Temperature"].between(DESIRED_MIN, DESIRED_MAX).sum()
    out_count = total - safe_count

    safe_plot = safe_count if safe_count > 0 else 0.0001
    out_plot = out_count if out_count > 0 else 0.0001

    safe_str = f"{safe_count:,}"
    out_str = f"{out_count:,}"

    fig = go.Figure()
    fig.add_trace(go.Pie(
        labels=["Safe", "Out-of-Range"],
        values=[safe_plot, out_plot],
        hole=0.65,
        marker=dict(colors=[color, "#eaeaea"]),
        sort=False,
        textinfo="none",
        hovertemplate=
            "Safe Range Readings: " + safe_str +
            "<br>Out-of-Range Readings: " + out_str +
            "<extra></extra>"
    ))

    percent = round((safe_count / total) * 100, 1) if total else 0

    fig.update_layout(
        margin=dict(l=5, r=5, t=5, b=5),
        showlegend=False,
        annotations=[{
            "text": f"<b>{percent}%</b><br>{channel_name}",
            "x": 0.5, "y": 0.5,
            "showarrow": False,
            "font": dict(size=15)
        }]
    )
    return fig


# ---------------------------------------------
# SUMMARY BAR CHART
# ---------------------------------------------
def channel_temp_summary_df(channels_dict):
    return pd.DataFrame([
        {"Channel": ch,
         "AvgTemp": df["Temperature"].mean(),
         "MinTemp": df["Temperature"].min(),
         "MaxTemp": df["Temperature"].max()}
        for ch, df in channels_dict.items()
    ])

def plot_channel_summary_bars(df_summary):
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Avg Temp", x=df_summary["Channel"], y=df_summary["AvgTemp"]))
    fig.add_trace(go.Bar(name="Min Temp", x=df_summary["Channel"], y=df_summary["MinTemp"]))
    fig.add_trace(go.Bar(name="Max Temp", x=df_summary["Channel"], y=df_summary["MaxTemp"]))
    fig.update_layout(barmode="group", height=480, title="Channel Temperature Summary")
    return fig

# ---------------------------------------------
# SAFE RANGE LINES
# ---------------------------------------------
def add_safe_lines(fig):
    fig.add_hline(y=DESIRED_MIN, line_dash="dash", line_color="red", line_width=2)
    fig.add_hline(y=DESIRED_MAX, line_dash="dash", line_color="red", line_width=2)

# ---------------------------------------------
# TODAY PANEL (FIXED)
# ---------------------------------------------
def small_today_hourly(df_channel):
    latest_day = df_channel["BaseDate"].max()
    df_day = df_channel[df_channel["BaseDate"] == latest_day].copy()

    if df_day.empty:
        return None

    df_day["HourDisplay"] = df_day["Hour_int"].replace({0: 24})
    df_day = df_day.sort_values("HourDisplay")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_day["HourDisplay"].astype(int),
        y=df_day["Temperature"],
        mode="lines+markers",
        line=dict(color="royalblue")
    ))

    add_safe_lines(fig)

    fig.update_layout(
        title=f"Today ({latest_day})",
        height=260,
        xaxis=dict(
            tickmode="array",
            tickvals=df_day["HourDisplay"],
            type="linear"
        )
    )
    return fig


# ---------------------------------------------
# WEEKLY PANEL
# ---------------------------------------------
def small_weekly(df_channel):
    df_w = df_channel.groupby(
        [df_channel["Year"], df_channel["ISO_Week"]]
    )["Temperature"].mean().reset_index()

    df_w["Label"] = df_w["Year"].astype(str) + "-W" + df_w["ISO_Week"].astype(str)

    fig = go.Figure(go.Scatter(x=df_w["Label"], y=df_w["Temperature"], mode="lines+markers"))
    add_safe_lines(fig)
    fig.update_layout(title="Weekly Avg Temp", height=260)
    return fig

# ---------------------------------------------
# MONTHLY PANEL
# ---------------------------------------------
def small_monthly(df_channel):
    df_m = df_channel.groupby(df_channel["MonthPeriod"].astype(str))["Temperature"].mean().reset_index()

    fig = go.Figure(go.Bar(x=df_m["MonthPeriod"], y=df_m["Temperature"]))
    add_safe_lines(fig)
    fig.update_layout(title="Monthly Avg Temp", height=260)
    return fig


# -----------------------------------------------
# TOP DONUTS
# -----------------------------------------------
st.markdown("## Channel Compliance")
cols = st.columns(len(channel_names))
for i, ch in enumerate(channel_names):
    cols[i].plotly_chart(donut_kpi(ch, channels[ch]), use_container_width=True)


# -----------------------------------------------
# SUMMARY
# -----------------------------------------------
st.markdown("---")
df_summary = channel_temp_summary_df(channels)
st.plotly_chart(plot_channel_summary_bars(df_summary), use_container_width=True)


# -----------------------------------------------
# PER-CHANNEL PANELS
# -----------------------------------------------
st.markdown("---")
st.markdown("## Channel Panels — Today / Weekly / Monthly")

for ch in channel_names:
    st.subheader(ch)

    col1, col2, col3 = st.columns(3)

    if selected_year == current_year:
        col1.plotly_chart(small_today_hourly(channels[ch]), use_container_width=True)
    else:
        col1.info("Only available for current year")

    col2.plotly_chart(small_weekly(channels[ch]), use_container_width=True)
    col3.plotly_chart(small_monthly(channels[ch]), use_container_width=True)


# -----------------------------------------------
# PEAK OUT-OF-RANGE HOURS (LATEST MONTH)
# -----------------------------------------------
st.markdown("---")
st.subheader("Peak Out-of-Range Hours — Latest Month")

latest_month = None
for ch, dfc in channels.items():
    if not dfc.empty:
        m = dfc["MonthPeriod"].max()
        if latest_month is None or m > latest_month:
            latest_month = m

if latest_month is None:
    st.info("No monthly data available.")
else:
    st.write(f"Latest Month: **{latest_month}**")

    selected_channel = st.radio("Select Channel", options=list(channels.keys()), horizontal=True)

    dfc = channels[selected_channel]
    dfm = dfc[dfc["MonthPeriod"] == latest_month].copy()

    if not dfm.empty:
        dfm["HourDisplay"] = dfm["Timestamp"].dt.hour.replace(0, 24)
        unique_hours = sorted(dfm["HourDisplay"].unique())

        df_out = dfm[~dfm["Temperature"].between(DESIRED_MIN, DESIRED_MAX)].copy()

        if df_out.empty:
            df_hour = pd.DataFrame({"HourDisplay": unique_hours, "Count": [0] * len(unique_hours)})
        else:
            df_out["HourDisplay"] = df_out["HourDisplay"].astype(int)
            df_hour = df_out.groupby("HourDisplay").size().reindex(unique_hours, fill_value=0).reset_index(name="Count")

        fig_peak = go.Figure()
        fig_peak.add_trace(go.Bar(x=df_hour["HourDisplay"], y=df_hour["Count"], marker_color="crimson"))

        fig_peak.update_layout(
            title=f"Out-of-Range Frequency — {selected_channel}",
            xaxis_title="Hour (1–24)",
            yaxis_title="Out-of-Range Count",
            height=400
        )

        st.plotly_chart(fig_peak, use_container_width=True)


# -----------------------------------------------
# ALERTS (LATEST AVAILABLE DATE)
# -----------------------------------------------
st.markdown("---")
st.subheader("Alerts Summary (Latest Available Date)")

latest_real_day = max(dfc["BaseDate"].max() for dfc in channels.values())

st.write(f"Latest Date in Dataset: **{latest_real_day}**")

alerts = []

for ch, dfc in channels.items():
    df_today = dfc[dfc["BaseDate"] == latest_real_day]
    out = df_today[~df_today["Temperature"].between(DESIRED_MIN, DESIRED_MAX)]

    for _, r in out.iterrows():
        alerts.append({
            "Channel": ch,
            "Timestamp": r["Timestamp"],
            "Temp": r["Temperature"]
        })

if alerts:
    df_alert = pd.DataFrame(alerts)
    df_alert["Timestamp"] = df_alert["Timestamp"].dt.strftime("%Y-%m-%d %H:%M")
    df_alert.index = df_alert.index + 1
    df_alert.index.name = "Sl No"
    st.table(df_alert)
else:
    st.success(f"No out-of-range readings on {latest_real_day}.")
