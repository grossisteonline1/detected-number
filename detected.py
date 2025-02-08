import streamlit as st
import pandas as pd
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, DisconnectEvent
import re
from datetime import datetime, timedelta
import asyncio
import logging

# Constants
SPAM_TIME_WINDOW = timedelta(minutes=3)

# Set up logging
logging.basicConfig(level=logging.ERROR)

# Function to extract valid 8-digit phone numbers
def extract_eight_digit_numbers(comment):
    digit_groups = re.findall(r'\d+', comment)
    cleaned_number = "".join(digit_groups)[:8]
    return [cleaned_number] if len(cleaned_number) == 8 else []

# Streamlit dashboard
def main():
    st.set_page_config(page_title="TikTok Scraper Dashboard", layout="wide")

    # Initialize session state
    if "connection_status" not in st.session_state:
        st.session_state["connection_status"] = {
            "stream1": "Not connected",
            "stream2": "Not connected",
            "stream3": "Not connected",
            "stream4": "Not connected"
        }
    if "logs" not in st.session_state:
        st.session_state["logs"] = pd.DataFrame(columns=["Timestamp", "Stream", "Username", "Number", "Comment", "Spam"])
    if "scraper_active" not in st.session_state:
        st.session_state["scraper_active"] = False
    if "recent_numbers" not in st.session_state:
        st.session_state["recent_numbers"] = {}

    st.title("TikTok Scraper Dashboard")

    # Input for TikTok Live IDs
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        live_id_1 = st.text_input("Enter TikTok Live ID for Stream 1:", "@ID1")
    with col2:
        live_id_2 = st.text_input("Enter TikTok Live ID for Stream 2:", "@ID2")
    with col3:
        live_id_3 = st.text_input("Enter TikTok Live ID for Stream 3:", "@ID3")
    with col4:
        live_id_4 = st.text_input("Enter TikTok Live ID for Stream 4:", "@ID4")

    # Display connection status
    st.subheader("Connection Status")
    st.text(f"Stream 1: {st.session_state['connection_status']['stream1']}")
    st.text(f"Stream 2: {st.session_state['connection_status']['stream2']}")
    st.text(f"Stream 3: {st.session_state['connection_status']['stream3']}")
    st.text(f"Stream 4: {st.session_state['connection_status']['stream4']}")

    # Create a container for logs
    log_container = st.empty()

    # Display logs
    log_container.subheader("Detected Numbers and Comments")
    log_container.dataframe(st.session_state["logs"], use_container_width=True)

    # Function to handle comment events
    async def handle_comment(event: CommentEvent, stream_name: str):
        try:
            detected_numbers = extract_eight_digit_numbers(event.comment)
            current_time = datetime.now()

            if detected_numbers:
                for detected_number in detected_numbers:
                    is_spam = detected_number in st.session_state["recent_numbers"] and (
                        current_time - st.session_state["recent_numbers"][detected_number] < SPAM_TIME_WINDOW
                    )
                    st.session_state["recent_numbers"][detected_number] = current_time

                    username = getattr(event.user, 'nickname', event.user.unique_id)
                    log_entry = {
                        "Timestamp": current_time.strftime('%Y-%m-%d %H:%M:%S'),
                        "Stream": stream_name,
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

                    # Update the displayed log on Streamlit
                    log_container.dataframe(st.session_state["logs"], use_container_width=True)
        except Exception as e:
            logging.error(f"Error processing comment: {e}")

    # Function to start the scraper for a single stream
    async def run_stream_client(stream_name: str, live_id: str):
        if live_id.strip() == "":
            st.session_state["connection_status"][stream_name] = "Not connected"
            return  # Skip this stream if the Live ID is empty

        # Initialize the TikTokLiveClient
        client = TikTokLiveClient(unique_id=live_id)

        # Define event handlers
        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            st.session_state["connection_status"][stream_name] = f"Connected to @{event.unique_id}"
            st.success(f"{stream_name} connected.")

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            st.session_state["connection_status"][stream_name] = "Disconnected"
            st.warning(f"{stream_name} disconnected. Attempting to reconnect...")

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            await handle_comment(event, stream_name)

        # Run client and reconnect on failure with fixed 10-second retry time
        while st.session_state["scraper_active"]:
            try:
                await client.start()
                break  # Break if the connection is successful
            except Exception as e:
                logging.error(f"{stream_name} connection lost. Error: {e}. Retrying in 10 seconds...")
                await asyncio.sleep(10)

    # Function to start all scrapers
    async def start_scrapers():
        tasks = []
        if live_id_1.strip():
            tasks.append(run_stream_client("stream1", live_id_1))
        if live_id_2.strip():
            tasks.append(run_stream_client("stream2", live_id_2))
        if live_id_3.strip():
            tasks.append(run_stream_client("stream3", live_id_3))
        if live_id_4.strip():
            tasks.append(run_stream_client("stream4", live_id_4))
        
        if tasks:
            await asyncio.gather(*tasks)
        else:
            st.error("Please enter at least one valid TikTok Live ID.")

    # Button to start the scraper
    if st.button("Start Scraper") or st.session_state["scraper_active"]:
        st.session_state["scraper_active"] = True
        with st.spinner("Scraper is running..."):
            try:
                asyncio.run(start_scrapers())
            except Exception as e:
                logging.error(f"Error in scraper: {e}")

    # Button to stop the scraper
    if st.button("Stop Scraper"):
        st.session_state["scraper_active"] = False
        st.session_state["connection_status"] = {
            "stream1": "Not connected",
            "stream2": "Not connected",
            "stream3": "Not connected",
            "stream4": "Not connected"
        }
        st.session_state["recent_numbers"] = {}  # Clear recent numbers
        st.success("Scraper stopped.")

    # Button to clear logs
    if st.button("Clear Logs"):
        st.session_state["logs"] = pd.DataFrame(columns=["Timestamp", "Stream", "Username", "Number", "Comment", "Spam"])
        st.success("Logs cleared.")

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
