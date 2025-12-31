import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, date
import plotly.express as px
import plotly.graph_objects as go
import pytz
import calendar

# --- CONFIGURATION ---
DAILY_BMR = 2400
TIMEZONE = pytz.timezone('US/Central')

st.set_page_config(page_title="Health Commander 4.0", page_icon="💪", layout="wide")

# --- SESSION STATE & INITIALIZATION ---
if 'offset' not in st.session_state:
    st.session_state.offset = 0
if 'view_mode' not in st.session_state:
    st.session_state.view_mode = "Today"

# Initialize form defaults if not present
if 'form_desc' not in st.session_state:
    st.session_state.form_desc = ""
if 'form_cal' not in st.session_state:
    st.session_state.form_cal = 0

# --- STARTER LIBRARY (The "Offline" Database) ---
STARTER_DB = {
    "Chicken Breast (4oz)": 165,
    "Rice (1 cup)": 200,
    "Eggs (2 large)": 140,
    "Oatmeal (1 cup)": 150,
    "Pizza (1 slice)": 285,
    "Burger": 500,
    "Fries (Medium)": 365,
    "Salad (Caesar)": 400,
    "Salmon (Fillet)": 350,
    "Pasta (1 cup)": 220,
    "Beer (1 pint)": 180,
    "Wine (Glass)": 125,
    "Whiskey (shot)": 105,
    "Protein Shake": 160,
    "Banana": 105,
    "Apple": 95,
    "Avocado (Half)": 160,
    "Tacos (2 street)": 300
}

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

# --- LOAD DATA (Moved up for History Logic) ---
raw_data = sheet.get_all_records()
df = pd.DataFrame(raw_data)

# Data Cleaning
if not df.empty:
    df['Calories'] = pd.to_numeric(df['Calories'], errors='coerce').fillna(0)
    df['Duration_Min'] = pd.to_numeric(df['Duration_Min'], errors='coerce').fillna(0)
    df['Distance_Mi'] = pd.to_numeric(df['Distance_Mi'], errors='coerce').fillna(0)
    df['Date'] = pd.to_datetime(df['Date']).dt.date
    # Create a proper Datetime object for filtering
    df['Datetime'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Time'].astype(str))
    # Extract Day Name for Analysis
    df['Day_Name'] = pd.to_datetime(df['Date']).dt.day_name()

# --- SIDEBAR: LOGGING ---
st.sidebar.header("📝 Log Activity")

# 1. SELECT MODE
entry_mode = st.sidebar.radio("Category:", ["Nutrition (In)", "Exercise (Out)"], horizontal=True)

# 2. QUICK ADD LOGIC (Only for Nutrition)
if entry_mode == "Nutrition (In)":
    st.sidebar.markdown("#### ⚡ Quick-Add")
    
    # Build a combined list of History + Starter DB
    history_items = {}
    if not df.empty:
        # Get unique items from history
        hist_df = df[df['Type'].isin(['Food (In)', 'Alcohol (In)'])]
        for _, row in hist_df.iterrows():
            history_items[f"{row['Item']} (Hist)"] = row['Calories']
    
    # Merge dictionaries (History overwrites Starter if duplicate names, but we appended (Hist) so it won't)
    full_db = {**STARTER_DB, **history_items}
    
    # Sort keys alphabetically
    sorted_options = sorted(list(full_db.keys()))
    
    selected_item = st.sidebar.selectbox("Search Common Foods:", ["Select an item..."] + sorted_options)
    
    if selected_item != "Select an item...":
        # Update session state to pre-fill the form
        st.session_state.form_desc = selected_item.replace(" (Hist)", "")
        st.session_state.form_cal = int(full_db[selected_item])
    else:
        # Keep blank if nothing selected (or let user type)
        pass

# 3. RENDER FORM
now_cst = datetime.now(TIMEZONE)

with st.sidebar.form(key=f'entry_form_{entry_mode}', clear_on_submit=True):
    date_val = st.date_input("Date", now_cst.date())
    time_val = st.time_input("Time", now_cst.time())
    
    if entry_mode == "Nutrition (In)":
        activity_type = st.selectbox("Type", ["Food (In)", "Alcohol (In)"])
        # Use Session State values for defaults
        item_name = st.text_input("Description", value=st.session_state.form_desc, placeholder="e.g., Tacos")
        calories = st.number_input("Calories", value=st.session_state.form_cal, min_value=0, step=10)
        ex_type, duration, distance = "", 0, 0.0
        
    else: # Exercise
        activity_type = "Exercise (Out)"
        ex_type = st.selectbox("Exercise Type", ["Run", "Walk", "Bike", "Peloton", "Lift", "Stair Stepper", "Other"])
        item_name = st.text_input("Description", placeholder="e.g., Morning Run")
        calories = st.number_input("Calories Burned", min_value=0, step=10)
        duration = st.number_input("Duration (Minutes)", min_value=0, step=5)
        distance = 0.0
        if ex_type in ["Run", "Walk", "Bike", "Peloton"]:
            distance = st.number_input("Distance (Miles)", min_value=0.0, step=0.1)

    if st.form_submit_button(label='Save Entry'):
        row_data = [str(date_val), str(time_val), activity_type, item_name, calories, ex_type, duration, distance]
        sheet.append_row(row_data)
        st.success("Saved!")
        # Reset session state
        st.session_state.form_desc = ""
        st.session_state.form_cal = 0
        st.rerun()

# --- VIEW CONTROLS ---
st.title("📊 Health Analytics")

if df.empty:
    st.warning("No data found. Use the sidebar to log your first activity!")
    st.stop()

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

else:
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

# Filter Data
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
tab1, tab2, tab3 = st.tabs(["🍎 Nutrition", "🏃 Fitness", "🧠 Correlations & Insights"])

# === TAB 1: NUTRITION ===
with tab1:
    m1, m2, m3 = st.columns(3)
    m1.metric("Calories In", f"{total_in:,.0f}")
    m2.metric("Total Burn", f"{total_out:,.0f}")
    m3.metric("Net Balance", f"{net_calories:,.0f}", "-500 Goal" if net_calories < -500 else "Over Goal", delta_color="inverse")

    # Stacked Chart Logic
    daily_stats = filtered_df.groupby(['Date', 'Type'])['Calories'].sum().reset_index()
    all_dates = pd.date_range(start_date, end_date).date
    
    def get_values(type_name):
        temp = pd.DataFrame({'Date': all_dates})
        merged = temp.merge(daily_stats[daily_stats['Type'] == type_name], on='Date', how='left').fillna(0)
        return merged['Calories'].values

    y_food = get_values("Food (In)")
    y_alc = get_values("Alcohol (In)")
    y_bmr = [DAILY_BMR] * len(all_dates)
    y_ex = get_values("Exercise (Out)")
    y_target = [b + e - 500 for b, e in zip(y_bmr, y_ex)]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Food", x=all_dates, y=y_food, offsetgroup=0, marker_color="#EF553B"))
    fig.add_trace(go.Bar(name="Alcohol", x=all_dates, y=y_alc, base=y_food, offsetgroup=0, marker_color="#FFA15A"))
    fig.add_trace(go.Bar(name="BMR", x=all_dates, y=y_bmr, offsetgroup=1, marker_color="#AB63FA"))
    fig.add_trace(go.Bar(name="Exercise", x=all_dates, y=y_ex, base=y_bmr, offsetgroup=1, marker_color="#00CC96"))
    fig.add_trace(go.Scatter(name="Deficit Goal (-500)", x=all_dates, y=y_target, mode='lines', line=dict(color='green', width=3, dash='dash')))

    fig.update_layout(barmode='group', title="Intake vs Burn", yaxis_title="Calories")
    st.plotly_chart(fig, use_container_width=True)

    c_alc, c_log = st.columns(2)
    with c_alc:
        alc_df = filtered_df[filtered_df['Type'] == "Alcohol (In)"]
        if not alc_df.empty:
            alc_daily = alc_df.groupby('Date').agg({'Calories': 'sum', 'Item': 'count'}).reset_index()
            fig_alc = px.bar(alc_daily, x='Date', y='Calories', text='Item', title="Alcohol Tracker", color_discrete_sequence=['#FFA15A'])
            st.plotly_chart(fig_alc, use_container_width=True)
        else:
            st.info("No alcohol logged.")
            
    with c_log:
        st.dataframe(filtered_df[filtered_df['Type'].isin(['Food (In)', 'Alcohol (In)'])][['Time', 'Item', 'Calories']], hide_index=True, use_container_width=True)

# === TAB 2: FITNESS ===
with tab2:
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
                st.info("No mileage activities.")
        
        # New Exercise Scatter
        fig_scat = px.scatter(ex_df, x='Duration_Min', y='Calories', color='Ex_Type', 
                              size='Calories', hover_name='Item', title="Efficiency: Duration vs Burn")
        st.plotly_chart(fig_scat, use_container_width=True)
        
        st.dataframe(ex_df[['Date', 'Time', 'Ex_Type', 'Item', 'Duration_Min', 'Distance_Mi', 'Calories']], hide_index=True)
    else:
        st.info("No exercise logged in this period.")

# === TAB 3: INSIGHTS & CORRELATIONS ===
with tab3:
    st.markdown("### 🧠 Behavioral Analytics")
    
    # Needs global data, not filtered data, to calculate trends properly
    if df.empty:
        st.warning("Not enough data for insights.")
    else:
        # 1. THE HANGOVER EFFECT
        # Logic: Aggregate daily data, create 'Prev_Day_Alcohol' flag
        daily_agg = df.groupby('Date').apply(
            lambda x: pd.Series({
                'Alcohol_Cals': x[x['Type'] == 'Alcohol (In)']['Calories'].sum(),
                'Exercise_Cals': x[x['Type'] == 'Exercise (Out)']['Calories'].sum()
            })
        ).reset_index()
        
        # Shift Alcohol to create "Yesterday's Alcohol" for each row
        daily_agg['Prev_Day_Alcohol'] = daily_agg['Alcohol_Cals'].shift(1).fillna(0)
        daily_agg['Condition'] = daily_agg['Prev_Day_Alcohol'].apply(lambda x: "After Drinking 🍺" if x > 0 else "After Sober 💧")
        
        # Group by Condition
        hangover_stats = daily_agg.groupby('Condition')['Exercise_Cals'].mean().reset_index()
        
        c_h1, c_h2 = st.columns(2)
        with c_h1:
            st.markdown("#### 🍺 The 'Hangover Effect'")
            if len(hangover_stats) > 1:
                fig_hangover = px.bar(hangover_stats, x='Condition', y='Exercise_Cals', 
                                      color='Condition', title="Avg. Exercise Burn: Sober vs Post-Drinking",
                                      color_discrete_map={"After Drinking 🍺": "#EF553B", "After Sober 💧": "#00CC96"})
                st.plotly_chart(fig_hangover, use_container_width=True)
                
                # Insight Text
                diff = hangover_stats.set_index('Condition')['Exercise_Cals']
                try:
                    drop = diff['After Sober 💧'] - diff['After Drinking 🍺']
                    if drop > 0:
                        st.caption(f"📉 Insight: You burn on average **{drop:.0f} fewer calories** the day after drinking.")
                    else:
                        st.caption("📈 Insight: Surprisingly, you exercise MORE after drinking!")
                except:
                    pass
            else:
                st.info("Need more data (both drinking and non-drinking days) to calculate.")

        # 2. DAY OF WEEK HEATMAP
        with c_h2:
            st.markdown("#### 📅 Day of Week Trends")
            # Order days correctly
            days_order = list(calendar.day_name)
            
            # Aggregate by day name and type
            # We want Average Calorie Intake and Average Calorie Burn per Day of Week
            df['Day_Name'] = pd.Categorical(df['Day_Name'], categories=days_order, ordered=True)
            
            day_trends = df.groupby(['Day_Name', 'Type'])['Calories'].sum().reset_index()
            # Normalize by number of weeks (roughly) to get Average? Or just show Total Volume?
            # Let's show Volume Distribution (Where does the bulk of activity happen?)
            
            fig_days = px.bar(day_trends[day_trends['Type'].isin(['Food (In)', 'Exercise (Out)'])], 
                              x='Day_Name', y='Calories', color='Type', barmode='group',
                              title="Volume by Day of Week",
                              color_discrete_map={"Food (In)": "#EF553B", "Exercise (Out)": "#00CC96"})
            st.plotly_chart(fig_days, use_container_width=True)

        # 3. MEAL TIMING HISTOGRAM
        st.markdown("---")
        st.markdown("#### 🕒 When do you eat?")
        food_logs = df[df['Type'].isin(['Food (In)', 'Alcohol (In)'])]
        if not food_logs.empty:
            # Extract hour
            food_logs['Hour'] = pd.to_datetime(food_logs['Time'].astype(str)).dt.hour
            
            fig_hist = px.histogram(food_logs, x='Hour', y='Calories', nbins=24, 
                                    title="Calorie Distribution by Hour of Day",
                                    range_x=[0, 24], color_discrete_sequence=['#FFA15A'])
            fig_hist.update_layout(xaxis_title="Hour of Day (0-24)", yaxis_title="Total Calories")
            st.plotly_chart(fig_hist, use_container_width=True)

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
