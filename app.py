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

# --- CSS ARCHITECTURE ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;900&display=swap');
.block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 900px; }
body { background-color: #000; color: #fff; font-family: 'Inter', sans-serif; }

/* FEED */
.masonry-wrapper { column-count: 2; column-gap: 1.5rem; }
@media (min-width: 768px) { .masonry-wrapper { column-count: 3; } }

.insta-card {
    break-inside: avoid; margin-bottom: 1.5rem; background: #000;
    border: 1px solid #1a1a1a; transition: transform 0.2s;
}
.insta-card:hover { transform: scale(1.02); border-color: #333; z-index: 10; }

.meta-overlay {
    padding: 10px; background: linear-gradient(to top, rgba(0,0,0,0.9), transparent);
    position: absolute; bottom: 0; width: 100%; display:flex; justify-content:space-between;
}

/* CHAT & COMMENTS */
.chat-bubble {
    background: #111; border-left: 3px solid #e91e63; padding: 15px;
    margin-bottom: 15px; border-radius: 4px; font-size: 0.95rem; line-height: 1.5; color: #eee;
}
.user-comment {
    font-size: 0.9rem; margin-bottom: 8px; border-bottom: 1px solid #222; padding-bottom: 8px;
}
.user-handle { font-weight: 700; color: #aaa; font-size: 0.8rem; margin-right: 5px; }

/* AUDIO PLAYER */
audio { width: 100%; height: 30px; margin-top: 10px; }
</style>
""", unsafe_allow_html=True)

# --- CONFIG ---
SCOPES = ['https://www.googleapis.com/auth/drive']
FOLDER_ID = st.secrets["general"]["folder_id"]

# --- IDENTITY SYSTEM ---
if "user_id" not in st.session_state:
    st.session_state.user_id = f"user_{str(uuid.uuid4())[:6]}"
    
def get_user_name():
    # Simple consistent fake names based on UUID for demo
    names = ["VibeCheck_99", "RoastMaster_X", "SilentObserver", "LaughingEmoji", "GymBro_42"]
    idx = int(st.session_state.user_id.split('_')[1], 16) % len(names)
    return names[idx]

# --- AUDIO CORE (THE "NO COMPROMISE" ENGINE) ---
class AudioCore:
    """
    The Sound Engineer.
    Instead of one TTS call, it breaks the joke into parts and masters them.
    """
    @staticmethod
    async def _gen_segment(text, rate, pitch, filename):
        communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural", rate=rate, pitch=pitch)
        await communicate.save(filename)
        return filename

    @staticmethod
    async def produce_standup_audio(setup_text, punchline_text):
        """
        Creates a mastered audio file with timing nuances.
        """
        # File paths
        t_setup = f"setup_{uuid.uuid4()}.mp3"
        t_punch = f"punch_{uuid.uuid4()}.mp3"
        t_final = f"master_{uuid.uuid4()}.mp3"

        # 1. GENERATE PARTS
        # Setup: Fast, casual (+15%)
        await AudioCore._gen_segment(setup_text, "+15%", "+0Hz", t_setup)
        # Punchline: Slower, emphatic (-5%), slightly deeper (-2Hz)
        await AudioCore._gen_segment(punchline_text, "-5%", "-2Hz", t_punch)

        # 2. AUDIO POST-PROCESSING (Pydub)
        # Load segments
        seg_setup = AudioSegment.from_mp3(t_setup)
        seg_punch = AudioSegment.from_mp3(t_punch)

        # Normalize volume (Make it loud)
        seg_setup = normalize(seg_setup)
        seg_punch = normalize(seg_punch)

        # Create The "Comedic Pause" (Silence)
        # Longer pause if setup is long
        pause_duration = 400 if len(setup_text) < 50 else 650
        pause = AudioSegment.silent(duration=pause_duration)

        # 3. MASTERING
        # Stitch: Setup -> Pause -> Punchline
        final_mix = seg_setup + pause + seg_punch
        
        # Add a tiny bit of "Room Tone" (optional, keeps it natural) or fade out
        final_mix = final_mix.fade_out(100)

        # Export
        final_mix.export(t_final, format="mp3")
        
        # Cleanup temp files
        os.remove(t_setup)
        os.remove(t_punch)
        
        return t_final

def run_audio_production(setup, punchline):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(AudioCore.produce_standup_audio(setup, punchline))

# --- DATABASE & STORAGE (PERSISTENCE) ---
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
        # ATOMIC-ISH SAVE
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
        except Exception as e: print(f"Save Error: {e}")

    def sync_drive_images(self):
        """Scans drive for new images."""
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
                    "file_id": f['id'],
                    "created_at": f.get('createdTime'),
                    "likes": 0,
                    "comments": [],  # New: Comments Array
                    "roast_ids": []
                }
                changes = True
        
        if changes: self.save()
        return self.data['posts']

    def add_comment(self, post_id, text):
        if post_id in self.data['posts']:
            comment = {
                "user_id": st.session_state.user_id,
                "user_name": get_user_name(),
                "text": text,
                "timestamp": str(datetime.now())
            }
            self.data['posts'][post_id]['comments'].append(comment)
            self.save() # Persist immediately

    def toggle_like(self, post_id):
        if post_id in self.data['posts']:
            # Naive increment (in a real app, track who liked to prevent duplicates)
            self.data['posts'][post_id]['likes'] += 1
            self.save()

    def add_roast(self, post_id, setup, punchline, style):
        rid = str(uuid.uuid4())
        self.data['roasts'][rid] = {
            "post_id": post_id,
            "setup": setup,
            "punchline": punchline,
            "style": style,
            "timestamp": time.time()
        }
        self.data['posts'][post_id]['roast_ids'].append(rid)
        self.save()
        return rid

if "db" not in st.session_state: st.session_state.db = VibeDB()

# --- MEDIA UTILS ---
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
    # 4:5 Crop Logic
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
    """The Observer: Returns facts."""
    prompt = """
    Analyze this image for a roast. Return JSON:
    {
      "visual_fact": "One specific verifiable detail (e.g. 'wearing a neon green shirt')",
      "roast_angle": "The core insecurity to target"
    }
    """
    try:
        completion = client.chat.completions.create(
            model="llama-3.2-11b-vision-preview",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt}, 
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
            ]}],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except: return {"visual_fact": "Selfie", "roast_angle": "Vanity"}

def stage_2_write_comedy(client, context, style):
    """The Writer: Returns structured Setup & Punchline."""
    prompt = f"""
    You are Samay Raina. Style: {style}.
    Context: {json.dumps(context)}
    
    Task: Write a 2-part roast.
    1. SETUP: Acknowledge the visual fact. (Hinglish, Casual)
    2. PUNCHLINE: The twist/insult. (Hinglish, Brutal)
    
    Output JSON ONLY: {{"setup": "...", "punchline": "..."}}
    """
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return json.loads(completion.choices[0].message.content)

# --- UI RENDERER ---

def render_roast_room():
    pid = st.session_state.selected_post
    # RELOAD DB to see fresh comments/likes from others
    st.session_state.db.data = st.session_state.db._load()
    post = st.session_state.db.data['posts'].get(pid)
    
    if not post:
        st.error("Post missing."); return

    # Header
    c1, c2 = st.columns([1, 6])
    if c1.button("← Back"):
        st.session_state.selected_post = None; st.rerun()

    col_img, col_interact = st.columns([1, 1], gap="medium")

    # IMAGE COLUMN
    with col_img:
        img = process_image(get_image_bytes(post['file_id']))
        st.image(img, use_container_width=True)
        
        # Like Bar
        lc1, lc2 = st.columns([1, 1])
        if lc1.button(f"❤️ {post['likes']} Likes", use_container_width=True):
            st.session_state.db.toggle_like(pid)
            st.rerun()

    # INTERACTION COLUMN
    with col_interact:
        st.markdown("### 💀 The Roast Room")
        
        # 1. GENERATOR
        style = st.select_slider("Intensity", ["Mild", "Savage", "Nuclear"], value="Savage")
        if st.button("🎤 Drop a Roast", type="primary", use_container_width=True):
            with st.spinner("Cooking..."):
                client = Groq(api_key=st.secrets["groq"]["api_key"])
                # Vision
                b64 = base64.b64encode(get_image_bytes(post['file_id'])).decode()
                ctx = stage_1_analyze(client, b64)
                # Text
                joke = stage_2_write_comedy(client, ctx, style)
                # Audio (Complex)
                audio_path = run_audio_production(joke['setup'], joke['punchline'])
                # Save
                st.session_state.db.add_roast(pid, joke['setup'], joke['punchline'], style)
                
                # Auto-play immediate result
                st.audio(audio_path, format="audio/mp3", autoplay=True)
                st.rerun()

        st.divider()

        # 2. FEED OF ROASTS & COMMENTS
        # Show recent Roasts
        roasts = [st.session_state.db.data['roasts'][rid] for rid in post['roast_ids'] if rid in st.session_state.db.data['roasts']]
        
        # Mix Comments and Roasts? No, keep separate for clarity.
        
        if roasts:
            last_roast = roasts[-1]
            st.markdown(f"""
            <div class="chat-bubble">
                <span class="user-handle" style="color:#e91e63">@SamayRaina_AI</span><br>
                {last_roast['setup']}... <b>{last_roast['punchline']}</b>
            </div>
            """, unsafe_allow_html=True)
            # Replay Audio Logic could go here if we stored file IDs (omitted for brevity)

        # COMMENTS SECTION
        st.markdown("#### 💬 Comments")
        # Input
        with st.form("comment_form", clear_on_submit=True):
            txt = st.text_input("Say something...", placeholder="Add a comment...")
            if st.form_submit_button("Post"):
                if txt:
                    st.session_state.db.add_comment(pid, txt)
                    st.rerun()
        
        # Display Comments (Reverse Chronological)
        comments = post.get('comments', [])
        for c in reversed(comments[-10:]): # Show last 10
            st.markdown(f"""
            <div class="user-comment">
                <span class="user-handle">{c['user_name']}</span>
                <span style="color:#ddd;">{c['text']}</span>
            </div>
            """, unsafe_allow_html=True)

def render_feed():
    st.session_state.db.data = st.session_state.db._load() # Fresh Load
    posts = st.session_state.db.sync_drive_images()
    
    # Sort by Likes (Trending)
    post_list = sorted(
        [{"id": k, **v} for k,v in posts.items()], 
        key=lambda x: x['likes'], 
        reverse=True
    )

    if not post_list: st.info("Feed Empty. Upload to Drive."); return

    html = ['<div class="masonry-wrapper">']
    for p in post_list:
        thumb = f"https://drive.google.com/thumbnail?id={p['file_id']}&sz=w400"
        card = f"""
        <div class="insta-card">
            <a href='#' id='{p['id']}' style="text-decoration:none; color:inherit; display:block;">
                <div style="width:100%; padding-top:125%; position:relative; overflow:hidden; background:#111;">
                     <img src="{thumb}" style="position:absolute; top:0; left:0; width:100%; height:100%; object-fit:cover;">
                </div>
                <div class="meta-overlay">
                    <span>🔥 {len(p['roast_ids'])} Roasts</span>
                    <span>❤️ {p['likes']}</span>
                </div>
            </a>
        </div>
        """
        html.append(card)
    html.append('</div>')
    
    clicked = click_detector("".join(html))
    if clicked:
        st.session_state.selected_post = clicked
        st.rerun()

# --- MAIN ---
if "selected_post" not in st.session_state: st.session_state.selected_post = None

if st.session_state.selected_post:
    render_roast_room()
else:
    st.markdown(f"## VibeGram 💀 <span style='font-size:0.8rem; color:#666'>Logged in as {get_user_name()}</span>", unsafe_allow_html=True)
    render_feed()
