import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

# Global DB client
db = None

def init_firebase():
    global db
    if db is not None:
        return db

    # 1. Try loading from environment variable (useful for cloud hosting like Render)
    cred_json = os.environ.get("FIREBASE_CREDENTIALS")
    if cred_json:
        try:
            cred_dict = json.loads(cred_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            print("[Firebase] Initialized successfully from environment variable.")
            return db
        except Exception as e:
            print(f"[Firebase] Error parsing environment credentials: {e}")

    # 2. Try loading from local file
    cred_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firebase-credentials.json")
    if os.path.exists(cred_file):
        try:
            cred = credentials.Certificate(cred_file)
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            print(f"[Firebase] Initialized successfully from {cred_file}.")
            return db
        except Exception as e:
            print(f"[Firebase] Error initializing from file {cred_file}: {e}")

    print("[Firebase] Warning: Credentials not found. Firebase is not connected.")
    return None

# Get Firestore Client
def get_db():
    global db
    if db is None:
        init_firebase()
    return db

# Save/Retrieve Google Drive Credentials in Firestore
def save_drive_token(token_json_str):
    client = get_db()
    if not client:
        return False
    try:
        client.collection("config").document("google_drive_token").set({
            "token_data": token_json_str
        })
        print("[Firebase] Successfully saved Google Drive token to Firestore.")
        return True
    except Exception as e:
        print(f"[Firebase] Error saving Drive token: {e}")
        return False

def get_drive_token():
    client = get_db()
    if not client:
        return None
    try:
        doc = client.collection("config").document("google_drive_token").get()
        if doc.exists:
            return doc.to_dict().get("token_data")
    except Exception as e:
        print(f"[Firebase] Error retrieving Drive token: {e}")
    return None

def delete_drive_token():
    client = get_db()
    if not client:
        return False
    try:
        client.collection("config").document("google_drive_token").delete()
        print("[Firebase] Google Drive token removed from Firestore.")
        return True
    except Exception as e:
        print(f"[Firebase] Error deleting Drive token: {e}")
        return False

# Manage File Metadata in Firestore
def add_pending_file(file_id, name, filename, category, custom_folder):
    client = get_db()
    if not client:
        return False
    try:
        client.collection("bills").document(file_id).set({
            "id": file_id,
            "name": name,
            "filename": filename,
            "category": category,
            "custom_folder": custom_folder,
            "status": "pending",
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        print(f"[Firebase] Saved metadata for pending bill {name} (ID: {file_id})")
        return True
    except Exception as e:
        print(f"[Firebase] Error saving metadata: {e}")
        return False

def list_pending_files():
    client = get_db()
    if not client:
        return []
    try:
        docs = client.collection("bills").where("status", "==", "pending").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
        results = []
        for doc in docs:
            results.append(doc.to_dict())
        return results
    except Exception as e:
        # Fallback to unordered if ordering index is still building in Firestore
        try:
            docs = client.collection("bills").where("status", "==", "pending").stream()
            results = []
            for doc in docs:
                results.append(doc.to_dict())
            return results
        except Exception as e2:
            print(f"[Firebase] Error listing pending bills: {e2}")
            return []

def update_file_status(file_id, status):
    client = get_db()
    if not client:
        return False
    try:
        client.collection("bills").document(file_id).update({
            "status": status
        })
        print(f"[Firebase] Updated status of file {file_id} to {status}.")
        return True
    except Exception as e:
        print(f"[Firebase] Error updating file status: {e}")
        return False

def get_file_status(file_id):
    client = get_db()
    if not client:
        return "unknown"
    try:
        doc = client.collection("bills").document(file_id).get()
        if doc.exists:
            return doc.to_dict().get("status", "pending")
    except Exception as e:
        print(f"[Firebase] Error fetching file status: {e}")
    return "unknown"
