import streamlit as st
import pandas as pd
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, DisconnectEvent
import re
from datetime import datetime, timedelta
import asyncio
import logging
import json
import io  # ✅ For StringIO

# ✅ Constants
SPAM_TIME_WINDOW = timedelta(minutes=3)

# ✅ In-memory storage for logs
recent_numbers = {}

# ✅ Logging setup
logging.basicConfig(level=logging.ERROR)


# ✅ Function to extract valid 8-digit phone numbers
def extract_eight_digit_numbers(comment):
    digit_groups = re.findall(r'\d+', comment)
    cleaned_number = "".join(digit_groups)[:8]
    return [cleaned_number] if len(cleaned_number) == 8 else []


# ✅ Streamlit Dashboard
def main():
    st.set_page_config(page_title="TikTok Scraper Dashboard", layout="wide")

    # --- Initialize session state ---
    if "connection_status" not in st.session_state:
        st.session_state["connection_status"] = "Not connected"
    if "logs" not in st.session_state:
        st.session_state["logs"] = pd.DataFrame(
            columns=["Timestamp", "Username", "Number", "Comment", "Spam"]
        )
    if "scraper_active" not in st.session_state:
        st.session_state["scraper_active"] = False
    if "logs_loaded" not in st.session_state:
        st.session_state["logs_loaded"] = False

    # --- Load logs from browser storage ---
    if not st.session_state["logs_loaded"]:
        js_code = """
        <script>
            const logs = localStorage.getItem("tiktok_logs");
            if (logs) {
                window.parent.postMessage({ type: "logs", data: logs }, "*");
            }
        </script>
        """
        st.markdown(js_code, unsafe_allow_html=True)

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

    # --- Handle logs from JS ---
    if "logs" in st.session_state:
        logs_json = st.session_state["logs"]
        if not logs_json.empty:
            try:
                logs_json_str = logs_json.to_json(orient="split")
                logs_df = pd.read_json(io.StringIO(logs_json_str), orient="split")
                st.session_state["logs"] = logs_df
                st.session_state["logs_loaded"] = True
            except Exception as e:
                st.error(f"Error loading logs: {e}")

    # --- UI ---
    st.title("TikTok Scraper Dashboard")

    live_id = st.text_input("Enter TikTok Live ID:", "@ID")

    st.subheader("Connection Status")
    st.text(st.session_state["connection_status"])

    log_container = st.empty()
    log_container.subheader("Detected Numbers and Comments")
    log_container.dataframe(st.session_state["logs"], width="stretch")

    # --- Handle Comment Events ---
    async def handle_comment(event: CommentEvent):
        try:
            detected_numbers = extract_eight_digit_numbers(event.comment)
            current_time = datetime.now()

            if detected_numbers:
                for detected_number in detected_numbers:
                    is_spam = (
                        detected_number in recent_numbers
                        and (current_time - recent_numbers[detected_number] < SPAM_TIME_WINDOW)
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

                    # Append new entry
                    st.session_state["logs"] = pd.concat(
                        [st.session_state["logs"], pd.DataFrame([log_entry])],
                        ignore_index=True
                    )

                    # Ensure safe dtypes for Arrow
                    st.session_state["logs"] = st.session_state["logs"].astype({
                        "Timestamp": "string",
                        "Username": "string",
                        "Number": "string",
                        "Comment": "string",
                        "Spam": "string"
                    })

                    # Save logs to browser storage
                    logs_json = st.session_state["logs"].to_json(orient="split")
                    js_code = f"""
                    <script>
                        localStorage.setItem("tiktok_logs", '{logs_json}');
                    </script>
                    """
                    st.markdown(js_code, unsafe_allow_html=True)

                    # Update logs display
                    log_container.dataframe(st.session_state["logs"], width="stretch")

        except Exception as e:
            logging.error(f"Error processing comment: {e}")

    # --- Start Scraper ---
    async def start_scraper():
        if live_id.strip() == "":
            st.error("Please enter a valid TikTok Live ID.")
            return

        client = TikTokLiveClient(unique_id=live_id)

        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            try:
                st.session_state["connection_status"] = f"Connected to @{event.unique_id}"
            except Exception as e:
                logging.error(f"Error during connection: {e}")

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            try:
                st.session_state["connection_status"] = "Disconnected"
                st.warning("Disconnected. Attempting to reconnect...")
            except Exception as e:
                logging.error(f"Error during disconnection: {e}")

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            await handle_comment(event)

        def handle_exception(loop, context):
            error_message = context.get("exception", context["message"])
            logging.error(f"Uncaught exception: {error_message}")

        asyncio.get_event_loop().set_exception_handler(handle_exception)

        async def run_client_with_reconnect():
            retries = 0
            while st.session_state["scraper_active"]:
                try:
                    await client.connect()
                    await client.run()
                except Exception as e:
                    retries += 1
                    logging.error(f"Connection lost. Retrying... (Retry {retries})")
                    await asyncio.sleep(5)

        await run_client_with_reconnect()

    # --- Buttons ---
    if st.button("Start Scraper") or st.session_state["scraper_active"]:
        st.session_state["scraper_active"] = True
        with st.spinner("Scraper is running..."):
            asyncio.run(start_scraper())

    if st.button("Stop Scraper"):
        st.session_state["scraper_active"] = False
        st.success("Scraper stopped.")

    # --- Download logs ---
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
