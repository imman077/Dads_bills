import os
import time
import socket
import json
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import drive_helper
import firebase_helper

# Allow HTTP for Google OAuth authentication callback locally if testing
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)
app.secret_key = 'dad-bills-cloud-secret-key-2026'  # Required for session storage

CREDENTIALS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")

# Initialize Firebase on server start
firebase_helper.init_firebase()

# Subfolders map
SUBFOLDERS = {
    "current": "Current Bill",
    "water": "Water Bill Receipt",
    "jio": "Jio Fiber",
    "other": "Other"
}

@app.route("/")
def index():
    return render_template("index.html", is_admin=False)

@app.route("/client")
def client():
    return render_template("index.html", is_admin=False)

@app.route("/admin")
def admin():
    # Render the admin UI directly from the cloud page if requested,
    # but actual local file saving must run via local_admin.py on the laptop
    return render_template("index.html", is_admin=True)

@app.route("/oauth/connect")
def oauth_connect():
    if not os.path.exists(CREDENTIALS_PATH):
        return "Missing credentials.json. Please upload Google OAuth credentials on the server first.", 400
    redirect_uri = request.url_root.rstrip('/') + "/oauth2callback"
    auth_url, code_verifier = drive_helper.generate_auth_url(CREDENTIALS_PATH, redirect_uri)
    session['code_verifier'] = code_verifier
    
    # Track which exact URL initiated the connection
    referer = request.referrer or ""
    if not referer or "oauth" in referer:
        referer = url_for('admin', _external=True)
    session['oauth_redirect_back'] = referer
        
    return redirect(auth_url)

@app.route("/oauth2callback")
def oauth2callback():
    authorization_response = request.url
    redirect_uri = request.url_root.rstrip('/') + "/oauth2callback"
    code_verifier = session.get('code_verifier')
    try:
        drive_helper.save_credentials(
            CREDENTIALS_PATH,
            redirect_uri,
            authorization_response,
            code_verifier=code_verifier
        )
        
        # Redirect back to the exact URL they came from (with the query param)
        redirect_back = session.get('oauth_redirect_back')
        if not redirect_back:
            redirect_back = url_for('admin', _external=True)
            
        from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
        u = list(urlparse(redirect_back))
        q = dict(parse_qsl(u[4]))
        q['drive_connected'] = 'true'
        u[4] = urlencode(q)
        redirect_back_with_param = urlunparse(u)
        
        return redirect(redirect_back_with_param)
    except Exception as e:
        print(f"[Error] OAuth callback failed: {e}")
        return f"Authentication failed: {str(e)}", 500

@app.route("/oauth/status")
def oauth_status():
    service = drive_helper.get_drive_service(CREDENTIALS_PATH)
    if service:
        try:
            about = service.about().get(fields="user(emailAddress)").execute()
            email = about.get("user", {}).get("emailAddress", "Connected")
            return jsonify({"connected": True, "email": email})
        except Exception:
            return jsonify({"connected": True, "email": "Connected Account"})
    return jsonify({"connected": False})

@app.route("/oauth/disconnect")
def oauth_disconnect():
    firebase_helper.delete_drive_token()
    return jsonify({"status": "disconnected"})

@app.route("/upload", methods=["POST"])
def upload():
    name = request.form.get("name", "Unknown").strip()
    if not name:
        name = "Unknown"
    category = request.form.get("category", "other").strip()
    custom_folder = request.form.get("custom_folder", "").strip()
    file = request.files.get("pdf")
    if not file:
        return jsonify({"error": "Please upload a file"}), 400
        
    filename_lower = file.filename.lower()
    allowed_extensions = (".pdf", ".png", ".jpg", ".jpeg", ".webp")
    if not filename_lower.endswith(allowed_extensions):
        return jsonify({"error": "Please upload a PDF or an image file (PNG, JPG, WEBP)"}), 400
    
    file_data = file.read()
    _, ext = os.path.splitext(filename_lower)
    
    safe_name = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).strip()
    if not safe_name:
        safe_name = "Unknown"

    service = drive_helper.get_drive_service(CREDENTIALS_PATH)
    if not service:
        return jsonify({"error": "Google Drive is not connected. Please connect Google Drive first."}), 400

    if category == "custom":
        folder_name = custom_folder
    else:
        folder_name = SUBFOLDERS.get(category, "Other")
        
    folder_name = "".join(c for c in folder_name if c.isalnum() or c in (" ", "-", "_")).strip()
    if not folder_name:
        folder_name = "Other"
        
    try:
        # Upload the file to Google Drive
        drive_file_id = drive_helper.upload_to_drive(service, file_data, f"{safe_name}{ext}", folder_name)
        
        # Save Metadata to Firebase Firestore
        firebase_helper.add_pending_file(
            file_id=drive_file_id,
            name=safe_name,
            filename=f"{safe_name}{ext}",
            category=category,
            custom_folder=custom_folder
        )

        # Trigger ntfy.sh push notification (optional helper for mobile)
        try:
            import requests 
            requests.post(
                "https://ntfy.sh/dad_bills_admin",
                data=f"New Bill '{safe_name}{ext}' uploaded to Google Drive folder '{folder_name}'.",
                headers={
                    "Title": "New Bill on Google Drive!",
                    "Priority": "high",
                    "Tags": "cloud"
                },
                timeout=5
            )
        except Exception as ne:
            print(f"[Warning] ntfy.sh notification failed: {ne}")
            
        return jsonify({"status": "pending", "id": drive_file_id})
    except Exception as e:
        print(f"[Error] Upload failed: {e}")
        return jsonify({"error": f"Upload failed: {str(e)}"}), 500

@app.route("/pending")
def get_pending():
    # Read the pending list directly from Firestore metadata database
    try:
        pending_list = firebase_helper.list_pending_files()
        return jsonify(pending_list)
    except Exception as e:
        print(f"[Error] Failed to fetch pending from Firestore: {e}")
        return jsonify([])

@app.route("/view/<file_id>")
def view_pdf(file_id):
    service = drive_helper.get_drive_service(CREDENTIALS_PATH)
    if not service:
        return "Google Drive not connected", 400
    try:
        file_meta = service.files().get(fileId=file_id, fields="name, mimeType").execute()
        filename = file_meta.get("name")
        mimetype = file_meta.get("mimeType")
        
        content = drive_helper.download_file_content(service, file_id)
        
        import io
        from flask import send_file
        return send_file(
            io.BytesIO(content),
            mimetype=mimetype,
            as_attachment=False,
            download_name=filename
        )
    except Exception as e:
        return str(e), 500

@app.route("/decide/<file_id>/<action>")
def decide(file_id, action):
    service = drive_helper.get_drive_service(CREDENTIALS_PATH)
    if not service:
        return jsonify({"error": "Google Drive is not connected."}), 400

    try:
        file_meta = service.files().get(fileId=file_id, fields="name").execute()
        filename = file_meta.get("name")
    except Exception:
        filename = "Unknown File"

    def send_mobile_notification(filename, status_text, tag):
        try:
            import requests
            title_text = "Bill Approved!" if action == "approve" else "Bill Rejected!"
            requests.post(
                "https://ntfy.sh/dad_bills_client",
                data=f"Bill '{filename}' was {status_text}!",
                headers={
                    "Title": title_text,
                    "Priority": "high",
                    "Tags": tag
                },
                timeout=5
            )
        except Exception as ne:
            print(f"[Warning] ntfy.sh client push notification failed: {ne}")

    if action == "approve":
        try:
            # Delete from Google Drive
            try:
                service.files().delete(fileId=file_id).execute()
            except Exception as de:
                print(f"[Warning] Failed to delete file {file_id} from Drive: {de}")
            
            # Update Firestore status
            firebase_helper.update_file_status(file_id, "approved")
            
            send_mobile_notification(filename, "Approved & saved to laptop", "white_check_mark")
            return jsonify({"status": "saved"})
        except Exception as e:
            return jsonify({"error": f"Failed to complete approval: {str(e)}"}), 500
    
    # Action is reject
    try:
        try:
            service.files().delete(fileId=file_id).execute()
        except Exception as de:
            print(f"[Warning] Failed to delete file {file_id} from Drive: {de}")
            
        # Update Firestore status
        firebase_helper.update_file_status(file_id, "rejected")
        
        send_mobile_notification(filename, "Rejected", "x")
        return jsonify({"status": "rejected"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/status/<file_id>")
def get_status(file_id):
    status = firebase_helper.get_file_status(file_id)
    return jsonify({"status": status})

if __name__ == "__main__":
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = socket.gethostbyname(socket.gethostname())
        
    port = int(os.environ.get("PORT", 5000))
    print(f"\n[OK] Server running! Open locally: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
