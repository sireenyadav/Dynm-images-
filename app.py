import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# --- CONFIGURATION ---
# We use Streamlit Secrets to avoid hardcoding keys
# format: st.secrets["gcp_service_account"]
SCOPES = ['https://www.googleapis.com/auth/drive']
PARENT_FOLDER_ID = st.secrets["general"]["folder_id"]

def authenticate():
    """Authenticates using the secrets found in Streamlit Cloud."""
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return creds

def upload_file(file_obj, filename):
    """Uploads a file to the configured Google Drive folder."""
    creds = authenticate()
    service = build('drive', 'v3', credentials=creds)
    
    file_metadata = {
        'name': filename,
        'parents': [PARENT_FOLDER_ID]
    }
    
    media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type, resumable=True)
    
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()
    
    return file.get('id')

def list_files():
    """Lists all images in the specific Drive folder."""
    creds = authenticate()
    service = build('drive', 'v3', credentials=creds)
    
    # Query: Trash is false, matches parent folder, is an image
    query = f"'{PARENT_FOLDER_ID}' in parents and mimeType contains 'image/' and trashed = false"
    
    results = service.files().list(
        q=query, pageSize=20, fields="nextPageToken, files(id, name, webContentLink, thumbnailLink)"
    ).execute()
    
    return results.get('files', [])

# --- APP LAYOUT ---
st.set_page_config(page_title="Cloud Vibe Gallery", layout="wide")
st.title("☁️ Drive-Connected Gallery")

# 1. UPLOAD SECTION
with st.expander("Upload New Photo"):
    uploaded_file = st.file_uploader("Choose an image", type=['png', 'jpg', 'jpeg'])
    if uploaded_file is not None:
        if st.button("Upload to Drive"):
            with st.spinner("Uploading to Google Drive..."):
                file_id = upload_file(uploaded_file, uploaded_file.name)
                st.success("Uploaded! Refresh to see it.")
                st.balloons()

# 2. GALLERY SECTION
st.divider()
st.subheader("Live Feed")

# Load images (This might be slow if you have 100s of images, pagination helps)
try:
    files = list_files()
    
    if not files:
        st.info("No images found in the Drive folder yet.")
    else:
        # Create grid
        cols = st.columns(3)
        for idx, file in enumerate(files):
            col = cols[idx % 3]
            with col:
                # We use thumbnailLink for speed, or webContentLink for quality
                # Note: 'webContentLink' might force download depending on browser settings.
                # A trick is to use string replacement to get the viewable link.
                image_url = file['thumbnailLink'].replace('=s220', '=s1000') # Hack to get higher res
                
                st.image(image_url, caption=file['name'], use_container_width=True)

except Exception as e:
    st.error(f"Error connecting to Drive: {e}")
