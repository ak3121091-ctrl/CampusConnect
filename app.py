"""
app.py - CampusConnect Lost & Found Flask Application
------------------------------------------------------
A secure, privacy-preserving, and mobile-responsive web application
built for university campus lost and found management.

Features:
- Parameterized SQLite3 persistence (zero external paid APIs).
- Strict environment-driven secret configuration without hardcoded fallback.
- Full CSRF protection on state-changing forms.
- Rate limiting and abuse prevention.
- Cryptographic PIN hashing and protected inbox authorization.
- Zero public exposure of student contact info.
- Production error handlers and security response headers.
"""

import os
import re
import datetime
import logging
import secrets
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, abort, session, send_from_directory
)
from werkzeug.security import check_password_hash
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
import database
from image_utils import validate_and_process_image, delete_image_file

# Load environment configuration from .env file if present
load_dotenv()

app = Flask(__name__)

# ---------------------------------------------------------------------
# Environment Configuration & Secret Key Management
# ---------------------------------------------------------------------
env_name = os.environ.get('FLASK_ENV', os.environ.get('CAMPUSCONNECT_ENV', 'development')).strip().lower()
is_production = env_name == 'production'

# Known insecure or default placeholder values that must never be used in production
INSECURE_PLACEHOLDER_SECRETS = {
    'your-production-secret-key-replace-with-at-least-32-characters',
    'change-me',
    'changeme',
    'secret',
    'secretkey',
    'secret_key',
    'development',
    'dev',
}

# In production, require SECRET_KEY from environment variables and fail safely if missing or default
secret_key = os.environ.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY')
if is_production:
    if not secret_key:
        raise RuntimeError(
            "CRITICAL SECURITY CONFIGURATION ERROR: The 'SECRET_KEY' environment variable "
            "must be configured in production environments. Application will not start."
        )
    if secret_key.strip() in INSECURE_PLACEHOLDER_SECRETS or len(secret_key.strip()) < 16:
        raise RuntimeError(
            "CRITICAL SECURITY CONFIGURATION ERROR: The production 'SECRET_KEY' must be "
            "a strong, unique cryptographic secret (at least 16 characters). Do not use default or placeholder keys."
        )

if not secret_key:
    # Development/Testing fallback: ephemeral random key or explicit dev key with warning
    secret_key = os.environ.get('CAMPUSCONNECT_DEV_SECRET') or secrets.token_hex(32)
    logging.warning("CampusConnect is running with an ephemeral development SECRET_KEY. Set SECRET_KEY in production.")

app.secret_key = secret_key

# ---------------------------------------------------------------------
# Cookie Security, CSRF Hardening & Proxy Support
# ---------------------------------------------------------------------
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
is_secure_cookie = os.environ.get(
    'SESSION_COOKIE_SECURE',
    'true' if is_production else 'false'
).strip().lower() in ('true', '1', 't')
app.config['SESSION_COOKIE_SECURE'] = is_secure_cookie
app.config['WTF_CSRF_SSL_STRICT'] = is_secure_cookie
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(hours=2)

# Upload Configuration (Separated from source code)
app.config['UPLOAD_FOLDER'] = os.environ.get('CAMPUSCONNECT_UPLOAD_DIR') or os.path.join(database.BASE_DIR, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max request payload
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Optional reverse-proxy headers support (ProxyFix) for deployments behind Nginx/ALB
num_proxies = int(os.environ.get('NUM_PROXIES', '0'))
if num_proxies > 0:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=num_proxies, x_proto=num_proxies, x_host=num_proxies)

# ---------------------------------------------------------------------
# CSRF Protection
# ---------------------------------------------------------------------
csrf = CSRFProtect(app)

# ---------------------------------------------------------------------
# Rate Limiting & Abuse Prevention
# ---------------------------------------------------------------------
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["400 per hour", "80 per minute"],
    storage_uri=os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
)

CATEGORIES = [
    'Electronics',
    'Student IDs & Keys',
    'Books & Stationery',
    'Bags & Backpacks',
    'Clothing & Accessories',
    'Other / Miscellaneous'
]


# Ensure tables and indexes are ready on startup (clean initialization, no demo data auto-seeding)
with app.app_context():
    database.init_db(seed_demo=False)


# ---------------------------------------------------------------------
# Security Response Headers
# ---------------------------------------------------------------------
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:;"
    )
    return response


# ---------------------------------------------------------------------
# Validation Helpers
# ---------------------------------------------------------------------
def is_valid_contact(contact_str):
    """
    Validates that a contact string looks like a reasonable campus email or phone number.
    Must have either an email pattern (user@domain.tld) or at least 7 digits for phone numbers.
    """
    if not contact_str or len(contact_str) < 5 or len(contact_str) > 100:
        return False
    # Check email format
    if '@' in contact_str and '.' in contact_str.split('@')[-1]:
        return True
    # Check phone number format (at least 7 digits)
    digits = re.sub(r'\D', '', contact_str)
    if len(digits) >= 7:
        return True
    return False


# ---------------------------------------------------------------------
# Route: Home Page (Search, Filters, Separate Lost & Found Sections)
# ---------------------------------------------------------------------
@app.route('/')
def index():
    raw_query = request.args.get('q', '').strip()
    search_query = raw_query[:100] if len(raw_query) > 100 else raw_query
    raw_type = request.args.get('type', 'all').strip().lower()
    raw_category = request.args.get('category', 'All').strip()
    raw_status = request.args.get('status', 'all').strip().lower()

    # Normalize parameters to prevent empty or invalid filter values from blanking out UI
    item_type = raw_type if raw_type in ('lost', 'found') else 'all'
    category = raw_category if raw_category in CATEGORIES else 'All'
    status = raw_status if raw_status in ('open', 'resolved') else 'all'

    filter_type = item_type if item_type in ('lost', 'found') else None
    filter_status = status if status in ('open', 'resolved') else None
    filter_category = category if category != 'All' else None

    # Fetch items matching current search, category, and status filters (without type restriction)
    # This provides accurate, helpful counts on the All / Lost / Found tab badges
    all_matching_items = database.get_items(
        search_query=search_query,
        item_type=None,
        category=filter_category,
        status=filter_status
    )

    matching_lost = [item for item in all_matching_items if item['item_type'] == 'lost']
    matching_found = [item for item in all_matching_items if item['item_type'] == 'found']

    total_count = len(all_matching_items)
    lost_count = len(matching_lost)
    found_count = len(matching_found)

    # Now filter by item_type if the user selected a specific tab
    if filter_type == 'lost':
        items = matching_lost
        lost_items = matching_lost
        found_items = []
    elif filter_type == 'found':
        items = matching_found
        lost_items = []
        found_items = matching_found
    else:
        items = all_matching_items
        lost_items = matching_lost
        found_items = matching_found

    # Highlighted showcase items for the interactive horizontal rail
    rail_items = items[:8]

    # Overview statistics
    stats = database.get_statistics()

    return render_template(
        'index.html',
        items=items,
        lost_items=lost_items,
        found_items=found_items,
        rail_items=rail_items,
        total_count=total_count,
        lost_count=lost_count,
        found_count=found_count,
        stats=stats,
        categories=CATEGORIES,
        current_search=search_query,
        current_type=item_type,
        current_category=category,
        current_status=status
    )


# ---------------------------------------------------------------------
# Route: Safely Serve Uploaded Item Photos
# ---------------------------------------------------------------------
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """
    Safely serves user uploaded item images from the upload directory.
    Prevents path traversal by strictly matching basename and verifying file existence.
    """
    safe_name = os.path.basename(filename)
    if safe_name != filename or not safe_name or '..' in filename or filename.startswith('/'):
        abort(404)
    upload_dir = app.config.get('UPLOAD_FOLDER', os.path.join(database.BASE_DIR, 'uploads'))
    file_path = os.path.join(upload_dir, safe_name)
    if not os.path.isfile(file_path):
        abort(404)
    return send_from_directory(upload_dir, safe_name)


# ---------------------------------------------------------------------
# Route: Submit a New Lost or Found Item
# ---------------------------------------------------------------------
@app.route('/items/new', methods=['GET', 'POST'])
@limiter.limit("20 per hour; 5 per minute", methods=["POST"])
def submit_item():
    today = datetime.date.today().strftime('%Y-%m-%d')

    if request.method == 'POST':
        item_type = request.form.get('item_type', '').strip().lower()
        title = request.form.get('title', '').strip()
        category = request.form.get('category', '').strip()
        location = request.form.get('location', '').strip()
        event_date = request.form.get('event_date', '').strip()
        description = request.form.get('description', '').strip()
        poster_name = request.form.get('poster_name', '').strip()
        poster_contact = request.form.get('poster_contact', '').strip()
        pin = request.form.get('pin', '').strip()

        form_data = {
            'item_type': item_type,
            'title': title,
            'category': category,
            'location': location,
            'event_date': event_date,
            'description': description,
            'poster_name': poster_name,
            'poster_contact': poster_contact,
            'pin': pin
        }

        # Server-Side Validation
        errors = []

        if item_type not in ('lost', 'found'):
            errors.append("Please specify whether this item was 'Lost' or 'Found'.")

        if not title or len(title) < 3 or len(title) > 100:
            errors.append("Title must be between 3 and 100 characters.")

        if category not in CATEGORIES:
            errors.append("Please select a valid category from the list.")

        if not location or len(location) < 3 or len(location) > 120:
            errors.append("Campus location must be between 3 and 120 characters.")

        if not event_date:
            errors.append("Please provide the date when the item was lost or found.")
        else:
            try:
                parsed_date = datetime.date.fromisoformat(event_date)
                if parsed_date > datetime.date.today():
                    errors.append("Date cannot be in the future.")
                elif parsed_date.year < 2000:
                    errors.append("Please provide a valid recent date (year 2000 or later).")
            except ValueError:
                errors.append("Invalid date format. Please use YYYY-MM-DD.")

        if not description or len(description) < 5 or len(description) > 2000:
            errors.append("Description must be between 5 and 2000 characters.")

        if not poster_name or len(poster_name) < 2 or len(poster_name) > 60:
            errors.append("Your name must be between 2 and 60 characters.")

        if not is_valid_contact(poster_contact):
            errors.append("Please provide a valid contact email address or phone number (5 to 100 characters).")

        if not pin or not re.match(r'^\d{4,8}$', pin):
            errors.append("Security PIN must be 4 to 8 digits (numeric only).")

        if errors:
            for err in errors:
                flash(err, 'error')
            return render_template(
                'submit.html',
                categories=CATEGORIES,
                today=today,
                form_data=form_data
            )

        # Process and validate image upload if provided (Pillow validation, stripping EXIF, resizing)
        photo_storage = (
            request.files.get('photo_camera') or
            request.files.get('photo_file') or
            request.files.get('image')
        )
        saved_image_filename = None
        if photo_storage and photo_storage.filename and photo_storage.filename.strip():
            try:
                saved_image_filename = validate_and_process_image(
                    photo_storage,
                    app.config['UPLOAD_FOLDER']
                )
            except ValueError as img_err:
                flash(str(img_err), 'error')
                return render_template(
                    'submit.html',
                    categories=CATEGORIES,
                    today=today,
                    form_data=form_data
                )

        # Insert item securely into SQLite (ensuring atomic cleanup if DB write fails)
        try:
            new_item_id = database.create_item(
                item_type=item_type,
                title=title,
                category=category,
                location=location,
                event_date=event_date,
                description=description,
                poster_name=poster_name,
                poster_contact=poster_contact,
                pin_plain=pin,
                image_filename=saved_image_filename
            )
        except Exception as db_err:
            if saved_image_filename:
                delete_image_file(saved_image_filename, app.config['UPLOAD_FOLDER'])
            logging.error("Failed to insert item into database: %s", str(db_err), exc_info=True)
            flash("A database error occurred while creating your report. Please try again.", 'error')
            return render_template(
                'submit.html',
                categories=CATEGORIES,
                today=today,
                form_data=form_data
            )

        flash(
            f"Success! Your {item_type.upper()} item was listed. "
            f"Please remember your Security PIN to resolve or view inquiries later.",
            'success'
        )
        return redirect(url_for('item_detail', item_id=new_item_id))

    preset_type = request.args.get('type', 'lost').strip().lower()
    initial_type = preset_type if preset_type in ('lost', 'found') else 'lost'

    return render_template(
        'submit.html',
        categories=CATEGORIES,
        today=today,
        form_data={'item_type': initial_type}
    )


# ---------------------------------------------------------------------
# Route: Item Detail Page (Safe Viewing, Inquiries, Poster Verification)
# ---------------------------------------------------------------------
@app.route('/items/<int:item_id>')
def item_detail(item_id):
    if item_id <= 0:
        abort(404)

    item = database.get_item_by_id(item_id)
    if not item:
        abort(404)

    contact_draft = None
    if session.get('contact_draft') and session['contact_draft'].get('item_id') == item_id:
        contact_draft = session.pop('contact_draft', None)

    return render_template(
        'item_detail.html',
        item=item,
        unlocked_messages=None,
        pin_verified=False,
        contact_draft=contact_draft
    )


# ---------------------------------------------------------------------
# Route: Safe Contact Request Interface (Submit an inquiry)
# ---------------------------------------------------------------------
@app.route('/items/<int:item_id>/contact', methods=['GET', 'POST'])
@limiter.limit("20 per hour; 5 per minute", methods=["POST"])
def submit_contact_request(item_id):
    if item_id <= 0:
        abort(404)

    item = database.get_item_by_id(item_id)
    if not item:
        abort(404)

    if request.method == 'GET':
        return redirect(url_for('item_detail', item_id=item_id, _anchor='contactSection'))

    sender_name = request.form.get('sender_name', '').strip()
    sender_contact = request.form.get('sender_contact', '').strip()
    message = request.form.get('message', '').strip()

    errors = []
    if not sender_name or len(sender_name) < 2 or len(sender_name) > 60:
        errors.append("Please enter your name (between 2 and 60 characters).")
    if not is_valid_contact(sender_contact):
        errors.append("Please provide a valid contact email address or phone number (between 5 and 100 characters).")
    if not message or len(message) < 5 or len(message) > 2000:
        errors.append("Inquiry message must be between 5 and 2000 characters.")

    if errors:
        for err in errors:
            flash(err, 'error')
        session['contact_draft'] = {
            'item_id': item_id,
            'sender_name': sender_name,
            'sender_contact': sender_contact,
            'message': message
        }
        return redirect(url_for('item_detail', item_id=item_id, _anchor='contactSection'))

    # Clear draft on successful submission
    if session.get('contact_draft') and session['contact_draft'].get('item_id') == item_id:
        session.pop('contact_draft', None)

    # Save inquiry into SQLite database
    database.create_contact_request(item_id, sender_name, sender_contact, message)

    flash(
        "Inquiry saved! Your message has been safely recorded in CampusConnect. "
        "The poster can view your message in their private item inbox using their secret PIN.",
        'success'
    )
    return redirect(url_for('item_detail', item_id=item_id, _anchor='contactSection'))


# ---------------------------------------------------------------------
# Route: Update Item Status (Resolve or Reopen with PIN)
# ---------------------------------------------------------------------
@app.route('/items/<int:item_id>/status', methods=['GET', 'POST'])
@limiter.limit("15 per minute; 40 per hour", methods=["POST"])
def update_status(item_id):
    if item_id <= 0:
        abort(404)

    item = database.get_item_by_id(item_id)
    if not item:
        abort(404)

    if request.method == 'GET':
        return redirect(url_for('item_detail', item_id=item_id, _anchor='resolutionControls'))

    submitted_pin = request.form.get('pin', '').strip()
    target_status = request.form.get('status', 'resolved').strip()

    if target_status not in ('open', 'resolved'):
        flash("Invalid status selected.", 'error')
        return redirect(url_for('item_detail', item_id=item_id, _anchor='resolutionControls'))

    if not submitted_pin or not re.match(r'^\d{4,8}$', submitted_pin):
        flash("Invalid Security PIN format. PIN must be 4 to 8 digits.", 'error')
        return redirect(url_for('item_detail', item_id=item_id, _anchor='resolutionControls'))

    # Security Check: Verify PIN hash
    pin_hash = item['pin_hash'] if 'pin_hash' in item.keys() else None
    if not pin_hash or not check_password_hash(pin_hash, submitted_pin):
        flash(
            "Authorization Failed: Incorrect Security PIN. "
            "Only the original poster with the correct PIN can change this item's status.",
            'error'
        )
        return redirect(url_for('item_detail', item_id=item_id, _anchor='resolutionControls'))

    # Update in database
    database.update_item_status(item_id, target_status)
    flash(
        f"Item status successfully updated to '{target_status.upper()}'!",
        'success'
    )
    return redirect(url_for('item_detail', item_id=item_id, _anchor='resolutionControls'))


# ---------------------------------------------------------------------
# Route: Unlock Private Inquiries Inbox with PIN
# ---------------------------------------------------------------------
@app.route('/items/<int:item_id>/inbox', methods=['GET', 'POST'])
@limiter.limit("15 per minute; 40 per hour", methods=["POST"])
def view_inbox(item_id):
    if item_id <= 0:
        abort(404)

    item = database.get_item_by_id(item_id)
    if not item:
        abort(404)

    if request.method == 'GET':
        return redirect(url_for('item_detail', item_id=item_id, _anchor='posterInbox'))

    submitted_pin = request.form.get('pin', '').strip()

    if not submitted_pin or not re.match(r'^\d{4,8}$', submitted_pin):
        flash("Invalid Security PIN format. PIN must be 4 to 8 digits.", 'error')
        return redirect(url_for('item_detail', item_id=item_id, _anchor='posterInbox'))

    # Security Check: Verify PIN hash
    pin_hash = item['pin_hash'] if 'pin_hash' in item.keys() else None
    if not pin_hash or not check_password_hash(pin_hash, submitted_pin):
        flash(
            "Authorization Failed: Incorrect Security PIN. Unable to unlock owner inbox.",
            'error'
        )
        return redirect(url_for('item_detail', item_id=item_id, _anchor='posterInbox'))

    # Fetch stored inquiries
    messages = database.get_contact_requests_for_item(item_id)
    flash(
        f"PIN Verified! Showing {len(messages)} inquiry message(s) received for this item.",
        'info'
    )

    return render_template(
        'item_detail.html',
        item=item,
        unlocked_messages=messages,
        pin_verified=True,
        contact_draft=None
    )


# ---------------------------------------------------------------------
# Route: About Page
# ---------------------------------------------------------------------
@app.route('/about')
def about():
    return render_template('about.html')


# ---------------------------------------------------------------------
# Error Handlers (Clean Branded Pages, No Stack Traces Exposed)
# ---------------------------------------------------------------------
@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    flash("Security token expired or invalid. Please refresh and try again.", "error")
    return render_template('400.html'), 400


@app.errorhandler(400)
def bad_request(e):
    return render_template('400.html'), 400


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return render_template('400.html'), 405


@app.errorhandler(429)
def ratelimit_handler(e):
    flash("Too many requests from your device. Please wait a moment before trying again.", "error")
    return render_template('429.html'), 429


@app.errorhandler(500)
def internal_server_error(e):
    logging.error("Internal Server Error: %s", str(e), exc_info=True)
    return render_template('500.html'), 500


if __name__ == '__main__':
    # Local development server on port 5000
    host = os.environ.get('FLASK_RUN_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    debug_mode = not is_production and os.environ.get('FLASK_DEBUG', '0') == '1'
    print(f"Starting CampusConnect Lost & Found on http://{host}:{port} (debug={debug_mode})")
    app.run(host=host, port=port, debug=debug_mode)
