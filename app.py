import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from groq import Groq
import io
import base64

# --- CONFIG ---
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
PARENT_FOLDER_ID = st.secrets["general"]["folder_id"]

# --- GOOGLE DRIVE FUNCTIONS ---
@st.cache_resource
def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)

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

# --- GROQ FUNCTIONS ---
def analyze_with_groq(image_bytes, user_prompt):
    client = Groq(
        api_key=st.secrets["groq"]["api_key"],
    )
    
    # Convert image to Base64
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    data_url = f"data:image/jpeg;base64,{base64_image}"

    try:
        completion = client.chat.completions.create(
            model="llama-3.2-11b-vision-preview", # Fast and capable vision model
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url
                            }
                        }
                    ]
                }
            ],
            temperature=0.5,
            max_tokens=1024,
            stream=True,
            stop=None,
        )
        return completion
    except Exception as e:
        return f"Error talking to Groq: {str(e)}"

# --- APP LAYOUT ---
st.set_page_config(page_title="GroqSpeed Gallery", layout="wide", page_icon="⚡")

# Initialize session state
if 'selected_image' not in st.session_state:
    st.session_state.selected_image = None
if 'selected_image_name' not in st.session_state:
    st.session_state.selected_image_name = None

st.title("⚡ Groq Vision Gallery")

# Layout: 40% Gallery | 60% Viewer
col_gallery, col_viewer = st.columns([2, 3])

with col_gallery:
    st.subheader("Drive Photos")
    files = list_files()
    
    if not files:
        st.info("Drive folder is empty.")
    else:
        # 3-Column Grid for thumbnails
        grid_cols = st.columns(3)
        for idx, file in enumerate(files):
            with grid_cols[idx % 3]:
                st.image(file['thumbnailLink'], use_container_width=True)
                # Unique key for every button is critical
                if st.button("Pick", key=f"btn_{file['id']}"):
                    st.session_state.selected_image = file['id']
                    st.session_state.selected_image_name = file['name']
                    st.rerun()

with col_viewer:
    if st.session_state.selected_image:
        st.subheader(f"Analyzing: {st.session_state.selected_image_name}")
        
        # 1. Download full resolution
        with st.spinner("Downloading from Drive..."):
            img_bytes = download_image_bytes(st.session_state.selected_image)
            st.image(img_bytes, use_container_width=True)
            
        # 2. Chat Interface
        st.divider()
        prompt = st.chat_input("Ask Groq about this image...")
        
        if prompt:
            st.markdown(f"**You:** {prompt}")
            st.markdown("**Groq:**")
            
            # Stream the response
            stream = analyze_with_groq(img_bytes, prompt)
            
            if isinstance(stream, str):
                st.error(stream)
            else:
                # Iterate through the stream generator
                st.write_stream(stream)
    else:
        st.info("👈 Select an image from the gallery to start.")
