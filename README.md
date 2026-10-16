# Detected-number

A Streamlit dashboard that watches a TikTok LIVE chat and records comments containing at least eight digits.

## Features

- Start and stop the scraper from the dashboard.
- Reconnect attempts after connection errors or disconnects.
- Live connection status and detection counters.
- Marks a number as a repeat when it appears again within three minutes.
- Search/filter the displayed log and export it as CSV.
- Keeps logs in the current Streamlit session.

## Run locally

Use Python 3.9 or newer.

```bash
python -m venv .venv
```

Activate the virtual environment, then install dependencies:

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

Enter the TikTok LIVE username or ID without the `@` prefix (the dashboard also accepts an `@` prefix).

## How number detection works

The app joins all digit groups found in a comment and records the first eight digits if at least eight digits are present. For example, `Call 1234-5678` becomes `12345678`. This is a simple pattern, not verification that the value is a valid phone number.

## Privacy and responsible use

The app processes publicly visible LIVE comments and stores detected comments and usernames in the current app session. Downloaded CSV files may contain personal information; handle and share them carefully. Use the tool only where permitted and respect TikTok's terms and applicable privacy laws.

## Notes

- The log is session-based and is not a permanent database. Reloading or ending the session may clear it.
- Reconnect behavior depends on TikTokLive and TikTok's availability; it cannot guarantee a successful connection.
