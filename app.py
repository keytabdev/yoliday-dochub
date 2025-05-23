import os
import json
import time
import requests
import zipfile
import shutil
import tempfile
import gradio as gr
from pathlib import Path

def backup_meilisearch(meilisearch_url, meilisearch_api_key):
    """Backup all Meilisearch indexes to a zip file."""
    # Ensure URL format is correct
    if meilisearch_url.endswith('/'):
        meilisearch_url = meilisearch_url[:-1]
    
    # Setup headers
    headers = {"Authorization": f"Bearer {meilisearch_api_key}"}
    
    # Create temporary directory for backup
    temp_dir = tempfile.mkdtemp()
    output_dir = Path(temp_dir) / "meilisearch_backup"
    output_dir.mkdir(exist_ok=True)
    
    # Get list of all indexes
    response = requests.get(f"{meilisearch_url}/indexes", headers=headers)
    if response.status_code != 200:
        return None, f"Failed to get indexes: {response.text}"
    
    indexes = response.json().get("results", [])
    log_output = f"Found {len(indexes)} indexes\n"
    
    # Process each index
    for index in indexes:
        index_uid = index["uid"]
        log_output += f"Processing index: {index_uid}\n"
        
        # Create index directory
        index_dir = output_dir / index_uid
        index_dir.mkdir(exist_ok=True)
        
        # Get index settings
        settings_response = requests.get(
            f"{meilisearch_url}/indexes/{index_uid}/settings", 
            headers=headers
        )
        if settings_response.status_code == 200:
            settings = settings_response.json()
            with open(index_dir / "settings.json", "w") as f:
                json.dump(settings, f, indent=2)
        
        # Get total documents count
        stats_response = requests.get(
            f"{meilisearch_url}/indexes/{index_uid}/stats", 
            headers=headers
        )
        
        total_docs = 0
        if stats_response.status_code == 200:
            stats = stats_response.json()
            total_docs = stats.get("numberOfDocuments", 0)
            log_output += f"Index {index_uid} has {total_docs} documents total\n"
        
        # Get documents (paginated)
        offset = 0
        limit = 1000
        all_documents = []
        
        while True:
            log_output += f"Fetching documents from {index_uid}: offset={offset}, limit={limit}\n"
            docs_response = requests.get(
                f"{meilisearch_url}/indexes/{index_uid}/documents",
                params={"offset": offset, "limit": limit},
                headers=headers
            )
            
            if docs_response.status_code != 200:
                log_output += f"Failed to get documents: {docs_response.text}\n"
                break
            
            # Check if the response is in the expected format
            try:
                documents = docs_response.json()
                # Check if we got a proper response with results field
                if isinstance(documents, dict) and "results" in documents:
                    documents = documents["results"]
                    log_output += f"Retrieved {len(documents)} documents (using 'results' field)\n"
                elif not isinstance(documents, list):
                    log_output += f"Unexpected response format: {type(documents)}\n"
                    log_output += f"Sample of response: {str(documents)[:200]}...\n"
                    break
            except json.JSONDecodeError:
                log_output += f"Failed to parse JSON response: {docs_response.text[:200]}...\n"
                break
            
            if not documents:
                log_output += "No more documents to retrieve\n"
                break
            
            all_documents.extend(documents)
            log_output += f"Retrieved {len(documents)} documents from index {index_uid}, total so far: {len(all_documents)}\n"
            
            if len(documents) < limit:
                break
            
            offset += limit
        
        # Save documents
        log_output += f"Saving {len(all_documents)} documents for index {index_uid}\n"
        with open(index_dir / "documents.json", "w") as f:
            json.dump(all_documents, f, indent=2)
        
        # Save index metadata
        with open(index_dir / "info.json", "w") as f:
            json.dump(index, f, indent=2)
    
    # Create zip file
    zip_path = os.path.join(temp_dir, "meilisearch_backup.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(output_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, temp_dir)
                zipf.write(file_path, arcname)
    
    log_output += f"Backup completed successfully. Zip file created at {zip_path}\n"
    
    return zip_path, log_output

def wait_for_task(meilisearch_url, task_id, headers):
    """Wait for a Meilisearch task to complete."""
    while True:
        response = requests.get(f"{meilisearch_url}/tasks/{task_id}", headers=headers)
        if response.status_code == 200:
            task = response.json()
            if task['status'] in ['succeeded', 'failed', 'canceled']:
                return task
        else:
            return None
        
        time.sleep(0.5)  # Wait before checking again

def restore_meilisearch(meilisearch_url, meilisearch_api_key, zip_file):
    """Restore Meilisearch indexes from a zip file."""
    # Ensure URL format is correct
    if meilisearch_url.endswith('/'):
        meilisearch_url = meilisearch_url[:-1]
    
    # Setup headers
    headers = {"Authorization": f"Bearer {meilisearch_api_key}", "Content-Type": "application/json"}
    
    # Create temporary directory for extraction
    temp_dir = tempfile.mkdtemp()
    
    # Extract zip file
    log_output = f"Extracting backup from {zip_file} to {temp_dir}\n"
    with zipfile.ZipFile(zip_file, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)
    
    # Find the backup directory
    backup_dir = None
    for item in os.listdir(temp_dir):
        if os.path.isdir(os.path.join(temp_dir, item)) and "meilisearch_backup" in item:
            backup_dir = Path(os.path.join(temp_dir, item))
            break
    
    if not backup_dir:
        return "Error: Could not find meilisearch_backup directory in the zip file."
    
    # Get all index directories
    index_dirs = [d for d in backup_dir.iterdir() if d.is_dir()]
    log_output += f"Found {len(index_dirs)} indexes to restore\n"
    
    # First restore regular indexes
    for index_dir in index_dirs:
        index_uid = index_dir.name
        log_output += f"Restoring index: {index_uid}\n"
        
        # Skip documents index as it will be handled separately
        if index_uid == 'documents':
            log_output += f"Skipping 'documents' index as it will be handled separately\n"
            continue
        
        # Special case handling for 'page' index
        requires_special_handling = index_uid == 'page'
        
        # Check if index already exists
        check_response = requests.get(f"{meilisearch_url}/indexes/{index_uid}", headers=headers)
        
        # If special handling is needed and index exists, delete it first
        if requires_special_handling and check_response.status_code == 200:
            log_output += f"Special handling for index {index_uid}: deleting existing index\n"
            delete_response = requests.delete(f"{meilisearch_url}/indexes/{index_uid}", headers=headers)
            
            if delete_response.status_code in (200, 202):
                task_id = delete_response.json().get('taskUid')
                log_output += f"Index deletion enqueued with task ID {task_id}, waiting for completion...\n"
                
                task = wait_for_task(meilisearch_url, task_id, headers)
                if task and task['status'] == 'succeeded':
                    log_output += f"Deleted index {index_uid}\n"
                else:
                    log_output += f"Failed to delete index {index_uid}: {task}\n"
                    continue
            else:
                log_output += f"Failed to delete index {index_uid}: {delete_response.text}\n"
                continue
            
            # Reset check_response to indicate index no longer exists
            check_response.status_code = 404
        
        # Create index if it doesn't exist
        if check_response.status_code == 404:
            # Get index info from backup
            info_file = index_dir / "info.json"
            if info_file.exists():
                with open(info_file, "r") as f:
                    info = json.load(f)
                
                # Create index with primary key if specified
                primary_key = info.get("primaryKey")
                create_data = {"uid": index_uid}
                
                # For special case indexes, ensure primary key is set
                if index_uid == 'page' and not primary_key:
                    primary_key = 'id'  # Force 'id' as primary key for page index
                
                if primary_key:
                    create_data["primaryKey"] = primary_key
                
                create_response = requests.post(
                    f"{meilisearch_url}/indexes",
                    headers=headers,
                    json=create_data
                )
                
                if create_response.status_code in (201, 200, 202):
                    # Get task ID from response and wait for completion
                    task_id = create_response.json().get('taskUid')
                    log_output += f"Index creation enqueued with task ID {task_id}, waiting for completion...\n"
                    
                    task = wait_for_task(meilisearch_url, task_id, headers)
                    if task and task['status'] == 'succeeded':
                        log_output += f"Created index {index_uid}\n"
                    else:
                        log_output += f"Failed to create index {index_uid}: {task}\n"
                        continue
                else:
                    log_output += f"Failed to create index {index_uid}: {create_response.text}\n"
                    continue
            else:
                # Create index without info
                create_data = {"uid": index_uid}
                
                # For special case indexes, ensure primary key is set
                if index_uid == 'page':
                    create_data["primaryKey"] = 'id'  # Force 'id' as primary key for page index
                
                create_response = requests.post(
                    f"{meilisearch_url}/indexes",
                    headers=headers,
                    json=create_data
                )
                
                if create_response.status_code in (201, 200, 202):
                    # Get task ID from response and wait for completion
                    task_id = create_response.json().get('taskUid')
                    log_output += f"Index creation enqueued with task ID {task_id}, waiting for completion...\n"
                    
                    task = wait_for_task(meilisearch_url, task_id, headers)
                    if task and task['status'] == 'succeeded':
                        log_output += f"Created index {index_uid}\n"
                    else:
                        log_output += f"Failed to create index {index_uid}: {task}\n"
                        continue
                else:
                    log_output += f"Failed to create index {index_uid}: {create_response.text}\n"
                    continue
        else:
            log_output += f"Index {index_uid} already exists\n"
        
        # Restore settings
        settings_file = index_dir / "settings.json"
        if settings_file.exists():
            try:
                with open(settings_file, "r") as f:
                    settings = json.load(f)
                
                # Apply all settings at once
                all_settings_response = requests.patch(
                    f"{meilisearch_url}/indexes/{index_uid}/settings",
                    headers=headers,
                    json=settings
                )
                
                if all_settings_response.status_code in (200, 202):
                    # Wait for task to complete
                    task_id = all_settings_response.json().get('taskUid')
                    if task_id is not None:
                        log_output += f"Settings update enqueued with task ID {task_id}, waiting for completion...\n"
                        task = wait_for_task(meilisearch_url, task_id, headers)
                        if task and task['status'] == 'succeeded':
                            log_output += f"Applied all settings to index {index_uid}\n"
                        else:
                            log_output += f"Failed to apply all settings to index {index_uid}: {task}\n"
                    else:
                        log_output += f"Applied settings to index {index_uid} but no task ID was returned\n"
                else:
                    log_output += f"Failed to apply all settings at once: {all_settings_response.text}\n"
                    log_output += "Trying to apply settings individually...\n"
                    
                    # Apply each setting type individually as fallback
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
                        if setting_type in settings and settings[setting_type]:  # Only update if there's a value
                            setting_value = settings[setting_type]
                            try:
                                settings_response = requests.put(
                                    f"{meilisearch_url}/indexes/{index_uid}/settings/{setting_type}",
                                    headers=headers,
                                    json=setting_value
                                )
                                
                                if settings_response.status_code in (200, 202):
                                    task_id = settings_response.json().get('taskUid')
                                    if task_id is not None:
                                        log_output += f"Setting {setting_type} update enqueued with task ID {task_id}, waiting for completion...\n"
                                        task = wait_for_task(meilisearch_url, task_id, headers)
                                        if task and task['status'] == 'succeeded':
                                            log_output += f"Applied setting {setting_type} to index {index_uid}\n"
                                        else:
                                            log_output += f"Failed to apply setting {setting_type} to index {index_uid}: {task}\n"
                                    else:
                                        log_output += f"Applied setting {setting_type} to index {index_uid} but no task ID was returned\n"
                                else:
                                    log_output += f"Failed to apply setting {setting_type} to index {index_uid}: {settings_response.text}\n"
                            except Exception as e:
                                log_output += f"Error applying setting {setting_type}: {str(e)}\n"
            except Exception as e:
                log_output += f"Error processing settings file: {str(e)}\n"
        
        # Restore documents
        documents_file = index_dir / "documents.json"
        if documents_file.exists():
            try:
                with open(documents_file, "r") as f:
                    documents = json.load(f)
                
                if documents:
                    # For page index, make sure we're using the correct primary key
                    if index_uid == 'page':
                        log_output += "Special handling for page index documents - ensuring primary key field\n"
                        for doc in documents:
                            if '_meilisearch_id' in doc and 'id' not in doc:
                                doc['id'] = doc['_meilisearch_id']  # Copy value to ensure 'id' exists
                    
                    # Add documents in batches to avoid timeouts
                    batch_size = 1000
                    for i in range(0, len(documents), batch_size):
                        batch = documents[i:i + batch_size]
                        log_output += f"Adding batch of {len(batch)} documents to index {index_uid} ({i+1}-{i+len(batch)} of {len(documents)})\n"
                        
                        try:
                            docs_response = requests.post(
                                f"{meilisearch_url}/indexes/{index_uid}/documents",
                                headers=headers,
                                json=batch
                            )
                            
                            if docs_response.status_code in (202, 201, 200):
                                # Wait for documents addition to complete
                                task_id = docs_response.json().get('taskUid')
                                if task_id is not None:
                                    log_output += f"Document addition enqueued with task ID {task_id}, waiting for completion...\n"
                                    
                                    task = wait_for_task(meilisearch_url, task_id, headers)
                                    if task and task['status'] == 'succeeded':
                                        log_output += f"Successfully added batch to index {index_uid}\n"
                                    else:
                                        log_output += f"Failed to add documents to index {index_uid}: {task}\n"
                                        
                                        # Special handling for page index if the error is about primary key
                                        if index_uid == 'page' and task and 'error' in task and 'primary_key' in str(task['error']):
                                            log_output += "Attempting to update page index with forced primary key...\n"
                                            # Update index with forced primary key
                                            update_response = requests.patch(
                                                f"{meilisearch_url}/indexes/{index_uid}",
                                                headers=headers,
                                                json={"primaryKey": "id"}
                                            )
                                            
                                            if update_response.status_code in (200, 202):
                                                task_id = update_response.json().get('taskUid')
                                                log_output += f"Index update enqueued with task ID {task_id}, waiting for completion...\n"
                                                update_task = wait_for_task(meilisearch_url, task_id, headers)
                                                
                                                if update_task and update_task['status'] == 'succeeded':
                                                    log_output += f"Updated index {index_uid} with primary key 'id'\n"
                                                    # Try adding documents again
                                                    log_output += "Trying to add documents again...\n"
                                                    
                                                    docs_response = requests.post(
                                                        f"{meilisearch_url}/indexes/{index_uid}/documents",
                                                        headers=headers,
                                                        json=batch
                                                    )
                                                    
                                                    if docs_response.status_code in (202, 201, 200):
                                                        task_id = docs_response.json().get('taskUid')
                                                        log_output += f"Document addition enqueued with task ID {task_id}, waiting for completion...\n"
                                                        
                                                        retry_task = wait_for_task(meilisearch_url, task_id, headers)
                                                        if retry_task and retry_task['status'] == 'succeeded':
                                                            log_output += f"Successfully added batch to index {index_uid} on retry\n"
                                                        else:
                                                            log_output += f"Failed to add documents to index {index_uid} on retry: {retry_task}\n"
                                                else:
                                                    log_output += f"Failed to update index {index_uid}: {update_task}\n"
                                else:
                                    log_output += f"Documents added to index {index_uid} but no task ID was returned\n"
                            else:
                                log_output += f"Failed to add documents to index {index_uid}: {docs_response.text}\n"
                        except Exception as e:
                            log_output += f"Error adding documents batch: {str(e)}\n"
                        
                        # Wait a bit to avoid overwhelming the server
                        time.sleep(1)
                else:
                    log_output += f"No documents found for index {index_uid}\n"
            except Exception as e:
                log_output += f"Error processing documents file: {str(e)}\n"
    
    log_output += "Regular indexes restore completed\n"
    
    # Fix documents index
    documents_index_dir = backup_dir / "documents"
    if documents_index_dir.exists():
        log_output += "Fixing documents index specifically\n"
        index_uid = "documents"
        
        # Delete the existing index if it exists
        check_response = requests.get(f"{meilisearch_url}/indexes/{index_uid}", headers=headers)
        if check_response.status_code == 200:
            log_output += f"Deleting existing index {index_uid}\n"
            delete_response = requests.delete(f"{meilisearch_url}/indexes/{index_uid}", headers=headers)
            
            if delete_response.status_code in (200, 202):
                task_id = delete_response.json().get('taskUid')
                log_output += f"Index deletion enqueued with task ID {task_id}, waiting for completion...\n"
                
                task = wait_for_task(meilisearch_url, task_id, headers)
                if task and task['status'] == 'succeeded':
                    log_output += f"Deleted index {index_uid}\n"
                else:
                    log_output += f"Failed to delete index {index_uid}: {task}\n"
                    return log_output
            else:
                log_output += f"Failed to delete index {index_uid}: {delete_response.text}\n"
                return log_output
        
        # Get index info from backup
        info_file = documents_index_dir / "info.json"
        primary_key = None
        if info_file.exists():
            with open(info_file, "r") as f:
                info = json.load(f)
                primary_key = info.get("primaryKey")
        
        # Create a new index
        create_data = {"uid": index_uid}
        if primary_key:
            create_data["primaryKey"] = primary_key
        
        log_output += f"Creating new index {index_uid} with primary key {primary_key}\n"
        create_response = requests.post(
            f"{meilisearch_url}/indexes",
            headers=headers,
            json=create_data
        )
        
        if create_response.status_code in (201, 200, 202):
            task_id = create_response.json().get('taskUid')
            log_output += f"Index creation enqueued with task ID {task_id}, waiting for completion...\n"
            
            task = wait_for_task(meilisearch_url, task_id, headers)
            if task and task['status'] == 'succeeded':
                log_output += f"Created index {index_uid}\n"
            else:
                log_output += f"Failed to create index {index_uid}: {task}\n"
                return log_output
        else:
            log_output += f"Failed to create index {index_uid}: {create_response.text}\n"
            return log_output
        
        # Apply settings with vector search disabled
        settings_file = documents_index_dir / "settings.json"
        if settings_file.exists():
            with open(settings_file, "r") as f:
                settings = json.load(f)
            
            # Remove embedders configuration to disable vector search
            if 'embedders' in settings:
                log_output += "Removing embedders configuration\n"
                del settings['embedders']
            
            # Apply modified settings
            settings_response = requests.patch(
                f"{meilisearch_url}/indexes/{index_uid}/settings",
                headers=headers,
                json=settings
            )
            
            if settings_response.status_code in (200, 202):
                task_id = settings_response.json().get('taskUid')
                log_output += f"Settings update enqueued with task ID {task_id}, waiting for completion...\n"
                
                task = wait_for_task(meilisearch_url, task_id, headers)
                if task and task['status'] == 'succeeded':
                    log_output += f"Applied settings to index {index_uid}\n"
                else:
                    log_output += f"Failed to apply settings to index {index_uid}: {task}\n"
            else:
                log_output += f"Failed to apply settings to index {index_uid}: {settings_response.text}\n"
        
        # Prepare documents for import
        documents_file = documents_index_dir / "documents.json"
        if documents_file.exists():
            with open(documents_file, "r") as f:
                documents = json.load(f)
            
            if documents:
                # Add _vectors.default: null to each document
                log_output += "Adding null vector embeddings to documents\n"
                for doc in documents:
                    if '_vectors' not in doc:
                        doc['_vectors'] = {'default': None}
                
                # Add documents in batches
                batch_size = 1000
                for i in range(0, len(documents), batch_size):
                    batch = documents[i:i + batch_size]
                    log_output += f"Adding batch of {len(batch)} documents to index {index_uid} ({i+1}-{i+len(batch)} of {len(documents)})\n"
                    
                    docs_response = requests.post(
                        f"{meilisearch_url}/indexes/{index_uid}/documents",
                        headers=headers,
                        json=batch
                    )
                    
                    if docs_response.status_code in (202, 201, 200):
                        task_id = docs_response.json().get('taskUid')
                        log_output += f"Document addition enqueued with task ID {task_id}, waiting for completion...\n"
                        
                        task = wait_for_task(meilisearch_url, task_id, headers)
                        if task and task['status'] == 'succeeded':
                            log_output += f"Successfully added batch to index {index_uid}\n"
                        else:
                            log_output += f"Failed to add documents to index {index_uid}: {task}\n"
                    else:
                        log_output += f"Failed to add documents to index {index_uid}: {docs_response.text}\n"
                    
                    # Wait a bit to avoid overwhelming the server
                    time.sleep(1)
            else:
                log_output += f"No documents found for index {index_uid}\n"
        else:
            log_output += f"Documents file not found for index {index_uid}\n"
        
        log_output += "Fix completed for documents index\n"
    
    # Clean up the temporary directory
    try:
        shutil.rmtree(temp_dir)
        log_output += f"Cleaned up temporary directory: {temp_dir}\n"
    except Exception as e:
        log_output += f"Error cleaning up temporary directory: {str(e)}\n"
    
    log_output += "Restore process completed!\n"
    return log_output

# Create Gradio interface
def create_interface():
    # Define interface components
    with gr.Blocks(title="Meilisearch Backup/Restore") as app:
        gr.Markdown("# Meilisearch Backup and Restore Tool")
        
        with gr.Tab("Backup"):
            backup_url = gr.Textbox(label="Meilisearch URL", placeholder="https://searchek.dev.eklavya.me")
            backup_key = gr.Textbox(label="Meilisearch API Key", placeholder="Your-API-Key", type="password")
            backup_button = gr.Button("Backup")
            backup_output = gr.Textbox(label="Backup Logs", lines=20)
            backup_file = gr.File(label="Download Backup File")
            
            def run_backup(url, key):
                if not url or not key:
                    return None, "Please provide both Meilisearch URL and API Key"
                
                try:
                    zip_path, log_output = backup_meilisearch(url, key)
                    if zip_path:
                        return zip_path, log_output
                    else:
                        return None, log_output
                except Exception as e:
                    return None, f"Error during backup: {str(e)}"
            
            backup_button.click(
                run_backup, 
                inputs=[backup_url, backup_key], 
                outputs=[backup_file, backup_output]
            )
        
        with gr.Tab("Restore"):
            restore_url = gr.Textbox(label="Meilisearch URL", placeholder="https://searchek.dev.eklavya.me")
            restore_key = gr.Textbox(label="Meilisearch API Key", placeholder="Your-API-Key", type="password")
            restore_file = gr.File(label="Upload Backup File")
            restore_button = gr.Button("Restore")
            restore_output = gr.Textbox(label="Restore Logs", lines=20)
            
            def run_restore(url, key, file):
                if not url or not key or not file:
                    return "Please provide Meilisearch URL, API Key, and a backup zip file"
                
                try:
                    log_output = restore_meilisearch(url, key, file.name)
                    return log_output
                except Exception as e:
                    return f"Error during restore: {str(e)}"
            
            restore_button.click(
                run_restore, 
                inputs=[restore_url, restore_key, restore_file], 
                outputs=[restore_output]
            )
    
    return app

# Launch the interface when run directly
if __name__ == "__main__":
    print("Starting Meilisearch Backup/Restore Tool...")
    app = create_interface()
    print("Interface created. Launching...")

    app.launch(server_name="0.0.0.0", server_port=7860)
    print(" Interface launched and running at http://0.0.0.0:7860")