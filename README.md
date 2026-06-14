# 📁 Dad Bills — Hybrid Cloud-Local Document Coordinator

A hybrid web application that coordinates file uploads from a mobile website and downloads them to a local computer directory. It utilizes **Google Drive** for temporary file storage, **Firebase Firestore** for metadata sync, and a **Flask** client-proxy to securely retrieve files onto a laptop disk.

---

## 🗺️ How It Works

```
                        ┌────────────────────────┐
                        │   Dad (Mobile Client)  │
                        └───────────┬────────────┘
                                    │
                              POST  │ /upload
                                    ▼
                      ┌────────────────────────────┐
                      │   Cloud Server (Render)    │
                      └──────┬──────────────┬──────┘
                             │              │
                       Store │              │ Metadata
                             ▼              ▼
                     ┌──────────────┐      ┌─────────────┐
                     │ Google Drive │      │  Firebase   │
                     └──────────────┘      └─────────────┘
                             ▲              ▲
                      Stream │              │ Poll /decide
                             └──────┬───────┘
                                    │
                                    │ Local Proxy
                      ┌─────────────┴──────────────┐
                      │   Local Admin (Laptop)     │
                      └─────────────┬──────────────┘
                                    │
                              Saves │ F:\Bills (or ~/Bills)
                                    ▼
                        ┌────────────────────────┐
                        │    Laptop Hard Drive   │
                        └────────────────────────┘
```

### 1. Client Side (Dad's Mobile Phone)
* **Accessing the App:** Open the cloud-deployed URL: `https://dads-bills.onrender.com`.
* **Uploading a Bill:** Dad chooses a category (Current, Water, Jio Fiber, or custom), gives it a display name, uploads a PDF or image, and clicks **Send**.
* **Storage:** 
  * The file is uploaded to the user's Google Drive under a folder named `DadBillsSync/<Category Name>`.
  * The file metadata (name, folder, status, timestamp) is registered in a Firebase Firestore collection called `bills` with a `pending` status.
  * A mobile push notification is sent to the admin via `ntfy.sh` (topic: `dad_bills_admin`).
* **Real-time Approval Status:** The client page displays a loading screen and polls `/status/<file_id>` every 2 seconds, displaying a success or reject alert the moment the admin makes a decision.

### 2. Admin Side (Your Laptop)
* **Accessing the App:** Open `http://localhost:5000/admin` in a web browser while the **Local Admin Client** is running.
* **Reviewing Bills:** 
  * The page automatically pulls the latest `pending` items from Firestore every 5 seconds (if "Auto Check" is active).
  * You can preview files in the browser.
* **Making a Decision:**
  * **Approve:** Downloads the raw binary from Google Drive via the proxy, saves it to your laptop storage (e.g., `F:\Bills\<Category Folder>` or `~/Bills` if the external drive is disconnected), triggers a local Windows desktop notification, deletes the temporary file from Google Drive, and marks it as `approved` in Firebase.
  * **Reject:** Deletes the temporary file from Google Drive and updates the status to `rejected` in Firebase.

---

## 🚀 Running the Local Admin Client (Laptop Shortcuts)

To make running the local application on your laptop as quick as possible, the project includes background runner shortcuts:

* ### 🟢 Start Local Admin (Background)
  Double-click **`run_background.vbs`** in the project folder.
  * Runs the local script in the background (`local_admin.py` on port `5000`).
  * Displays a pop-up confirmation alert.
  * You can now open your browser and navigate to `http://localhost:5000/admin`.

* ### 🔴 Stop Local Admin
  Double-click **`stop_background.bat`** in the project folder.
  * Safely finds and terminates any background Python instance running the `local_admin.py` proxy.
  * Outputs a terminal message confirming the stop.

---

## 🛠️ Installation & Setup (One-time Setup)

### 1. Install Dependencies
Open your terminal in the project directory and install the required Python libraries:
```bash
pip install -r requirements.txt
```

### 2. File Configuration (Git-Ignored Secrets)
Place these files in the root directory:
* **`credentials.json`**: Google OAuth client ID secrets (downloaded from the Google Cloud Console).
* **`firebase-credentials.json`**: Firebase service account credentials (downloaded from Firebase Project Settings).
* **`cloud_url.txt`**: A plaintext file containing the URL of your deployed Render service (e.g., `https://dads-bills.onrender.com`). The local client uses this to know where the server resides.

---

## ☁️ Cloud Deployment Configuration (Render)

1. Create a **Web Service** on Render pointing to your GitHub repository.
2. **Start Command:** `python server.py`
3. In the **Environment** tab:
   * **Add Environment Variable:**
     * **Key:** `FIREBASE_CREDENTIALS`
     * **Value:** Copy/paste the entire JSON text from your `firebase-credentials.json` file.
   * **Add Secret File:**
     * **Filename:** `credentials.json`
     * **Contents:** Copy/paste the entire JSON text from your Google OAuth `credentials.json` file.
4. **Google Cloud Console Update:**
   Add `https://your-service-name.onrender.com/oauth2callback` to your OAuth Client's **Authorized Redirect URIs** so Google allows cloud-based logins.