import os
import io
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import firebase_helper

# Use drive.file scope so the app only has access to files it creates/opens
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def get_drive_service(credentials_path):
    creds = None
    
    # Fetch token JSON from Firestore
    token_json_str = firebase_helper.get_drive_token()
    if token_json_str:
        try:
            token_info = json.loads(token_json_str)
            creds = Credentials.from_authorized_user_info(token_info, SCOPES)
        except Exception as e:
            print(f"[Google Drive] Error loading credentials from Firestore: {e}")
            return None

    # If there are no credentials or they are expired, refresh them
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Update refreshed token in Firestore
                firebase_helper.save_drive_token(creds.to_json())
            except Exception as e:
                print(f"[Google Drive] Error refreshing credentials: {e}")
                return None
        else:
            return None
    try:
        service = build('drive', 'v3', credentials=creds)
        return service
    except Exception as e:
        print(f"[Google Drive] Error building service: {e}")
        return None

def generate_auth_url(credentials_path, redirect_uri):
    flow = Flow.from_client_secrets_file(
        credentials_path,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    # Disable PKCE (code_challenge) - not needed for confidential web clients
    auth_url, _ = flow.authorization_url(
        prompt='consent',
        access_type='offline',
        include_granted_scopes='true'
    )
    return auth_url, flow.code_verifier

def save_credentials(credentials_path, redirect_uri, authorization_response_url, code_verifier=None):
    flow = Flow.from_client_secrets_file(
        credentials_path,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        autogenerate_code_verifier=False
    )
    flow.fetch_token(authorization_response=authorization_response_url)
    creds = flow.credentials
    
    # Save token in Firestore
    firebase_helper.save_drive_token(creds.to_json())
    return creds

def get_or_create_folder(service, folder_name, parent_id=None):
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    
    # Create the folder if not found
    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    if parent_id:
        file_metadata['parents'] = [parent_id]
        
    folder = service.files().create(body=file_metadata, fields='id').execute()
    return folder.get('id')

def upload_to_drive(service, file_data, filename, category_folder):
    # Get or create the root folder: DadBillsSync
    root_folder_id = get_or_create_folder(service, 'DadBillsSync')
    
    # Get or create the category subfolder inside DadBillsSync
    subfolder_id = get_or_create_folder(service, category_folder, parent_id=root_folder_id)
    
    # Determine the mimetype based on the file extension
    ext = os.path.splitext(filename)[1].lower()
    mimetypes = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp"
    }
    mimetype = mimetypes.get(ext, "application/octet-stream")
    
    file_metadata = {
        'name': filename,
        'parents': [subfolder_id]
    }
    
    fh = io.BytesIO(file_data)
    media = MediaIoBaseUpload(fh, mimetype=mimetype, resumable=True)
    
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()
    
    return file.get('id')

def list_sync_files(service):
    # Find the DadBillsSync root folder
    query = "name = 'DadBillsSync' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    folders = results.get('files', [])
    if not folders:
        return []
    
    root_id = folders[0]['id']
    
    # List all subfolders in DadBillsSync
    query_subs = f"'{root_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results_subs = service.files().list(q=query_subs, spaces='drive', fields='files(id, name)').execute()
    subfolders = results_subs.get('files', [])
    
    sync_files = []
    for sub in subfolders:
        sub_name = sub['name']
        sub_id = sub['id']
        
        # List all files inside this subfolder
        query_files = f"'{sub_id}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        results_files = service.files().list(q=query_files, spaces='drive', fields='files(id, name, mimeType)').execute()
        files = results_files.get('files', [])
        
        for f in files:
            sync_files.append({
                'id': f['id'],
                'name': f['name'],
                'category': sub_name,
                'mimeType': f['mimeType']
            })
            
    return sync_files

def download_file_content(service, file_id):
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    return fh.getvalue()

def download_and_delete_file(service, file_id, local_path):
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    
    # Ensure local path directory exists and write content
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, 'wb') as f:
        f.write(fh.getvalue())
        
    # Delete the source file from Google Drive after successful local download
    service.files().delete(fileId=file_id).execute()
