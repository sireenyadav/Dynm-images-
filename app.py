import streamlit as st
import os

# Page Config for the aesthetic
st.set_page_config(page_title="My Vibe Gallery", layout="wide")

st.title("📸 Dynamic Photo Gallery")
st.markdown("### A collection of moments")

# Path to your images folder in the repo
IMAGE_FOLDER = 'photos' 

# Check if folder exists
if not os.path.exists(IMAGE_FOLDER):
    st.error(f"Folder '{IMAGE_FOLDER}' not found. Please create it and add images!")
else:
    # Get all image files
    images = [f for f in os.listdir(IMAGE_FOLDER) if f.endswith(('png', 'jpg', 'jpeg', 'webp'))]
    
    if not images:
        st.warning("No images found in the folder.")
    else:
        # Create a dynamic grid
        cols = st.columns(3) # 3 columns for a clean look
        
        for idx, image_file in enumerate(images):
            # Cycle through columns
            col = cols[idx % 3]
            
            # Display image with a caption
            with col:
                st.image(
                    os.path.join(IMAGE_FOLDER, image_file), 
                    use_container_width=True, # Responsive sizing
                    caption=image_file
                )

