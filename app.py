import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from groq import Groq
from streamlit_autorefresh import st_autorefresh
import edge_tts
import asyncio
import io
import base64
import random
import json
import time
from datetime import datetime

# --- PAGE CONFIG (The "Dark Web" Vibe) ---
st.set_page_config(page_title="VibeGram 💀", layout="wide", page_icon="💣", initial_sidebar_state="expanded")

# --- EXTREME CSS (Glassmorphism + Neon) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;800&family=Inter:wght@400;700&display=swap');
    
    /* GLOBAL RESET */
    .stApp { background-color: #050505; color: #e0e0e0; font-family: 'Inter', sans-serif; }
    
    /* GLASSMORPHISM CARD */
    .glass-card {
        background: rgba(20, 20, 20, 0.7);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 0;
        overflow: hidden;
        margin-bottom: 20px;
        transition: transform 0.2s ease;
    }
    .glass-card:hover { transform: scale(1.01); border-color: rgba(255, 0, 85, 0.5); }

    /* NEON TEXT */
    .neon-text {
        font-family: 'JetBrains Mono', monospace;
        color: #fff;
        text-shadow: 0 0 10px rgba(255, 0, 85, 0.8), 0 0 20px rgba(255, 0, 85, 0.4);
    }

    /* CHAT BUBBLES */
    .chat-bubble {
        background: #1a1a1a;
        border-left: 2px solid #333;
        padding: 8px 12px;
        margin-bottom: 8px;
        border-radius: 0 8px 8px 0;
        font-size: 0.85rem;
    }
    .chat-user { color: #ff0055; font-weight: bold; font-size: 0.75rem; margin-bottom: 2px; }
    
    /* COMMENT SECTION */
    .comment-row { display: flex; gap: 10px; margin-bottom: 12px; font-size: 0.9rem; }
    .comment-user { font-weight: 700; color: #fff; min-width: 80px; }
    .comment-text { color: #aaa; }

    /* HIDE STREAMLIT JUNK */
    header, footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# --- CONFIG & AUTH ---
SCOPES = ['https://www.googleapis.com/auth/drive']
PARENT_FOLDER_ID = st.secrets["general"]["folder_id"]

@st.cache_resource
def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)

# --- ENGINE: DRIVE METADATA (The "Hacker" DB) ---
# We store likes/comments in the file's 'description' field to avoid downloading JSONs.

def get_feed_data():
    """Fetches feed extremely fast by reading metadata only."""
    service = get_drive_service()
    try:
        results = service.files().list(
            q=f"'{PARENT_FOLDER_ID}' in parents and mimeType contains 'image/' and trashed=false",
            fields="files(id, name, thumbnailLink, description)", # FETCH METADATA DIRECTLY
            pageSize=50
        ).execute()
        
        files = []
        for f in results.get('files', []):
            # Parse the metadata JSON or create default
            meta = {}
            if f.get('description'):
                try: meta = json.loads(f['description'])
                except: meta = {"likes": 0, "comments": []}
            else:
                meta = {"likes": 0, "comments": []}
            
            f['meta'] = meta
            files.append(f)
        return files
    except: return []

def update_file_meta(file_id, meta_dict):
    """Updates the file metadata instantly."""
    service = get_drive_service()
    try:
        service.files().update(
            fileId=file_id, 
            body={'description': json.dumps(meta_dict)}
        ).execute()
    except: pass

# --- ENGINE: GLOBAL CHAT (JSON Append) ---
CHAT_FILE_NAME = "vibegram_global_chat.json"

def get_global_chat():
    service = get_drive_service()
    try:
        results = service.files().list(q=f"'{PARENT_FOLDER_ID}' in parents and name='{CHAT_FILE_NAME}'", fields="files(id)").execute()
        if not results.get('files'): return []
        
        file_id = results['files'][0]['id']
        request = service.files().get_media(fileId=file_id)
        file_obj = io.BytesIO()
        downloader = MediaIoBaseDownload(file_obj, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        return json.loads(file_obj.getvalue().decode('utf-8'))
    except: return []

def send_chat_message(user, msg):
    service = get_drive_service()
    # 1. Get current
    history = get_global_chat()
    # 2. Append (Keep last 50)
    history.append({"u": user, "m": msg, "t": time.time()})
    if len(history) > 50: history = history[-50:]
    
    # 3. Overwrite file
    results = service.files().list(q=f"'{PARENT_FOLDER_ID}' in parents and name='{CHAT_FILE_NAME}'", fields="files(id)").execute()
    
    media = MediaIoBaseUpload(io.BytesIO(json.dumps(history).encode('utf-8')), mimetype='application/json')
    
    if results.get('files'):
        service.files().update(fileId=results['files'][0]['id'], media_body=media).execute()
    else:
        service.files().create(body={'name': CHAT_FILE_NAME, 'parents': [PARENT_FOLDER_ID]}, media_body=media).execute()

# --- ENGINE: TOXIC ROAST & AUDIO ---
def generate_toxic_comments(client, image_desc):
    """Generates 3 REALISTIC hateful comments based on image context."""
    prompt = f"""
    Context: An image of {image_desc}.
    Task: Write 3 comments from internet trolls.
    Style: Hinglish, Gen-Z slang, Brutally honest, No punctuation.
    Users: 'dank_rishu', 'papa_ki_pari', 'gym_rat_99'
    Format: JSON array of objects {{'user': '...', 'text': '...'}}
    """
    try:
        completion = client.chat.completions.create(
            model="meta-llama/llama-3.2-11b-vision-instruct", # Using a smaller, faster model
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)['comments']
    except:
        return [{"user": "unknown", "text": "bruh what is this"}]

async def get_audio_stream(text):
    communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural", rate="+10%")
    with io.BytesIO() as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
        return f.getvalue()

# --- UI COMPONENTS ---

def render_sidebar():
    with st.sidebar:
        st.markdown("<h2 class='neon-text'>🔴 LIVE GLOBAL</h2>", unsafe_allow_html=True)
        
        # Fake Online Counter (Fluctuates)
        online = 1200 + int(time.time() % 100)
        st.caption(f"🟢 {online} users online now")
        
        # Global Chat
        st_autorefresh(interval=5000, key="chat_refresh") # Auto-refresh every 5s
        
        chat_container = st.container(height=400)
        history = get_global_chat()
        
        with chat_container:
            for c in reversed(history): # Show newest first
                st.markdown(f"""
                <div class="chat-bubble">
                    <div class="chat-user">{c['u']}</div>
                    <div>{c['m']}</div>
                </div>
                """, unsafe_allow_html=True)
        
        # Chat Input
        with st.form("chat_form", clear_on_submit=True):
            user_msg = st.text_input("Say something toxic...", placeholder="Type here...")
            if st.form_submit_button("Send 🚀"):
                if user_msg:
                    send_chat_message("You", user_msg)
                    st.rerun()

def render_feed_card(file_data, client):
    f_id = file_data['id']
    meta = file_data.get('meta', {})
    likes = meta.get('likes', 0)
    comments = meta.get('comments', [])
    
    col1, col2 = st.columns([1.5, 1])
    
    with col1:
        # The Image Card
        st.markdown(f"""
        <div class="glass-card">
            <img src="{file_data['thumbnailLink'].replace('=s220', '=s800')}" style="width:100%; display:block;">
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        # The Interaction Panel
        st.markdown(f"<h3 style='margin:0;'>{file_data['name']}</h3>", unsafe_allow_html=True)
        
        # Like Button (Stateful)
        if st.button(f"❤️ {likes}", key=f"like_{f_id}", use_container_width=True):
            meta['likes'] = likes + 1
            update_file_meta(f_id, meta)
            st.rerun()

        st.divider()
        
        # REAL Comments Section
        if not comments:
            if st.button("🔥 Analyze & Roast", key=f"roast_{f_id}", type="primary", use_container_width=True):
                with st.spinner("Summoning trolls..."):
                    # 1. Download image for analysis
                    # (In production, send URL if public, but here we mock the desc for speed)
                    desc = "a cringy selfie in a dirty mirror" 
                    
                    # 2. Generate Toxic Comments
                    new_comments = generate_toxic_comments(client, desc)
                    
                    # 3. Save to Metadata
                    meta['comments'] = new_comments
                    update_file_meta(f_id, meta)
                    st.rerun()
        else:
            st.markdown("<b>Top Comments</b>", unsafe_allow_html=True)
            for c in comments:
                st.markdown(f"""
                <div class="comment-row">
                    <div class="comment-user">{c['user']}</div>
                    <div class="comment-text">{c['text']}</div>
                </div>
                """, unsafe_allow_html=True)
                
            # Reply Input (Real-time feel)
            reply = st.text_input("Reply...", key=f"reply_{f_id}", label_visibility="collapsed")
            if reply:
                meta['comments'].append({"user": "You", "text": reply})
                update_file_meta(f_id, meta)
                st.rerun()

# --- MAIN APP ---
def main():
    client = Groq(api_key=st.secrets["groq"]["api_key"])
    
    render_sidebar()
    
    st.markdown("<h1 style='text-align:center; margin-bottom:40px;'>💀 VIBEGRAM <span style='color:#ff0055'>DARK</span></h1>", unsafe_allow_html=True)
    
    # Load Feed (Fast Metadata)
    files = get_feed_data()
    
    # Sort by Likes (Trending Algorithm)
    files.sort(key=lambda x: x.get('meta', {}).get('likes', 0), reverse=True)
    
    if not files:
        st.warning("Feed is empty. Upload photos to Drive folder.")
    else:
        for f in files:
            render_feed_card(f, client)
            st.markdown("<br>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
