import os
import socket
import requests
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file
import io

app = Flask(__name__)
app.secret_key = 'dad-bills-local-admin-secret-key-2026'

# Subfolders map
SUBFOLDERS = {
    "current": "Current Bill",
    "water": "Water Bill Receipt",
    "jio": "Jio Fiber",
    "other": "Other"
}

BASE_DIR = r"F:\Bills"

# Load Cloud Server URL
CLOUD_URL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloud_url.txt")
if os.path.exists(CLOUD_URL_FILE):
    with open(CLOUD_URL_FILE, "r") as f:
        CLOUD_SERVER_URL = f.read().strip().rstrip("/")
else:
    # Default to localhost for testing, can be overwritten by writing the Render URL to cloud_url.txt
    CLOUD_SERVER_URL = "http://localhost:5000"

print(f"[Local Admin] Connecting to Cloud Server at: {CLOUD_SERVER_URL}")

def get_save_folder(folder_name):
    # Try using F:\Bills, fallback to ~/Bills if F:\ is not writeable or accessible
    try:
        target = os.path.join(BASE_DIR, folder_name)
        os.makedirs(target, exist_ok=True)
        # Test write permission
        test_file = os.path.join(target, ".write_test")
        with open(test_file, "w") as f:
            f.write("")
        os.remove(test_file)
        return target
    except Exception:
        fallback_base = os.path.join(os.path.expanduser("~"), "Bills")
        target = os.path.join(fallback_base, folder_name)
        os.makedirs(target, exist_ok=True)
        return target

@app.route("/")
def index():
    return redirect(url_for('admin'))

@app.route("/client")
def client():
    # On the laptop, /client can just proxy the Cloud Server's client view
    try:
        r = requests.get(f"{CLOUD_SERVER_URL}/client")
        return r.text
    except Exception as e:
        return f"Error connecting to Cloud Server: {e}", 502

@app.route("/admin")
def admin():
    # Serves the index.html from local templates, set as admin view
    return render_template("index.html", is_admin=True)

@app.route("/oauth/status")
def oauth_status():
    try:
        r = requests.get(f"{CLOUD_SERVER_URL}/oauth/status")
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)})

@app.route("/oauth/connect")
def oauth_connect():
    # Redirect to the Cloud Server's connect flow
    return redirect(f"{CLOUD_SERVER_URL}/oauth/connect")

@app.route("/oauth/disconnect")
def oauth_disconnect():
    try:
        r = requests.get(f"{CLOUD_SERVER_URL}/oauth/disconnect")
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.route("/pending")
def get_pending():
    # Fetch pending files from the Cloud Server
    try:
        r = requests.get(f"{CLOUD_SERVER_URL}/pending")
        return jsonify(r.json())
    except Exception as e:
        print(f"[Error] Failed to fetch pending from Cloud Server: {e}")
        return jsonify([])

@app.route("/view/<file_id>")
def view_pdf(file_id):
    # Proxy the file preview stream from the Cloud Server
    try:
        r = requests.get(f"{CLOUD_SERVER_URL}/view/{file_id}")
        if r.status_code != 200:
            return r.text, r.status_code
        
        mimetype = r.headers.get("Content-Type", "application/pdf")
        filename = r.headers.get("Content-Disposition", "filename=bill.pdf")
        if "filename=" in filename:
            filename = filename.split("filename=")[1].strip('"')
        
        return send_file(
            io.BytesIO(r.content),
            mimetype=mimetype,
            as_attachment=False,
            download_name=filename
        )
    except Exception as e:
        return str(e), 500

@app.route("/decide/<file_id>/<action>")
def decide(file_id, action):
    if action == "approve":
        try:
            # 1. Fetch the list of pending items from the Cloud Server to find the filename & folder
            r_list = requests.get(f"{CLOUD_SERVER_URL}/pending")
            if r_list.status_code != 200:
                return jsonify({"error": "Failed to get pending list from Cloud Server"}), 502
            
            pending_items = r_list.json()
            target_item = None
            for item in pending_items:
                if item["id"] == file_id:
                    target_item = item
                    break
            
            if not target_item:
                return jsonify({"error": "File metadata not found in pending list"}), 404
            
            category_key = target_item.get("category", "other")
            custom_folder = target_item.get("custom_folder", "")
            filename = target_item.get("filename", "bill.pdf")
            
            # Map category to folder name
            if category_key == "custom" and custom_folder:
                folder_name = custom_folder
            else:
                folder_name = SUBFOLDERS.get(category_key, "Other")
                
            folder_name = "".join(c for c in folder_name if c.isalnum() or c in (" ", "-", "_")).strip()
            if not folder_name:
                folder_name = "Other"
                
            # 2. Fetch the file content from the Cloud Server
            r_file = requests.get(f"{CLOUD_SERVER_URL}/view/{file_id}")
            if r_file.status_code != 200:
                return jsonify({"error": "Failed to download file from Cloud Server"}), 502
                
            # 3. Determine save folder and handle duplicates
            save_dir = get_save_folder(folder_name)
            base, ext = os.path.splitext(filename)
            path = os.path.join(save_dir, filename)
            
            counter = 1
            while os.path.exists(path):
                filename = f"{base}_{counter}{ext}"
                path = os.path.join(save_dir, filename)
                counter += 1
                
            # 4. Save the file locally on the laptop disk
            with open(path, "wb") as f:
                f.write(r_file.content)
            print(f"[Local Admin] Successfully saved file locally to: {path}")
            
            # Trigger Windows native desktop notification via plyer
            try:
                from plyer import notification
                notification.notify(
                    title="Bill Saved Locally! 📁",
                    message=f"File: {filename}\nFolder: {folder_name}",
                    app_name="Dad Bills",
                    timeout=5
                )
            except Exception as ne:
                print(f"[Warning] Desktop notification failed: {ne}")
                
            # 5. Tell the Cloud Server to approve (which deletes the file from Drive & marks approved in Firestore)
            r_decide = requests.get(f"{CLOUD_SERVER_URL}/decide/{file_id}/approve")
            if r_decide.status_code != 200:
                return jsonify({"error": "File saved locally but Cloud Server approval state failed to sync."}), 502
                
            return jsonify({"status": "saved", "path": path})
        except Exception as e:
            print(f"[Local Admin] Error during approval: {e}")
            return jsonify({"error": f"Failed to save file: {str(e)}"}), 500

    # Action is reject
    try:
        r_decide = requests.get(f"{CLOUD_SERVER_URL}/decide/{file_id}/reject")
        return jsonify(r_decide.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.route("/status/<file_id>")
def get_status(file_id):
    try:
        r = requests.get(f"{CLOUD_SERVER_URL}/status/{file_id}")
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"status": "unknown", "error": str(e)})

if __name__ == "__main__":
    print(f"\n[OK] Local Admin App starting on your laptop!")
    print(f"Open: http://localhost:5000/admin\n")
    app.run(host="127.0.0.1", port=5000, debug=True)
