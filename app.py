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
st.set_page_config(page_title="VibeGram", layout="wide", page_icon="📸")

# --- EXTREME UI CSS (THE INSTAGRAM OVERHAUL) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&display=swap');

    /* GLOBAL RESET */
    .block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 1200px; }
    header, footer { visibility: hidden; }
    body { background-color: #000; color: #fff; font-family: 'Inter', sans-serif; }

    /* MASONRY LAYOUT */
    .masonry-wrapper {
        column-count: 2;
        column-gap: 1.5rem;
    }
    @media (min-width: 768px) { .masonry-wrapper { column-count: 3; } }
    @media (min-width: 1200px) { .masonry-wrapper { column-count: 4; } }

    /* INSTAGRAM CARD STYLE */
    .insta-card {
        break-inside: avoid;
        margin-bottom: 1.5rem;
        background: #121212;
        border-radius: 15px;
        overflow: hidden;
        border: 1px solid #262626;
        transition: transform 0.2s;
    }
    .insta-card:hover { transform: translateY(-3px); border-color: #444; }

    /* IMAGE */
    .insta-img {
        width: 100%;
        display: block;
        aspect-ratio: auto;
    }

    /* CARD FOOTER (Action Bar) */
    .insta-footer {
        padding: 12px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: rgba(18, 18, 18, 0.9);
    }

    /* ICONS (SVG Styling) */
    .icon-group { display: flex; gap: 15px; align-items: center; }
    .icon-btn { cursor: pointer; transition: transform 0.1s; }
    .icon-btn:hover { transform: scale(1.1); }
    
    .likes-text {
        font-size: 0.85rem;
        font-weight: 600;
        color: #e0e0e0;
        margin-left: 5px;
    }

    /* HEADER STYLE */
    .app-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem 0;
        margin-bottom: 2rem;
        border-bottom: 1px solid #262626;
    }
    .logo {
        font-family: 'Inter', sans-serif; 
        font-size: 1.8rem; 
        font-weight: 800;
        background: linear-gradient(45deg, #f09433 0%, #e6683c 25%, #dc2743 50%, #cc2366 75%, #bc1888 100%); 
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    /* COMMENT SECTION STYLE */
    .comment-box {
        background: #121212;
        border-radius: 12px;
        padding: 15px;
        border: 1px solid #333;
        margin-top: 10px;
    }
    .username { font-weight: 700; font-size: 0.9rem; margin-right: 8px; }
    .verified { color: #3897f0; margin-left: 2px; }
    .comment-text { color: #dbdbdb; font-size: 0.95rem; line-height: 1.4; }
    
</style>
""", unsafe_allow_html=True)

# --- CONFIG & SECRETS ---
SCOPES = ['https://www.googleapis.com/auth/drive']
PARENT_FOLDER_ID = st.secrets["general"]["folder_id"]

# --- DRIVE DATABASE ---
@st.cache_resource
def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)

def load_votes_db():
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
    except: pass
    return {}

def save_votes_db(votes_dict):
    service = get_drive_service()
    try:
        results = service.files().list(
            q=f"'{PARENT_FOLDER_ID}' in parents and name = 'votes.json' and trashed = false",
            fields="files(id)"
        ).execute()
        files = results.get('files', [])
        
        json_str = json.dumps(votes_dict)
        media = MediaIoBaseUpload(io.BytesIO(json_str.encode('utf-8')), mimetype='application/json', resumable=True)
        
        if files: service.files().update(fileId=files[0]['id'], media_body=media).execute()
        else: service.files().create(body={'name': 'votes.json', 'parents': [PARENT_FOLDER_ID]}, media_body=media).execute()
    except: pass

# --- INIT STATE ---
if "image_votes" not in st.session_state: st.session_state.image_votes = load_votes_db()
if "current_image" not in st.session_state: st.session_state.current_image = None
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "audio_path" not in st.session_state: st.session_state.audio_path = None

# --- CORE FUNCTIONS ---
@st.cache_data(ttl=300)
def list_files():
    service = get_drive_service()
    results = service.files().list(
        q=f"'{PARENT_FOLDER_ID}' in parents and mimeType contains 'image/' and trashed = false",
        pageSize=100, fields="files(id, name, thumbnailLink)"
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
    # FAST & HINDI
    communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural", rate="+30%", pitch="+5Hz")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
        await communicate.save(tmp_file.name)
        return tmp_file.name

def run_tts(text):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(generate_audio(text))

def get_samay_roast(image_bytes):
    client = Groq(api_key=st.secrets["groq"]["api_key"])
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    # HINGLISH ONLY PROMPT
    system_prompt = (
        "You are Samay Raina. You are on Instagram Live reacting to photos. "
        "Speak ONLY in Hinglish. No pure English. "
        "Be savage, fast, dark comedy. "
        "Keep it under 2 sentences. "
        "Use words: 'Bhai', 'Cringe', 'Ye kya hai', 'Gajab'."
    )
    try:
        completion = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": "Roast this photo for your followers."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]}
            ],
            temperature=0.8,
            max_tokens=250
        )
        return completion.choices[0].message.content
    except: return "Server busy, but you look funny anyway."

# --- UI COMPONENTS ---

# SVG ICONS (The magic sauce for UI)
ICON_HEART = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ed4956" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>"""
ICON_COMMENT = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>"""
ICON_SHARE = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>"""

@st.dialog("📸 VibeGram Post", width="large")
def open_post_modal(file_id, file_name):
    col_img, col_comments = st.columns([1.3, 1], gap="large")
    
    with col_img:
        with st.spinner("Loading..."):
            img_data = download_image_bytes(file_id)
            st.image(img_data, use_container_width=True)
            
            # ACTION BAR
            votes = st.session_state.image_votes.get(file_id, 0)
            
            c1, c2, c3 = st.columns([1,1,3])
            if c1.button("❤️ Like", use_container_width=True):
                st.session_state.image_votes[file_id] = votes + 1
                save_votes_db(st.session_state.image_votes)
                st.rerun()
            if c2.button("🎤 Roast", use_container_width=True, type="primary"):
                # GENERATE ROAST
                with st.spinner("Samay is typing..."):
                    roast = get_samay_roast(img_data)
                    st.session_state.chat_history = [{"role": "assistant", "content": roast}]
                    st.session_state.audio_path = run_tts(roast)
                    st.rerun()
            
            st.markdown(f"**{votes} likes**")

    with col_comments:
        st.markdown("### Comments")
        st.divider()
        
        # User (You)
        st.markdown(f"""
        <div style="display:flex; margin-bottom:15px;">
            <div style="background:#333; width:35px; height:35px; border-radius:50%; margin-right:10px;"></div>
            <div>
                <span class="username">you</span>
                <div class="comment-text">Uploaded <b>{file_name}</b></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # AI (Samay)
        if st.session_state.chat_history:
            msg = st.session_state.chat_history[-1]["content"]
            st.markdown(f"""
            <div class="comment-box">
                <div style="display:flex; align-items:center; margin-bottom:5px;">
                    <span class="username">samay_raina_ai</span>
                    <span style="color:#3897f0;">✓</span>
                    <span style="color:#888; font-size:0.8rem; margin-left:auto;">Just now</span>
                </div>
                <div class="comment-text">{msg}</div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.session_state.audio_path:
                st.audio(st.session_state.audio_path, format="audio/mp3", autoplay=True)
        else:
            st.info("Tap '🎤 Roast' to summon Samay.")

def generate_insta_grid(files):
    html = ['<div class="masonry-wrapper">']
    for f in files:
        thumb = f['thumbnailLink'].replace('=s220', '=s800')
        votes = st.session_state.image_votes.get(f['id'], 0)
        
        card = f"""
        <div class="insta-card">
            <a href='#' id='{f['id']}' style="text-decoration:none; color:inherit;">
                <img src="{thumb}" class="insta-img" loading="lazy">
                <div class="insta-footer">
                    <div class="icon-group">
                        <div class="icon-btn">{ICON_HEART}</div>
                        <div class="icon-btn">{ICON_COMMENT}</div>
                        <div class="icon-btn">{ICON_SHARE}</div>
                    </div>
                </div>
                <div style="padding: 0 12px 12px 12px;">
                    <div class="likes-text">{votes} likes</div>
                </div>
            </a>
        </div>
        """
        html.append(card)
    html.append('</div>')
    return "".join(html)

# --- MAIN LAYOUT ---
st.markdown("""
<div class="app-header">
    <div class="logo">VibeGram</div>
    <div style="display:flex; gap:15px;">
        <div style="background:#262626; padding:8px 15px; border-radius:20px; font-weight:600;">Log in</div>
        <div style="background:#0095f6; color:white; padding:8px 15px; border-radius:20px; font-weight:600;">Sign Up</div>
    </div>
</div>
""", unsafe_allow_html=True)

# STORY BAR MOCKUP
st.markdown("""
<div style="display:flex; gap:15px; overflow-x:auto; padding-bottom:15px; margin-bottom:10px; scrollbar-width:none;">
    <div style="text-align:center;"><div style="width:65px; height:65px; border-radius:50%; background:linear-gradient(45deg, #f09433, #bc1888); padding:2px;"><div style="background:#000; width:100%; height:100%; border-radius:50%; border:2px solid #000;"></div></div><span style="font-size:0.75rem;">Your Story</span></div>
    <div style="text-align:center;"><div style="width:65px; height:65px; border-radius:50%; background:#262626; border:2px solid #000;"></div><span style="font-size:0.75rem; color:#888;">samay_ai</span></div>
    <div style="text-align:center;"><div style="width:65px; height:65px; border-radius:50%; background:#262626; border:2px solid #000;"></div><span style="font-size:0.75rem; color:#888;">utkarsh</span></div>
    <div style="text-align:center;"><div style="width:65px; height:65px; border-radius:50%; background:#262626; border:2px solid #000;"></div><span style="font-size:0.75rem; color:#888;">trending</span></div>
</div>
""", unsafe_allow_html=True)

try:
    files = list_files()
    if not files: st.info("Feed is empty.")
    else:
        # Sort by votes to show "Trending" first
        files.sort(key=lambda x: st.session_state.image_votes.get(x['id'], 0), reverse=True)
        
        grid_html = generate_insta_grid(files)
        clicked_id = click_detector(grid_html)
        
        if clicked_id:
            if st.session_state.current_image != clicked_id:
                st.session_state.current_image = clicked_id
                st.session_state.chat_history = []
                st.session_state.audio_path = None
            
            target = next((f for f in files if f['id'] == clicked_id), None)
            if target: open_post_modal(clicked_id, target['name'])

except Exception as e: st.error(str(e))
