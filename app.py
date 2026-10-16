import asyncio
import logging
import queue
import re
import threading
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent, ConnectEvent, DisconnectEvent

SPAM_TIME_WINDOW = timedelta(minutes=3)
LOG_COLUMNS = ["Timestamp", "Username", "Number", "Comment", "Spam"]
logging.basicConfig(level=logging.ERROR)


def extract_eight_digit_numbers(comment: str) -> list[str]:
    """Join digit groups and return the first eight digits, if available."""
    digits = "".join(re.findall(r"\d+", str(comment)))
    return [digits[:8]] if len(digits) >= 8 else []


def scraper_worker(live_id: str, events: queue.Queue, stop_event: threading.Event) -> None:
    """Run TikTokLive in a background thread; send UI updates through a queue."""
    async def run() -> None:
        client = TikTokLiveClient(unique_id=live_id)
        recent_numbers: dict[str, datetime] = {}

        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            events.put(("status", f"Connected to @{event.unique_id}"))

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            events.put(("status", "Disconnected; reconnecting…"))

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            try:
                found = extract_eight_digit_numbers(event.comment)
                now = datetime.now()
                for number in found:
                    previous = recent_numbers.get(number)
                    is_spam = previous is not None and now - previous < SPAM_TIME_WINDOW
                    recent_numbers[number] = now
                    username = getattr(event.user, "nickname", None) or getattr(
                        event.user, "unique_id", "Unknown"
                    )
                    events.put(("log", {
                        "Timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "Username": str(username),
                        "Number": number,
                        "Comment": str(event.comment),
                        "Spam": "Yes" if is_spam else "No",
                    }))
                # Expire old entries so this dictionary stays small.
                cutoff = now - SPAM_TIME_WINDOW
                for number, timestamp in list(recent_numbers.items()):
                    if timestamp < cutoff:
                        recent_numbers.pop(number, None)
            except Exception:
                logging.exception("Could not process TikTok comment")

        while not stop_event.is_set():
            try:
                events.put(("status", f"Connecting to @{live_id}…"))
                task = asyncio.create_task(client.start())
                while not task.done() and not stop_event.is_set():
                    await asyncio.sleep(0.25)
                if stop_event.is_set() and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                elif task.done():
                    # Surface connection failures to the dashboard and retry.
                    error = task.exception()
                    if error:
                        logging.error("TikTok connection failed: %s", error)
                        events.put(("status", f"Connection error: {error}"))
                if not stop_event.is_set():
                    await asyncio.sleep(3)
            except Exception as exc:
                logging.exception("TikTok connection loop failed")
                events.put(("status", f"Connection error: {exc}"))
                await asyncio.sleep(3)
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass

        events.put(("status", "Stopped"))

    try:
        asyncio.run(run())
    except Exception as exc:
        logging.exception("Scraper worker stopped unexpectedly")
        events.put(("status", f"Scraper error: {exc}"))


def init_state() -> None:
    defaults = {
        "logs": pd.DataFrame(columns=LOG_COLUMNS),
        "connection_status": "Not connected",
        "scraper_thread": None,
        "stop_event": None,
        "event_queue": queue.Queue(),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def drain_events() -> None:
    events = st.session_state.event_queue
    while True:
        try:
            kind, payload = events.get_nowait()
        except queue.Empty:
            break
        if kind == "status":
            st.session_state.connection_status = payload
        elif kind == "log":
            st.session_state.logs = pd.concat(
                [st.session_state.logs, pd.DataFrame([payload])],
                ignore_index=True,
            ).astype({column: "string" for column in LOG_COLUMNS})


def main() -> None:
    st.set_page_config(page_title="TikTok Number Dashboard", layout="wide")
    init_state()

    st.title("TikTok Number Dashboard")
    st.caption("Detect 8-digit numbers in TikTok LIVE comments. Use only where you have permission.")

    live_id = st.text_input("TikTok LIVE username or ID", value="rafikaouayy")
    live_id = live_id.strip().removeprefix("@").strip()

    thread = st.session_state.scraper_thread
    running = thread is not None and thread.is_alive()
    left, right = st.columns(2)
    with left:
        start_clicked = st.button("Start scraper", disabled=running, type="primary", use_container_width=True)
    with right:
        stop_clicked = st.button("Stop scraper", disabled=not running, use_container_width=True)

    if start_clicked:
        if not live_id:
            st.error("Enter a TikTok LIVE username or ID first.")
        else:
            stop_event = threading.Event()
            events = st.session_state.event_queue
            worker = threading.Thread(
                target=scraper_worker,
                args=(live_id, events, stop_event),
                daemon=True,
                name="tiktok-live-scraper",
            )
            st.session_state.stop_event = stop_event
            st.session_state.scraper_thread = worker
            worker.start()
            st.rerun()

    if stop_clicked and st.session_state.stop_event is not None:
        st.session_state.stop_event.set()
        st.session_state.connection_status = "Stopping…"

    @st.fragment(run_every="1s")
    def live_dashboard():
        drain_events()
        active_thread = st.session_state.scraper_thread
        active = active_thread is not None and active_thread.is_alive()
        st.subheader("Connection")
        st.write(f"**Status:** {st.session_state.connection_status}")
        st.write(f"**Scraper:** {'Running' if active else 'Stopped'}")
        logs = st.session_state.logs
        total = len(logs)
        unique_numbers = logs["Number"].nunique() if total else 0
        spam_count = int((logs["Spam"] == "Yes").sum()) if total else 0
        a, b, c = st.columns(3)
        a.metric("Detections", total)
        b.metric("Unique numbers", unique_numbers)
        c.metric("Repeat detections", spam_count)

        search = st.text_input("Filter logs", placeholder="Search username, number, or comment")
        view = logs
        if search:
            mask = logs.apply(
                lambda column: column.astype("string").str.contains(search, case=False, na=False)
            ).any(axis=1)
            view = logs[mask]
        st.dataframe(view, width="stretch", hide_index=True)

        if not logs.empty:
            st.download_button(
                "Download CSV",
                data=logs.to_csv(index=False).encode("utf-8"),
                file_name="tiktok_logs.csv",
                mime="text/csv",
            )
        if st.button("Clear logs"):
            st.session_state.logs = pd.DataFrame(columns=LOG_COLUMNS)
            st.rerun()

    live_dashboard()


if __name__ == "__main__":
    main()
