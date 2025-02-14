import streamlit as st
import pandas as pd
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, DisconnectEvent
import re
from datetime import datetime
import asyncio
import logging
import os

# Suppress watchdog DEBUG logs
logging.getLogger('watchdog').setLevel(logging.WARNING)

# Constants
LOG_FILE = "logs.csv"  # File to store logs persistently

# In-memory storage for logs
recent_numbers = {}  # Use a dictionary to track numbers for the entire live session

# Function to extract valid 8-digit phone numbers
def extract_eight_digit_numbers(comment):
    """
    Extract valid 8-digit numbers from a comment.
    """
    try:
        # Regex to match 8-digit numbers, allowing for spaces, hyphens, or other separators
        number_pattern = re.compile(
            r"""
            (?<!\d)          # Negative lookbehind to ensure the number is not part of a longer sequence
            (\d{2}[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{2})  # Match 8 digits with optional separators
            (?!\d)           # Negative lookahead to ensure the number is not part of a longer sequence
            """,
            re.VERBOSE
        )

        # Find all matches in the comment
        matches = number_pattern.findall(comment)

        # Clean the matches by removing non-digit characters
        cleaned_numbers = []
        for match in matches:
            # Remove all non-digit characters
            cleaned_number = re.sub(r"[^\d]", "", match)
            if len(cleaned_number) == 8:
                cleaned_numbers.append(cleaned_number)

        return cleaned_numbers
    except Exception as e:
        logging.error(f"Error extracting numbers from comment: {e}")
        return []

# Function to load logs from file
def load_logs():
    try:
        if os.path.exists(LOG_FILE):
            return pd.read_csv(LOG_FILE)
        return pd.DataFrame(columns=["Timestamp", "Username", "Number", "Comment", "Spam"])
    except Exception as e:
        logging.error(f"Error loading logs: {e}")
        return pd.DataFrame(columns=["Timestamp", "Username", "Number", "Comment", "Spam"])

# Function to save logs to file
def save_logs(logs_df):
    try:
        if os.path.exists(LOG_FILE):
            logs_df.to_csv(LOG_FILE, mode="a", header=False, index=False)
        else:
            logs_df.to_csv(LOG_FILE, index=False)
    except Exception as e:
        logging.error(f"Error saving logs: {e}")

# Function to clear logs
def clear_logs():
    try:
        # Clear in-memory logs
        st.session_state["logs"] = pd.DataFrame(columns=["Timestamp", "Username", "Number", "Comment", "Spam"])
        # Clear persistent log file
        if os.path.exists(LOG_FILE):
            os.remove(LOG_FILE)
        st.success("Logs cleared successfully!")
    except Exception as e:
        logging.error(f"Error clearing logs: {e}")
        st.error(f"Error clearing logs: {e}")

# Function to handle comment events
async def handle_comment(event: CommentEvent):
    try:
        detected_numbers = extract_eight_digit_numbers(event.comment)
        current_time = datetime.now()

        if detected_numbers:
            for detected_number in detected_numbers:
                # Check if the number has been seen before in the entire live session
                is_spam = detected_number in recent_numbers

                # Update the recent_numbers dictionary to track this number
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
                st.session_state["log_container"].dataframe(st.session_state["logs"], use_container_width=True)

    except Exception as e:
        logging.error(f"Error processing comment: {e}")
        st.error(f"Error processing comment: {e}")

# Function to start the scraper
async def start_scraper(live_id):
    if live_id.strip() == "":
        st.error("Please enter a valid TikTok Live ID.")
        return

    try:
        # Initialize the TikTokLiveClient
        client = TikTokLiveClient(unique_id=live_id)

        # Define event handlers
        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            try:
                st.success(f"Successfully connected to @{event.unique_id}!")
            except Exception as e:
                logging.error(f"Error during connection: {e}")
                st.error(f"Error during connection: {e}")

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            try:
                st.warning("Disconnected. Attempting to reconnect...")
            except Exception as e:
                logging.error(f"Error during disconnection: {e}")
                st.error(f"Error during disconnection: {e}")

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            await handle_comment(event)

        # Global error handler for the asyncio loop
        def handle_exception(loop, context):
            error_message = context.get("exception", context["message"])
            logging.error(f"Uncaught exception: {error_message}")
            st.error(f"Uncaught exception: {error_message}")

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
                    st.warning(f"Connection lost. Retrying... (Retry {retries})")
                    await asyncio.sleep(5)  # Wait before retrying

        # Run the async client in an asyncio loop
        await run_client_with_reconnect()
    except Exception as e:
        logging.error(f"Error starting scraper: {e}")
        st.error(f"Error starting scraper: {e}")

# Streamlit dashboard
def main():
    st.set_page_config(page_title="TikTok Scraper Dashboard", layout="wide")

    # Initialize session state variables
    if "logs" not in st.session_state:
        st.session_state["logs"] = load_logs()  # Load logs from file
    if "scraper_active" not in st.session_state:
        st.session_state["scraper_active"] = False
    if "log_container" not in st.session_state:
        st.session_state["log_container"] = st.empty()

    st.title("TikTok Scraper Dashboard")

    # Input for TikTok Live ID
    live_id = st.text_input("Enter TikTok Live ID:", "@ID")

    # Display logs (initially loaded from file)
    st.session_state["log_container"].subheader("Detected Numbers and Comments")
    st.session_state["log_container"].dataframe(st.session_state["logs"], use_container_width=True)

    # Button to start the scraper
    if st.button("Start Scraper") or st.session_state["scraper_active"]:
        st.session_state["scraper_active"] = True
        # Use asyncio.run() to start the scraper
        try:
            asyncio.run(start_scraper(live_id))
        except Exception as e:
            st.error(f"Error starting scraper: {e}")
        st.spinner("Scraper is running...")

    # Button to stop the scraper
    if st.button("Stop Scraper"):
        st.session_state["scraper_active"] = False
        st.success("Scraper stopped.")

    # Button to clear logs
    if st.button("Clear Logs"):
        clear_logs()
        st.session_state["log_container"].dataframe(st.session_state["logs"], use_container_width=True)  # Refresh the displayed logs

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
