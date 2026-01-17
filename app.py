import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from groq import Groq
from st_click_detector import click_detector
import io
import base64

# --- PAGE CONFIG ---
st.set_page_config(page_title="Vibe Gallery", layout="wide", page_icon="✨")

# --- CUSTOM CSS ---
st.markdown("""
<style>
    header {visibility: hidden;}
    footer {visibility: hidden;}
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    /* Stylish instruction text */
    .instruction-text {
        text-align: center;
        color: #888;
        font-size: 1.1rem;
        margin-bottom: 2rem;
        font-family: sans-serif;
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0% { opacity: 0.6; }
        50% { opacity: 1; }
        100% { opacity: 0.6; }
    }
</style>
""", unsafe_allow_html=True)

# --- CONFIG & SECRETS ---
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
PARENT_FOLDER_ID = st.secrets["general"]["folder_id"]

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
        q=query, pageSize=50, 
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
        status, done = downloader.next_chunk()
    return file_obj.getvalue()

def analyze_with_groq(image_bytes, user_prompt, chat_history):
    client = Groq(api_key=st.secrets["groq"]["api_key"])
    
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    data_url = f"data:image/jpeg;base64,{base64_image}"

    messages = []
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
            temperature=0.6,
            max_tokens=1024,
            stream=True
        )
        
        # FIX: We yield only the content string, not the whole object
        for chunk in completion:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
                
    except Exception as e:
        yield f"Error: {str(e)}"

# --- UI COMPONENTS ---

@st.dialog("✨ Visual Intelligence", width="large")
def show_image_dialog(file_id, file_name):
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    
    # 1. Load Image
    with st.spinner("Analyzing pixels..."):
        img_bytes = download_image_bytes(file_id)
        st.image(img_bytes, use_container_width=True)
        
    st.divider()
    
    # 2. Chat Interface
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            
    if prompt := st.chat_input("Ask Groq..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)
            
        with st.chat_message("assistant"):
            # Stream the response correctly now
            response_generator = analyze_with_groq(img_bytes, prompt, st.session_state.chat_history[:-1])
            response_text = st.write_stream(response_generator)
            
        st.session_state.chat_history.append({"role": "assistant", "content": response_text})


def generate_html_grid(files):
    html_blocks = []
    
    # Added "cursor-pointer" and hover effects to make it obvious these are clickable
    header = """
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .masonry-item { break-inside: avoid; margin-bottom: 1.5rem; }
    </style>
    <div class="p-4 columns-2 md:columns-3 lg:columns-4 gap-6 space-y-6 mx-auto max-w-7xl">
    """
    html_blocks.append(header)
    
    for file in files:
        thumb_url = file['thumbnailLink'].replace('=s220', '=s600')
        card = f"""
        <div class="masonry-item relative group overflow-hidden rounded-2xl shadow-lg cursor-pointer transition-all duration-300 hover:shadow-2xl hover:-translate-y-1">
            <a href='#' id='{file['id']}'>
                <img src="{thumb_url}" class="w-full h-auto object-cover transition-transform duration-500 group-hover:scale-105" alt="{file['name']}">
                <div class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex items-center justify-center">
                    <p class="text-white font-semibold text-lg tracking-wide">✨ Analyze Vibe</p>
                </div>
            </a>
        </div>
        """
        html_blocks.append(card)
        
    html_blocks.append("</div>")
    return "".join(html_blocks)


# --- MAIN APP ---
st.title("Search Visuals")

# INSTRUCTION TEXT
st.markdown('<div class="instruction-text">Tap any image to extract its vibe & code</div>', unsafe_allow_html=True)

try:
    files = list_files()
    if not files:
        st.warning("No images found in Drive folder.")
    else:
        html_content = generate_html_grid(files)
        clicked_id = click_detector(html_content)
        
        if clicked_id:
            selected_file = next((f for f in files if f['id'] == clicked_id), None)
            if selected_file:
                show_image_dialog(clicked_id, selected_file['name'])
                
except Exception as e:
    st.error(f"System Error: {e}")
