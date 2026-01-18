import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from groq import Groq
from st_click_detector import click_detector
import edge_tts
import asyncio
import io
import base64
import random
import tempfile
import json
import os

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Roast Gallery 💀", layout="wide", page_icon="💀")

# --- CUSTOM CSS (Pinterest Masonry + UI Polish) ---
st.markdown("""
<style>
    /* Clean up the page */
    .block-container { padding-top: 2rem; padding-bottom: 5rem; max-width: 95%; }
    header, footer { visibility: hidden; }

    /* MASONRY GRID LAYOUT */
    .masonry-wrapper {
        column-count: 2;
        column-gap: 1rem;
    }
    @media (min-width: 768px) { .masonry-wrapper { column-count: 3; } }
    @media (min-width: 1200px) { .masonry-wrapper { column-count: 4; } }
    @media (min-width: 1600px) { .masonry-wrapper { column-count: 5; } }

    /* CARD STYLE */
    .pin-card {
        break-inside: avoid;
        margin-bottom: 1rem;
        position: relative;
        border-radius: 16px;
        overflow: hidden;
        cursor: pointer;
        transition: transform 0.2s ease, filter 0.2s;
    }
    .pin-card:hover {
        transform: translateY(-4px);
        filter: brightness(1.1);
        z-index: 5;
    }

    /* IMAGE STYLE */
    .pin-img {
        width: 100%;
        display: block;
        border-radius: 16px;
    }

    /* OVERLAY ON HOVER */
    .pin-overlay {
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        background: linear-gradient(to top, rgba(0,0,0,0.8) 0%, transparent 40%);
        opacity: 0;
        transition: opacity 0.2s;
        display: flex;
        align-items: flex-end;
        padding: 15px;
        justify-content: space-between;
    }
    .pin-card:hover .pin-overlay { opacity: 1; }

    /* BADGES */
    .vote-badge {
        background: rgba(255, 69, 58, 0.9);
        color: white;
        padding: 4px 10px;
        border-radius: 12px;
        font-weight: bold;
        font-size: 0.8rem;
    }
    .roast-badge {
        background: white;
        color: black;
        padding: 4px 10px;
        border-radius: 12px;
        font-weight: bold;
        font-size: 0.8rem;
    }

    /* TITLE */
    .app-title {
        text-align: center;
        font-size: 3rem;
        font-weight: 900;
        background: -webkit-linear-gradient(45deg, #ff0055, #ff5500);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# --- SETUP CREDENTIALS ---
SCOPES = ['https://www.googleapis.com/auth/drive']
PARENT_FOLDER_ID = st.secrets["general"]["folder_id"]

# --- GOOGLE DRIVE DATABASE FUNCTIONS ---
@st.cache_resource
def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)

def load_votes_db():
    """Reads votes.json from Drive"""
    service = get_drive_service()
    try:
        results = service.files().list(
            q=f"'{PARENT_FOLDER_ID}' in parents and name = 'votes.json' and trashed = false",
            fields="files(id)"
        ).execute()
        files = results.get('files', [])
        
        if files:
            request = service.files().get_media(fileId=files[0]['id'])
            file_obj = io.BytesIO()
            downloader = MediaIoBaseDownload(file_obj, request)
            done = False
            while not done: _, done = downloader.next_chunk()
            return json.loads(file_obj.getvalue().decode('utf-8'))
    except Exception as e:
        print(f"DB Load Error: {e}")
    return {}

def save_votes_db(votes_dict):
    """Writes votes.json to Drive"""
    service = get_drive_service()
    try:
        # Check for existing file
        results = service.files().list(
            q=f"'{PARENT_FOLDER_ID}' in parents and name = 'votes.json' and trashed = false",
            fields="files(id)"
        ).execute()
        files = results.get('files', [])

        json_str = json.dumps(votes_dict)
        media = MediaIoBaseUpload(io.BytesIO(json_str.encode('utf-8')), mimetype='application/json', resumable=True)

        if files:
            service.files().update(fileId=files[0]['id'], media_body=media).execute()
        else:
            file_metadata = {'name': 'votes.json', 'parents': [PARENT_FOLDER_ID]}
            service.files().create(body=file_metadata, media_body=media).execute()
    except Exception as e:
        st.error(f"Failed to save vote: {e}")

# --- INIT SESSION STATE ---
if "image_votes" not in st.session_state:
    st.session_state.image_votes = load_votes_db() # Load from Cloud on startup
if "current_image" not in st.session_state:
    st.session_state.current_image = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "audio_path" not in st.session_state:
    st.session_state.audio_path = None

# --- HELPER FUNCTIONS ---
@st.cache_data(ttl=300)
def list_files():
    service = get_drive_service()
    query = f"'{PARENT_FOLDER_ID}' in parents and mimeType contains 'image/' and trashed = false"
    results = service.files().list(
        q=query, pageSize=100, fields="files(id, name, thumbnailLink)"
    ).execute()
    return results.get('files', [])

def download_image_bytes(file_id):
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    file_obj = io.BytesIO()
    downloader = MediaIoBaseDownload(file_obj, request)
    done = False
    while not done: _, done = downloader.next_chunk()
    return file_obj.getvalue()

async def generate_audio(text):
    # FAST SPEED & HINDI VOICE
    communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural", rate="+25%", pitch="+5Hz")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
        await communicate.save(tmp_file.name)
        return tmp_file.name

def run_tts(text):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(generate_audio(text))

def get_samay_roast(image_bytes, prompt_text=""):
    client = Groq(api_key=st.secrets["groq"]["api_key"])
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    system_prompt = (
        "You are Samay Raina, a savage Indian standup comedian. "
        "Your task is to ROAST the user's image. "
        "RULES: "
        "1. Speak ONLY in Hinglish (Hindi words using English alphabet). "
        "2. Do NOT speak pure English. "
        "3. Be dark, fast, sarcastic, and insulting. "
        "4. Keep it short (max 2 sentences). "
        "5. Use words like 'Bhai', 'Kya bawasir hai', 'Ye kya dekh liya'. "
    )
    
    try:
        completion = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": "Roast this image hard in Hinglish."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]}
            ],
            temperature=0.8,
            max_tokens=300
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"

# --- DIALOG (POPUP) ---
@st.dialog("🎙️ Roast Studio", width="large")
def open_roast_modal(file_id, file_name):
    # Layout
    c1, c2 = st.columns([1.2, 1], gap="medium")
    
    with c1:
        with st.spinner("Loading pixels..."):
            img_data = download_image_bytes(file_id)
            st.image(img_data, use_container_width=True, output_format="JPEG")
            
            # --- VOTING SECTION ---
            st.markdown("### 💀 Rate the Cringe")
            current_votes = st.session_state.image_votes.get(file_id, 0)
            
            col_v1, col_v2 = st.columns(2)
            if col_v1.button("🔥 Cringe (+1)", use_container_width=True):
                st.session_state.image_votes[file_id] = current_votes + 1
                save_votes_db(st.session_state.image_votes)
                st.rerun()
                
            if col_v2.button("💀 Dead (+5)", use_container_width=True):
                st.session_state.image_votes[file_id] = current_votes + 5
                save_votes_db(st.session_state.image_votes)
                st.rerun()
            
            st.caption(f"Current Roast Score: **{current_votes}**")

    with c2:
        st.markdown("### 💬 Samay's Corner")
        
        # Action Button
        if st.button("🎤 ROAST ME NOW", type="primary", use_container_width=True):
            with st.spinner("Writing jokes..."):
                roast_text = get_samay_roast(img_data)
                
                # Save to history
                st.session_state.chat_history = [{"role": "assistant", "content": roast_text}]
                
                # Generate Audio
                audio_file = run_tts(roast_text)
                st.session_state.audio_path = audio_file
                st.rerun()

        # Display Result
        if st.session_state.chat_history:
            msg = st.session_state.chat_history[-1]
            st.success(f"**Samay:** {msg['content']}")
            
            if st.session_state.audio_path:
                st.audio(st.session_state.audio_path, format="audio/mp3", autoplay=True)


# --- MAIN MASONRY GENERATOR ---
def generate_html(files):
    html_parts = ['<div class="masonry-wrapper">']
    
    for f in files:
        # Get higher res thumbnail for better look
        thumb = f['thumbnailLink'].replace('=s220', '=s600')
        votes = st.session_state.image_votes.get(f['id'], 0)
        
        # HTML Block for one card
        card_html = f"""
        <div class="pin-card">
            <a href='#' id='{f['id']}'>
                <img src="{thumb}" class="pin-img" loading="lazy">
                <div class="pin-overlay">
                    <span class="vote-badge">💀 {votes}</span>
                    <span class="roast-badge">🎤 Roast Me</span>
                </div>
            </a>
        </div>
        """
        html_parts.append(card_html)
        
    html_parts.append('</div>')
    return "".join(html_parts)

# --- MAIN APP EXECUTION ---
st.markdown('<div class="app-title">ROAST GALLERY 💀</div>', unsafe_allow_html=True)

try:
    files = list_files()
    
    if not files:
        st.info("No images found in the Drive folder.")
    else:
        # Sort by votes descending (Most roasted at top)
        # Or you can use random.shuffle(files) for variety
        files.sort(key=lambda x: st.session_state.image_votes.get(x['id'], 0), reverse=True)
        
        # 1. Generate Grid HTML
        grid_html = generate_html(files)
        
        # 2. Detect Clicks
        clicked_id = click_detector(grid_html)
        
        # 3. Handle Click
        if clicked_id:
            # Clear previous session data when opening new image
            if st.session_state.current_image != clicked_id:
                st.session_state.current_image = clicked_id
                st.session_state.chat_history = []
                st.session_state.audio_path = None
            
            # Find file name
            target_file = next((f for f in files if f['id'] == clicked_id), None)
            if target_file:
                open_roast_modal(clicked_id, target_file['name'])

except Exception as e:
    st.error(f"App Error: {e}")
