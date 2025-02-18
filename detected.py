import logging
import streamlit as st
import pandas as pd
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, DisconnectEvent
import re
from datetime import datetime, timedelta
import asyncio
import json
from websockets.exceptions import ConnectionClosedError

# Suppress watchdog debug logs
logging.getLogger("watchdog.observers.inotify_buffer").setLevel(logging.WARNING)

# Constants
SPAM_TIME_WINDOW = timedelta(minutes=3)

# In-memory storage for logs
recent_numbers = {}  # Use a dictionary to store timestamps for each number

# Set up logging for uncaught exceptions
logging.basicConfig(level=logging.DEBUG)  # Enable debug logging

# Function to extract valid 8-digit phone numbers
def extract_eight_digit_numbers(comment):
    # Remove all non-digit characters (spaces, symbols, emojis, etc.)
    cleaned_comment = re.sub(r'\D', '', comment)
    
    # Find all sequences of exactly 8 digits
    eight_digit_numbers = re.findall(r'\d{8}', cleaned_comment)
    
    return eight_digit_numbers

# Streamlit dashboard
def main():
    st.set_page_config(page_title="TikTok Scraper Dashboard", layout="wide")

    # Initialize session state variables
    if "connection_status" not in st.session_state:
        st.session_state["connection_status"] = "Not connected"
    if "logs" not in st.session_state:
        st.session_state["logs"] = pd.DataFrame(columns=["Timestamp", "Username", "Number", "Comment", "Spam"])
    if "scraper_active" not in st.session_state:
        st.session_state["scraper_active"] = False

    # Load logs from browser storage (if available)
    if "logs_loaded" not in st.session_state:
        st.session_state["logs_loaded"] = False

    if not st.session_state["logs_loaded"]:
        # Inject JavaScript to retrieve logs from localStorage
        js_code = """
        <script>
        const logs = localStorage.getItem("tiktok_logs");
        if (logs) {
            window.parent.postMessage({ type: "logs", data: logs }, "*");
        }
        </script>
        """
        st.markdown(js_code, unsafe_allow_html=True)

        # Listen for messages from JavaScript
        st.markdown(
            """
            <script>
            window.addEventListener("message", (event) => {
                if (event.data.type === "logs") {
                    const logs = JSON.parse(event.data.data);
                    window.parent.postMessage({ type: "streamlit", logs: logs }, "*");
                }
            });
            </script>
            """,
            unsafe_allow_html=True,
        )

        # Handle logs sent from JavaScript
        if "logs" in st.session_state:
            logs_json = st.session_state["logs"]
            if isinstance(logs_json, str):  # Ensure logs_json is a string
                try:
                    logs_df = pd.read_json(logs_json, orient="split")
                    st.session_state["logs"] = logs_df
                    st.session_state["logs_loaded"] = True
                except Exception as e:
                    logging.error(f"Error loading logs: {e}")

    st.title("TikTok Scraper Dashboard")

    # Input for TikTok Live ID
    live_id = st.text_input("Enter TikTok Live ID:", "@ID")

    # Display connection status
    st.subheader("Connection Status")
    st.text(st.session_state["connection_status"])

    # Create a container for logs
    log_container = st.empty()

    # Display logs (initially loaded from session state or browser storage)
    log_container.subheader("Detected Numbers and Comments")
    log_container.dataframe(st.session_state["logs"], use_container_width=True)

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

                    # Save logs to browser storage
                    logs_json = st.session_state["logs"].to_json(orient="split")
                    js_code = f"""
                    <script>
                    localStorage.setItem("tiktok_logs", '{logs_json}');
                    </script>
                    """
                    st.markdown(js_code, unsafe_allow_html=True)

                    # Update the displayed log on Streamlit
                    log_container.dataframe(st.session_state["logs"], use_container_width=True)
        except Exception as e:
            logging.error(f"Error processing comment: {e}")

    # Function to start the scraper
    async def start_scraper():
        if live_id.strip() == "":
            st.error("Please enter a valid TikTok Live ID.")
            return

        # Initialize the TikTokLiveClient
        client = TikTokLiveClient(unique_id=live_id)

        # Define event handlers
        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            try:
                st.session_state["connection_status"] = f"Connected to @{event.unique_id}"
                st.toast("🎉 Stream Connected!", icon="✅")
                logging.info(f"Connected to TikTok Live: @{event.unique_id}")
            except Exception as e:
                logging.error(f"Error during connection: {e}")
                st.error(f"Error during connection: {e}")

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            try:
                st.session_state["connection_status"] = "Disconnected"
                st.toast("⚠️ Stream Disconnected!", icon="❌")
                st.warning("Disconnected. Attempting to reconnect...")
                logging.warning("Disconnected. Attempting to reconnect...")
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
            # Do not use st.error here to avoid Streamlit UI updates

        # Register global exception handler for asyncio loop
        asyncio.get_event_loop().set_exception_handler(handle_exception)

        # Run client and reconnect on failure
        async def run_client_with_reconnect():
            while st.session_state["scraper_active"]:
                try:
                    await client.connect()
                    await client.run()
                except ConnectionClosedError as e:
                    logging.error(f"Connection closed. Retrying...")
                    st.warning("🔌 Stream is Offline. Retrying...")
                    await asyncio.sleep(10)  # Wait before retrying
                except Exception as e:
                    logging.error(f"Unexpected error: {e}")
                    break

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
        st.toast("🛑 Scraper Stopped!", icon="⏹️")
        st.success("Scraper stopped.")

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
