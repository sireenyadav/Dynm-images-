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

# --- CUSTOM CSS (Global Styles) ---
# We inject some global CSS to hide standard Streamlit elements for a cleaner look
st.markdown("""
<style>
    /* Hide header and footer */
    header {visibility: hidden;}
    footer {visibility: hidden;}
    /* Remove padding for a full-screen feel */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 0rem;
        padding-left: 2rem;
        padding-right: 2rem;
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

@st.cache_data(ttl=3600) # Cache file list for 1 hour to speed up UI
def list_files():
    service = get_drive_service()
    query = f"'{PARENT_FOLDER_ID}' in parents and mimeType contains 'image/' and trashed = false"
    # Fetching webContentLink (high res) and thumbnailLink (low res)
    results = service.files().list(
        q=query, pageSize=50, 
        fields="files(id, name, thumbnailLink, webContentLink)"
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

    # Prepare messages with history
    messages = []
    # Add previous history (text only for context, to save bandwidth)
    for msg in chat_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    
    # Add current visual query
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": data_url}}
        ]
    })

    try:
        completion = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct", # 2026 Model
            messages=messages,
            temperature=0.6,
            max_tokens=1024,
            stream=True
        )
        return completion
    except Exception as e:
        return f"Error: {str(e)}"

# --- UI COMPONENTS ---

@st.dialog("✨ Visual Intelligence", width="large")
def show_image_dialog(file_id, file_name):
    """
    This runs inside a modal popup when an image is clicked.
    """
    # Initialize chat history for this specific image
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    
    # Layout: Image on top, Chat below (or side-by-side if wide)
    
    # 1. Load Image
    with st.spinner("Loading high-res..."):
        img_bytes = download_image_bytes(file_id)
        st.image(img_bytes, use_container_width=True)
        
    st.divider()
    
    # 2. Chat Interface
    st.subheader("Chat with this image")
    
    # Display history
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            
    # Input
    if prompt := st.chat_input("Ask Groq... (e.g. 'Describe the vibe')"):
        # Add user message
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)
            
        # Get response
        with st.chat_message("assistant"):
            stream = analyze_with_groq(img_bytes, prompt, st.session_state.chat_history[:-1])
            response_text = st.write_stream(stream)
            
        # Append assistant response to history
        st.session_state.chat_history.append({"role": "assistant", "content": response_text})


# --- MAIN MASONRY LAYOUT GENERATOR ---
def generate_html_grid(files):
    """
    Generates a Tailwind CSS Masonry Layout HTML string.
    """
    html_blocks = []
    
    # Tailwind + Custom Styles injected directly into the component
    # We use 'columns-2 md:columns-3 lg:columns-4' for the masonry effect
    header = """
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .masonry-item {
            break-inside: avoid;
            margin-bottom: 1.5rem;
        }
        .img-hover:hover {
            transform: scale(1.02);
            filter: brightness(1.1);
        }
    </style>
    <div class="p-4 columns-2 md:columns-3 lg:columns-4 gap-6 space-y-6 mx-auto max-w-7xl">
    """
    
    html_blocks.append(header)
    
    for file in files:
        # Hack: Drive thumbnail links are small (s220). We replace to get s600 for better grid quality
        thumb_url = file['thumbnailLink'].replace('=s220', '=s600')
        
        # Each image is an anchor tag with a specific ID
        # The ID is returned by click_detector when clicked
        card = f"""
        <div class="masonry-item relative group overflow-hidden rounded-2xl shadow-lg cursor-pointer transition-all duration-300 hover:shadow-2xl">
            <a href='#' id='{file['id']}'>
                <img src="{thumb_url}" class="w-full h-auto object-cover img-hover transition-transform duration-500 ease-in-out" alt="{file['name']}">
                <div class="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-4 opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                    <p class="text-white text-sm font-medium truncate">{file['name']}</p>
                </div>
            </a>
        </div>
        """
        html_blocks.append(card)
        
    html_blocks.append("</div>")
    return "".join(html_blocks)


# --- APP EXECUTION ---
st.title("Search Visuals")

# 1. Fetch Files
try:
    files = list_files()
    if not files:
        st.warning("No images found in Drive folder.")
    else:
        # 2. Generate HTML Grid
        html_content = generate_html_grid(files)
        
        # 3. Render Click Detector
        # This renders the HTML and waits for a click. 
        # When clicked, it returns the ID of the <a> tag.
        clicked_id = click_detector(html_content)
        
        # 4. Handle Click -> Open Dialog
        if clicked_id:
            # Find the file name for the clicked ID
            selected_file = next((f for f in files if f['id'] == clicked_id), None)
            if selected_file:
                # We use a session state check to prevent re-opening if already open logic interferes
                show_image_dialog(clicked_id, selected_file['name'])
                
except Exception as e:
    st.error(f"System Error: {e}")
