import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from groq import Groq
from st_click_detector import click_detector
import edge_tts
import asyncio
import io
import base64
import random
import tempfile
import os

# --- PAGE CONFIG ---
st.set_page_config(page_title="Vibe Gallery 🔥", layout="wide", page_icon="💀")

# --- CUSTOM CSS ---
st.markdown("""
<style>
    header {visibility: hidden;}
    footer {visibility: hidden;}
    .block-container { padding-top: 1rem; padding-bottom: 5rem; }
    
    /* Dark Vibe Title */
    .main-title {
        text-align: center; font-size: 3.5rem; font-weight: 800;
        background: linear-gradient(45deg, #ff0000, #2b2b2b, #ff0000);
        background-size: 200% auto;
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        animation: gradient 3s linear infinite;
        margin-bottom: 0rem;
    }
    @keyframes gradient { 0% {background-position: 0% 50%;} 50% {background-position: 100% 50%;} 100% {background-position: 0% 50%;} }
    
    .tagline { text-align: center; color: #888; font-size: 1.1rem; margin-bottom: 2rem; font-style: italic;}
    
    /* Stats & Leaderboard */
    .vote-badge { position: absolute; top: 10px; right: 10px; background: rgba(0,0,0,0.8); color: #ff512f; padding: 4px 8px; border-radius: 8px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- CONFIG & SECRETS ---
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
PARENT_FOLDER_ID = st.secrets["general"]["folder_id"]

# --- SESSION STATE ---
if "stats" not in st.session_state:
    st.session_state.stats = {"roasts": 0, "voice_generations": 0}
if "image_votes" not in st.session_state:
    st.session_state.image_votes = {} 
if "roast_mode" not in st.session_state:
    st.session_state.roast_mode = False
if "voice_mode" not in st.session_state:
    st.session_state.voice_mode = False
if "favorite_images" not in st.session_state:
    st.session_state.favorite_images = []
if "trigger_dialog_id" not in st.session_state:
    st.session_state.trigger_dialog_id = None

# --- CONSTANTS ---
VIBE_PROMPTS = {
    # UPDATED PROMPT FOR SAMAY RAINA STYLE
    "🔥 Roast": "Roast this image in informal Hindi (mix of Hindi/English). Be sarcastic, dark, and brutal like Samay Raina. Keep it short (2 sentences max). Use words like 'Bhai', 'Ye kya hai', etc. Make fun of the aesthetic.",
    "😂 Meme": "Create a viral meme caption for this. Short and punchy.",
    "🕵️ Detective": "Analyze the background details to deduce where this photo was taken.",
    "🔮 Future": "Predict the future of the person or object in this photo.",
    "🎵 Song": "What song matches this vibe? Give me artist and title.",
    "🥒 Pickle": "Describe this image but relate everything to pickles."
}

# --- BACKEND FUNCTIONS ---

@st.cache_resource
def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)

@st.cache_data(ttl=3600)
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
    while not done:
        status, done = downloader.next_chunk()
    return file_obj.getvalue()

# --- TTS FUNCTION (UPDATED FOR HINDI) ---
async def generate_speech_async(text, voice):
    communicate = edge_tts.Communicate(text, voice)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
        await communicate.save(tmp_file.name)
        return tmp_file.name

def text_to_speech(text, is_hindi=False):
    """Selects the correct voice accent"""
    try:
        # If roasting (Hindi), use Madhur (Male Hindi). If normal, use Guy (US Male).
        voice = "hi-IN-MadhurNeural" if is_hindi else "en-US-GuyNeural"
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        audio_path = loop.run_until_complete(generate_speech_async(text, voice))
        return audio_path
    except Exception as e:
        return None

# --- GROQ ANALYSIS (SAMAY RAINA PERSONA) ---
def analyze_with_groq(image_bytes, user_prompt, chat_history, roast_mode=False):
    client = Groq(api_key=st.secrets["groq"]["api_key"])
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    data_url = f"data:image/jpeg;base64,{base64_image}"

    # Default System Prompt
    system_content = "You are a helpful, witty AI assistant."
    
    # SAMAY RAINA PERSONA INJECTION
    if roast_mode:
        system_content = (
            "You are a savage Indian standup comedian (like Samay Raina style). "
            "Speak in 'Hinglish' (Hindi written in English script or Devanagari). "
            "Be dark, sarcastic, deadpan, and brutally honest. "
            "Do not be polite. Use slang. Keep it short and insulting but funny."
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
            temperature=0.8 if roast_mode else 0.6,
            max_tokens=800,
            stream=True
        )
        for chunk in completion:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        yield f"Error: {str(e)}"

# --- UI COMPONENTS ---

@st.dialog("✨ Vibe Check Studio", width="large")
def show_image_dialog(file_id, file_name):
    if "current_image_id" not in st.session_state or st.session_state.current_image_id != file_id:
        st.session_state.current_image_id = file_id
        st.session_state.chat_history = []
        st.session_state.current_audio_file = None 

    col_img, col_chat = st.columns([1.2, 1])
    
    with col_img:
        with st.spinner("Loading pixels..."):
            img_bytes = download_image_bytes(file_id)
            st.image(img_bytes, use_container_width=True)
            
            # Voting
            st.markdown("### 🔥 Rate the Burn")
            vote = st.feedback("stars", key=f"vote_{file_id}")
            if vote is not None:
                if file_id not in st.session_state.image_votes:
                    st.session_state.image_votes[file_id] = 0
                st.session_state.image_votes[file_id] += (vote + 1)
                st.caption(f"Score: {st.session_state.image_votes[file_id]}")

    with col_chat:
        # Toggles
        t1, t2, t3 = st.columns(3)
        with t1:
            is_fav = file_id in st.session_state.favorite_images
            if st.button("💛 Fav" if is_fav else "⭐ Fav"):
                if is_fav: st.session_state.favorite_images.remove(file_id)
                else: st.session_state.favorite_images.append(file_id)
                st.rerun()
        with t2:
            st.session_state.roast_mode = st.toggle("💀 Roast", value=st.session_state.roast_mode)
        with t3:
            st.session_state.voice_mode = st.toggle("🔊 Voice", value=st.session_state.voice_mode)

        # Quick Prompts
        st.divider()
        st.caption("Choose your fate:")
        q_cols = st.columns(3)
        selected_prompt = None
        for idx, (btn_text, prompt_text) in enumerate(VIBE_PROMPTS.items()):
            with q_cols[idx % 3]:
                if st.button(btn_text, key=f"quick_{idx}", use_container_width=True):
                    selected_prompt = prompt_text

        # Chat Area
        chat_container = st.container(height=350)
        with chat_container:
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])

        user_input = st.chat_input("Type something...")
        final_prompt = selected_prompt if selected_prompt else user_input
        
        if final_prompt:
            st.session_state.stats["roasts"] += 1
            st.session_state.chat_history.append({"role": "user", "content": final_prompt})
            
            with chat_container:
                 with st.chat_message("user"):
                    st.write(final_prompt)
                 
                 with st.chat_message("assistant"):
                    response_gen = analyze_with_groq(
                        img_bytes, final_prompt, 
                        st.session_state.chat_history[:-1], 
                        st.session_state.roast_mode
                    )
                    full_response = st.write_stream(response_gen)
            
            st.session_state.chat_history.append({"role": "assistant", "content": full_response})
            
            # AUDIO GENERATION
            if st.session_state.voice_mode:
                with st.spinner("🎙️ Generating Voice..."):
                    st.session_state.stats["voice_generations"] += 1
                    # Pass roast_mode to select Hindi voice if needed
                    audio_file = text_to_speech(full_response, is_hindi=st.session_state.roast_mode)
                    st.session_state.current_audio_file = audio_file
                    st.rerun()

        if st.session_state.current_audio_file:
            st.audio(st.session_state.current_audio_file, format="audio/mp3", autoplay=True)

def generate_html_grid(files):
    html_blocks = []
    header = """
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .masonry-item { break-inside: avoid; margin-bottom: 1.5rem; }
    </style>
    <div class="p-2 columns-2 md:columns-3 lg:columns-4 gap-4 mx-auto max-w-7xl">
    """
    html_blocks.append(header)
    
    for file in files:
        thumb_url = file['thumbnailLink'].replace('=s220', '=s600')
        votes = st.session_state.image_votes.get(file['id'], 0)
        vote_html = f'<div class="vote-badge">💀 {votes}</div>' if votes > 0 else ''
        
        card = f"""
        <div class="masonry-item relative group rounded-xl overflow-hidden shadow-md hover:shadow-2xl transition-all duration-300">
            <a href='#' id='{file['id']}'>
                {vote_html}
                <img src="{thumb_url}" class="w-full h-auto object-cover transform group-hover:scale-105 transition-transform duration-500" alt="img">
                <div class="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex items-center justify-center">
                    <span class="text-white font-bold border border-white px-4 py-2 rounded-full">💀 Roast Me</span>
                </div>
            </a>
        </div>
        """
        html_blocks.append(card)
    html_blocks.append("</div>")
    return "".join(html_blocks)

# --- MAIN APP ---
st.markdown('<h1 class="main-title">Roast Gallery 💀</h1>', unsafe_allow_html=True)
st.markdown('<p class="tagline">Samay Raina Mode: ON</p>', unsafe_allow_html=True)

tab_gallery, tab_leaderboard = st.tabs(["🖼️ Gallery", "🏆 Hall of Shame"])

try:
    all_files = list_files()
    
    with tab_gallery:
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            filter_opt = st.selectbox("📂 View", ["All Images", "⭐ Favorites Only", "💀 Most Roasted"], label_visibility="collapsed")
        with c2:
            if st.button("🎲 Random Victim", use_container_width=True):
                if all_files:
                    rando = random.choice(all_files)
                    st.session_state.trigger_dialog_id = rando['id']
                    st.rerun()
        
        display_files = all_files
        if filter_opt == "⭐ Favorites Only":
            display_files = [f for f in all_files if f['id'] in st.session_state.favorite_images]
        elif filter_opt == "💀 Most Roasted":
            display_files = sorted(all_files, key=lambda x: st.session_state.image_votes.get(x['id'], 0), reverse=True)

        if display_files:
            html = generate_html_grid(display_files)
            clicked_id = click_detector(html)
            
            final_id = clicked_id if clicked_id else st.session_state.trigger_dialog_id
            if final_id:
                target = next((f for f in all_files if f['id'] == final_id), None)
                if target:
                    st.session_state.trigger_dialog_id = None
                    show_image_dialog(final_id, target['name'])
        else:
            st.info("No victims found.")

    with tab_leaderboard:
        st.markdown("### 🏆 Hall of Shame")
        if st.session_state.image_votes:
            sorted_votes = sorted(st.session_state.image_votes.items(), key=lambda x: x[1], reverse=True)
            for file_id, score in sorted_votes[:5]:
                fname = next((f['name'] for f in all_files if f['id'] == file_id), "Unknown")
                st.markdown(f"**{fname}** — Roast Score: {score} 💀")
        else:
            st.caption("No one has been roasted enough yet.")

except Exception as e:
    st.error(f"App Error: {e}")
