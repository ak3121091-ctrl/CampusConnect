# CampusConnect Lost & Found 🎓

A privacy-focused, lightweight, and modern campus Lost & Found web application built for college hackathons.

---

## 🌟 Key Features

1. **Interactive Campus Discovery Rail:**
   - Horizontal sliding showcase of recently reported campus items inspired by the 21st.dev `ClothingRailHero`.
   - Physics-based momentum drag-to-scroll, arrow navigation, keyboard controls, and 3D card tilt on hover.
2. **Responsive Home Page & Search Bar:**
   - Instant search across item titles, locations, descriptions, categories, and poster aliases.
   - Quick statistics dashboard (Total Items, Open Lost, Open Found, Reunited).
3. **Separate Lost & Found Sections:**
   - Distinct sections on the home page for **Lost Items** and **Found Items**.
   - Tab toggles: *All Items*, *Lost Items*, *Found Items*.
4. **Multi-Filter Controls:**
   - Filter by Category (Electronics, Student IDs & Keys, Books, Bags, Clothing, Other).
   - Filter by Status (*All*, *Open Only*, *Resolved Only*).
5. **Rich Information Cards:**
   - Highlights item title, category, campus building/location, date, and status badges.
   - Clear visual pill badges: `LOST`, `FOUND`, `OPEN`, `RESOLVED`, and `DEMO DATA`.
5. **Item Submission Form:**
   - Fast reporting for lost or found belongings.
   - Server-side validation ensuring valid inputs and clean data.
6. **Safe Contact & Inquiry Interface:**
   - **Zero Public Exposure:** Student email addresses and phone numbers are never printed on public web pages.
   - Anyone who finds an item or wants to claim it submits a secure inquiry message stored directly inside the SQLite database.
   - The message is kept safe without making false claims about third-party email/SMS delivery.
7. **PIN-Protected Authorization:**
   - When posting an item, the owner sets a 4-to-8 digit Security PIN.
   - The PIN is securely hashed using `werkzeug.security` (PBKDF2/SHA256).
   - Anonymous visitors **cannot** modify or resolve items without the owner's PIN.
   - The owner can unlock and read all inquiries sent to them using their PIN.
8. **Pre-Seeded Demo Data:**
   - 6 realistic sample items across campus spots (Library, Science Hall, Rec Center, Bus Stop).
   - Demo records are clearly badged `DEMO DATA`.
   - Demo PIN for testing: `1234`.

---

## 💻 Tech Stack (100% Free & Local)

- **Backend:** Python Flask
- **Database:** Python built-in `sqlite3` (parameterized queries for SQL injection prevention)
- **Frontend:** Semantic HTML5 & Jinja2 Templates
- **Styling:** Vanilla CSS with responsive design, modern design tokens, and accessible contrast
- **Interactions:** Vanilla JavaScript (tabs, mobile drawer, PIN formatting)
- **Dependencies:** Zero paid APIs, zero subscriptions, zero cloud accounts required.

---

## 🚀 How to Run the Application

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Start the Server
```bash
python app.py
```

### 3. Open in Your Browser
Visit: **[http://127.0.0.1:5000](http://127.0.0.1:5000)**

---

## 🧪 Running the Automated Test Suite

To verify all 13 integration and security tests:
```bash
python test_app.py
```

All tests execute parameterized SQL checks, form validation, PIN hashing, status updates, and privacy protections.

---

## 📁 File Structure & Beginner Guide

- **`app.py`**: The main Flask server containing all route handlers (`/`, `/items/new`, `/items/<id>`, `/items/<id>/status`, `/items/<id>/inbox`, `/about`), server-side validation, and security checks.
- **`database.py`**: Manages the SQLite database connection, table creation, demo seeding, and parameterized queries using Python's standard `sqlite3` library.
- **`campusconnect.db`**: The SQLite database file created automatically on initial run.
- **`templates/`**:
  - **`base.html`**: Shared layout with navigation, brand icon, flash alerts, and footer.
  - **`index.html`**: The home page with search bar, filter tabs, stats, and separate Lost/Found grids.
  - **`_item_card.html`**: Reusable item card component with badge cluster.
  - **`submit.html`**: Form to submit a lost or found item.
  - **`item_detail.html`**: Detailed view, safe contact inquiry form, and PIN-protected owner controls.
  - **`about.html`**: Hackathon guide and testing instructions for judges.
  - **`404.html`**: Friendly 404 page for missing records.
- **`static/css/styles.css`**: Responsive styling, custom badge colors, and mobile-friendly layout.
- **`static/js/main.js`**: Interactive tab filters, mobile menu toggle, and client-side PIN guards.
- **`requirements.txt`**: Minimal requirements (`Flask>=3.0.0`, `Werkzeug>=3.0.0`).
- **`test_app.py`**: Automated test suite verifying all routes, persistence, and security controls.
