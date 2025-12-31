import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, date
import plotly.express as px
import plotly.graph_objects as go
import pytz

# --- CONFIGURATION ---
DAILY_BMR = 2400
HOURLY_BMR = 100
CALORIES_PER_POUND = 3500
TIMEZONE = pytz.timezone('US/Central')

st.set_page_config(page_title="Health Commander 3.0", page_icon="💪", layout="wide")

# --- SESSION STATE FOR PAGINATION ---
if 'offset' not in st.session_state:
    st.session_state.offset = 0
if 'view_mode' not in st.session_state:
    st.session_state.view_mode = "Today"

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

# Get Current Time in CST
now_cst = datetime.now(TIMEZONE)

with st.sidebar.form(key='entry_form', clear_on_submit=True):
    # Auto-fill Date/Time with CST, but allow editing
    date_val = st.date_input("Date", now_cst.date())
    time_val = st.time_input("Time", now_cst.time())
    
    activity_type = st.selectbox("Type", ["Food (In)", "Alcohol (In)", "Exercise (Out)"])
    
    # Dynamic Form Fields
    item_name = st.text_input("Description", placeholder="e.g., Tacos")
    calories = st.number_input("Calories", min_value=0, step=10, value=0)
    
    # Specific Exercise Fields
    ex_type = ""
    duration = 0
    distance = 0.0
    
    if activity_type == "Exercise (Out)":
        ex_type = st.selectbox("Exercise Type", ["Run", "Walk", "Bike", "Peloton", "Lift", "Stair Stepper", "Other"])
        duration = st.number_input("Duration (Minutes)", min_value=0, step=5, value=0)
        
        if ex_type in ["Run", "Walk", "Bike", "Peloton"]:
            distance = st.number_input("Distance (Miles)", min_value=0.0, step=0.1, value=0.0)

    submit_button = st.form_submit_button(label='Commit to Database')

if submit_button:
    # Prepare row with 8 columns (matching new schema)
    # If not exercise, fill explicit fields with empty/zero
    row_data = [
        str(date_val), 
        str(time_val), 
        activity_type, 
        item_name, 
        calories, 
        ex_type if activity_type == "Exercise (Out)" else "",
        duration if activity_type == "Exercise (Out)" else 0,
        distance if activity_type == "Exercise (Out)" else 0
    ]
    sheet.append_row(row_data)
    st.sidebar.success("Saved!")
    st.rerun()

# --- DATA LOADING & CLEANING ---
raw_data = sheet.get_all_records()
df = pd.DataFrame(raw_data)

if df.empty:
    st.info("No data found. Start logging!")
    st.stop()

# Clean Data
df['Calories'] = pd.to_numeric(df['Calories'], errors='coerce').fillna(0)
df['Duration_Min'] = pd.to_numeric(df['Duration_Min'], errors='coerce').fillna(0)
df['Distance_Mi'] = pd.to_numeric(df['Distance_Mi'], errors='coerce').fillna(0)
df['Date'] = pd.to_datetime(df['Date']).dt.date

# --- FILTERING & PAGINATION LOGIC ---
st.title("📊 Health Analytics")

# Top Control Row
c_filter, c_prev, c_next = st.columns([2, 1, 1])

with c_filter:
    view_mode = st.radio("View Mode:", ["Today", "Week View", "Custom Range"], horizontal=True)
    # Reset offset if mode changes
    if view_mode != st.session_state.view_mode:
        st.session_state.offset = 0
        st.session_state.view_mode = view_mode

# Calculate Dates based on Offset + View Mode
base_date = now_cst.date()

if view_mode == "Today":
    # Offset represents Days
    effective_date = base_date + timedelta(days=st.session_state.offset)
    start_date = effective_date
    end_date = effective_date
    shift_amount = 1 # Button moves 1 day
    display_range = f"{effective_date.strftime('%B %d, %Y')}"

elif view_mode == "Week View":
    # Offset represents Weeks
    # Calculate start of the window (offset * 7 days back/forward)
    end_of_window = base_date + timedelta(weeks=st.session_state.offset)
    start_of_window = end_of_window - timedelta(days=6)
    start_date = start_of_window
    end_date = end_of_window
    shift_amount = 1 # Button moves 1 "Unit" (logic handled in button)
    display_range = f"{start_date} to {end_date}"

else: # Custom Range
    # No pagination for custom range
    col_dates = st.columns(2)
    start_date = c_filter.date_input("Start", base_date - timedelta(days=7))
    end_date = c_filter.date_input("End", base_date)
    display_range = "Custom Range"
    shift_amount = 0

# Pagination Buttons
if view_mode != "Custom Range":
    if c_prev.button(f"◀ Previous {view_mode.split(' ')[0]}"):
        st.session_state.offset -= 1
        st.rerun()
    if c_next.button(f"Next {view_mode.split(' ')[0]} ▶"):
        st.session_state.offset += 1
        st.rerun()

st.subheader(f"Analyzing: {display_range}")

# Filter Data
mask = (df['Date'] >= start_date) & (df['Date'] <= end_date)
filtered_df = df.loc[mask]

# --- CALCS ---
total_in = filtered_df[filtered_df['Type'].isin(["Food (In)", "Alcohol (In)"])]['Calories'].sum()
total_exercise = filtered_df[filtered_df['Type'] == "Exercise (Out)"]['Calories'].sum()

# BMR Calc
num_days = (end_date - start_date).days + 1
total_bmr = num_days * DAILY_BMR
total_out = total_exercise + total_bmr
net_calories = total_in - total_out
target_intake = total_out - 500 # The "Goal" Line

# --- TABS ---
tab1, tab2 = st.tabs(["🍎 Nutrition & Weight", "🏃 Fitness & Activities"])

with tab1:
    # Metric Row
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Calories In", f"{total_in:,.0f}")
    m2.metric("Total Burn", f"{total_out:,.0f}", f"{total_exercise:,.0f} Active")
    m3.metric("Net Balance", f"{net_calories:,.0f}", "-500 Goal" if net_calories < -500 else "Over Goal", delta_color="inverse")
    lbs = (total_out - total_in) / 3500
    m4.metric("Est. Weight Loss", f"{lbs:.2f} lbs")

    # MAIN CHART: INTAKE vs BURN with GOAL LINE
    st.markdown("##### 📉 Calorie Performance")
    
    # Prepare Data for Chart
    daily_stats = filtered_df.groupby(['Date', 'Type'])['Calories'].sum().reset_index()
    
    # Add BMR to chart data
    dates_in_range = pd.date_range(start_date, end_date).date
    bmr_rows = [{'Date': d, 'Type': 'BMR (Living)', 'Calories': DAILY_BMR} for d in dates_in_range]
    chart_df = pd.concat([daily_stats, pd.DataFrame(bmr_rows)])

    fig_cal = px.bar(chart_df, x='Date', y='Calories', color='Type',
                     color_discrete_map={"Food (In)": "#EF553B", "Alcohol (In)": "#FFA15A", "Exercise (Out)": "#00CC96", "BMR (Living)": "#AB63FA"},
                     title="Daily Intake vs Total Burn")
    
    # Add Goal Lines (Target Intake)
    # We calculate the Target for each day: (BMR + Exercise) - 500
    
    # Pivot to get total burn per day
    daily_burn = chart_df[chart_df['Type'].isin(['BMR (Living)', 'Exercise (Out)'])].groupby('Date')['Calories'].sum().reset_index()
    daily_burn['Target'] = daily_burn['Calories'] - 500
    
    # Add the line trace
    fig_cal.add_trace(go.Scatter(
        x=daily_burn['Date'], y=daily_burn['Target'],
        mode='lines+markers', name='Deficit Goal (-500)',
        line=dict(color='green', width=3, dash='dash')
    ))
    
    st.plotly_chart(fig_cal, use_container_width=True)

    # ALCOHOL TRACKER
    col_alc, col_log = st.columns([1, 1])
    with col_alc:
        st.markdown("##### 🍺 Alcohol Tracker")
        alc_df = filtered_df[filtered_df['Type'] == "Alcohol (In)"].copy()
        
        if not alc_df.empty:
            # Count drinks per day
            alc_daily = alc_df.groupby('Date').agg({'Calories': 'sum', 'Item': 'count'}).reset_index()
            alc_daily.rename(columns={'Item': 'Drink_Count'}, inplace=True)
            
            fig_alc = px.bar(alc_daily, x='Date', y='Calories', 
                             text='Drink_Count', # Shows number of drinks on bar
                             title="Alcohol Calories (Count label)",
                             color_discrete_sequence=['#FFA15A'])
            fig_alc.update_traces(textposition='outside')
            st.plotly_chart(fig_alc, use_container_width=True)
        else:
            st.success("No alcohol logged in this period.")

    with col_log:
        st.markdown("##### 📋 Detailed Food Log")
        st.dataframe(filtered_df[filtered_df['Type'].isin(['Food (In)', 'Alcohol (In)'])][['Time', 'Item', 'Calories']], hide_index=True, use_container_width=True)

with tab2:
    st.markdown("### 🏃 Exercise Analysis")
    
    ex_df = filtered_df[filtered_df['Type'] == "Exercise (Out)"]
    
    if not ex_df.empty:
        c_ex1, c_ex2 = st.columns(2)
        
        with c_ex1:
            # Activity Breakdown (Pie)
            fig_pie = px.pie(ex_df, values='Calories', names='Ex_Type', title="Calories Burned by Activity Type", hole=0.4)
            st.plotly_chart(fig_pie, use_container_width=True)
            
        with c_ex2:
            # Distance Tracker (Bar)
            dist_df = ex_df[ex_df['Distance_Mi'] > 0]
            if not dist_df.empty:
                fig_dist = px.bar(dist_df, x='Date', y='Distance_Mi', color='Ex_Type', title="Miles Logged (Run/Walk/Bike)")
                st.plotly_chart(fig_dist, use_container_width=True)
            else:
                st.info("No distance-based activities logged.")

        # Duration vs Calories Scatter
        fig_scat = px.scatter(ex_df, x='Duration_Min', y='Calories', color='Ex_Type', size='Calories', 
                              title="Efficiency: Duration vs Calorie Burn", hover_data=['Item'])
        st.plotly_chart(fig_scat, use_container_width=True)
        
        # Log
        st.dataframe(ex_df[['Date', 'Ex_Type', 'Item', 'Duration_Min', 'Distance_Mi', 'Calories']], hide_index=True)
        
    else:
        st.info("No exercise logged for this period. Go for a run!")

# --- DELETE SECTION ---
st.markdown("---")
with st.expander("🗑️ Manage Data"):
    # Show last 10 entries from raw df
    last_10 = df.tail(10).sort_index(ascending=False)
    del_options = {f"{r['Date']} - {r['Item']} ({r['Calories']} cal)": idx for idx, r in last_10.iterrows()}
    
    to_del = st.selectbox("Select entry to delete:", list(del_options.keys()))
    if st.button("Delete Entry"):
        idx_to_del = del_options[to_del]
        sheet.delete_rows(idx_to_del + 2)
        st.success("Deleted.")
        st.rerun()
