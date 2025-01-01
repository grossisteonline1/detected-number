from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent
import re
from datetime import datetime, timedelta
import os

# Create the client instance with the correct argument
client: TikTokLiveClient = TikTokLiveClient(unique_id="@www.qpr.tn")

# Directory to store daily logs
log_dir = "logs"

# Ensure the main log directory exists
os.makedirs(log_dir, exist_ok=True)

# Function to get the daily log folder
def get_daily_log_folder():
    current_date = datetime.now().strftime('%Y-%m-%d')
    daily_folder = os.path.join(log_dir, current_date)
    os.makedirs(daily_folder, exist_ok=True)  # Create the folder if it doesn't exist
    return daily_folder

# Function to write a custom entry to the log file
def write_to_log(daily_folder, filename, log_entry):
    file_path = os.path.join(daily_folder, filename)
    with open(file_path, "a", encoding="utf-8") as log_file:
        log_file.write(log_entry)
        log_file.flush()

# Dictionary to track detected numbers and their timestamps
recent_numbers = {}

# Time window for spam detection (3 minutes)
SPAM_TIME_WINDOW = timedelta(minutes=3)

# Updated function to extract valid 8-digit phone numbers
def extract_eight_digit_numbers(comment):
    """
    Extract phone numbers intelligently from comments.
    Assumes 8-digit phone numbers may appear fragmented.
    """
    # Find all digit groups in the comment
    digit_groups = re.findall(r'\d+', comment)
    cleaned_number = ""

    # Merge groups into an 8-digit phone number
    for group in digit_groups:
        if len(cleaned_number) < 8:
            cleaned_number += group
        elif len(cleaned_number) == 8:
            break  # Stop adding once we have 8 digits

    # If we formed a valid phone number, return it
    if len(cleaned_number) == 8:
        return [cleaned_number]
    return []

# Event handler for successful connection
@client.on(ConnectEvent)
async def on_connect(event: ConnectEvent):
    print(f"Connected to @{event.unique_id} (Room ID: {client.room_id})")

# Event handler for comments
@client.on(CommentEvent)
async def on_comment(event: CommentEvent):
    # Extract potential 8-digit numbers from the comment
    detected_numbers = extract_eight_digit_numbers(event.comment)
    current_time = datetime.now()
    daily_folder = get_daily_log_folder()

    if detected_numbers:
        for detected_number in detected_numbers:
            is_spam = False
            was_flagged = False

            # Check if the number has been recently logged
            if detected_number in recent_numbers:
                last_logged_time = recent_numbers[detected_number]
                if current_time - last_logged_time < SPAM_TIME_WINDOW:
                    is_spam = True  # Mark as spam
                else:
                    was_flagged = True  # Previously logged but outside the spam window

            # Update the timestamp of the detected number
            recent_numbers[detected_number] = current_time

            # Add "FLAGGED" prefix if previously flagged
            if was_flagged:
                detected_number = f"FLAGGED {detected_number}"

            # Log the detected number
            username = event.user.nickname if hasattr(event.user, 'nickname') else event.user.unique_id
            timestamp = current_time.strftime('%Y-%m-%d %H:%M:%S')
            log_entry = f"[{timestamp}] Username: {username} - Number: {detected_number} - Comment: {event.comment}\n"

            # Write the log entry to the daily log file
            if not is_spam or (is_spam and current_time - last_logged_time >= SPAM_TIME_WINDOW):
                write_to_log(daily_folder, "flagged_comments.log", log_entry)

            # Print message with spam status
            if is_spam:
                print(f"Spam detected and flagged: {detected_number}")
            else:
                print(f"New number detected: {detected_number} from {username} at {timestamp}")

    # Check for the !write command in comments
    elif event.comment.startswith("!write"):
        # Extract the custom text after the command
        custom_text = event.comment[6:].strip()
        if custom_text:  # Ensure there's text to write
            write_to_log(daily_folder, "custom_log.log", f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] {custom_text}\n")
            print(f"Custom text added to log: {custom_text}")

# Main entry point
if __name__ == "__main__":
    import asyncio

    asyncio.run(client.run())