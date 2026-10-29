# CampusConnect Lost & Found 🎓

A secure, privacy-first, lightweight, and modern campus Lost & Found web portal engineered for university communities.

---

## 🌟 Primary Capabilities

1. **Collegiate Design & Responsive UI:**
   - Navy-blue and gold collegiate visual identity.
   - Responsive design tested across mobile, tablet, and desktop viewports (`320px`, `375px`, `390px`, `768px`, `1024px`, and `1440px`).
   - Interactive Campus Discovery Rail with smooth horizontal momentum glide, 3D card perspective, and keyboard navigation.
2. **Camera & Photo Upload with Security Guardrails:**
   - **Take Photo & Upload Photo:** Mobile camera integration with `capture="environment"` and file-picker fallback with `accept="image/*"`.
   - **Instant Client-Side Preview:** Interactive preview card with Retake / Change and Remove controls.
   - **Server-Side Pillow Inspection:** Deep byte and structure validation for JPEG, PNG, and WebP (rejects disguised executables, PDFs, and corrupt streams).
   - **5 MB Size Limit & Downscaling:** Automatically enforces 5 MB limit and downscales large images (max 1200px) while maintaining aspect ratio.
   - **Privacy & Safety:** Strips all unnecessary EXIF metadata (camera specs, GPS coordinates) and uses cryptographically random UUID filenames to prevent path traversal.
   - **Atomic Cleanup:** Orphaned files are automatically deleted if database insertion fails.
   - **Card & Detail Displays:** Displays verified photo thumbnails on item cards, the showcase rail, and large views on item detail pages with clean fallback placeholders.
3. **Instant Search & Multi-Filters:**
   - Multi-term keyword search across titles, descriptions, campus buildings, categories, and poster aliases.
   - Filter by Item Type (*All*, *Lost Items*, *Found Items*), Category, and Status (*Open*, *Resolved*).
   - Tab badge counters remain consistent and accurate during filtered navigation.
3. **Safe Inquiry Interface (Zero Public Exposure):**
   - Student contact emails and phone numbers are **never** displayed on public directory cards or detail pages.
   - Finders and claimants send secure inquiries stored in the SQLite database.
4. **PIN Authorization & Owner Controls:**
   - Posters choose a 4-to-8 digit Security PIN upon submission.
   - PINs are cryptographically hashed using `werkzeug.security` (`scrypt` / `pbkdf2:sha256`) — plain text PINs are never stored.
   - Resolving, reopening, or unlocking the private inquiry inbox requires the poster's PIN.
5. **Robust Security & Abuse Prevention:**
   - **CSRF Protection:** Synchronizer tokens enforced on all state-changing POST forms via Flask-WTF.
   - **Rate Limiting:** Built-in abuse prevention via Flask-Limiter protecting item submissions, contact messages, and PIN verification against brute-force attacks.
   - **Strict Secret Management:** Fails safely in production if `SECRET_KEY` is not configured in environment variables.
   - **Hardened Cookies:** `HttpOnly`, `SameSite=Lax`, and `Secure` cookie enforcement over HTTPS.
   - **Security Headers:** Content-Security-Policy (CSP), `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, and `Referrer-Policy: strict-origin-when-cross-origin`.
   - **SQL Injection Prevention:** 100% of database queries utilize parameterized SQL statements (`?` placeholders).
   - **XSS Mitigation:** Automatic HTML entity escaping via Jinja2 templates on all user inputs.

---

## 💻 Tech Stack

- **Backend:** Python 3.10+ & Flask 3.x
- **Image Processing:** Pillow (PIL) 10+
- **Database:** SQLite 3 with Write-Ahead Logging (WAL) and foreign key constraints
- **Security:** Flask-WTF (CSRF), Flask-Limiter (Rate Limiting), Werkzeug (Password/PIN Hashing)
- **Environment:** python-dotenv
- **Testing:** pytest & unittest (isolated temporary database fixtures)
- **Frontend:** Semantic HTML5, Vanilla CSS3 (Custom design tokens, responsive media queries), Vanilla JavaScript

---

## 🚀 Quickstart Guide (Windows PowerShell)

### 1. Clone & Enter Project Directory
```powershell
cd C:\Users\ASUS\OneDrive\Desktop\CampusConnect
```

### 2. Create and Activate Virtual Environment
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install Tested Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Configure Environment
Copy the example configuration to `.env`:
```powershell
Copy-Item .env.example .env
```
*(In production, set `FLASK_ENV=production` and generate a unique `SECRET_KEY`.)*

### 5. Initialize the Database
```powershell
python manage_db.py init
```

### 6. Run the Application
For local development:
```powershell
python app.py
```
Visit **[http://127.0.0.1:5000](http://127.0.0.1:5000)** in your browser.

---

## 🧪 Running Automated Tests

CampusConnect includes a test suite covering routes, validation, search, filters, CSRF protection, rate limiting, PIN authorization, and data persistence on an isolated temporary database:

```powershell
pytest -v
```

All tests execute against isolated temporary databases and never touch production records.

---

## 🗄️ Database Management & Backup CLI (`manage_db.py`)

CampusConnect provides a CLI for database administration:

```powershell
# 1. Inspect database status (genuine reports vs demo items):
python manage_db.py status

# 2. Create an atomic online backup in the backups/ directory:
python manage_db.py backup

# 3. Clean all sample/demo records while preserving genuine user reports:
python manage_db.py clean

# 4. Initialize tables without seeding demo data:
python manage_db.py init

# 5. Apply database migrations (safe, repeatable schema migration):
python manage_db.py migrate

# 6. Reset tables to a clean, empty state (automatically creates pre-reset backup):
python manage_db.py reset-empty

# 7. Seed sample testing items (flagged with is_demo = 1):
python manage_db.py seed
```

---

## 🌐 Production Deployment Considerations

### SQLite Concurrency & Storage Limitations
- **WAL Mode Enabled:** CampusConnect automatically configures SQLite in `WAL` (Write-Ahead Logging) mode. This allows simultaneous read queries while a write transaction is executing, preventing readers from blocking writers.
- **Concurrency Scope:** SQLite in WAL mode handles typical campus traffic (thousands of daily page views, dozens of submissions per hour) smoothly on a single host.
- **Write Locking:** SQLite permits only one writer at a time. If your campus scales to hundreds of simultaneous writes per second across multiple server instances, migrate the database layer to PostgreSQL.
- **Persistent Storage:** SQLite stores records in a local file (`campusconnect.db`). When deploying in containers (Docker, Render, AWS ECS, Fly.io), you **must** mount a persistent disk volume to the database file path specified in `CAMPUSCONNECT_DB`. If deployed on an ephemeral container filesystem, restarting the container will destroy the database!

### Reverse Proxy & SSL Configuration
When deploying behind a reverse proxy (e.g., Nginx, Caddy, AWS ALB, Cloudflare, Fly.io):
- **Configure ProxyFix:** Set `NUM_PROXIES=1` (or matching hop count) in your `.env`. This ensures `request.remote_addr` correctly resolves client IPs for Flask-Limiter and enforces scheme detection (`https://`).
- **Enforce HTTPS & Secure Cookies:** Set `SESSION_COOKIE_SECURE=true`. When enabled, session cookies and CSRF tokens strictly require SSL transmission.
- **Fail-Safe Secret Validation:** Set `FLASK_ENV=production` and generate a cryptographically random secret of at least 16 characters (`python -c "import secrets; print(secrets.token_hex(32))"`). If `SECRET_KEY` is missing or contains placeholder values, the application will refuse to start to protect user sessions.

### Production WSGI Server
Do not run Flask's built-in development server in production. Instead, run with a production WSGI server:

**On Windows (PowerShell):**
```powershell
waitress-serve --port=5000 app:app
```

**On Linux / Docker:**
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

---

## 📁 Project File Structure

- **`app.py`**: Main Flask application entrypoint with security middleware, CSRF, rate limiting, and route handlers.
- **`image_utils.py`**: Secure image validation, Pillow content verification, EXIF stripping, resizing, and atomic file cleanup.
- **`database.py`**: SQLite database layer with WAL mode, atomic backups, parameterized queries, and indexes.
- **`manage_db.py`**: Safe administrative CLI for backups, status inspection, migrations, and maintenance.
- **`test_app.py`**: Automated test suite with dynamic test fixtures and isolated databases.
- **`uploads/`**: Dedicated storage directory for user-uploaded images (separate from source code and ignored by git).
- **`requirements.txt`**: Pinned, tested dependency definitions.
- **`.env.example`**: Template for environment variable configuration.
- **`.gitignore`**: Excludes cache files, virtual environments, database backups, and secrets.
- **`templates/`**:
  - `base.html`: Shared navigation, branding, flash alerts, and collegiate footer.
  - `index.html`: Home page with live stats, interactive showcase rail, search bar, and lost/found sections.
  - `submit.html`: Item reporting form with client and server-side validation.
  - `item_detail.html`: Item details, PIN-protected resolution controls, and private inbox interface.
  - `about.html`: Guide and architecture documentation.
  - `400.html`: Custom branded CSRF / Bad Request error page.
  - `404.html`: Custom branded Page Not Found error page.
  - `429.html`: Custom branded Rate Limit Exceeded error page.
  - `500.html`: Custom branded Internal Server Error page.
- **`static/css/styles.css`**: Responsive design tokens, media queries for 320px–1440px, and navy-and-gold styling.
- **`static/js/main.js`**: Vanilla JavaScript for mobile navigation, discovery rail dragging, and PIN visibility toggle.
- **`backups/`**: Directory for safe timestamped database backups.
