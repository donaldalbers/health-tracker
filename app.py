import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, date
import plotly.express as px
import plotly.graph_objects as go

# --- CONFIGURATION ---
DAILY_BMR = 2400
HOURLY_BMR = 100
CALORIES_PER_POUND = 3500

st.set_page_config(page_title="Health Commander 2.0", page_icon="💪", layout="wide")

# --- GOOGLE SHEETS CONNECTION ---
def get_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open("Health_Tracker_DB").worksheet("Logs")

try:
    sheet = get_sheet()
except Exception:
    st.error("Connection Error! Check your secrets setup.")
    st.stop()

# --- SIDEBAR: DATA ENTRY ---
st.sidebar.header("📝 Log Activity")

with st.sidebar.form(key='entry_form'):
    date_val = st.date_input("Date", datetime.now())
    time_val = st.time_input("Time", datetime.now())
    # Added "Alcohol" to the list
    activity_type = st.selectbox("Type", ["Food (In)", "Alcohol (In)", "Exercise (Out)"])
    item_name = st.text_input("Description", "e.g., Tacos / 3mi Run")
    calories = st.number_input("Calories", min_value=1, step=10)
    
    submit_button = st.form_submit_button(label='Commit to Database')

if submit_button:
    # Save to Google Sheet
    row_data = [str(date_val), str(time_val), activity_type, item_name, calories]
    sheet.append_row(row_data)
    st.sidebar.success("Entry Saved!")
    st.rerun() # Refresh page to show new data immediately

# --- LOAD DATA ---
raw_data = sheet.get_all_records()
df = pd.DataFrame(raw_data)

if df.empty:
    st.info("No data found. Start logging in the sidebar!")
    st.stop()

# Data Cleaning
df['Calories'] = pd.to_numeric(df['Calories'], errors='coerce').fillna(0)
df['Date'] = pd.to_datetime(df['Date']).dt.date
df['Datetime'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Time'].astype(str))

# --- DASHBOARD CONTROLS ---
st.title("📊 Health Analytics")

# Date Range Filter
filter_option = st.radio("Time Range:", ["Today", "Last 7 Days", "Last 30 Days", "All Time"], horizontal=True)

today = date.today()
if filter_option == "Today":
    start_date = today
    end_date = today
elif filter_option == "Last 7 Days":
    start_date = today - timedelta(days=6)
    end_date = today
elif filter_option == "Last 30 Days":
    start_date = today - timedelta(days=29)
    end_date = today
else:
    start_date = df['Date'].min()
    end_date = today

# Filter Logic
mask = (df['Date'] >= start_date) & (df['Date'] <= end_date)
filtered_df = df.loc[mask]

# --- CALCULATIONS ---
# 1. Calculate base metrics from logs
total_food = filtered_df[filtered_df['Type'] == "Food (In)"]['Calories'].sum()
total_alcohol = filtered_df[filtered_df['Type'] == "Alcohol (In)"]['Calories'].sum()
total_exercise = filtered_df[filtered_df['Type'] == "Exercise (Out)"]['Calories'].sum()

# 2. Calculate BMR (Living Expense)
# Number of days in the selected range (inclusive)
num_days = (end_date - start_date).days + 1
total_bmr = num_days * DAILY_BMR

# 3. Aggregates
total_in = total_food + total_alcohol
total_out = total_exercise + total_bmr
net_calories = total_in - total_out

# 4. Weight Estimation
estimated_lbs_lost = (total_out - total_in) / CALORIES_PER_POUND

# --- TOP LEVEL METRICS ---
c1, c2, c3, c4 = st.columns(4)

c1.metric("Total Intake", f"{total_in:,.0f}", delta=f"{total_alcohol:,.0f} from Alcohol", delta_color="inverse")
c2.metric("Total Burn", f"{total_out:,.0f}", help=f"Includes {total_bmr:,.0f} BMR (Living) + {total_exercise:,.0f} Exercise")

# Logic for Excess vs Deficit display
if net_calories > 0:
    c3.metric("Net Balance", f"+{net_calories:,.0f}", "⚠️ Excess Calories", delta_color="inverse")
else:
    c3.metric("Net Balance", f"{net_calories:,.0f}", "✅ Deficit", delta_color="normal")

# Weight Estimation Color Logic
w_color = "normal" if estimated_lbs_lost > 0 else "inverse"
c4.metric("Est. Weight Impact", f"{estimated_lbs_lost:,.2f} lbs", "Based on 3500kcal rule", delta_color=w_color)

st.markdown("---")

# --- VISUALIZATIONS ---

# CHART 1: TIMELINE (If Single Day) or TREND (If Date Range)
if start_date == end_date:
    # === SINGLE DAY HOURLY VIEW ===
    st.subheader(f"Hourly Breakdown: {start_date}")
    
    # Create Synthetic BMR Data for the Chart (24 hours of 100 cal burn)
    hours = [f"{i:02d}:00:00" for i in range(24)]
    bmr_data = pd.DataFrame({
        "Time": hours,
        "Calories": [HOURLY_BMR] * 24,
        "Type": ["BMR (Living)"] * 24,
        "Item": ["Base Metabolic Rate"] * 24
    })
    
    # Combine with actual logs
    day_view_df = filtered_df[['Time', 'Calories', 'Type', 'Item']].copy()
    # Normalize time column to string for consistent plotting
    day_view_df['Time'] = day_view_df['Time'].astype(str)
    
    # Stack BMR with Logs
    combined_day_df = pd.concat([bmr_data, day_view_df])
    
    # Sort by time
    combined_day_df = combined_day_df.sort_values("Time")

    fig_timeline = px.bar(combined_day_df, x='Time', y='Calories', color='Type', 
                          title="Hourly Calorie Velocity",
                          color_discrete_map={
                              "Food (In)": "#EF553B", 
                              "Alcohol (In)": "#FFA15A",
                              "Exercise (Out)": "#00CC96",
                              "BMR (Living)": "#AB63FA"
                          })
    st.plotly_chart(fig_timeline, use_container_width=True)

else:
    # === MULTI-DAY TREND VIEW ===
    st.subheader("Daily Trends")
    
    # Group data by Date
    daily_stats = filtered_df.groupby(['Date', 'Type'])['Calories'].sum().reset_index()
    
    # We need to manually add BMR to every day in the range for the chart
    dates_in_range = pd.date_range(start_date, end_date).date
    bmr_rows = []
    for d in dates_in_range:
        bmr_rows.append({'Date': d, 'Type': 'BMR (Living)', 'Calories': DAILY_BMR})
    
    daily_stats = pd.concat([daily_stats, pd.DataFrame(bmr_rows)])
    
    fig_trend = px.bar(daily_stats, x='Date', y='Calories', color='Type',
                       title="Daily Intake vs Burn", barmode='group',
                       color_discrete_map={
                           "Food (In)": "#EF553B", 
                           "Alcohol (In)": "#FFA15A",
                           "Exercise (Out)": "#00CC96",
                           "BMR (Living)": "#AB63FA"
                       })
    st.plotly_chart(fig_trend, use_container_width=True)


# CHART 2: ALCOHOL TRACKER
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("🍺 Alcohol Consumption")
    alcohol_df = filtered_df[filtered_df['Type'] == "Alcohol (In)"]
    if not alcohol_df.empty:
        fig_alc = px.bar(alcohol_df, x='Date', y='Calories', color='Item', title="Alcohol Calories by Day")
        st.plotly_chart(fig_alc, use_container_width=True)
    else:
        st.info("No alcohol logged in this period.")

with col_b:
    st.subheader("Detailed Logs")
    st.dataframe(filtered_df[['Date', 'Time', 'Type', 'Item', 'Calories']], hide_index=True, use_container_width=True)

st.markdown("---")

# --- DELETE FUNCTIONALITY ---
with st.expander("🗑️ Manage Data / Delete Entries"):
    st.warning("Warning: Deleting an entry is permanent.")
    
    # Show the last 10 entries from the RAW dataframe (not filtered)
    # We use the original dataframe index to identify rows
    last_entries = df.tail(10).sort_index(ascending=False)
    
    # Create a selection box for deletion
    # We map the display string to the DATAFRAME INDEX
    entry_options = {f"{row['Date']} - {row['Item']} ({row['Calories']} cal)": idx for idx, row in last_entries.iterrows()}
    
    selected_entry_label = st.selectbox("Select Entry to Delete:", options=list(entry_options.keys()))
    
    if st.button("Delete Selected Entry"):
        if selected_entry_label:
            df_index_to_delete = entry_options[selected_entry_label]
            
            # GSpread uses 1-based indexing.
            # Row 1 is Headers. Row 2 is Index 0. 
            # So Sheet Row = DataFrame Index + 2
            sheet_row_number = df_index_to_delete + 2
            
            sheet.delete_rows(sheet_row_number)
            st.success(f"Deleted row {sheet_row_number}. Please refresh.")
            st.rerun()
