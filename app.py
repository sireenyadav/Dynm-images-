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

# --- PAGE CONFIG ---
st.set_page_config(page_title="Roast Gallery 💀", layout="wide", page_icon="💀")

# --- CUSTOM CSS (THE PINTEREST FIX) ---
st.markdown("""
<style>
    /* Remove default padding for a cleaner app look */
    .block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 100%; }
    header, footer { visibility: hidden; }
    
    /* True Masonry Layout using CSS Columns */
    .masonry-container {
        column-count: 2;
        column-gap: 1rem;
    }
    @media (min-width: 768px) { .masonry-container { column-count: 3; } }
    @media (min-width: 1024px) { .masonry-container { column-count: 4; } }
    @media (min-width: 1280px) { .masonry-container { column-count: 5; } }
    
    /* The Card Styling */
    .masonry-item {
        break-inside: avoid;
        margin-bottom: 1rem;
        position: relative;
        border-radius: 16px;
        overflow: hidden;
        background: #1e1e1e;
        transition: transform 0.2s ease, filter 0.2s ease;
    }
    
    /* Hover Effects */
    .masonry-item:hover {
        transform: translateY(-4px);
        filter: brightness(1.1);
        z-index: 10;
        box-shadow: 0 10px 25px rgba(0,0,0,0.5);
    }
    
    /* Overlay Text (Hidden by default, shown on hover) */
    .overlay-content {
        position: absolute;
        bottom: 0; left: 0; right: 0;
        background: linear-gradient(to top, rgba(0,0,0,0.9), transparent);
        padding: 20px 10px 10px 10px;
        opacity: 0;
        transition: opacity 0.3s;
        display: flex;
        justify-content: space-between;
        align-items: end;
    }
    .masonry-item:hover .overlay-content { opacity: 1; }
    
    .roast-btn {
        background: #ff4b4b; color: white;
        padding: 5px 12px; border-radius: 20px;
        font-weight: bold; font-size: 0.8rem;
    }
    
    .vote-pill {
        background: rgba(255,255,255,0.2);
        backdrop-filter: blur(4px);
        padding: 4px 8px; border-radius: 8px;
        font-size: 0.8rem; font-weight: bold; color: #fff;
    }

    /* Main Title Styling */
    .main-title {
        font-family: 'Inter', sans-serif;
        font-weight: 900;
        letter-spacing: -2px;
        background: -webkit-linear-gradient(0deg, #ff2f2f, #ff8f2f);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        font-size: 3rem;
        margin-bottom: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# --- CONFIG & SECRETS ---
SCOPES = ['https://www.googleapis.com/auth/drive']
PARENT_FOLDER_ID = st.secrets["general"]["folder_id"]

# --- STATE MANAGEMENT ---
if "image_votes" not in st.session_state:
    st.session_state.image_votes = {} 
if "roast_mode" not in st.session_state:
    st.session_state.roast_mode = True # Default to ON because Samay Raina
if "trigger_dialog_id" not in st.session_state:
    st.session_state.trigger_dialog_id = None

# --- BACKEND FUNCTIONS ---

@st.cache_resource
def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)

# --- GOOGLE DRIVE DATABASE (THE FIX) ---
def load_votes_db():
    """Downloads votes.json from Drive to sync votes across users."""
    service = get_drive_service()
    # Search for votes.json
    query = f"'{PARENT_FOLDER_ID}' in parents and name = 'votes.json' and trashed = false"
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])
    
    if files:
        # File exists, download it
        request = service.files().get_media(fileId=files[0]['id'])
        file_obj = io.BytesIO()
        downloader = MediaIoBaseDownload(file_obj, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        try:
            return json.loads(file_obj.getvalue().decode('utf-8'))
        except:
            return {}
    return {}

def save_votes_db(votes_dict):
    """Uploads the updated votes dict to Drive."""
    service = get_drive_service()
    # Check if exists to update, or create new
    query = f"'{PARENT_FOLDER_ID}' in parents and name = 'votes.json' and trashed = false"
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])
    
    # Convert dict to JSON string stream
    json_str = json.dumps(votes_dict)
    media = MediaIoBaseUpload(io.BytesIO(json_str.encode('utf-8')), mimetype='application/json', resumable=True)
    
    if files:
        # Update existing
        service.files().update(fileId=files[0]['id'], media_body=media).execute()
    else:
        # Create new
        file_metadata = {'name': 'votes.json', 'parents': [PARENT_FOLDER_ID]}
        service.files().create(body=file_metadata, media_body=media).execute()

# Load DB on startup
if not st.session_state.image_votes:
    st.session_state.image_votes = load_votes_db()


# --- FILE HANDLING ---
@st.cache_data(ttl=3600)
def list_files():
    service = get_drive_service()
    # List images only, ignore the json file
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

# --- VOICE & AI ENGINE ---

async def generate_speech_async(text, voice):
    # RATE INCREASED: +20% for that fast comedian pace
    # PITCH INCREASED: +5Hz for crispness
    communicate = edge_tts.Communicate(text, voice, rate="+20%", pitch="+5Hz")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
        await communicate.save(tmp_file.name)
        return tmp_file.name

def text_to_speech(text):
    try:
        # Always Hindi mode for Samay style
        voice = "hi-IN-MadhurNeural" 
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        audio_path = loop.run_until_complete(generate_speech_async(text, voice))
        return audio_path
    except Exception as e:
        return None

def analyze_with_groq(image_bytes, user_prompt, chat_history):
    client = Groq(api_key=st.secrets["groq"]["api_key"])
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    data_url = f"data:image/jpeg;base64,{base64_image}"

    # STRICT SAMAY RAINA PROMPT
    system_content = (
        "You are Samay Raina, a savage Indian standup comedian. "
        "IMPORTANT: Speak ONLY in Hinglish (Hindi words written in English). "
        "DO NOT use pure English sentences. "
        "Be brutally honest, dark, deadpan, and sarcastic. "
        "Roast the person's choices, the aesthetics, or the vibe. "
        "Use slang like 'Bhai', 'Kya bawasir hai', 'Gajab bejjati hai'. "
        "Keep it fast, punchy, and under 3 sentences."
    )

    messages = [{"role": "system", "content": system_content}]
    for msg in chat_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": data_url}}
        ]
    })

    try:
        completion = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct", 
            messages=messages,
            temperature=0.8,
            max_tokens=600,
            stream=True
        )
        for chunk in completion:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        yield f"Error: {str(e)}"

# --- UI LOGIC ---

@st.dialog("🎙️ Roast Studio", width="large")
def show_image_dialog(file_id, file_name):
    if "current_image_id" not in st.session_state or st.session_state.current_image_id != file_id:
        st.session_state.current_image_id = file_id
        st.session_state.chat_history = []
        st.session_state.current_audio_file = None 

    col_img, col_chat = st.columns([1, 1], gap="medium")
    
    with col_img:
        with st.spinner("Loading victim..."):
            img_bytes = download_image_bytes(file_id)
            st.image(img_bytes, use_container_width=True)
            
            # --- PERSISTENT VOTING ---
            st.markdown("### 💀 Rate the Cringe")
            # Get current votes from DB
            current_score = st.session_state.image_votes.get(file_id, 0)
            
            # Use columns for custom button layout
            v1, v2 = st.columns(2)
            if v1.button("🔥 Cringe (+1)", use_container_width=True):
                st.session_state.image_votes[file_id] = current_score + 1
                save_votes_db(st.session_state.image_votes) # SAVE TO DRIVE
                st.rerun()
                
            if v2.button("💀 Dead (+5)", use_container_width=True):
                st.session_state.image_votes[file_id] = current_score + 5
                save_votes_db(st.session_state.image_votes) # SAVE TO DRIVE
                st.rerun()
                
            st.caption(f"Current Roast Score: **{current_score}**")

    with col_chat:
        st.markdown("#### 💬 Samay's Corner")
        
        # Default roast trigger
        if not st.session_state.chat_history:
             if st.button("🎤 Start Roast (Auto)", type="primary", use_container_width=True):
                 initial_prompt = "Bhai is photo ko dekh ke roast kar gande wala. Hinglish only."
                 st.session_state.chat_history.append({"role": "user", "content": initial_prompt})
                 
                 # Generate Response
                 response_text = ""
                 response_gen = analyze_with_groq(img_bytes, initial_prompt, [])
                 placeholder = st.empty()
                 
                 for chunk in response_gen:
                     response_text += chunk
                     placeholder.markdown(f"**Samay:** {response_text}")
                 
                 st.session_state.chat_history.append({"role": "assistant", "content": response_text})
                 
                 # Auto-play Voice
                 audio = text_to_speech(response_text)
                 st.session_state.current_audio_file = audio
                 st.rerun()

        # Chat History Display
        for msg in st.session_state.chat_history:
            if msg['role'] == 'assistant':
                st.info(f"**Samay:** {msg['content']}")
            elif msg['role'] == 'user' and "Bhai" not in msg['content']: # Hide system triggers
                st.write(f"**You:** {msg['content']}")
        
        # Audio Player
        if st.session_state.current_audio_file:
            st.audio(st.session_state.current_audio_file, format="audio/mp3", autoplay=True)
            
        # Follow up input
        if prompt := st.chat_input("Reply to Samay..."):
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            st.rerun()

def generate_masonry_grid(files):
    html_blocks = []
    
    # We wrap everything in the 'masonry-container' defined in CSS
    html_blocks.append('<div class="masonry-container">')
    
    for file in files:
        # High res thumbnail for crispness
        thumb_url = file['thumbnailLink'].replace('=s220', '=s800')
        votes = st.session_state.image_votes.get(file['id'], 0)
        
        # The Card HTML
        card = f"""
        <div class="masonry-item">
            <a href='#' id='{file['id']}'>
                <img src="{thumb_url}" style="width:100%; display:block;" alt="img">
                <div class="overlay-content">
                    <span class="vote-pill">💀 {votes}</span>
                    <span class="roast-btn">🎤 Roast Me</span>
                </div>
            </a>
        </div>
        """
        html_blocks.append(card)
        
    html_blocks.append("</div>")
    return "".join(html_blocks)

# --- MAIN APP LAYOUT ---
st.markdown('<div class="main-title">ROAST GALLERY 💀</div>', unsafe_allow_html=True)

# Tabs
tab1, tab2 = st.tabs(["🔥 The Feed", "🏆 Hall of Shame"])

try:
    all_files = list_files()
    
    with tab1:
        # Pinterest-style Grid
        if all_files:
            # Sort by newest (Google Drive default) or randomize
            random.shuffle(all_files) 
            
            html_grid = generate_masonry_grid(all_files)
            clicked_id = click_detector(html_grid)
            
            if clicked_id:
                target = next((f for f in all_files if f['id'] == clicked_id), None)
                if target:
                    show_image_dialog(clicked_id, target['name'])
        else:
            st.warning("Upload photos to Drive to get started.")

    with tab2:
        # Leaderboard based on Drive JSON DB
        st.markdown("### Top Victims")
        if st.session_state.image_votes:
            # Sort by score
            sorted_votes = sorted(st.session_state.image_votes.items(), key=lambda x: x[1], reverse=True)
            
            for rank, (fid, score) in enumerate(sorted_votes[:10]):
                # Find image object
                img_obj = next((f for f in all_files if f['id'] == fid), None)
                if img_obj:
                    c1, c2 = st.columns([1, 4])
                    with c1:
                        st.image(img_obj['thumbnailLink'], width=100)
                    with c2:
                        st.markdown(f"**#{rank+1}** | Score: **{score}** 💀")
                        st.caption(f"ID: {img_obj['name']}")
                    st.divider()

except Exception as e:
    st.error(f"System Glitch: {e}")
