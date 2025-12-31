import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import plotly.express as px

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Health Commander", page_icon="💪", layout="wide")

# --- SETUP GOOGLE SHEETS CONNECTION ---
# We use Streamlit Secrets management to securely handle the API key
def get_data():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # Access credentials from Streamlit secrets
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    # Open the sheet
    sheet = client.open("Health_Tracker_DB").worksheet("Logs")
    return sheet

try:
    sheet = get_data()
except Exception as e:
    st.error("Connection Error! Did you set up the secrets correctly?")
    st.stop()

# --- SIDEBAR: DATA ENTRY ---
st.sidebar.header("📝 Log Activity")

with st.sidebar.form(key='entry_form'):
    date_val = st.date_input("Date", datetime.now())
    time_val = st.time_input("Time", datetime.now())
    activity_type = st.selectbox("Type", ["Food (In)", "Exercise (Out)"])
    item_name = st.text_input("Description", "e.g., 3 Eggs / 5k Run")
    calories = st.number_input("Calories", min_value=0, step=10)
    
    submit_button = st.form_submit_button(label='Commit to Database')

if submit_button:
    # Format data for GSheets
    # Note: We make 'Exercise' negative for math later, or keep positive and filter by type.
    # Let's keep strictly positive in DB, handle logic in app.
    row_data = [str(date_val), str(time_val), activity_type, item_name, calories]
    sheet.append_row(row_data)
    st.sidebar.success("Entry Saved!")

# --- MAIN DASHBOARD ---
st.title("📊 Health Command Center")

# Fetch data for analysis
all_data = sheet.get_all_records()

if not all_data:
    st.info("No data found yet. Log your first meal in the sidebar!")
else:
    df = pd.DataFrame(all_data)
    
    # Convert Calories to numeric just in case
    df['Calories'] = pd.to_numeric(df['Calories'])
    df['Date'] = pd.to_datetime(df['Date'])

    # --- DAILY SUMMARY LOGIC ---
    # Filter for selected date (default to today)
    selected_date = st.date_input("View Summary For:", datetime.now())
    day_df = df[df['Date'].dt.date == selected_date]

    # Calculate Totals
    food_df = day_df[day_df['Type'] == "Food (In)"]
    exercise_df = day_df[day_df['Type'] == "Exercise (Out)"]

    total_in = food_df['Calories'].sum()
    total_out = exercise_df['Calories'].sum()
    net = total_in - total_out

    # Metrics Row
    col1, col2, col3 = st.columns(3)
    col1.metric("Calories In", f"{total_in}", delta="Food")
    col2.metric("Calories Out", f"{total_out}", delta="-Exercise", delta_color="inverse")
    col3.metric("Net Calories", f"{net}", delta="Daily Balance", delta_color="off")

    st.markdown("---")

    # --- VISUALIZATIONS ---
    c1, c2 = st.columns([2, 1])

    with c1:
        st.subheader("Today's Timeline")
        if not day_df.empty:
            # Create a simple timeline chart
            fig_timeline = px.bar(day_df, x='Time', y='Calories', color='Type', 
                                  title="Intake vs Burn", barmode='group',
                                  color_discrete_map={"Food (In)": "#EF553B", "Exercise (Out)": "#00CC96"})
            st.plotly_chart(fig_timeline, use_container_width=True)
        else:
            st.write("No activity logged for this date.")

    with c2:
        st.subheader("Log Details")
        st.dataframe(day_df[['Time', 'Item', 'Calories', 'Type']], hide_index=True)
