import re
import datetime
import streamlit as st
from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent
import pandas as pd
import io

# --- Authentification ---
st.title("🔐 TikTok Live Phone Extractor - Login")

# Identifiants fixes
USERNAME = "admin"
PASSWORD = "1234"

# Formulaire login
login_username = st.text_input("Nom d'utilisateur")
login_password = st.text_input("Mot de passe", type="password")

if st.button("Se connecter"):
    if login_username == USERNAME and login_password == PASSWORD:
        st.success("✅ Connexion réussie")
        st.session_state["logged_in"] = True
    else:
        st.error("❌ Identifiants incorrects")

# --- Interface principale ---
if st.session_state.get("logged_in", False):
    st.title("📊 TikTok Live Phone Extractor")

    tiktok_id = st.text_input("Enter TikTok Live ID:", "rafikaouayy")

    # Option Spam
    filter_spam = st.checkbox("Activer le filtre anti-spam (supprimer doublons)")

    status_placeholder = st.empty()
    table_placeholder = st.empty()
    
    # Download button placeholder
    download_placeholder = st.empty()

    # Stockage des résultats
    if "data" not in st.session_state:
        st.session_state.data = []
    if "numero_count" not in st.session_state:
        st.session_state.numero_count = {}

    # --- Function: Always extract first 8 digits if available ---
    def extract_eight_digit_numbers(comment):
        digit_groups = re.findall(r'\d+', comment)  # all groups of digits
        if not digit_groups:
            return []  # no digits found
        cleaned_number = "".join(digit_groups)[:8]  # keep first 8 digits only
        return [cleaned_number] if len(cleaned_number) == 8 else []

    # Function to create downloadable CSV
    def convert_to_csv(data):
        if not data:
            return None
        df = pd.DataFrame(data)
        return df.to_csv(index=False, encoding='utf-8')

    # Download button logic
    if st.session_state.data:
        csv_data = convert_to_csv(st.session_state.data)
        if csv_data:
            download_placeholder.download_button(
                label="📥 Download Logs as CSV",
                data=csv_data,
                file_name=f"tiktok_live_numbers_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )

    if st.button("Connect"):
        if tiktok_id and tiktok_id != "@ID":
            status_placeholder.write("✅ Connecting to TikTok Live...")

            # Client TikTok Live
            client = TikTokLiveClient(unique_id=tiktok_id.replace("@", ""))

            @client.on(CommentEvent)
            async def on_comment(event: CommentEvent):
                # Extract numbers using your updated function
                numeros = extract_eight_digit_numbers(event.comment)

                if numeros:
                    for num in numeros:
                        # Compter les occurrences
                        st.session_state.numero_count[num] = st.session_state.numero_count.get(num, 0) + 1

                        # Si filtre spam activé → ignorer doublons
                        if filter_spam and st.session_state.numero_count[num] > 1:
                            continue

                        # Champ Spam
                        if filter_spam:
                            spam_status = "No"
                        else:
                            spam_status = (
                                "No" if st.session_state.numero_count[num] == 1
                                else f"Oui : {st.session_state.numero_count[num]}ème fois"
                            )

                        # Ajouter dans data avec un ID clair
                        st.session_state.data.append({
                            "ID": len(st.session_state.data) + 1,
                            "Timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "Username": event.user.nickname,
                            "Detected Number": num,  # ✅ always 8 digits
                            "Original Comment": event.comment,  # full comment
                            "Spam": spam_status
                        })

                        # Affichage du tableau en direct
                        table_placeholder.table(st.session_state.data)
                        
                        # Update download button
                        csv_data = convert_to_csv(st.session_state.data)
                        if csv_data:
                            download_placeholder.download_button(
                                label="📥 Download Logs as CSV",
                                data=csv_data,
                                file_name=f"tiktok_live_numbers_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv"
                            )

            # Lancer le client
            client.run()
        else:
            status_placeholder.write("❌ Please enter a valid TikTok ID")
