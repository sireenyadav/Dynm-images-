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
import time
import textwrap
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# --- PAGE CONFIG ---
st.set_page_config(page_title="VibeGram 💀", layout="wide", page_icon="💣")

# --- PRODUCT-GRADE CSS ---
st.markdown("""
<style>  
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;900&display=swap');  
  
/* DARK MODE & RESET */  
.block-container { padding-top: 0.5rem; padding-bottom: 5rem; max-width: 1000px; }  
header, footer { visibility: hidden; }  
body { background-color: #000; color: #fff; font-family: 'Inter', sans-serif; }  
  
/* MASONRY LAYOUT */  
.masonry-wrapper { column-count: 2; column-gap: 1rem; }  
@media (min-width: 768px) { .masonry-wrapper { column-count: 3; } }  
  
/* CARD STYLING */  
.insta-card {  
    break-inside: avoid;  
    margin-bottom: 1rem;  
    background: #121212;  
    border-radius: 12px;  
    overflow: hidden;  
    position: relative;  
    border: 1px solid #1f1f1f;  
    transition: all 0.2s cubic-bezier(0.25, 0.8, 0.25, 1);  
}  
.insta-card:hover { transform: translateY(-4px); border-color: #333; z-index: 10; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }  
  
/* LIVE BADGE */  
.live-badge {  
    background: #ff0055; color: white;  
    padding: 4px 8px; border-radius: 4px;  
    font-weight: 800; font-size: 0.7rem;  
    text-transform: uppercase; letter-spacing: 1px;  
    animation: pulse-red 2s infinite;  
}  
@keyframes pulse-red { 0% { opacity: 1; } 50% { opacity: 0.6; } 100% { opacity: 1; } }  
  
/* COMMENT SECTION UI */  
.comment-container { background: #0a0a0a; padding: 12px; border-radius: 8px; margin-top: 10px; border-left: 3px solid #333; }  
.samay-handle { font-weight: 900; color: #fff; margin-right: 5px; font-size: 0.9rem; }  
.verified-tick { color: #0095f6; font-size: 0.8rem; }  
.comment-body { color: #e0e0e0; font-size: 0.95rem; line-height: 1.4; margin-top: 2px; }  
  
/* ROAST LEVEL METER */  
.heat-meter { height: 4px; width: 100%; background: #333; margin-top: 10px; border-radius: 2px; overflow: hidden; }  
.heat-fill { height: 100%; transition: width 0.5s ease; }  
</style>  """, unsafe_allow_html=True)

# --- CONFIG & AUTH ---

SCOPES = ['https://www.googleapis.com/auth/drive']
# Ensure "folder_id" exists in your secrets.toml
PARENT_FOLDER_ID = st.secrets["general"]["folder_id"]

@st.cache_resource
def get_drive_service():
    # Ensure "gcp_service_account" exists in your secrets.toml
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)

# --- DATABASE ENGINE (JSON in Drive) ---

def load_db():
    service = get_drive_service()
    try:
        results = service.files().list(
            q=f"'{PARENT_FOLDER_ID}' in parents and name='vibegram_db.json' and trashed=false", 
            fields="files(id)"
        ).execute()
        files = results.get('files', [])
        if files:
            request = service.files().get_media(fileId=files[0]['id'])
            file_obj = io.BytesIO()
            downloader = MediaIoBaseDownload(file_obj, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return json.loads(file_obj.getvalue().decode('utf-8'))
    except Exception:
        pass
    # Default Structure
    return {"votes": {}, "comments": {}, "roast_history": {}}

def save_db(db):
    service = get_drive_service()
    try:
        results = service.files().list(
            q=f"'{PARENT_FOLDER_ID}' in parents and name='vibegram_db.json' and trashed=false", 
            fields="files(id)"
        ).execute()
        files = results.get('files', [])
        json_str = json.dumps(db)
        media = MediaIoBaseUpload(io.BytesIO(json_str.encode('utf-8')), mimetype='application/json', resumable=True)

        if files:   
            service.files().update(fileId=files[0]['id'], media_body=media).execute()  
        else:   
            service.files().create(body={'name': 'vibegram_db.json', 'parents': [PARENT_FOLDER_ID]}, media_body=media).execute()  
    except Exception:  
        pass

# --- STATE MANAGEMENT ---

if "db" not in st.session_state: st.session_state.db = load_db()
if "visual_context" not in st.session_state: st.session_state.visual_context = {}
if "current_level" not in st.session_state: st.session_state.current_level = 1
if "audio_path" not in st.session_state: st.session_state.audio_path = None
if "roast_text" not in st.session_state: st.session_state.roast_text = None

# --- CORE FUNCTIONS ---

@st.cache_data(ttl=600)
def list_files():
    service = get_drive_service()
    results = service.files().list(
        q=f"'{PARENT_FOLDER_ID}' in parents and mimeType contains 'image/' and trashed=false", 
        pageSize=100, 
        fields="files(id, name, thumbnailLink)"
    ).execute()
    return results.get('files', [])

def download_image_bytes(file_id):
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    file_obj = io.BytesIO()
    downloader = MediaIoBaseDownload(file_obj, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return file_obj.getvalue()

# --- THE PREDATOR PIPELINE (AI LOGIC) ---

def stage_1_context_builder(client, base64_image):
    """
    The Silent Observer. Extracts signals using Llama 3.2 Vision.
    """
    prompt = """
    Analyze this image for a roast comedian.
    Describe the vibe, objects, pose, setting, and one specific "roastable point".

    Return JSON format with keys: vibe, objects, pose, setting, roastable_point.  
    """  
    try:  
        completion = client.chat.completions.create(  
            model="llama-3.2-90b-vision-preview", # LATEST VISION MODEL  
            messages=[  
                {  
                    "role": "user",   
                    "content": [  
                        {"type": "text", "text": prompt},   
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}  
                    ]  
                }  
            ],  
            temperature=0.5,   
            max_tokens=300,   
            response_format={"type": "json_object"}  
        )  
        return json.loads(completion.choices[0].message.content)  
    except Exception as e:  
        print(f"Vision Error: {e}")  
        return {"vibe": "generic", "roastable_point": "trying too hard"}

def stage_2_dynamic_roast(client, context, level):
    """
    The Roast Engine using Llama 3.3.
    """
    # 5% Chance of Refusal (Unpredictability)
    if random.random() < 0.05:
        return "Yaar mood nahi hai. Yeh photo dekh ke waise hi din kharab ho gaya. Next."

    # Escalation Logic  
    styles = {  
        1: "Light teasing. Point out the obvious.",  
        2: "Personal attack. Focus on insecurity.",  
        3: "NUCLEAR. Question their life choices. Brutal."  
    }  

    # SYSTEM: The Persona  
    system_prompt = """  
    You are Samay Raina (Indian Standup Comedian).  
    1. HINGLISH ONLY (Hindi words in English script).  
    2. Use slang: "Bhai", "Matlab", "Gajab", "Khatam", "Chomu".  
    3. No "Hello" or pleasantries. Start attacking immediately.  
    4. Make it sound like a live stream chat comment.  
    5. Max 2 short sentences.  
    """  

    # USER: The Trigger  
    user_prompt = f"""  
    Roast this person based on these details:  
    CONTEXT: {json.dumps(context)}  
    HEAT LEVEL: {level}/3 ({styles[level]})  
    
    Specifically mention the '{context.get('roastable_point')}' to make it personal.  
    """  

    try:  
        completion = client.chat.completions.create(  
            model="llama-3.3-70b-versatile", # LATEST TEXT MODEL  
            messages=[  
                {"role": "system", "content": system_prompt},  
                {"role": "user", "content": user_prompt}  
            ],  
            temperature=0.8 + (level * 0.1),   
            max_tokens=150  
        )  
        return completion.choices[0].message.content  
    except Exception as e:  
        return f"Arre server crash ho gaya teri photo dekh ke. (Error: {str(e)})"

async def stage_3_audio_chaos(text):
    """
    Adds stutters, pauses, and speed variations.
    """
    # Insert Pause
    if "," in text: text = text.replace(",", " ... ")

    # Random Stutter  
    words = text.split()  
    if len(words) > 5 and random.random() < 0.3:  
        idx = random.randint(0, len(words)-3)  
        words[idx] = words[idx][0] + "-" + words[idx]  
        text = " ".join(words)  

    # Variation  
    rate = random.choice(["+25%", "+30%", "+35%"])  
    pitch = random.choice(["-2Hz", "+0Hz", "+2Hz"])  

    communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural", rate=rate, pitch=pitch)  
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:  
        await communicate.save(tmp.name)  
        return tmp.name

def run_tts(text):
    # Fix for Event Loop in Streamlit
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(stage_3_audio_chaos(text))

# --- VIRAL CARD GENERATOR ---

def generate_viral_card(img_bytes, roast_text):
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")

        # Dark Overlay  
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 150))  
        img = Image.alpha_composite(img, overlay)  

        # Text Setup   
        draw = ImageDraw.Draw(img)  
        
        # Determine Font (Basic fallback)
        try:
            # You might need a .ttf file in your directory for this to work perfectly
            font = ImageFont.truetype("arial.ttf", 40)
        except:
            font = ImageFont.load_default()

        # Simple word wrap logic  
        margin = 40  
        offset = img.height // 2  
        for line in textwrap.wrap(roast_text, width=25):  
            draw.text((margin, offset), line, fill="white", font=font)  
            offset += 50  

        # Branding  
        draw.text((margin, img.height - 80), "💀 VibeGram", fill="#ff0055", font=font)  

        output = io.BytesIO()  
        img.convert("RGB").save(output, format="JPEG")  
        return output.getvalue()  
    except Exception as e: 
        print(e)
        return None

# --- FAKE COMMENT GENERATOR ---

def get_fake_comments():
    users = ["tanmaybhat", "suhani.shah", "random_guy_12", "gym_bro_99", "papa_ki_pari"]
    comments = [
        "💀💀💀 bhai saans lene de usko",
        "Emotional damage.",
        "Police ko bulao, murder hua hai",
        "Why is this so accurate though? 😭",
        "Bro deleted his account after this"
    ]
    return random.sample(list(zip(users, comments)), 2)

# --- UI CONTROLLER ---

@st.dialog("💀 The Roast Room", width="large")
def open_roast_room(file_id, file_name):
    # Load State
    votes = st.session_state.db["votes"].get(file_id, 0)

    col_vis, col_int = st.columns([1.2, 1], gap="medium")  

    with col_vis:  
        with st.spinner("Analyzing visuals..."):  
            img_bytes = download_image_bytes(file_id)  
            st.image(img_bytes, use_container_width=True)  

        # Like Animation Button  
        if st.button(f"❤️ Like ({votes})", use_container_width=True):  
            st.session_state.db["votes"][file_id] = votes + 1  
            save_db(st.session_state.db)  
            st.rerun()  

    with col_int:  
        st.markdown("### Samay's Corner")  

        # Heat Level Visualization  
        lvl = st.session_state.current_level  
        colors = {1: "#ffd700", 2: "#ff8c00", 3: "#ff0000"}  
        st.markdown(f"""  
        <div class="heat-meter">  
        <div class="heat-fill" style="width: {lvl*33}%; background: {colors[lvl]};"></div>  
        </div>  
        <div style="text-align:right; font-size:0.8rem; color:{colors[lvl]}; font-weight:bold;">HEAT LEVEL {lvl}</div>  
        """, unsafe_allow_html=True)  

        # Action Button  
        btn_text = "🎤 Start Roast" if lvl == 1 else ("🔥 Go Harder" if lvl == 2 else "💀 NUKE THEM")  

        if st.button(btn_text, type="primary", use_container_width=True):  
            # Ensure "groq" exists in secrets.toml
            client = Groq(api_key=st.secrets["groq"]["api_key"])  
            b64_img = base64.b64encode(img_bytes).decode('utf-8')  

            # Stage 1: Context (Run once)  
            if file_id not in st.session_state.visual_context:  
                with st.status("🧠 Analyzing psychology...", expanded=False):  
                    ctx = stage_1_context_builder(client, b64_img)  
                    st.session_state.visual_context[file_id] = ctx  

            # Stage 2: Roast  
            with st.spinner("Writing violation..."):  
                time.sleep(1) # Dramatic pause  
                roast = stage_2_dynamic_roast(client, st.session_state.visual_context[file_id], lvl)  
                st.session_state.roast_text = roast  

            # Stage 3: Audio  
            st.session_state.audio_path = run_tts(roast)  

            # Increment Level  
            st.session_state.current_level = min(lvl + 1, 3)  
            st.rerun()  

        st.divider()  

        # RESULT DISPLAY  
        if st.session_state.roast_text:  
            # Main Roast Comment  
            st.markdown(f"""  
            <div class="comment-container">  
            <div style="display:flex; align-items:center;">  
            <span class="samay-handle">samay_raina_ai</span>  
            <span class="verified-tick">✓</span>  
            </div>  
            <div class="comment-body">{st.session_state.roast_text}</div>  
            </div>  
            """, unsafe_allow_html=True)  

            if st.session_state.audio_path:  
                st.audio(st.session_state.audio_path, format="audio/mp3", autoplay=True)  

            # Fake Comments (Social Proof)  
            st.markdown("<br><b>Comments</b>", unsafe_allow_html=True)  
            for user, txt in get_fake_comments():  
                st.markdown(f"<div style='font-size:0.85rem; margin-bottom:5px;'><b>{user}</b>: {txt}</div>", unsafe_allow_html=True)  

        # Share Button  
        st.divider()  
        if st.button("📤 Generate Viral Card", use_container_width=True):  
            if st.session_state.roast_text:  
                card_bytes = generate_viral_card(img_bytes, st.session_state.roast_text)  
                if card_bytes:  
                    st.download_button("Download for Story", card_bytes, "story.jpg", "image/jpeg", use_container_width=True)

# --- FEED RENDERER ---

def render_feed(files):
    html = ['<div class="masonry-wrapper">']
    for f in files:
        # Use simple string replacement for thumbnail size if using standard Google drive thumbnails
        thumb = f.get('thumbnailLink', '').replace('=s220', '=s800')
        votes = st.session_state.db["votes"].get(f['id'], 0)

        # Calculate Trending  
        is_trending = False  
        if votes > 5: is_trending = True # Simple threshold for demo logic  

        badge = '<div class="live-badge" style="position:absolute; top:10px; right:10px;">🔥 TRENDING</div>' if is_trending else ''  

        card = f"""  
        <div class="insta-card">  
        <a href='#' id='{f['id']}' style="text-decoration:none; color:inherit;">  
        {badge}  
        <img src="{thumb}" style="width:100%; display:block;">  
        <div style="padding:10px; display:flex; justify-content:space-between; align-items:center;">  
        <div style="font-weight:bold; font-size:0.9rem;">❤️ {votes}</div>  
        <div style="font-size:0.8rem; opacity:0.7;">Tap to Roast</div>  
        </div>  
        </a>  
        </div>  
        """  
        html.append(card)  
    html.append('</div>')  
    return "".join(html)

# --- MAIN EXECUTION ---

# Live Activity Header
online_users = random.randint(800, 1500)
st.markdown(f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; padding:10px; background:#111; border-radius:8px;">  
<div style="font-weight:900; font-size:1.5rem;">VibeGram</div>  
<div style="color:#00ff00; font-size:0.8rem;">● {online_users} Online</div>  
</div>  
""", unsafe_allow_html=True)

try:
    files = list_files()
    if not files:
        st.info("Feed empty. Add images to the Drive folder.")
    else:
        # Sort by votes
        files.sort(key=lambda x: st.session_state.db["votes"].get(x['id'], 0), reverse=True)

        grid_html = render_feed(files)  
        clicked_id = click_detector(grid_html)  

        if clicked_id:  
            # Reset Roast State on New Click  
            if "current_view_id" not in st.session_state or st.session_state.current_view_id != clicked_id:  
                st.session_state.current_view_id = clicked_id  
                st.session_state.current_level = 1  
                st.session_state.roast_text = None  
                st.session_state.audio_path = None  
                st.session_state.visual_context.pop(clicked_id, None) # Clear context to force re-analysis if needed  

            target = next((f for f in files if f['id'] == clicked_id), None)  
            if target:   
                open_roast_room(clicked_id, target['name'])

except Exception as e:
    st.error(f"System Malfunction: {e}")
