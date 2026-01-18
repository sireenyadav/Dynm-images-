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

# --- PAGE CONFIG ---
st.set_page_config(page_title="VibeGram", layout="wide", page_icon="💣")

# --- PRODUCT-GRADE CSS ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;900&display=swap');
    
    /* RESET & DARK MODE */
    .block-container { padding-top: 0.5rem; padding-bottom: 5rem; max-width: 1000px; }
    header, footer { visibility: hidden; }
    body { background-color: #000; color: #fff; font-family: 'Inter', sans-serif; }

    /* MASONRY LAYOUT */
    .masonry-wrapper { column-count: 2; column-gap: 1rem; }
    @media (min-width: 768px) { .masonry-wrapper { column-count: 3; } }

    /* INSTAGRAM CARD */
    .insta-card {
        break-inside: avoid;
        margin-bottom: 1rem;
        background: #121212;
        border-radius: 12px;
        overflow: hidden;
        position: relative;
        border: 1px solid #1f1f1f;
        transition: all 0.2s;
    }
    .insta-card:hover { transform: scale(1.01); border-color: #333; z-index: 10; }

    /* MICRO-INTERACTIONS */
    .like-anim { animation: pop 0.3s ease; }
    @keyframes pop { 0% { transform: scale(1); } 50% { transform: scale(1.3); } 100% { transform: scale(1); } }

    /* TRENDING BADGE */
    .trending-badge {
        position: absolute; top: 10px; right: 10px;
        background: rgba(255, 40, 40, 0.9);
        color: white; font-size: 0.7rem; font-weight: 800;
        padding: 4px 8px; border-radius: 4px;
        text-transform: uppercase; letter-spacing: 1px;
        backdrop-filter: blur(4px); box-shadow: 0 4px 10px rgba(255,0,0,0.3);
    }

    /* FOOTER ICONS */
    .card-footer {
        padding: 10px;
        background: #121212;
        display: flex; justify-content: space-between; align-items: center;
    }
    .likes-count { font-weight: 700; font-size: 0.85rem; color: #fff; margin-left: 5px;}

    /* COMMENT SECTION UI */
    .comment-container { background: #000; padding: 10px; border-radius: 8px; margin-top: 15px; border-left: 2px solid #333; }
    .samay-handle { font-weight: 900; color: #fff; margin-right: 5px; font-size: 0.9rem; }
    .verified-tick { color: #0095f6; font-size: 0.8rem; }
    .comment-body { color: #e0e0e0; font-size: 0.95rem; line-height: 1.5; margin-top: 4px; }
    
    /* LOADING SKELETON */
    .skeleton { animation: pulse 1.5s infinite; background: #222; height: 20px; width: 100%; border-radius: 4px; }
    @keyframes pulse { 0% { opacity: 0.6; } 50% { opacity: 1; } 100% { opacity: 0.6; } }

</style>
""", unsafe_allow_html=True)

# --- ICONS ---
ICON_HEART_FILLED = """<svg width="20" height="20" viewBox="0 0 24 24" fill="#ed4956" stroke="none"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>"""
ICON_HEART_OUTLINE = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>"""
ICON_COMMENT = """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>"""

# --- CONFIG ---
SCOPES = ['https://www.googleapis.com/auth/drive']
PARENT_FOLDER_ID = st.secrets["general"]["folder_id"]

# --- DRIVE DB ---
@st.cache_resource
def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)

def load_votes_db():
    service = get_drive_service()
    try:
        results = service.files().list(q=f"'{PARENT_FOLDER_ID}' in parents and name='votes.json' and trashed=false", fields="files(id)").execute()
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
        results = service.files().list(q=f"'{PARENT_FOLDER_ID}' in parents and name='votes.json' and trashed=false", fields="files(id)").execute()
        files = results.get('files', [])
        json_str = json.dumps(votes_dict)
        media = MediaIoBaseUpload(io.BytesIO(json_str.encode('utf-8')), mimetype='application/json', resumable=True)
        if files: service.files().update(fileId=files[0]['id'], media_body=media).execute()
        else: service.files().create(body={'name': 'votes.json', 'parents': [PARENT_FOLDER_ID]}, media_body=media).execute()
    except: pass

# --- STATE INIT ---
if "image_votes" not in st.session_state: st.session_state.image_votes = load_votes_db()
if "roast_level" not in st.session_state: st.session_state.roast_level = {} # {file_id: int level}
if "visual_signals" not in st.session_state: st.session_state.visual_signals = {} # {file_id: string description}
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "audio_path" not in st.session_state: st.session_state.audio_path = None

# --- CORE FUNCTIONS ---
@st.cache_data(ttl=600)
def list_files():
    service = get_drive_service()
    results = service.files().list(q=f"'{PARENT_FOLDER_ID}' in parents and mimeType contains 'image/' and trashed=false", pageSize=100, fields="files(id, name, thumbnailLink)").execute()
    return results.get('files', [])

def download_image_bytes(file_id):
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    file_obj = io.BytesIO()
    downloader = MediaIoBaseDownload(file_obj, request)
    done = False
    while not done: _, done = downloader.next_chunk()
    return file_obj.getvalue()

async def generate_audio_imperfect(text):
    # Samay isn't a robot. He speaks fast, then pauses for effect.
    # We use random variations to break the "TTS Monotony"
    rates = ["+35%", "+30%", "+40%"]
    pitches = ["+2Hz", "+0Hz", "-2Hz"]
    
    selected_rate = random.choice(rates)
    selected_pitch = random.choice(pitches)
    
    communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural", rate=selected_rate, pitch=selected_pitch)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
        await communicate.save(tmp_file.name)
        return tmp_file.name

def run_tts(text):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(generate_audio_imperfect(text))

# --- THE PREDATOR PIPELINE ---

def stage_1_extract_signals(client, base64_image):
    """
    The Silent Observer.
    Analyzes the image for CRINGE, CONTEXT, and VIBE.
    User NEVER sees this.
    """
    prompt = """
    Analyze this image specifically for a roast comedian.
    Identify:
    1. The Setting (messy room, gym, bathroom, rented car?)
    2. The Pose (trying too hard, candid, awkward hand placement?)
    3. The Vibe (Wannabe influencer, sadboi, rich kid energy?)
    4. Specific Details (dirty mirror, fake watch, weird background object).
    Output only raw bullet points.
    """
    completion = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]}
        ],
        max_tokens=150
    )
    return completion.choices[0].message.content

def stage_2_generate_roast(client, base64_image, signals, level):
    """
    The Delivery System.
    Takes signals + Roast Level -> Generates Comedy.
    """
    
    # LEVEL DEFINITIONS
    intensity = "Playful teasing"
    if level == 2: intensity = "Personal attack, focus on insecurities"
    if level >= 3: intensity = "NUCLEAR. SAVAGE. DESTROY EGO."

    system_prompt = f"""
    You are Samay Raina. You are roasting a fan on a livestream.
    
    INPUT DATA (Visual Signals):
    {signals}
    
    CURRENT HEAT LEVEL: {level}/3 ({intensity})
    
    RULES:
    1. Language: Hinglish (Hindi written in English). Organic, flowy.
    2. NO "Hello" or "Welcome". Start attacking immediately.
    3. Use fillers like "Arre bhai...", "Matlab...", "Dekho...".
    4. Focus on the specific details found in the signals.
    5. Be conversationally rude. Not AI rude.
    6. Max 2-3 sentences. Punchy.
    """
    
    completion = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": "Roast this person based on the visual signals."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]}
        ],
        temperature=0.8 + (level * 0.1), # Higher temp for higher chaos
        max_tokens=200
    )
    return completion.choices[0].message.content

# --- MODAL CONTROLLER ---
@st.dialog("📸 VibeGram", width="large")
def open_post(file_id, file_name):
    # Retrieve current state
    current_level = st.session_state.roast_level.get(file_id, 0)
    
    col_img, col_interaction = st.columns([1.2, 1], gap="medium")
    
    with col_img:
        with st.spinner("Loading high-res..."):
            img_data = download_image_bytes(file_id)
            st.image(img_data, use_container_width=True)
            
            # --- DOUBLE TAP SIMULATION ---
            likes = st.session_state.image_votes.get(file_id, 0)
            if st.button(f"❤️ Like ({likes})", use_container_width=True):
                st.session_state.image_votes[file_id] = likes + 1
                save_votes_db(st.session_state.image_votes)
                st.rerun()

    with col_interaction:
        st.markdown("### The Roast Loop")
        
        # --- ESCALATION BUTTON ---
        btn_label = "🎤 Start Roast"
        if current_level == 1: btn_label = "🔥 Go Harder (Lvl 2)"
        if current_level >= 2: btn_label = "💀 DESTROY (Lvl 3)"
        
        if st.button(btn_label, type="primary", use_container_width=True):
            client = Groq(api_key=st.secrets["groq"]["api_key"])
            b64_img = base64.b64encode(img_data).decode('utf-8')
            
            # STAGE 1: Extract Signals (If not done yet)
            if file_id not in st.session_state.visual_signals:
                with st.status("👀 Samay is analyzing details...", expanded=False):
                    signals = stage_1_extract_signals(client, b64_img)
                    st.session_state.visual_signals[file_id] = signals
            
            # STAGE 2: Generate Roast
            new_level = min(current_level + 1, 3)
            st.session_state.roast_level[file_id] = new_level
            
            # Artificial Delay for anticipation (1.5s)
            with st.spinner("Thinking of a violation..."):
                time.sleep(1.0)
                roast_text = stage_2_generate_roast(
                    client, 
                    b64_img, 
                    st.session_state.visual_signals[file_id], 
                    new_level
                )
            
            # STAGE 3: Audio & History
            st.session_state.chat_history = [{"role": "assistant", "content": roast_text}]
            st.session_state.audio_path = run_tts(roast_text)
            st.rerun()

        st.divider()
        
        # COMMENT DISPLAY (INSTAGRAM STYLE)
        if st.session_state.chat_history:
            msg = st.session_state.chat_history[-1]["content"]
            st.markdown(f"""
            <div class="comment-container">
                <div style="display:flex; align-items:center;">
                    <span class="samay-handle">samay_raina_ai</span>
                    <span class="verified-tick">✓</span>
                </div>
                <div class="comment-body">{msg}</div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.session_state.audio_path:
                st.audio(st.session_state.audio_path, format="audio/mp3", autoplay=True)
                
            # Social Proof Fake
            st.caption(f"Liked by tanmaybhat and {random.randint(50, 500)} others")
        else:
            st.markdown("""
            <div style="color:#666; text-align:center; padding:20px;">
                <i>Tap the button to summon the roaster.<br>Warning: It gets meaner every click.</i>
            </div>
            """, unsafe_allow_html=True)


# --- FEED GENERATOR ---
def render_feed(files):
    html = ['<div class="masonry-wrapper">']
    for f in files:
        thumb = f['thumbnailLink'].replace('=s220', '=s800')
        votes = st.session_state.image_votes.get(f['id'], 0)
        
        # Trending Logic: Top 10% get a badge
        is_trending = False
        if files and votes > 0:
            top_threshold = sorted([st.session_state.image_votes.get(x['id'], 0) for x in files], reverse=True)[:3]
            if votes in top_threshold: is_trending = True
        
        badge_html = '<div class="trending-badge">🔥 TRENDING</div>' if is_trending else ''
        
        card = f"""
        <div class="insta-card">
            <a href='#' id='{f['id']}' style="text-decoration:none; color:inherit;">
                {badge_html}
                <img src="{thumb}" style="width:100%; display:block;">
                <div class="card-footer">
                    <div style="display:flex; align-items:center;">
                        {ICON_HEART_FILLED if votes > 0 else ICON_HEART_OUTLINE}
                        <span class="likes-count">{votes}</span>
                    </div>
                    {ICON_COMMENT}
                </div>
            </a>
        </div>
        """
        html.append(card)
    html.append('</div>')
    return "".join(html)

# --- MAIN EXECUTION ---
st.markdown("""
<div style="display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid #333; margin-bottom:20px;">
    <div style="font-family:'Inter',sans-serif; font-weight:900; font-size:1.5rem; letter-spacing:-1px;">VibeGram</div>
    <div style="background:#0095f6; padding:6px 14px; border-radius:4px; font-weight:700; font-size:0.9rem;">Upload</div>
</div>
""", unsafe_allow_html=True)

try:
    all_files = list_files()
    if not all_files:
        st.info("Feed empty. Upload photos to Drive.")
    else:
        # Sort: Trending first, then new
        all_files.sort(key=lambda x: st.session_state.image_votes.get(x['id'], 0), reverse=True)
        
        feed_html = render_feed(all_files)
        clicked_id = click_detector(feed_html)
        
        if clicked_id:
            # Reset state if clicking new image
            if "current_view" not in st.session_state or st.session_state.current_view != clicked_id:
                st.session_state.current_view = clicked_id
                st.session_state.chat_history = []
                st.session_state.audio_path = None
                # Don't reset roast level, we want to remember if we already roasted it!
            
            target = next((f for f in all_files if f['id'] == clicked_id), None)
            if target: open_post(clicked_id, target['name'])

except Exception as e:
    st.error(f"Server Error: {e}")
