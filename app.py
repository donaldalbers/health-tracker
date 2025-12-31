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
TIMEZONE = pytz.timezone('US/Central')

st.set_page_config(page_title="Health Commander Final", page_icon="💪", layout="wide")

# --- SESSION STATE ---
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

# --- SIDEBAR: LOGGING ---
st.sidebar.header("📝 Log Activity")

# 1. SELECT MODE FIRST (Triggers UI Update)
entry_mode = st.sidebar.radio("Category:", ["Nutrition (In)", "Exercise (Out)"], horizontal=True)

# Get Current Time CST
now_cst = datetime.now(TIMEZONE)

# 2. RENDER DYNAMIC FORM
with st.sidebar.form(key=f'entry_form_{entry_mode}', clear_on_submit=True):
    date_val = st.date_input("Date", now_cst.date())
    time_val = st.time_input("Time", now_cst.time())
    
    # Dynamic Inputs based on mode
    if entry_mode == "Nutrition (In)":
        activity_type = st.selectbox("Type", ["Food (In)", "Alcohol (In)"])
        item_name = st.text_input("Description", placeholder="e.g., Tacos")
        calories = st.number_input("Calories", min_value=0, step=10)
        # Empty Exercise Fields
        ex_type, duration, distance = "", 0, 0.0
        
    else: # Exercise
        activity_type = "Exercise (Out)"
        ex_type = st.selectbox("Exercise Type", ["Run", "Walk", "Bike", "Peloton", "Lift", "Stair Stepper", "Other"])
        item_name = st.text_input("Description", placeholder="e.g., Morning Run")
        # Optional: Auto-calc calories? For now manual.
        calories = st.number_input("Calories Burned", min_value=0, step=10)
        duration = st.number_input("Duration (Minutes)", min_value=0, step=5)
        
        distance = 0.0
        if ex_type in ["Run", "Walk", "Bike", "Peloton"]:
            distance = st.number_input("Distance (Miles)", min_value=0.0, step=0.1)

    submit_button = st.form_submit_button(label='Save Entry')

if submit_button:
    # 8-Column Schema
    row_data = [
        str(date_val), str(time_val), activity_type, item_name, calories, 
        ex_type, duration, distance
    ]
    sheet.append_row(row_data)
    st.sidebar.success("Saved!")
    st.rerun()

# --- DATA LOADING ---
raw_data = sheet.get_all_records()
df = pd.DataFrame(raw_data)

if df.empty:
    st.info("No data yet.")
    st.stop()

# Clean Data
df['Calories'] = pd.to_numeric(df['Calories'], errors='coerce').fillna(0)
df['Duration_Min'] = pd.to_numeric(df['Duration_Min'], errors='coerce').fillna(0)
df['Distance_Mi'] = pd.to_numeric(df['Distance_Mi'], errors='coerce').fillna(0)
df['Date'] = pd.to_datetime(df['Date']).dt.date

# --- VIEW CONTROLS ---
st.title("📊 Health Analytics")

c_filter, c_prev, c_next = st.columns([2, 1, 1])

with c_filter:
    view_mode = st.radio("View Mode:", ["Today", "Week View", "Custom Range"], horizontal=True)
    if view_mode != st.session_state.view_mode:
        st.session_state.offset = 0
        st.session_state.view_mode = view_mode

base_date = now_cst.date()

# Pagination Logic
if view_mode == "Today":
    effective_date = base_date + timedelta(days=st.session_state.offset)
    start_date = end_date = effective_date
    display_range = effective_date.strftime('%B %d, %Y')
    prev_label = "◀ Previous Day"
    next_label = "Next Day ▶"

elif view_mode == "Week View":
    end_of_window = base_date + timedelta(weeks=st.session_state.offset)
    start_date = end_of_window - timedelta(days=6)
    end_date = end_of_window
    display_range = f"{start_date} to {end_date}"
    prev_label = "◀ Previous Week"
    next_label = "Next Week ▶"

else: # Custom
    c1, c2 = st.columns(2)
    start_date = c_filter.date_input("Start", base_date - timedelta(days=7))
    end_date = c_filter.date_input("End", base_date)
    display_range = "Custom Range"

if view_mode != "Custom Range":
    if c_prev.button(prev_label):
        st.session_state.offset -= 1
        st.rerun()
    if c_next.button(next_label):
        st.session_state.offset += 1
        st.rerun()

st.subheader(f"Analyzing: {display_range}")

# Filtering
mask = (df['Date'] >= start_date) & (df['Date'] <= end_date)
filtered_df = df.loc[mask]

# --- METRICS CALC ---
total_in = filtered_df[filtered_df['Type'].isin(["Food (In)", "Alcohol (In)"])]['Calories'].sum()
total_exercise = filtered_df[filtered_df['Type'] == "Exercise (Out)"]['Calories'].sum()
num_days = (end_date - start_date).days + 1
total_bmr = num_days * DAILY_BMR
total_out = total_exercise + total_bmr
net_calories = total_in - total_out

# --- TABS ---
tab1, tab2 = st.tabs(["🍎 Nutrition & Weight", "🏃 Fitness & Activities"])

with tab1:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Calories In", f"{total_in:,.0f}")
    m2.metric("Total Burn", f"{total_out:,.0f}")
    m3.metric("Net Balance", f"{net_calories:,.0f}", "-500 Goal" if net_calories < -500 else "Over Goal", delta_color="inverse")
    lbs = (total_out - total_in) / 3500
    m4.metric("Est. Weight Loss", f"{lbs:.2f} lbs")

    # --- COMPLEX CHART: GROUPED STACKED BARS ---
    st.markdown("##### 📉 Daily Balance")
    
    # 1. Aggregate Data by Date and Type
    daily_stats = filtered_df.groupby(['Date', 'Type'])['Calories'].sum().reset_index()
    
    # 2. Ensure every date in range exists for correct alignment
    all_dates = pd.date_range(start_date, end_date).date
    
    # Helper to get array of values for a specific type across all dates
    def get_values(type_name):
        # Merge with all_dates to ensure 0s where missing
        temp = pd.DataFrame({'Date': all_dates})
        merged = temp.merge(daily_stats[daily_stats['Type'] == type_name], on='Date', how='left').fillna(0)
        return merged['Calories'].values

    y_food = get_values("Food (In)")
    y_alc = get_values("Alcohol (In)")
    y_bmr = [DAILY_BMR] * len(all_dates) # Constant
    y_ex = get_values("Exercise (Out)")
    
    # 3. Calculate Target Line (Burn - 500)
    # Burn = BMR + Exercise
    y_target = [b + e - 500 for b, e in zip(y_bmr, y_ex)]

    fig = go.Figure()

    # GROUP 1: INTAKE (Food + Alcohol)
    fig.add_trace(go.Bar(
        name="Food", x=all_dates, y=y_food, 
        offsetgroup=0, marker_color="#EF553B"
    ))
    fig.add_trace(go.Bar(
        name="Alcohol", x=all_dates, y=y_alc, 
        base=y_food, # Manual Stacking: Start where food ends
        offsetgroup=0, marker_color="#FFA15A"
    ))

    # GROUP 2: BURN (BMR + Exercise)
    fig.add_trace(go.Bar(
        name="BMR", x=all_dates, y=y_bmr, 
        offsetgroup=1, marker_color="#AB63FA"
    ))
    fig.add_trace(go.Bar(
        name="Exercise", x=all_dates, y=y_ex, 
        base=y_bmr, # Manual Stacking: Start where BMR ends
        offsetgroup=1, marker_color="#00CC96"
    ))

    # GOAL LINE
    fig.add_trace(go.Scatter(
        name="Deficit Goal (-500)", x=all_dates, y=y_target,
        mode='lines', line=dict(color='green', width=3, dash='dash')
    ))

    fig.update_layout(
        barmode='group', 
        title="Intake vs Burn (Side-by-Side Groups)",
        xaxis_title=None,
        yaxis_title="Calories"
    )
    st.plotly_chart(fig, use_container_width=True)

    # Alcohol & Log Columns
    c_alc, c_log = st.columns(2)
    with c_alc:
        st.markdown("##### 🍺 Alcohol Tracker")
        alc_df = filtered_df[filtered_df['Type'] == "Alcohol (In)"]
        if not alc_df.empty:
            alc_daily = alc_df.groupby('Date').agg({'Calories': 'sum', 'Item': 'count'}).reset_index()
            fig_alc = px.bar(alc_daily, x='Date', y='Calories', text='Item', 
                             title="Calories (Drinks Counted)", color_discrete_sequence=['#FFA15A'])
            fig_alc.update_traces(textposition='outside')
            st.plotly_chart(fig_alc, use_container_width=True)
        else:
            st.info("Dry streak! No alcohol logged.")
            
    with c_log:
        st.markdown("##### 📋 Nutrition Log")
        st.dataframe(filtered_df[filtered_df['Type'].isin(['Food (In)', 'Alcohol (In)'])][['Time', 'Item', 'Calories']], hide_index=True, use_container_width=True)

with tab2:
    st.markdown("### 🏃 Fitness Analytics")
    
    ex_df = filtered_df[filtered_df['Type'] == "Exercise (Out)"]
    
    if not ex_df.empty:
        c1, c2 = st.columns(2)
        with c1:
            fig_pie = px.pie(ex_df, values='Calories', names='Ex_Type', title="Burn by Activity", hole=0.4)
            st.plotly_chart(fig_pie, use_container_width=True)
        with c2:
            dist_df = ex_df[ex_df['Distance_Mi'] > 0]
            if not dist_df.empty:
                fig_dist = px.bar(dist_df, x='Date', y='Distance_Mi', color='Ex_Type', title="Mileage Tracker")
                st.plotly_chart(fig_dist, use_container_width=True)
            else:
                st.info("No mileage activities yet.")
                
        st.dataframe(ex_df[['Date', 'Time', 'Ex_Type', 'Item', 'Duration_Min', 'Distance_Mi', 'Calories']], hide_index=True)
    else:
        st.info("No exercise logged in this period.")

# --- DELETE ---
st.markdown("---")
with st.expander("🗑️ Manage Data"):
    last_10 = df.tail(10).sort_index(ascending=False)
    del_options = {f"{r['Date']} {r['Time']} - {r['Item']}": idx for idx, r in last_10.iterrows()}
    to_del = st.selectbox("Select entry to delete:", list(del_options.keys()))
    if st.button("Delete Entry"):
        sheet.delete_rows(del_options[to_del] + 2)
        st.success("Deleted.")
        st.rerun()
