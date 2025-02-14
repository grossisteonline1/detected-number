import streamlit as st
import pandas as pd
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, DisconnectEvent
import re
from datetime import datetime, timedelta
import asyncio
import logging
import os

# Constants
SPAM_TIME_WINDOW = timedelta(minutes=3)
LOG_FILE = "logs.csv"  # File to store logs persistently

# In-memory storage for logs
recent_numbers = {}  # Use a dictionary to store timestamps for each number

# Set up logging for uncaught exceptions
logging.basicConfig(level=logging.ERROR)

# Function to extract valid 8-digit phone numbers
def extract_eight_digit_numbers(comment):
    digit_groups = re.findall(r'\d+', comment)
    cleaned_number = "".join(digit_groups)[:8]
    return [cleaned_number] if len(cleaned_number) == 8 else []

# Function to load logs from file
def load_logs():
    if os.path.exists(LOG_FILE):
        return pd.read_csv(LOG_FILE)
    return pd.DataFrame(columns=["Timestamp", "Username", "Number", "Comment", "Spam"])

# Function to save logs to file
def save_logs(logs_df):
    logs_df.to_csv(LOG_FILE, index=False)

# Function to clear logs
def clear_logs():
    # Clear in-memory logs
    st.session_state["logs"] = pd.DataFrame(columns=["Timestamp", "Username", "Number", "Comment", "Spam"])
    # Clear persistent log file
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
    st.session_state["notification"] = "Logs cleared successfully!"  # Store notification in session state

# Streamlit dashboard
def main():
    st.set_page_config(page_title="TikTok Scraper Dashboard", layout="wide")

    # Initialize session state variables
    if "logs" not in st.session_state:
        st.session_state["logs"] = load_logs()  # Load logs from file
    if "scraper_active" not in st.session_state:
        st.session_state["scraper_active"] = False
    if "notification" not in st.session_state:
        st.session_state["notification"] = None  # Initialize notification

    st.title("TikTok Scraper Dashboard")

    # Input for TikTok Live ID
    live_id = st.text_input("Enter TikTok Live ID:", "@ID")

    # Create a container for logs
    log_container = st.empty()

    # Display logs (initially loaded from file)
    log_container.subheader("Detected Numbers and Comments")
    log_container.dataframe(st.session_state["logs"], use_container_width=True)

    # Notification placeholder
    notification_placeholder = st.empty()

    # Display notification if it exists
    if st.session_state["notification"]:
        notification_placeholder.success(st.session_state["notification"])
        st.session_state["notification"] = None  # Clear notification after displaying

    # Function to handle comment events
    async def handle_comment(event: CommentEvent):
        try:
            detected_numbers = extract_eight_digit_numbers(event.comment)
            current_time = datetime.now()

            if detected_numbers:
                for detected_number in detected_numbers:
                    is_spam = detected_number in recent_numbers and (
                        current_time - recent_numbers[detected_number] < SPAM_TIME_WINDOW
                    )
                    recent_numbers[detected_number] = current_time

                    username = getattr(event.user, 'nickname', event.user.unique_id)
                    log_entry = {
                        "Timestamp": current_time.strftime('%Y-%m-%d %H:%M:%S'),
                        "Username": username,
                        "Number": detected_number,
                        "Comment": event.comment,
                        "Spam": "Yes" if is_spam else "No"
                    }

                    # Append new log entry to session state logs
                    st.session_state["logs"] = pd.concat(
                        [st.session_state["logs"], pd.DataFrame([log_entry])],
                        ignore_index=True
                    )

                    # Save logs to file
                    save_logs(st.session_state["logs"])

                    # Update the displayed log on Streamlit
                    log_container.dataframe(st.session_state["logs"], use_container_width=True)
        except Exception as e:
            logging.error(f"Error processing comment: {e}")
            st.session_state["notification"] = f"Error processing comment: {e}"  # Store error in session state

    # Function to start the scraper
    async def start_scraper():
        if live_id.strip() == "":
            st.session_state["notification"] = "Please enter a valid TikTok Live ID."  # Store error in session state
            return

        # Initialize the TikTokLiveClient
        client = TikTokLiveClient(unique_id=live_id)

        # Define event handlers
        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            try:
                st.session_state["notification"] = f"Successfully connected to @{event.unique_id}!"  # Store success in session state
            except Exception as e:
                logging.error(f"Error during connection: {e}")
                st.session_state["notification"] = f"Error during connection: {e}"  # Store error in session state

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            try:
                st.session_state["notification"] = "Disconnected. Attempting to reconnect..."  # Store warning in session state
            except Exception as e:
                logging.error(f"Error during disconnection: {e}")
                st.session_state["notification"] = f"Error during disconnection: {e}"  # Store error in session state

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            await handle_comment(event)

        # Global error handler for the asyncio loop
        def handle_exception(loop, context):
            error_message = context.get("exception", context["message"])
            logging.error(f"Uncaught exception: {error_message}")
            st.session_state["notification"] = f"Uncaught exception: {error_message}"  # Store error in session state

        # Register global exception handler for asyncio loop
        asyncio.get_event_loop().set_exception_handler(handle_exception)

        # Run client and reconnect on failure
        async def run_client_with_reconnect():
            retries = 0
            while st.session_state["scraper_active"]:
                try:
                    await client.connect()
                    await client.run()
                except Exception as e:
                    retries += 1
                    logging.error(f"Connection lost. Retrying... (Retry {retries})")
                    st.session_state["notification"] = f"Connection lost. Retrying... (Retry {retries})"  # Store warning in session state
                    await asyncio.sleep(5)  # Wait before retrying

        # Run the async client in an asyncio loop
        await run_client_with_reconnect()

    # Button to start the scraper
    if st.button("Start Scraper") or st.session_state["scraper_active"]:
        st.session_state["scraper_active"] = True
        with st.spinner("Scraper is running..."):
            asyncio.run(start_scraper())

    # Button to stop the scraper
    if st.button("Stop Scraper"):
        st.session_state["scraper_active"] = False
        st.session_state["notification"] = "Scraper stopped."  # Store success in session state

    # Button to clear logs
    if st.button("Clear Logs"):
        clear_logs()

    # Button to download the logs as CSV
    if not st.session_state["logs"].empty:
        csv = st.session_state["logs"].to_csv(index=False)
        st.download_button(
            label="Download Logs as CSV",
            data=csv,
            file_name="tiktok_logs.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()
