import streamlit as st
import requests
import json
import os
import time
from pathlib import Path
import tempfile
import base64
import pandas as pd
import zipfile
import io

st.set_page_config(page_title="Yoliday-DocHub", layout="wide")

# App title and description
st.title("Yoliday-DocHub")
st.markdown("""
This application allows you to:
1. Backup and restore Meilisearch indexes
2. Embed documents (text or PDF from S3) 
3. Ask questions using the embedded documents
""")

# Create tabs for different functionalities
tab1, tab2, tab3, tab4 = st.tabs(["Meilisearch Backup", "Meilisearch Restore", "Embed Documents", "Ask Questions"])

# Helper functions for Meilisearch operations
def get_meilisearch_headers(api_key):
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

def create_zip_download_link(data, filename):
    """Generate a download link for the backup data as a zip file"""
    # Create a zip file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Add each index as a separate JSON file
        for index_uid, index_data in data.items():
            # Convert index data to JSON
            json_str = json.dumps(index_data, indent=2)
            zip_file.writestr(f"{index_uid}.json", json_str)
        
        # Add a summary JSON with all indexes
        summary_json = json.dumps(data, indent=2)
        zip_file.writestr("all_indexes.json", summary_json)
    
    # Create download link
    zip_buffer.seek(0)
    b64 = base64.b64encode(zip_buffer.read()).decode()
    href = f'<a href="data:application/zip;base64,{b64}" download="{filename}">Download {filename}</a>'
    return href

# Tab 1: Meilisearch Backup
with tab1:
    st.header("Backup Meilisearch Indexes")
    
    # Simple configuration inputs
    meilisearch_url = st.text_input("Meilisearch URL", "https://searchek.dev.eklavya.me", key="backup_url")
    meilisearch_api_key = st.text_input("Meilisearch API Key", "Eklavya@2023", type="password", key="backup_key")
    
    # Store indexes in session state to prevent reloading issues
    if 'indexes_loaded' not in st.session_state:
        st.session_state.indexes_loaded = False
        st.session_state.index_options = []
    
    # Button to fetch indexes
    if not st.session_state.indexes_loaded:
        if st.button("Get All Indexes"):
            with st.spinner("Fetching indexes..."):
                try:
                    response = requests.get(f"{meilisearch_url}/indexes", headers=get_meilisearch_headers(meilisearch_api_key))
                    if response.status_code == 200:
                        indexes = response.json().get("results", [])
                        if indexes:
                            st.session_state.index_options = [index["uid"] for index in indexes]
                            st.session_state.indexes_loaded = True
                            st.success(f"Found {len(indexes)} indexes")
                        else:
                            st.info("No indexes found")
                    else:
                        st.error(f"Failed to get indexes: {response.text}")
                except Exception as e:
                    st.error(f"Error: {str(e)}")
    else:
        # Display a message that indexes are loaded
        st.success(f"Found {len(st.session_state.index_options)} indexes")
        
        # Button to reload indexes if needed
        if st.button("Reload Indexes"):
            st.session_state.indexes_loaded = False
            st.rerun()
    
    # If indexes are loaded, show the multiselect and backup button
    if st.session_state.indexes_loaded:
        # Select all indexes by default
        selected_indexes = st.multiselect("Select indexes to backup", 
                                          st.session_state.index_options, 
                                          default=st.session_state.index_options)
        
        # Separate button for backup action
        if selected_indexes and st.button("Backup Selected Indexes"):
            backup_data = {}
            progress_bar = st.progress(0)
            
            for i, index_uid in enumerate(selected_indexes):
                st.write(f"Processing index: {index_uid}")
                index_data = {}
                
                # Get index settings
                settings_response = requests.get(
                    f"{meilisearch_url}/indexes/{index_uid}/settings", 
                    headers=get_meilisearch_headers(meilisearch_api_key)
                )
                if settings_response.status_code == 200:
                    index_data["settings"] = settings_response.json()
                
                # Get index stats
                stats_response = requests.get(
                    f"{meilisearch_url}/indexes/{index_uid}/stats", 
                    headers=get_meilisearch_headers(meilisearch_api_key)
                )
                if stats_response.status_code == 200:
                    stats = stats_response.json()
                    index_data["stats"] = stats
                    total_docs = stats.get("numberOfDocuments", 0)
                    st.write(f"Index {index_uid} has {total_docs} documents total")
                
                # Get documents
                offset = 0
                limit = 1000
                all_documents = []
                
                while True:
                    docs_response = requests.get(
                        f"{meilisearch_url}/indexes/{index_uid}/documents",
                        params={"offset": offset, "limit": limit},
                        headers=get_meilisearch_headers(meilisearch_api_key)
                    )
                    
                    if docs_response.status_code != 200:
                        st.error(f"Failed to get documents: {docs_response.text}")
                        break
                    
                    try:
                        documents = docs_response.json()
                        if isinstance(documents, dict) and "results" in documents:
                            documents = documents["results"]
                        elif not isinstance(documents, list):
                            st.error(f"Unexpected response format")
                            break
                    except json.JSONDecodeError:
                        st.error(f"Failed to parse JSON response")
                        break
                    
                    if not documents:
                        break
                    
                    all_documents.extend(documents)
                    st.write(f"Retrieved {len(documents)} documents, total so far: {len(all_documents)}")
                    
                    if len(documents) < limit:
                        break
                    
                    offset += limit
                
                index_data["documents"] = all_documents
                backup_data[index_uid] = index_data
                
                # Update progress
                progress_bar.progress((i + 1) / len(selected_indexes))
            
            # Offer download as a zip file
            st.markdown(create_zip_download_link(backup_data, "meilisearch_backup.zip"), 
                        unsafe_allow_html=True)

# Tab 2: Meilisearch Restore
with tab2:
    st.header("Restore Meilisearch Indexes")
    
    # Simple configuration inputs
    meilisearch_url = st.text_input("Meilisearch URL", "https://searchek.dev.eklavya.me", key="restore_url")
    meilisearch_api_key = st.text_input("Meilisearch API Key", "Eklavya@2023", type="password", key="restore_key")
    
    # Store restore data in session state
    if 'restore_data_loaded' not in st.session_state:
        st.session_state.restore_data_loaded = False
        st.session_state.backup_data = {}
        st.session_state.restore_index_options = []
    
    uploaded_file = st.file_uploader("Upload backup file", type=["json", "zip"])
    
    # Process the uploaded file
    if uploaded_file is not None:
        try:
            # Only process the file if it hasn't been processed yet or if it's a new file
            file_name = uploaded_file.name
            if not st.session_state.restore_data_loaded or 'last_uploaded_file' not in st.session_state or st.session_state.last_uploaded_file != file_name:
                st.session_state.last_uploaded_file = file_name
                backup_data = {}
                
                # Handle different file types
                if uploaded_file.name.endswith('.zip'):
                    with zipfile.ZipFile(uploaded_file) as z:
                        # Check if all_indexes.json exists
                        if "all_indexes.json" in z.namelist():
                            with z.open("all_indexes.json") as f:
                                backup_data = json.load(f)
                        else:
                            # Process individual JSON files
                            for file_name in z.namelist():
                                if file_name.endswith('.json'):
                                    with z.open(file_name) as f:
                                        index_uid = file_name.replace('.json', '')
                                        backup_data[index_uid] = json.load(f)
                else:
                    # Handle regular JSON file
                    backup_data = json.load(uploaded_file)
                
                # Update session state with the processed data
                st.session_state.backup_data = backup_data
                st.session_state.restore_index_options = list(backup_data.keys())
                st.session_state.restore_data_loaded = True
            
            # Display the restore options
            index_options = st.session_state.restore_index_options
            
            if index_options:
                st.success(f"Backup file contains {len(index_options)} indexes")
                
                # Select all indexes by default
                selected_indexes = st.multiselect("Select indexes to restore", index_options, default=index_options)
                
                # Separate button for restore action
                if selected_indexes and st.button("Restore Selected Indexes"):
                    progress_bar = st.progress(0)
                    
                    for i, index_uid in enumerate(selected_indexes):
                        st.write(f"Restoring index: {index_uid}")
                        index_data = st.session_state.backup_data[index_uid]
                        
                        # Check if index exists
                        check_response = requests.get(
                            f"{meilisearch_url}/indexes/{index_uid}", 
                            headers=get_meilisearch_headers(meilisearch_api_key)
                        )
                        
                        # Create index if it doesn't exist
                        if check_response.status_code == 404:
                            # Get primary key from stats or first document
                            primary_key = None
                            if "stats" in index_data and "primaryKey" in index_data["stats"]:
                                primary_key = index_data["stats"]["primaryKey"]
                            elif index_data.get("documents") and index_data["documents"]:
                                # Try to guess primary key from first document
                                first_doc = index_data["documents"][0]
                                for key in ["id", "docId", "documentId"]:
                                    if key in first_doc:
                                        primary_key = key
                                        break
                            
                            create_data = {"uid": index_uid}
                            if primary_key:
                                create_data["primaryKey"] = primary_key
                                
                            create_response = requests.post(
                                f"{meilisearch_url}/indexes",
                                headers=get_meilisearch_headers(meilisearch_api_key),
                                json=create_data
                            )
                            
                            if create_response.status_code not in (201, 200):
                                st.error(f"Failed to create index {index_uid}: {create_response.text}")
                                continue
                                
                            st.write(f"Created index {index_uid}")
                            time.sleep(1)
                        else:
                            st.write(f"Index {index_uid} already exists")
                        
                        # Restore settings
                        if "settings" in index_data:
                            settings = index_data["settings"]
                            
                            setting_types = [
                                "displayedAttributes", 
                                "filterableAttributes",
                                "sortableAttributes", 
                                "rankingRules", 
                                "stopWords",
                                "synonyms", 
                                "distinctAttribute"
                            ]
                            
                            for setting_type in setting_types:
                                if setting_type in settings and settings[setting_type]:
                                    settings_response = requests.put(
                                        f"{meilisearch_url}/indexes/{index_uid}/settings/{setting_type}",
                                        headers=get_meilisearch_headers(meilisearch_api_key),
                                        json=settings[setting_type]
                                    )
                                    
                                    if settings_response.status_code in (200, 202):
                                        st.write(f"Applied setting {setting_type}")
                                    else:
                                        st.error(f"Failed to apply setting {setting_type}: {settings_response.text}")
                        
                        # Restore documents
                        if "documents" in index_data and index_data["documents"]:
                            documents = index_data["documents"]
                            
                            # Add documents in batches
                            batch_size = 1000
                            for j in range(0, len(documents), batch_size):
                                batch = documents[j:j + batch_size]
                                st.write(f"Adding batch of {len(batch)} documents ({j+1}-{j+len(batch)} of {len(documents)})")
                                
                                docs_response = requests.post(
                                    f"{meilisearch_url}/indexes/{index_uid}/documents",
                                    headers=get_meilisearch_headers(meilisearch_api_key),
                                    json=batch
                                )
                                
                                if docs_response.status_code in (202, 201, 200):
                                    st.write(f"Successfully added batch")
                                else:
                                    st.error(f"Failed to add documents: {docs_response.text}")
                                    
                                time.sleep(1)
                        else:
                            st.write(f"No documents found for index {index_uid}")
                        
                        # Update progress
                        progress_bar.progress((i + 1) / len(selected_indexes))
                    
                    st.success("Restore completed successfully!")
            else:
                st.error("Backup file does not contain any indexes")
        except json.JSONDecodeError:
            st.error("Invalid JSON file")
        except zipfile.BadZipFile:
            st.error("Invalid ZIP file")
        except Exception as e:
            st.error(f"Error: {str(e)}")

# Tab 3: Embed Documents
with tab3:
    st.header("Embed Documents")
    
    # Simple URL and password inputs
    embed_api_url = st.text_input("Embedding API URL", "https://embedly.dev.yoliday.in", key="embed_api_url")
    embed_api_password = st.text_input("API Password", "Yoliday@2023", type="password", key="embed_api_password")
    
    # Select embedding type
    embed_type = st.radio("What do you want to embed?", ["Text Document", "PDF from S3"])
    
    # Common fields
    index_name = st.text_input("Index Name", "knowledge_base")
    
    if embed_type == "Text Document":
        document_name = st.text_input("Document Name", "document_1")
        text_content = st.text_area("Document Text", height=300)
        
        if st.button("Embed Text") and text_content and document_name:
            with st.spinner("Embedding document..."):
                try:
                    payload = {
                        "index_name": index_name,
                        "text": text_content,
                        "document_name": document_name
                    }
                    
                    # Add auth headers
                    headers = {"Content-Type": "application/json"}
                    headers["Authorization"] = "Basic " + base64.b64encode(f"user:{embed_api_password}".encode()).decode()
                    
                    response = requests.post(
                        f"{embed_api_url}/embed",
                        headers=headers,
                        json=payload
                    )
                    
                    if response.status_code in (200, 201):
                        st.success("Document embedded successfully!")
                        st.json(response.json())
                    else:
                        st.error(f"Failed to embed document: {response.text}")
                except Exception as e:
                    st.error(f"Error: {str(e)}")
    
    else:  # PDF from S3
        s3_url = st.text_input("S3 URL", "https://your-bucket.s3.amazonaws.com/file.pdf")
        
        # Metadata fields
        st.subheader("Metadata (Optional)")
        col1, col2 = st.columns(2)
        
        with col1:
            author = st.text_input("Author")
            year = st.text_input("Year")
            
        with col2:
            category = st.text_input("Category")
            custom_key = st.text_input("Custom Field Name")
            custom_value = st.text_input("Custom Field Value")
        
        if st.button("Embed PDF") and s3_url:
            with st.spinner("Embedding PDF from S3..."):
                try:
                    # Prepare metadata
                    metadata = {}
                    if author:
                        metadata["author"] = author
                    if year:
                        metadata["year"] = year
                    if category:
                        metadata["category"] = category
                    if custom_key and custom_value:
                        metadata[custom_key] = custom_value
                    
                    payload = {
                        "index_name": index_name,
                        "s3_url": s3_url
                    }
                    
                    if metadata:
                        payload["metadata"] = metadata
                    
                    # Add auth headers
                    headers = {"Content-Type": "application/json"}
                    headers["Authorization"] = "Basic " + base64.b64encode(f"user:{embed_api_password}".encode()).decode()
                    
                    response = requests.post(
                        f"{embed_api_url}/embed",
                        headers=headers,
                        json=payload
                    )
                    
                    if response.status_code in (200, 201):
                        st.success("PDF embedded successfully!")
                        st.json(response.json())
                    else:
                        st.error(f"Failed to embed PDF: {response.text}")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

# Tab 4: Ask Questions
with tab4:
    st.header("Ask Questions")
    
    # Simple configuration inputs
    question_api_url = st.text_input("API URL", "https://embedly.dev.yoliday.in", key="ask_api_url")
    question_api_password = st.text_input("API Password", "Yoliday@2023", type="password", key="ask_api_password")
    
    # For Meilisearch configuration (needed to list indexes)
    meilisearch_url = st.text_input("Meilisearch URL", "https://searchek.dev.eklavya.me", key="ask_meili_url")
    meilisearch_api_key = st.text_input("Meilisearch API Key", "Eklavya@2023", type="password", key="ask_meili_key")
    
    # Get available indexes
    if st.button("Refresh Available Indexes"):
        try:
            response = requests.get(f"{meilisearch_url}/indexes", headers=get_meilisearch_headers(meilisearch_api_key))
            
            if response.status_code == 200:
                indexes = response.json().get("results", [])
                if indexes:
                    st.session_state.available_indexes = [index["uid"] for index in indexes]
                    st.success(f"Found {len(indexes)} indexes")
                else:
                    st.info("No indexes found")
                    st.session_state.available_indexes = []
            else:
                st.error(f"Failed to get indexes: {response.text}")
        except Exception as e:
            st.error(f"Error: {str(e)}")
    
    # Select index
    index_options = st.session_state.get("available_indexes", [])
    if not index_options:
        st.info("Click 'Refresh Available Indexes' to load indexes")
    
    selected_index = st.selectbox("Select an index", index_options if index_options else ["No indexes available"])
    
    # Question input
    question = st.text_area("Your Question", "What are the key concepts of machine learning?")
    k_value = st.slider("Number of results (k)", min_value=1, max_value=50, value=10)
    
    if st.button("Ask Question") and question and selected_index != "No indexes available":
        with st.spinner("Processing question..."):
            try:
                payload = {
                    "question": question,
                    "index": selected_index,
                    "k": k_value
                }
                
                # Add auth headers
                headers = {"Content-Type": "application/json"}
                headers["Authorization"] = "Basic " + base64.b64encode(f"user:{question_api_password}".encode()).decode()
                
                response = requests.post(
                    f"{question_api_url}/ask",
                    headers=headers,
                    json=payload
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # Display answer
                    if "answer" in result:
                        st.subheader("Answer")
                        st.write(result["answer"])
                    
                    # Display sources/context
                    if "context" in result or "sources" in result:
                        st.subheader("Sources & Context")
                        sources = result.get("sources", result.get("context", []))
                        
                        if isinstance(sources, list):
                            for i, source in enumerate(sources):
                                with st.expander(f"Source {i+1}"):
                                    st.json(source)
                        else:
                            st.json(sources)
                    
                    # If there's any other data in the response
                    other_keys = [k for k in result.keys() if k not in ["answer", "context", "sources"]]
                    if other_keys:
                        st.subheader("Additional Information")
                        for key in other_keys:
                            st.write(f"**{key}:**")
                            st.write(result[key])
                else:
                    st.error(f"Failed to process question: {response.text}")
            except Exception as e:
                st.error(f"Error: {str(e)}")

