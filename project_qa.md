# Dad Bills - Project Architecture & Q&A Reference

This document provides a comprehensive overview of how the **Dad Bills** application operates. It covers the flow of data, network mechanisms (sockets, TCP, UDP), notification services, role-based controls, and client updates.

---

## 🗺️ Project Architecture Overview

```mermaid
graph TD
    subgraph Client (Phone / Dad)
        UploadForm[1. Uploads PDF Form]
        LiveStatus[6. Polls /status/<id> for decisions]
    end

    subgraph Server (Flask Backend on Laptop)
        FlaskUpload[2. Handles /upload, saves to pending_uploads/]
        Plyer[3. Shows local Windows Notification]
        NtfyAdmin[4. Sends ntfy.sh Admin Push Alert]
        DecideRoute[7. Handles /decide/<id>/approve or reject]
    end

    subgraph Admin Dashboard (Laptop / index.html)
        PendingList[5. Auto Check polls /pending]
        ReviewModal[Allows reviewing PDF & deciding]
    end

    subgraph Storage
        DiskBills[(F:\Bills or ~/Bills)]
    end

    UploadForm -->|POST /upload| FlaskUpload
    FlaskUpload --> Plyer
    FlaskUpload --> NtfyAdmin
    NtfyAdmin -->|Push Alert| ReviewModal
    PendingList -->|GET /pending| DecideRoute
    DecideRoute -->|Approve & Save| DiskBills
    LiveStatus -->|GET /status/<id>| DecideRoute
```

---

## ❓ Questions & Detailed Answers

### Q1: How does the overall application work?
The application is a web-based document coordination system built using a **Flask** backend (Python) and a **Tailwind CSS/JavaScript** frontend.
* It allows users on the local network (e.g., Dad on his mobile phone) to send PDF invoices to your laptop.
* Instead of saving the bills immediately to their final destination, they are stored in a **pending queue** (`pending_uploads/` directory on disk and `PENDING` dictionary in memory) to prevent data loss if the server restarts.
* The Admin (on the laptop) can review the bills via the `/admin` dashboard.
* If approved, the files are moved to their permanent folders (e.g., `F:\Bills\Current Bill`). If rejected, they are cleaned up.

---

### Q2: How is the upload done?
The upload happens in two stages (Client-side trigger and Server-side handler):

#### 1. Client-Side (HTML / JS)
The client selects a category, fills in a name (either text or via a date picker that formats to `DD-MM-YYYY`), and selects a PDF file. Upon clicking "Send", JavaScript compiles this data into a `FormData` object and transmits it via an HTTP POST request:
```javascript
// index.html (Lines 1043-1052)
const formData = new FormData();
formData.append("name", name);
formData.append("category", category);
formData.append("custom_folder", customFolder);
formData.append("pdf", selectedFile);

fetch("/upload", {
  method: "POST",
  body: formData,
})
```

#### 2. Server-Side (Python Flask)
The `/upload` route in `server.py` receives the files. It:
1. Extracts variables (`name`, `category`, `custom_folder`, `pdf`).
2. Generates a unique millisecond timestamp `file_id` (e.g., `17154210300`).
3. Saves a metadata `.json` file and a raw `.pdf` binary file inside the temporary `pending_uploads/` folder.
4. Adds the data to the in-memory `PENDING` dictionary.

---

### Q3: How is the file stored in the folders?
When the Admin approves a bill, it is written to the destination folder using specific rules:

#### 1. Folder Selection & Falling Back
The server tries to write to the primary folder `F:\Bills` (which might be an external drive or shared space). If `F:\` is unplugged, missing, or write-protected, it handles the error gracefully and falls back to a folder named `Bills` in the user's home directory (`~/Bills`):
```python
# server.py (Lines 46-63)
def get_save_folder(folder_name):
    try:
        # Check if F:\Bills can be written to
        target = os.path.join(BASE_DIR, folder_name)
        os.makedirs(target, exist_ok=True)
        # Test write permission by writing a temp file
        test_file = os.path.join(target, ".write_test")
        with open(test_file, "w") as f:
            f.write("")
        os.remove(test_file)
        return target
    except Exception:
        # Fallback to local user home folder Bills
        fallback_base = os.path.join(os.path.expanduser("~"), "Bills")
        target = os.path.join(fallback_base, folder_name)
        os.makedirs(target, exist_ok=True)
        return target
```

#### 2. Resolving Filename Clashes
If a file with the same name already exists in that folder (e.g. `2026-05-31.pdf`), the server appends an incrementing counter (`_1`, `_2`, etc.) to prevent overwriting:
```python
# server.py (Lines 232-237)
counter = 1
while os.path.exists(path):
    filename = f"{base}_{counter}{ext}"
    path = os.path.join(save_dir, filename)
    counter += 1
```

---

### Q4: What network methods are used?

The project relies on **HTTP over TCP/IP** for normal application behavior, and a clever **UDP** socket trick to auto-detect its local IP address.

#### TCP vs. UDP in this project:
* **TCP (Transmission Control Protocol)**: Used for all web pages and file transfers (`/upload`, `/pending`, `/decide`). TCP is connection-oriented and reliable. If packets of your PDF file are dropped, TCP guarantees they will be retransmitted so the PDF isn't corrupted.
* **UDP (User Datagram Protocol)**: Used *only once* on startup to detect the computer's network IP. UDP is connectionless and fast. It doesn't perform any handshakes or check if the destination is listening.

#### The Local IP Detection Trick:
Instead of forcing you to look up your laptop's IP address manually to connect your phone, the server finds it automatically on startup:
```python
# server.py (Lines 271-277)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # 1. Create UDP socket
s.connect(("8.8.8.8", 80))                           # 2. Pretend to connect to Google DNS
ip = s.getsockname()[0]                              # 3. Retrieve the local IP used by the OS
s.close()                                            # 4. Close the socket immediately
```
> [!NOTE]
> Because it's a **UDP** socket, `s.connect` does not send any packets over the internet. It simply asks the Windows Routing Table: *"Hey, if we wanted to talk to 8.8.8.8, which network card IP would we use?"* The system returns your local network IP (e.g., `192.168.1.15`).

---

### Q5: What notifications are used for the mobile and the client?

The system uses two kinds of notifications to keep both parties updated:

#### 1. Windows Local Desktop Notifications (`plyer`)
When a file is uploaded, the server triggers a native Windows notification box on the laptop to alert the admin:
```python
from plyer import notification
notification.notify(
    title="New Bill Received! 📁",
    message=f"Name: {name}\nFile: {file.filename}\nFolder: {folder_name}",
    app_name="Dad Bills",
    timeout=10
)
```

#### 2. Mobile Push Notifications via `ntfy.sh`
**ntfy.sh** is a free, open-source push notification service that does not require you to sign up or use developer keys. It works by having your phone subscribe to a specific public **topic name** (like subscribing to a newsletter channel).
* **When a client uploads a bill**: The backend sends an HTTP POST request to `https://ntfy.sh/dad_bills_admin` notifying the Admin's phone.
* **When an Admin approves/rejects**: The backend sends a POST request to `https://ntfy.sh/dad_bills_client` notifying the Client's phone.

```python
# server.py (Lines 139-148)
import requests 
requests.post(
    "https://ntfy.sh/dad_bills_admin",
    data=f"New Bill '{file.filename}' uploaded by {name} (Folder: {folder_name}).",
    headers={
        "Title": "New Bill Pending Approval!",
        "Priority": "high",
        "Tags": "incoming_envelope"
    },
    timeout=5
)
```
> [!TIP]
> **How does it reach your mobile?**
> You install the **ntfy mobile app** (Android/iOS) and subscribe to the topic name `dad_bills_admin` or `dad_bills_client`. The app keeps a continuous connection to the `ntfy.sh` server (using WebSockets or native Apple/Google push networks) to instantly alert you when a new message is posted to those topics.

---

### Q6: What is the "Auto Check" toggle button?

The **Auto Check** switch is a client-side toggle built in HTML/JavaScript (visible on desktop viewports by default):
* When enabled, it activates a background timer (`setInterval`) that queries the `/pending` endpoint on the server every **5 seconds**:
  ```javascript
  // index.html (Lines 1510-1516)
  function startPolling() {
    if (autoPollTimer) clearInterval(autoPollTimer);
    autoPollTimer = setInterval(() => {
      fetchPendingList(false);
    }, 5000);
  }
  ```
* This means you don't have to manually click the "Refresh" button; the pending bills automatically appear on the Admin's dashboard as soon as they are uploaded.
* The selection is stored in the browser's `localStorage` (saved as `autoCheck = true` or `false`) to ensure your preference remains saved even if you close the tab.

---

### Q7: How is approval restricted for the Admin only?

Access roles are controlled simply using route parameters and front-end rendering logic:
1. **Routing**:
   * The home page `/` and `/client` render the page with `is_admin=False`.
   * The page `/admin` renders the page with `is_admin=True`.
2. **DOM Controls**:
   The backend injects this boolean value directly into the Javascript global namespace:
   ```javascript
   const IS_ADMIN = "{{ 'true' if is_admin else 'false' }}" === "true";
   ```
3. **Restricting Buttons**:
   When the list of pending bills is drawn in the browser, the Javascript checks if `IS_ADMIN` is true. If it is **false**, it replaces the Approve / Reject / Review buttons with a simple text box saying: `⏳ Waiting for Admin` and hides the Auto Check toggle switch.

---

### Q8: How do pending requests show for the client?

When a client (like your Dad on his phone) uploads a bill:
1. The upload form is replaced with a **Success screen** containing details of the bill.
2. The page starts an active status-check loop specifically for that document ID using `startStatusPolling(fileId)` (running every **2 seconds**):
   ```javascript
   // index.html (Lines 1526-1573)
   function startStatusPolling(fileId) {
     statusPollTimer = setInterval(() => {
       fetch(`/status/${fileId}`)
         .then((res) => res.json())
         .then((data) => {
           if (data.status === "approve") {
             // Stop polling and display "Approved & Saved! 🎉" in a green box
           } else if (data.status === "reject") {
             // Stop polling and display "Rejected by laptop ❌" in a red box
           }
         });
     }, 2000);
   }
   ```
3. This creates a real-time responsive interface on the phone, immediately displaying the final decision the moment you click "Approve" or "Reject" on your laptop!
