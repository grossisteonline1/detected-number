import streamlit as st
import pandas as pd
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent
import re
from datetime import datetime, timedelta
import asyncio
import io

# In-memory storage for logs
data_log = []
recent_numbers = {}
SPAM_TIME_WINDOW = timedelta(minutes=3)

# Function to extract valid 8-digit phone numbers
def extract_eight_digit_numbers(comment):
    digit_groups = re.findall(r'\d+', comment)
    cleaned_number = ""
    for group in digit_groups:
        if len(cleaned_number) < 8:
            cleaned_number += group
        elif len(cleaned_number) == 8:
            break
    return [cleaned_number] if len(cleaned_number) == 8 else []

# Streamlit dashboard
def main():
    st.set_page_config(page_title="TikTok Scraper Dashboard", layout="wide")

    if "connection_status" not in st.session_state:
        st.session_state["connection_status"] = "Not connected"
    if "logs" not in st.session_state:
        st.session_state["logs"] = pd.DataFrame(columns=["Timestamp", "Username", "Number", "Comment", "Spam"])

    st.title("TikTok Scraper Dashboard")

    # Input for TikTok Live ID
    live_id = st.text_input("Enter TikTok Live ID:", "@ID")

    # Display connection status
    st.subheader("Connection Status")
    st.text(st.session_state["connection_status"])

    # Create a container for logs
    log_container = st.empty()

    # Display logs (initially empty)
    log_container.subheader("Detected Numbers and Comments")
    log_container.dataframe(st.session_state["logs"], use_container_width=True)

    # Start the TikTok client
    if st.button("Start Scraper"):
        try:
            if live_id.strip() == "":
                st.error("Please enter a valid TikTok Live ID.")
                return

            client = TikTokLiveClient(unique_id=live_id)

            # Event handler for connection
            @client.on(ConnectEvent)
            async def on_connect(event: ConnectEvent):
                st.session_state["connection_status"] = f"Connected to @{event.unique_id}"

            # Event handler for comments
            @client.on(CommentEvent)
            async def on_comment(event: CommentEvent):
                detected_numbers = extract_eight_digit_numbers(event.comment)
                current_time = datetime.now()

                if detected_numbers:
                    for detected_number in detected_numbers:
                        is_spam = False
                        was_flagged = False

                        if detected_number in recent_numbers:
                            last_logged_time = recent_numbers[detected_number]
                            if current_time - last_logged_time < SPAM_TIME_WINDOW:
                                is_spam = True
                            else:
                                was_flagged = True

                        recent_numbers[detected_number] = current_time

                        if was_flagged:
                            detected_number = f"FLAGGED {detected_number}"

                        username = event.user.nickname if hasattr(event.user, 'nickname') else event.user.unique_id
                        timestamp = current_time.strftime('%Y-%m-%d %H:%M:%S')
                        log_entry = {
                            "Timestamp": timestamp,
                            "Username": username,
                            "Number": detected_number,
                            "Comment": event.comment,
                            "Spam": "Yes" if is_spam else "No"
                        }

                        data_log.append(log_entry)
                        
                        # Update session state with new log entries
                        st.session_state["logs"] = pd.DataFrame(data_log)

                        # Update the log container dynamically
                        log_container.dataframe(st.session_state["logs"], use_container_width=True)

            asyncio.run(client.run())
        except Exception as e:
            st.error(f"An error occurred: {e}")

    # Button to download the logs as CSV
    if not st.session_state["logs"].empty:
        # Convert the DataFrame to CSV format
        csv = st.session_state["logs"].to_csv(index=False)
        # Create a download button
        st.download_button(
            label="Download Logs as CSV",
            data=csv,
            file_name="tiktok_logs.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()
