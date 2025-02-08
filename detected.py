import streamlit as st
import pandas as pd
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, DisconnectEvent
import re
from datetime import datetime, timedelta
import asyncio
import logging

# Constants
SPAM_TIME_WINDOW = timedelta(minutes=3)  # Time window for spam detection
RECONNECT_DELAY = 10  # Delay in seconds before reconnecting

# In-memory storage for logs and timestamps
recent_numbers = {}  # Store timestamps for each number

# Set up logging for uncaught exceptions
logging.basicConfig(level=logging.ERROR)

# Function to extract valid 8-digit phone numbers
def extract_eight_digit_numbers(comment):
    digit_groups = re.findall(r'\d+', comment)
    cleaned_number = "".join(digit_groups)[:8]
    return [cleaned_number] if len(cleaned_number) == 8 else []

# Streamlit dashboard
def main():
    st.set_page_config(page_title="TikTok Scraper Dashboard", layout="wide")

    # Initialize session state variables
    if "connection_status" not in st.session_state:
        st.session_state["connection_status"] = {}
    if "logs" not in st.session_state:
        st.session_state["logs"] = {}
    if "scraper_active" not in st.session_state:
        st.session_state["scraper_active"] = {}
    if "connection_lost_notified" not in st.session_state:
        st.session_state["connection_lost_notified"] = {}
    if "clients" not in st.session_state:
        st.session_state["clients"] = {}

    st.title("TikTok Scraper Dashboard")

    # Sidebar for dynamic stream count and allow duplicates option
    MAX_STREAMS = st.sidebar.number_input("Number of Streams", min_value=1, max_value=10, value=4, key="max_streams")
    ALLOW_DUPLICATES = st.sidebar.checkbox("Allow Duplicate Numbers", value=False, key="allow_duplicates")

    # Input for TikTok Live IDs
    live_ids = []
    for i in range(MAX_STREAMS):
        live_id = st.text_input(f"Stream {i + 1} Live ID:", key=f"live_id_{i}")
        live_ids.append(live_id)

    # Display connection status for each stream with visual badges
    st.subheader("Connection Status")
    for i in range(MAX_STREAMS):
        status = st.session_state["connection_status"].get(i, "Not connected")
        color = "green" if "Connected" in status else "red"
        st.markdown(
            f"Stream {i + 1}: <span style='color: {color}; font-weight: bold;'>{status}</span>",
            unsafe_allow_html=True
        )

    # Create a container for combined logs
    log_container = st.empty()

    # Function to combine logs from all streams
    def combine_logs():
        combined_logs = pd.concat([st.session_state["logs"].get(i, pd.DataFrame(columns=["Timestamp", "Username", "Number", "Comment", "Spam", "Stream"])) for i in range(MAX_STREAMS)], ignore_index=True)
        return combined_logs.sort_values(by="Timestamp", ascending=False)  # Sort by timestamp

    # Display combined logs
    log_container.subheader("Detected Numbers and Comments (All Streams)")
    log_container.dataframe(combine_logs(), use_container_width=True)

    # Function to handle comment events
    async def handle_comment(event: CommentEvent, stream_index: int):
        try:
            detected_numbers = extract_eight_digit_numbers(event.comment)
            current_time = datetime.now()

            if detected_numbers:
                for detected_number in detected_numbers:
                    # Check if duplicates are allowed
                    if not ALLOW_DUPLICATES and detected_number in recent_numbers:
                        continue  # Skip duplicate numbers if not allowed

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
                        "Spam": "Yes" if is_spam else "No",
                        "Stream": f"Stream {stream_index + 1}"  # Add stream identifier
                    }

                    # Append new log entry to session state logs for the specific stream
                    if stream_index not in st.session_state["logs"]:
                        st.session_state["logs"][stream_index] = pd.DataFrame(columns=["Timestamp", "Username", "Number", "Comment", "Spam", "Stream"])
                    st.session_state["logs"][stream_index] = pd.concat(
                        [st.session_state["logs"][stream_index], pd.DataFrame([log_entry])],
                        ignore_index=True
                    )

                    # Update the displayed combined logs on Streamlit
                    log_container.dataframe(combine_logs(), use_container_width=True)
        except Exception as e:
            logging.error(f"Error processing comment in Stream {stream_index + 1}: {e}")

    # Function to start the scraper for a specific stream
    async def start_scraper(stream_index: int, live_id: str):
        if live_id.strip() == "":
            st.error(f"Please enter a valid TikTok Live ID for Stream {stream_index + 1}.")
            return

        # Initialize the TikTokLiveClient
        client = TikTokLiveClient(unique_id=live_id)
        st.session_state["clients"][stream_index] = client  # Store client in session state

        # Define event handlers
        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            try:
                st.session_state["connection_status"][stream_index] = f"Connected to @{event.unique_id}"
                st.session_state["connection_lost_notified"][stream_index] = False  # Reset notification flag
            except Exception as e:
                logging.error(f"Error during connection in Stream {stream_index + 1}: {e}")

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            try:
                st.session_state["connection_status"][stream_index] = "Disconnected"
                if not st.session_state["connection_lost_notified"].get(stream_index, False):
                    st.warning(f"Connection lost for Stream {stream_index + 1}! Attempting to reconnect...")
                    st.session_state["connection_lost_notified"][stream_index] = True  # Set notification flag

                # Add a delay before reconnecting
                await asyncio.sleep(RECONNECT_DELAY)
                await client.connect()  # Reconnect the client
            except Exception as e:
                logging.error(f"Error during disconnection in Stream {stream_index + 1}: {e}")

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            await handle_comment(event, stream_index)

        # Run the client
        try:
            await client.connect()
            await client.run()
        except Exception as e:
            logging.error(f"Error running client for Stream {stream_index + 1}: {e}")
            st.session_state["connection_status"][stream_index] = "Connection failed"

    # Function to run all scrapers
    async def run_all_scrapers():
        tasks = []
        for i in range(MAX_STREAMS):
            if live_ids[i].strip() != "":
                tasks.append(start_scraper(i, live_ids[i]))
        await asyncio.gather(*tasks)

    # Function to stop all scrapers
    async def stop_all_scrapers():
        for i in range(MAX_STREAMS):
            st.session_state["scraper_active"][i] = False
            if i in st.session_state["clients"]:
                client = st.session_state["clients"][i]
                await client.disconnect()  # Gracefully disconnect
                del st.session_state["clients"][i]  # Remove client from session state
        st.success("All scrapers stopped.")

    # Button to start all scrapers
    if st.button("Start All Scrapers"):
        for i in range(MAX_STREAMS):
            if live_ids[i].strip() != "":
                st.session_state["scraper_active"][i] = True

        # Create and run the event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_all_scrapers())

    # Button to stop all scrapers
    if st.button("Stop All Scrapers"):
        # Create and run the event loop for stopping
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(stop_all_scrapers())

    # Button to download combined logs as CSV
    combined_logs = combine_logs()
    if not combined_logs.empty:
        csv = combined_logs.to_csv(index=False)
        st.download_button(
            label="Download Combined Logs as CSV",
            data=csv,
            file_name="tiktok_logs_combined.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()
