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

# --- PREMIUM CSS ARCHITECTURE ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;800&display=swap');

/* RESET & BASICS */
.block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 900px; }
body { background-color: #000; color: #fff; font-family: 'Inter', sans-serif; }
a { text-decoration: none !important; }

/* FEED GRID */
.masonry-wrapper { column-count: 2; column-gap: 1.5rem; }
@media (min-width: 768px) { .masonry-wrapper { column-count: 3; } }

/* PREMIUM CARD STYLING */
.insta-card {
    break-inside: avoid;
    margin-bottom: 1.5rem;
    background: #000;
    border-radius: 16px; /* Smooth corners */
    position: relative;
    overflow: hidden;
    border: 1px solid #1f1f1f;
    transition: all 0.3s ease;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5);
}
.insta-card:hover { 
    transform: translateY(-5px); 
    border-color: #444; 
    box-shadow: 0 12px 40px rgba(0,0,0,0.8);
}

/* GLASSMORPHISM OVERLAY (The "Premium" Look) */
.glass-overlay {
    position: absolute;
    bottom: 0;
    width: 100%;
    padding: 12px 16px;
    background: rgba(0, 0, 0, 0.65); /* Dark semi-transparent */
    backdrop-filter: blur(12px);      /* The Apple/Insta blur effect */
    -webkit-backdrop-filter: blur(12px);
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

/* ICON STYLING INSIDE HTML */
.icon-row { display: flex; align-items: center; gap: 6px; }
.stat-text { font-size: 0.85rem; font-weight: 600; color: #f0f0f0; letter-spacing: 0.5px; }

/* CHAT & COMMENTS */
.chat-bubble {
    background: #111; border-left: 3px solid #e91e63; padding: 15px;
    margin-bottom: 15px; border-radius: 4px; font-size: 0.95rem; line-height: 1.5; color: #eee;
}
.user-comment {
    font-size: 0.9rem; margin-bottom: 8px; border-bottom: 1px solid #222; padding-bottom: 8px;
}
.user-handle { font-weight: 700; color: #aaa; font-size: 0.8rem; margin-right: 5px; }

</style>
""", unsafe_allow_html=True)

# --- CONFIG ---
SCOPES = ['https://www.googleapis.com/auth/drive']
FOLDER_ID = st.secrets["general"]["folder_id"]

# --- IDENTITY SYSTEM ---
if "user_id" not in st.session_state:
    st.session_state.user_id = f"user_{str(uuid.uuid4())[:6]}"
    
def get_user_name():
    names = ["VibeCheck_99", "RoastMaster_X", "SilentObserver", "LaughingEmoji", "GymBro_42"]
    idx = int(st.session_state.user_id.split('_')[1], 16) % len(names)
    return names[idx]

# --- AUDIO CORE (No Changes - Kept for context) ---
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
        await AudioCore._gen_segment(setup_text, "+15%", "+0Hz", t_setup)
        await AudioCore._gen_segment(punchline_text, "-5%", "-2Hz", t_punch)
        seg_setup = normalize(AudioSegment.from_mp3(t_setup))
        seg_punch = normalize(AudioSegment.from_mp3(t_punch))
        pause = AudioSegment.silent(duration=500)
        final_mix = seg_setup + pause + seg_punch
        final_mix.export(t_final, format="mp3")
        os.remove(t_setup)
        os.remove(t_punch)
        return t_final

def run_audio_production(setup, punchline):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(AudioCore.produce_standup_audio(setup, punchline))

# --- DATABASE (Persistence) ---
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

# --- MEDIA PROCESSING ---
@st.cache_data(ttl=3600)
def get_image_bytes(file_id):
    service = st.session_state.db.service
    request = service.files().get_media(fileId=file_id)
    file_obj = io.BytesIO()
    downloader = MediaIoBaseDownload(file_obj, request)
    done = False
    while not done: _, done = downloader.next_chunk()
    return file_obj.getvalue()

def process_image(img_bytes):
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    target_ratio = 4/5
    w, h = img.size
    current_ratio = w/h
    if current_ratio > target_ratio:
        new_w = int(h * target_ratio)
        img = img.crop(((w-new_w)//2, 0, (w-new_w)//2 + new_w, h))
    else:
        new_h = int(w / target_ratio)
        img = img.crop((0, (h-new_h)//2, w, (h-new_h)//2 + new_h))
    return img

# --- AI LOGIC ---
def stage_1_analyze(client, b64_img):
    try:
        completion = client.chat.completions.create(
            model="llama-3.2-11b-vision-preview",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "Analyze for a roast. JSON: {visual_fact, roast_angle}"}, 
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
            ]}],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except: return {"visual_fact": "Selfie", "roast_angle": "Vanity"}

def stage_2_write_comedy(client, context, style):
    prompt = f"Style: {style}. Context: {context}. Write structured JSON roast: {{setup, punchline}}. Hinglish."
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

    # Simple Header
    if st.button("← Back to Feed"):
        st.session_state.selected_post = None
        st.rerun()

    col_img, col_interact = st.columns([1, 1], gap="medium")
    with col_img:
        img = process_image(get_image_bytes(post['file_id']))
        st.image(img, use_container_width=True)
        if st.button(f"❤️ Like ({post['likes']})", use_container_width=True):
            st.session_state.db.toggle_like(pid)
            st.rerun()

    with col_interact:
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

        st.markdown("#### 💬 Comments")
        with st.form("c_form", clear_on_submit=True):
            if st.form_submit_button("Post") and (txt := st.text_input("Comment")):
                st.session_state.db.add_comment(pid, txt)
                st.rerun()
        
        for c in reversed(post.get('comments', [])[-5:]):
            st.markdown(f"<div class='user-comment'><b>{c['user_name']}</b>: {c['text']}</div>", unsafe_allow_html=True)

def render_feed():
    st.session_state.db.data = st.session_state.db._load()
    posts = st.session_state.db.sync_drive_images()
    post_list = sorted([{"id": k, **v} for k,v in posts.items()], key=lambda x: x['likes'], reverse=True)

    if not post_list: st.info("Feed Empty."); return

    html = ['<div class="masonry-wrapper">']
    for p in post_list:
        thumb = f"https://drive.google.com/thumbnail?id={p['file_id']}&sz=w400"
        
        # --- PREMIUM HTML CARD ---
        # Note: href='javascript:void(0);' prevents the reload loop
        card = f"""
        <div class="insta-card">
            <a href='javascript:void(0);' id='{p['id']}' style="display:block; cursor:pointer;">
                <div style="width:100%; padding-top:125%; position:relative; overflow:hidden; background:#101010;">
                     <img src="{thumb}" style="position:absolute; top:0; left:0; width:100%; height:100%; object-fit:cover;">
                     
                     <div class="glass-overlay">
                        <div class="icon-row">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
                            <span class="stat-text">{p['likes']}</span>
                        </div>
                        
                        <div class="icon-row">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
                            <span class="stat-text">{len(p['roast_ids'])}</span>
                        </div>
                     </div>
                </div>
            </a>
        </div>
        """
        html.append(card)
    html.append('</div>')
    
    # CLICK DETECTOR
    clicked_id = click_detector("".join(html))
    
    if clicked_id:
        st.session_state.selected_post = clicked_id
        st.rerun()

# --- MAIN ---
if "selected_post" not in st.session_state: st.session_state.selected_post = None

if st.session_state.selected_post:
    render_roast_room()
else:
    st.markdown(f"## VibeGram 💀 <span style='font-size:0.8rem; color:#666'>@{get_user_name()}</span>", unsafe_allow_html=True)
    render_feed()
