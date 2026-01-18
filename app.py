import streamlit as st
import io
import json
import time
import random
import base64
import asyncio
import uuid
import os
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from groq import Groq
from st_click_detector import click_detector
import edge_tts
from PIL import Image, ImageOps, ImageFilter
from pydub import AudioSegment
from pydub.effects import normalize

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="VibeGram 💀",
    layout="wide",
    page_icon="💣",
    initial_sidebar_state="collapsed"
)

# --- CSS ARCHITECTURE (FIXED FOR MOBILE) ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;900&display=swap');

/* GLOBAL RESET */
.block-container { padding-top: 0.5rem; padding-bottom: 5rem; max-width: 900px; }
body { background-color: #000; color: #fff; font-family: 'Inter', sans-serif; }
a { text-decoration: none !important; }

/* GRID SYSTEM (Mobile First) 
   Forces 2 columns even on small screens 
*/
.grid-wrapper { 
    display: grid;
    grid-template-columns: repeat(2, 1fr); /* STRICT 2 COLUMNS */
    gap: 10px;
    padding-bottom: 50px;
}

/* Tablet/Desktop: 3 Columns */
@media (min-width: 768px) { 
    .grid-wrapper { grid-template-columns: repeat(3, 1fr); gap: 20px; } 
}

/* CARD STYLING */
.insta-card {
    background: #000;
    border-radius: 12px;
    position: relative;
    overflow: hidden;
    border: 1px solid #1f1f1f;
    aspect-ratio: 4/5; /* Enforce Instagram Ratio */
    transition: transform 0.2s ease;
}
.insta-card:active { transform: scale(0.98); } /* Touch feedback */

/* IMAGE FIT */
.card-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}

/* GLASS OVERLAY */
.glass-overlay {
    position: absolute;
    bottom: 0;
    width: 100%;
    padding: 8px 10px;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.stat-text { font-size: 0.75rem; font-weight: 700; color: #fff; margin-left: 4px; }
.icon-row { display: flex; align-items: center; }

/* ROAST CHAT UI */
.chat-bubble {
    background: #111; border-left: 3px solid #e91e63; padding: 12px;
    margin-bottom: 12px; border-radius: 6px; font-size: 0.9rem; color: #eee;
}
</style>
""", unsafe_allow_html=True)

# --- CONFIG ---
SCOPES = ['https://www.googleapis.com/auth/drive']
FOLDER_ID = st.secrets["general"]["folder_id"]

# --- IDENTITY ---
if "user_id" not in st.session_state:
    st.session_state.user_id = f"user_{str(uuid.uuid4())[:6]}"
    
def get_user_name():
    names = ["VibeCheck_99", "RoastMaster_X", "SilentObserver", "LaughingEmoji", "GymBro_42"]
    idx = int(st.session_state.user_id.split('_')[1], 16) % len(names)
    return names[idx]

# --- DATABASE ---
class VibeDB:
    def __init__(self):
        self.creds = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"], scopes=SCOPES
        )
        self.service = build('drive', 'v3', credentials=self.creds)
        self.file_name = "vibegram_social_db.json"
        self.data = self._load()

    def _load(self):
        try:
            results = self.service.files().list(
                q=f"'{FOLDER_ID}' in parents and name='{self.file_name}' and trashed=false", 
                fields="files(id)"
            ).execute()
            files = results.get('files', [])
            if files:
                request = self.service.files().get_media(fileId=files[0]['id'])
                file_obj = io.BytesIO()
                downloader = MediaIoBaseDownload(file_obj, request)
                done = False
                while not done: _, done = downloader.next_chunk()
                return json.loads(file_obj.getvalue().decode('utf-8'))
        except Exception: pass
        return {"posts": {}, "roasts": {}}

    def save(self):
        try:
            json_str = json.dumps(self.data)
            media = MediaIoBaseUpload(io.BytesIO(json_str.encode('utf-8')), mimetype='application/json', resumable=True)
            results = self.service.files().list(
                q=f"'{FOLDER_ID}' in parents and name='{self.file_name}' and trashed=false", 
                fields="files(id)"
            ).execute()
            files = results.get('files', [])
            if files:
                self.service.files().update(fileId=files[0]['id'], media_body=media).execute()
            else:
                self.service.files().create(body={'name': self.file_name, 'parents': [FOLDER_ID]}, media_body=media).execute()
        except Exception: pass

    def sync_drive_images(self):
        results = self.service.files().list(
            q=f"'{FOLDER_ID}' in parents and mimeType contains 'image/' and trashed=false",
            fields="files(id, name, createdTime)"
        ).execute()
        drive_files = results.get('files', [])
        changes = False
        existing_ids = {p['file_id'] for p in self.data['posts'].values()}
        for f in drive_files:
            if f['id'] not in existing_ids:
                pid = str(uuid.uuid4())[:8]
                self.data['posts'][pid] = {
                    "file_id": f['id'], "created_at": f.get('createdTime'),
                    "likes": random.randint(10, 50), "comments": [], "roast_ids": []
                }
                changes = True
        if changes: self.save()
        return self.data['posts']

    def add_comment(self, post_id, text):
        if post_id in self.data['posts']:
            self.data['posts'][post_id]['comments'].append({
                "user_name": get_user_name(), "text": text, "timestamp": str(datetime.now())
            })
            self.save()

    def toggle_like(self, post_id):
        if post_id in self.data['posts']:
            self.data['posts'][post_id]['likes'] += 1
            self.save()

    def add_roast(self, post_id, setup, punchline, style):
        rid = str(uuid.uuid4())
        self.data['roasts'][rid] = {
            "post_id": post_id, "setup": setup, "punchline": punchline, "style": style
        }
        self.data['posts'][post_id]['roast_ids'].append(rid)
        self.save()
        return rid

if "db" not in st.session_state: st.session_state.db = VibeDB()

# --- MEDIA & AUDIO ---
@st.cache_data(ttl=3600)
def get_image_bytes(file_id):
    service = st.session_state.db.service
    request = service.files().get_media(fileId=file_id)
    file_obj = io.BytesIO()
    downloader = MediaIoBaseDownload(file_obj, request)
    done = False
    while not done: _, done = downloader.next_chunk()
    return file_obj.getvalue()

# (Using HEADLESS audio gen to avoid package crash)
class AudioCore:
    @staticmethod
    async def _gen_segment(text, rate, pitch, filename):
        communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural", rate=rate, pitch=pitch)
        await communicate.save(filename)
        return filename

    @staticmethod
    async def produce_standup_audio(setup_text, punchline_text):
        t_setup = f"setup_{uuid.uuid4()}.mp3"
        t_punch = f"punch_{uuid.uuid4()}.mp3"
        t_final = f"master_{uuid.uuid4()}.mp3"
        
        # Simple generation to prevent ffmpeg panic if system libs missing
        await AudioCore._gen_segment(setup_text + " ... " + punchline_text, "+0%", "+0Hz", t_final)
        return t_final

def run_audio_production(setup, punchline):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(AudioCore.produce_standup_audio(setup, punchline))

# --- AI LOGIC ---
def stage_1_analyze(client, b64_img):
    try:
        completion = client.chat.completions.create(
            model="llama-3.2-11b-vision-preview",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "Roast analysis JSON: {visual_fact, roast_angle}"}, 
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
            ]}],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except: return {"visual_fact": "Selfie", "roast_angle": "Vanity"}

def stage_2_write_comedy(client, context, style):
    prompt = f"Style: {style}. Context: {context}. JSON: {{setup, punchline}}. Hinglish."
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return json.loads(completion.choices[0].message.content)

# --- UI RENDERER ---
def render_roast_room():
    pid = st.session_state.selected_post
    st.session_state.db.data = st.session_state.db._load()
    post = st.session_state.db.data['posts'].get(pid)
    
    if not post: st.error("Post missing."); return

    if st.button("← Back to Feed"):
        st.session_state.selected_post = None
        st.rerun()

    img = Image.open(io.BytesIO(get_image_bytes(post['file_id'])))
    st.image(img, use_container_width=True)

    col1, col2 = st.columns([2, 1])
    if col1.button(f"❤️ Like ({post['likes']})", use_container_width=True):
        st.session_state.db.toggle_like(pid)
        st.rerun()

    st.markdown("### 💀 The Roast Room")
    style = st.select_slider("Intensity", ["Mild", "Savage", "Nuclear"], value="Savage")
    
    if st.button("🎤 Drop a Roast", type="primary", use_container_width=True):
        with st.spinner("Cooking..."):
            client = Groq(api_key=st.secrets["groq"]["api_key"])
            b64 = base64.b64encode(get_image_bytes(post['file_id'])).decode()
            ctx = stage_1_analyze(client, b64)
            joke = stage_2_write_comedy(client, ctx, style)
            audio_path = run_audio_production(joke['setup'], joke['punchline'])
            st.session_state.db.add_roast(pid, joke['setup'], joke['punchline'], style)
            st.audio(audio_path, format="audio/mp3", autoplay=True)
            st.rerun()

    st.divider()
    roasts = [st.session_state.db.data['roasts'][rid] for rid in post['roast_ids'] if rid in st.session_state.db.data['roasts']]
    if roasts:
        last = roasts[-1]
        st.markdown(f"<div class='chat-bubble'><b>@SamayRaina_AI</b><br>{last['setup']}... <b>{last['punchline']}</b></div>", unsafe_allow_html=True)

def render_feed():
    st.session_state.db.data = st.session_state.db._load()
    posts = st.session_state.db.sync_drive_images()
    post_list = sorted([{"id": k, **v} for k,v in posts.items()], key=lambda x: x['likes'], reverse=True)

    if not post_list: st.info("Feed Empty."); return

    html = ['<div class="grid-wrapper">']
    for p in post_list:
        thumb = f"https://drive.google.com/thumbnail?id={p['file_id']}&sz=w400"
        
        # --- FIXED CLICK CARD ---
        # href='#' is standard. id is set.
        # We rely on st_click_detector to catch the ID.
        card = f"""
        <div class="insta-card">
            <a href='#' id='{p['id']}' style="display:block; height:100%;">
                <img src="{thumb}" class="card-img">
                <div class="glass-overlay">
                    <div class="icon-row">
                        <span style="font-size:12px">❤️</span>
                        <span class="stat-text">{p['likes']}</span>
                    </div>
                    <div class="icon-row">
                        <span style="font-size:12px">💬</span>
                        <span class="stat-text">{len(p['roast_ids'])}</span>
                    </div>
                </div>
            </a>
        </div>
        """
        html.append(card)
    html.append('</div>')
    
    # DETECTOR
    clicked_id = click_detector("".join(html))
    
    if clicked_id:
        st.session_state.selected_post = clicked_id
        st.rerun()

# --- MAIN ---
if st.session_state.selected_post:
    render_roast_room()
else:
    st.markdown(f"### VibeGram 💀", unsafe_allow_html=True)
    render_feed()
        st.rerun()

# --- MAIN ---
if "selected_post" not in st.session_state: st.session_state.selected_post = None

if st.session_state.selected_post:
    render_roast_room()
else:
    st.markdown(f"## VibeGram 💀 <span style='font-size:0.8rem; color:#666'>@{get_user_name()}</span>", unsafe_allow_html=True)
    render_feed()
