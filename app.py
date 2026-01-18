import streamlit as st
import io
import os
import json
import time
import uuid
import random
import asyncio
import logging
import base64
import textwrap
import tempfile
from datetime import datetime
from PIL import Image, ImageFilter, ImageDraw, ImageOps, ImageFont

# --- EXTERNAL SERVICES ---
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from groq import Groq
import edge_tts

# Try importing pydub, handle if ffmpeg is missing gracefully
try:
    from pydub import AudioSegment
    HAS_FFMPEG = True
except ImportError:
    HAS_FFMPEG = False
    print("⚠️ Pydub/FFmpeg not found. Audio mastering disabled.")

# --- CONFIGURATION ---
st.set_page_config(page_title="VibeGram Pro", layout="wide", page_icon="💀")

# SYSTEM CONSTANTS
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1350
FOLDER_ID = st.secrets["general"]["folder_id"]
DB_FILENAME = "vibegram_pro_db.json"

# --- CSS & UX ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;900&display=swap');
body { background-color: #050505; color: #e0e0e0; font-family: 'Inter', sans-serif; }
.block-container { max-width: 1000px; padding-top: 1rem; }

/* PRO CARD DESIGN */
.feed-card {
    background: #111; border: 1px solid #222; border-radius: 8px;
    margin-bottom: 24px; overflow: hidden; transition: transform 0.2s;
    position: relative;
}
.feed-card:hover { border-color: #444; transform: translateY(-2px); }
.meta-bar { padding: 12px; display: flex; justify-content: space-between; align-items: center; background: #0e0e0e; border-top: 1px solid #1a1a1a; }
.stat-pill { background: #1a1a1a; padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; color: #888; display: flex; align-items: center; gap: 5px;}
.trending { color: #00ff66; border: 1px solid #004411; background: #002208; }
.img-overlay { position: absolute; top: 10px; right: 10px; z-index: 10; }
</style>
""", unsafe_allow_html=True)

# --- 1. THE DATA LAYER (Real Persistence) ---
class VibeDB:
    def __init__(self):
        self.creds = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"], scopes=['https://www.googleapis.com/auth/drive']
        )
        self.service = build('drive', 'v3', credentials=self.creds)
        
        # Load DB immediately into Session State
        if "db_data" not in st.session_state:
            st.session_state.db_data = self._load_db_file()

    def _load_db_file(self):
        """Downloads the central JSON DB from Drive"""
        try:
            results = self.service.files().list(
                q=f"'{FOLDER_ID}' in parents and name='{DB_FILENAME}' and trashed=false", 
                fields="files(id)"
            ).execute()
            files = results.get('files', [])
            
            if files:
                st.session_state.db_file_id = files[0]['id']
                request = self.service.files().get_media(fileId=files[0]['id'])
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done: _, done = downloader.next_chunk()
                return json.loads(fh.getvalue().decode())
            else:
                st.session_state.db_file_id = None
                return {} # Start fresh
        except Exception as e:
            st.error(f"DB Load Error: {e}")
            return {}

    def save(self):
        """Uploads the current Session State DB back to Drive"""
        data = st.session_state.db_data
        media = MediaIoBaseUpload(io.BytesIO(json.dumps(data).encode()), mimetype='application/json')
        
        try:
            if st.session_state.get("db_file_id"):
                self.service.files().update(
                    fileId=st.session_state.db_file_id, media_body=media
                ).execute()
            else:
                file_metadata = {'name': DB_FILENAME, 'parents': [FOLDER_ID]}
                f = self.service.files().create(
                    body=file_metadata, media_body=media, fields='id'
                ).execute()
                st.session_state.db_file_id = f.get('id')
        except Exception as e:
            st.error(f"Save Failed: {e}")

    def fetch_feed_images(self):
        """Fetches list of image files"""
        query = f"'{FOLDER_ID}' in parents and mimeType contains 'image/' and trashed=false"
        results = self.service.files().list(
            q=query, pageSize=50, fields="files(id, name, createdTime, thumbnailLink)"
        ).execute()
        return results.get('files', [])

    def get_metadata(self, file_id):
        if file_id not in st.session_state.db_data:
            st.session_state.db_data[file_id] = {
                "likes": 0, "comments": [], "roast_history": [], "last_active": time.time()
            }
        return st.session_state.db_data[file_id]

# --- 2. THE MEDIA ENGINE (Image Processing) ---
class InstaProcess:
    @staticmethod
    def standardize(image_bytes):
        """Forces 4:5 Aspect Ratio with Blurred Background"""
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            
            target_ratio = 4/5
            img_ratio = img.width / img.height
            
            new_img = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT))
            
            if img_ratio > target_ratio:
                # Landscape -> Fit width, blur background
                scale = TARGET_WIDTH / img.width
                new_h = int(img.height * scale)
                resized = img.resize((TARGET_WIDTH, new_h), Image.Resampling.LANCZOS)
                
                # Blur BG
                bg = img.resize((TARGET_WIDTH, TARGET_HEIGHT)).filter(ImageFilter.GaussianBlur(40))
                # Darken BG
                overlay = Image.new('RGB', (TARGET_WIDTH, TARGET_HEIGHT), (0,0,0))
                bg = Image.blend(bg, overlay, 0.3)
                
                new_img.paste(bg, (0, 0))
                y_offset = (TARGET_HEIGHT - new_h) // 2
                new_img.paste(resized, (0, y_offset))
            else:
                # Portrait -> Center Crop
                new_img = ImageOps.fit(img, (TARGET_WIDTH, TARGET_HEIGHT), Image.Resampling.LANCZOS)
                
            return new_img
        except Exception:
            return None

# --- 3. THE COMEDY WRITER (2-Stage LLM) ---
class ComedyEngine:
    def __init__(self):
        self.client = Groq(api_key=st.secrets["groq"]["api_key"])

    def analyze_vibe(self, b64_img):
        """Stage 1: Llama 3.2 Vision Analysis"""
        prompt = """
        Analyze this image for a roast.
        Output JSON with keys: 
        - "insecurity": (Deep psychological guess)
        - "observation": (Visual proof)
        - "ammo": (The most embarrassing specific detail)
        """
        try:
            completion = self.client.chat.completions.create(
                model="llama-3.2-90b-vision-preview",
                messages=[{
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                    ]
                }],
                response_format={"type": "json_object"}
            )
            return json.loads(completion.choices[0].message.content)
        except:
            return {"ammo": "trying too hard", "observation": "generic pose"}

    def write_set(self, analysis, history, level):
        """Stage 2: Llama 3.3 Text Generation"""
        # Context building
        prev_roasts = " | ".join(history[-3:])
        
        system_prompt = """
        You are Samay Raina (Indian Comic). 
        - Style: Brutal, deadpan, Hinglish slang (Bhai, Matlab, Chomu).
        - Format: 1-2 punchy sentences.
        - NO EMOJIS (breaks audio).
        """
        
        user_prompt = f"""
        Target: {analysis.get('ammo')}
        Insecurity: {analysis.get('insecurity')}
        Previous Insults: {prev_roasts}
        Aggression: {level}/3
        
        Write a NEW roast. Do not repeat previous points.
        """
        
        completion = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.85
        )
        return completion.choices[0].message.content

# --- 4. THE AUDIO FORGE (Audio Engineering) ---
class AudioForge:
    @staticmethod
    async def synthesize(text):
        """Generates Audio -> Masters it with Pydub"""
        # Clean text
        clean_text = text.replace("*", "").replace('"', '').strip()
        
        communicate = edge_tts.Communicate(clean_text, "hi-IN-MadhurNeural", rate="+10%")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            await communicate.save(tmp.name)
            
            if not HAS_FFMPEG:
                return tmp.name

            try:
                # Mastering
                sound = AudioSegment.from_mp3(tmp.name)
                # Add 300ms silence at start for timing
                silence = AudioSegment.silent(duration=300)
                final_sound = silence + sound
                # Boost volume / Normalize
                final_sound = final_sound.normalize()
                
                output_path = tmp.name.replace(".mp3", "_mastered.mp3")
                final_sound.export(output_path, format="mp3")
                return output_path
            except Exception as e:
                print(f"Mastering failed: {e}")
                return tmp.name

# --- INITIALIZATION ---
db = VibeDB()
engine = ComedyEngine()
processor = InstaProcess()

# --- HELPER: DOWNLOAD IMAGE ---
def get_image_bytes(file_id):
    request = db.service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done: _, done = downloader.next_chunk()
    return fh.getvalue()

# --- UI CONTROLLER: ROAST ROOM ---
@st.dialog("🔥 The Roast Room", width="large")
def open_roast_room(file_id, file_name):
    # Fetch Data
    meta = db.get_metadata(file_id)
    
    col_img, col_act = st.columns([1, 1], gap="medium")
    
    # 1. Image Column
    with col_img:
        if f"img_{file_id}" not in st.session_state:
            with st.spinner("Loading visuals..."):
                raw = get_image_bytes(file_id)
                st.session_state[f"img_{file_id}"] = processor.standardize(raw)
                st.session_state[f"raw_{file_id}"] = raw # Keep raw for AI analysis
        
        if st.session_state.get(f"img_{file_id}"):
            st.image(st.session_state[f"img_{file_id}"], use_container_width=True)
            
            # Like Button
            if st.button(f"❤️ Like ({meta['likes']})", use_container_width=True):
                meta['likes'] += 1
                db.save()
                st.rerun()

    # 2. Action Column
    with col_act:
        st.subheader("Samay's Corner")
        
        # History
        if meta['roast_history']:
            st.markdown("#### History")
            for r in meta['roast_history'][-3:]:
                st.info(f"🎤 {r}")
        
        st.divider()
        
        # Controls
        level = st.select_slider("Heat Level", options=[1, 2, 3], value=2, 
                               format_func=lambda x: "Tease" if x==1 else ("Roast" if x==2 else "NUKE"))
        
        if st.button("🎙️ Generate Violation", type="primary", use_container_width=True):
            status = st.status("Analyzing target...", expanded=True)
            try:
                # A. Vision
                status.write("🧠 Scanning insecurities...")
                b64 = base64.b64encode(st.session_state[f"raw_{file_id}"]).decode()
                analysis = engine.analyze_vibe(b64)
                
                # B. Text
                status.write("📝 Writing material...")
                roast_text = engine.write_set(analysis, meta['roast_history'], level)
                
                # C. Audio
                status.write("🎚️ Recording audio...")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                audio_path = loop.run_until_complete(AudioForge.synthesize(roast_text))
                
                # D. Save
                meta['roast_history'].append(roast_text)
                meta['last_active'] = time.time()
                db.save()
                
                status.update(label="Violated", state="complete", expanded=False)
                
                # E. Play
                st.success(roast_text)
                st.audio(audio_path, format="audio/mp3", autoplay=True)
                
            except Exception as e:
                status.update(label="Error", state="error")
                st.error(f"System failed: {e}")

# --- MAIN FEED ---
st.title("VibeGram 💀")

# Algorithm: Heat Score
def get_heat(item, meta):
    # (Likes * 2) + (Roasts * 3) / Age_Hours
    try:
        created = datetime.strptime(item['createdTime'], "%Y-%m-%dT%H:%M:%S.%fZ")
        hours = max(1, (datetime.utcnow() - created).total_seconds() / 3600)
        score = (meta['likes'] * 2 + len(meta['roast_history']) * 3) / (hours ** 0.8)
        return score
    except: return 0

try:
    files = db.fetch_feed_images()
    if not files:
        st.info("Feed is empty. Upload images to Google Drive.")
    else:
        # Prepare Feed Data
        feed = []
        for f in files:
            m = db.get_metadata(f['id'])
            feed.append({
                **f, 
                "meta": m, 
                "heat": get_heat(f, m)
            })
        
        # Sort by Heat
        feed.sort(key=lambda x: x['heat'], reverse=True)
        
        # Grid Layout
        cols = st.columns(3)
        for idx, item in enumerate(feed):
            with cols[idx % 3]:
                # Trending Logic
                is_trending = idx < 2 and item['heat'] > 0
                badge = '<span class="stat-pill trending">🔥 HOT</span>' if is_trending else ''
                
                # Thumbnail
                thumb = item['thumbnailLink'].replace('=s220', '=s800')
                
                # Card HTML
                st.markdown(f"""
                <div class="feed-card">
                    <div class="img-overlay">{badge}</div>
                    <img src="{thumb}" style="width:100%; aspect-ratio:4/5; object-fit:cover; display:block; opacity:0.9;">
                    <div class="meta-bar">
                        <span class="stat-pill">❤️ {item['meta']['likes']}</span>
                        <span class="stat-pill">💬 {len(item['meta']['roast_history'])} roasts</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button("Roast This", key=f"btn_{item['id']}", use_container_width=True):
                    open_roast_room(item['id'], item['name'])

except Exception as e:
    st.error(f"Critical Application Error: {e}")
