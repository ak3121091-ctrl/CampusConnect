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
import json
from functools import wraps
from urllib.parse import quote, urlparse, urlencode
import urllib.request
import urllib.error
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
        "img-src 'self' data: blob: https://lh3.googleusercontent.com;"
    )
    return response


# ---------------------------------------------------------------------
# Google OAuth Configuration & Safe Redirect Handling
# ---------------------------------------------------------------------
def clean_oauth_credential(value):
    """
    Safely strips leading/trailing whitespace, newlines, and enclosing quotes
    from environment credential strings.
    """
    if not value or not isinstance(value, str):
        return ''
    clean = value.strip().strip('\r\n\t ')
    if (clean.startswith('"') and clean.endswith('"')) or (clean.startswith("'") and clean.endswith("'")):
        clean = clean[1:-1].strip()
    return clean


def get_google_credentials():
    """
    Dynamically loads Google OAuth client ID and client secret from environment.
    Strips quotes and whitespace, falling back to .env if not found in os.environ.
    """
    client_id = clean_oauth_credential(os.environ.get('GOOGLE_CLIENT_ID', ''))
    client_secret = clean_oauth_credential(os.environ.get('GOOGLE_CLIENT_SECRET', ''))
    if not client_id or not client_secret:
        load_dotenv(override=False)
        client_id = clean_oauth_credential(os.environ.get('GOOGLE_CLIENT_ID', ''))
        client_secret = clean_oauth_credential(os.environ.get('GOOGLE_CLIENT_SECRET', ''))
    return client_id, client_secret


GOOGLE_CLIENT_ID = clean_oauth_credential(os.environ.get('GOOGLE_CLIENT_ID', ''))
GOOGLE_CLIENT_SECRET = clean_oauth_credential(os.environ.get('GOOGLE_CLIENT_SECRET', ''))


def is_google_oauth_configured():
    """
    Returns True if valid Google OAuth client ID and client secret are set.
    """
    client_id, client_secret = get_google_credentials()
    return bool(
        client_id and
        client_secret and
        not client_id.startswith('replace-with') and
        not client_secret.startswith('replace-with')
    )


def get_google_redirect_uri():
    """
    Resolves the exact OAuth callback redirect URI.
    Prefers explicit GOOGLE_REDIRECT_URI environment variable if configured,
    otherwise dynamically constructs the full URL from the current request.
    """
    configured = clean_oauth_credential(os.environ.get('GOOGLE_REDIRECT_URI', ''))
    if configured:
        return configured
    return url_for('google_callback', _external=True)


def is_safe_redirect_url(target):
    """
    Validates redirect targets to prevent Open Redirect vulnerabilities.
    Only allows local, relative paths without host or protocol.
    """
    if not target:
        return False
    parsed = urlparse(target)
    return (
        not parsed.netloc and
        not parsed.scheme and
        target.startswith('/') and
        not target.startswith('//') and
        not target.startswith('/\\')
    )


@app.context_processor
def inject_auth_context():
    """
    Injects current authenticated user, formatted initials, OAuth status, and notification data into all templates.
    """
    user = None
    user_id = session.get('user_id')
    user_initials = 'CC'
    unread_notifications_count = 0
    recent_notifications = []

    if user_id:
        try:
            user = database.get_user_by_id(user_id)
            if user and user['name']:
                parts = [p for p in user['name'].strip().split() if p]
                if len(parts) >= 2:
                    user_initials = (parts[0][0] + parts[1][0]).upper()
                elif len(parts) == 1:
                    user_initials = parts[0][:2].upper()
            unread_notifications_count = database.get_unread_notification_count(user_id)
            recent_notifications = database.get_notifications_for_user(user_id, limit=5)
        except Exception:
            user = None
            unread_notifications_count = 0
            recent_notifications = []

    return {
        'current_user': user,
        'current_user_initials': user_initials,
        'google_oauth_configured': is_google_oauth_configured(),
        'unread_notifications_count': unread_notifications_count,
        'recent_notifications': recent_notifications
    }


def login_required(f):
    """
    Route decorator requiring an authenticated session.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash("Please sign in to access this page.", "info")
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated_function


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
# Route: Home Page (Search, Filters, Active Listings & Resolved Archive)
# ---------------------------------------------------------------------
@app.route('/')
def index():
    raw_query = request.args.get('q', '').strip()
    search_query = raw_query[:100] if len(raw_query) > 100 else raw_query
    raw_type = request.args.get('type', 'all').strip().lower()
    raw_category = request.args.get('category', 'All').strip()
    raw_status = request.args.get('status', '').strip().lower()

    # Normalize category
    category = raw_category if raw_category in CATEGORIES else 'All'

    # Determine status: default to 'open' for active listings;
    # Route to 'resolved' when explicitly requested via status or type
    has_explicit_status = bool(raw_status in ('open', 'resolved', 'all') or raw_type == 'resolved')
    if raw_type == 'resolved' or raw_status == 'resolved':
        status = 'resolved'
        item_type = 'all'
    elif raw_status == 'all':
        status = 'all'
        item_type = raw_type if raw_type in ('lost', 'found') else 'all'
    elif raw_status == 'open':
        status = 'open'
        item_type = raw_type if raw_type in ('lost', 'found') else 'all'
    else:
        # Default: active open listings only (resolved records kept out of active listings)
        status = 'open'
        item_type = raw_type if raw_type in ('lost', 'found') else 'all'

    filter_type = item_type if item_type in ('lost', 'found') else None
    filter_category = category if category != 'All' else None

    # Tab counts (calculated at database query level):
    # 1. Matching open items for active tabs (All Active, Lost, Found)
    matching_open_items = database.get_items(
        search_query=search_query,
        item_type=None,
        category=filter_category,
        status='open'
    )
    open_lost_count = sum(1 for i in matching_open_items if i['item_type'] == 'lost')
    open_found_count = sum(1 for i in matching_open_items if i['item_type'] == 'found')
    open_total_count = len(matching_open_items)

    # 2. Matching resolved items for resolved tab
    matching_resolved_items = database.get_items(
        search_query=search_query,
        item_type=None,
        category=filter_category,
        status='resolved'
    )
    resolved_count = len(matching_resolved_items)

    # Filter items to be displayed in the results area:
    if status == 'resolved':
        filtered = matching_resolved_items
        if filter_type:
            filtered = [i for i in filtered if i['item_type'] == filter_type]
        items = filtered
        lost_items = [i for i in filtered if i['item_type'] == 'lost']
        found_items = [i for i in filtered if i['item_type'] == 'found']
        resolved_items = filtered
    elif status == 'all':
        matching_all_items = database.get_items(
            search_query=search_query,
            item_type=None,
            category=filter_category,
            status=None
        )
        if filter_type:
            items = [i for i in matching_all_items if i['item_type'] == filter_type]
        else:
            items = matching_all_items
        lost_items = [i for i in items if i['item_type'] == 'lost']
        found_items = [i for i in items if i['item_type'] == 'found']
        resolved_items = [i for i in items if i['status'] == 'resolved']
    else:  # status == 'open' (default active directory)
        if filter_type:
            items = [i for i in matching_open_items if i['item_type'] == filter_type]
        else:
            items = matching_open_items
        lost_items = [i for i in items if i['item_type'] == 'lost']
        found_items = [i for i in items if i['item_type'] == 'found']
        resolved_items = []

    # Highlighted showcase items for the interactive horizontal rail
    # Display only open/active items matching current filters (never resolved items!)
    if status == 'resolved':
        rail_items = []
    else:
        rail_items = items[:8]

    # Overview statistics calculated directly from SQLite database
    stats = database.get_statistics()

    return render_template(
        'index.html',
        items=items,
        lost_items=lost_items,
        found_items=found_items,
        resolved_items=resolved_items,
        rail_items=rail_items,
        total_count=open_total_count,
        lost_count=open_lost_count,
        found_count=open_found_count,
        resolved_count=resolved_count,
        stats=stats,
        categories=CATEGORIES,
        current_search=search_query,
        current_type=item_type,
        current_category=category,
        current_status=status,
        has_explicit_status=has_explicit_status
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
# Route: User Registration (Signup)
# ---------------------------------------------------------------------
@app.route('/signup', methods=['GET', 'POST'])
@limiter.limit("15 per minute; 50 per hour", methods=["POST"])
def signup():
    if session.get('user_id'):
        return redirect(url_for('index'))

    next_url = request.args.get('next') or request.form.get('next') or ''
    if not is_safe_redirect_url(next_url):
        next_url = ''

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        raw_email = request.form.get('email', '')
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        form_data = {'name': name, 'email': raw_email}
        errors = []

        if not name or len(name) < 2 or len(name) > 60:
            errors.append("Name must be between 2 and 60 characters.")

        if not raw_email or not database.is_valid_email(raw_email):
            errors.append("Please provide a valid email address. Must be a properly formatted email address without leading or trailing spaces.")

        if not password or len(password) < 8 or len(password) > 128:
            errors.append("Password must be between 8 and 128 characters.")

        if password != confirm_password:
            errors.append("Passwords do not match.")

        if errors:
            for err in errors:
                flash(err, 'error')
            return render_template('signup.html', form_data=form_data, next_url=next_url)

        email = raw_email.strip().lower()
        verification_token = secrets.token_urlsafe(32)
        token_expiry = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')

        try:
            user_id = database.create_user(
                email=email,
                name=name,
                password_plain=password,
                is_verified=0,
                verification_token=verification_token,
                token_expiry=token_expiry
            )
            session.clear()
            session['user_id'] = user_id
            session['user_email'] = email
            session['user_name'] = name

            database.create_notification(
                user_id=user_id,
                notification_type='welcome',
                title="Welcome to CampusConnect!",
                message=f"Welcome, {name}! Your account has been created. Please verify your campus email to secure your account and access all features.",
                target_url=url_for('profile')
            )

            verify_url = url_for('verify_email', token=verification_token, _external=True)
            flash(
                f"Welcome to CampusConnect, {name}! Your account has been created. "
                f"Please verify your email address to complete verification: {verify_url}",
                'success'
            )
            target = next_url if is_safe_redirect_url(next_url) else url_for('index')
            return redirect(target)
        except ValueError as err:
            flash(str(err), 'error')
            return render_template('signup.html', form_data=form_data, next_url=next_url)

    return render_template('signup.html', form_data={}, next_url=next_url)


# ---------------------------------------------------------------------
# Route: User Authentication (Login)
# ---------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("15 per minute; 40 per hour", methods=["POST"])
def login():
    if session.get('user_id'):
        return redirect(url_for('index'))

    next_url = request.args.get('next') or request.form.get('next') or ''
    if not is_safe_redirect_url(next_url):
        next_url = ''

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        form_data = {'email': email}

        if not email or not password:
            flash("Please enter both your email and password.", 'error')
            return render_template('login.html', form_data=form_data, next_url=next_url)

        user = database.get_user_by_email(email)
        if not user or not database.verify_user_password(user, password):
            # Generic message to prevent account enumeration
            flash("Invalid email or password. Please check your credentials and try again.", 'error')
            return render_template('login.html', form_data=form_data, next_url=next_url)

        # Session fixation prevention
        session.clear()
        session['user_id'] = user['id']
        session['user_email'] = user['email']
        session['user_name'] = user['name']
        flash(f"Welcome back, {user['name']}!", 'success')
        target = next_url if is_safe_redirect_url(next_url) else url_for('index')
        return redirect(target)

    return render_template('login.html', form_data={}, next_url=next_url)


# ---------------------------------------------------------------------
# Route: User Session Termination (Logout)
# ---------------------------------------------------------------------
@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    flash("You have been signed out safely.", 'info')
    return redirect(url_for('index'))


# ---------------------------------------------------------------------
# Route: Initiate Google OAuth Sign-In
# ---------------------------------------------------------------------
@app.route('/login/google')
def google_login():
    if not is_google_oauth_configured():
        flash(
            "Google sign-in setup required: Google Sign-In is not currently configured. "
            "Please configure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the .env file.",
            'info'
        )
        return redirect(url_for('login'))

    client_id, _ = get_google_credentials()
    redirect_uri = get_google_redirect_uri()

    next_url = request.args.get('next', '')
    if not is_safe_redirect_url(next_url):
        next_url = ''

    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state
    session['oauth_next'] = next_url
    # Store the exact redirect_uri and client_id used for this authorization request
    session['oauth_redirect_uri'] = redirect_uri
    session['oauth_client_id'] = client_id

    google_auth_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'prompt': 'select_account'
    }
    encoded_params = '&'.join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
    return redirect(f"{google_auth_endpoint}?{encoded_params}")


# ---------------------------------------------------------------------
# Route: Google OAuth Callback
# ---------------------------------------------------------------------
@app.route('/login/google/callback')
def google_callback():
    stored_state = session.pop('oauth_state', None)
    next_url = session.pop('oauth_next', '')
    # Retrieve the exact redirect_uri and client_id used in the authorization request
    stored_redirect_uri = session.pop('oauth_redirect_uri', None)
    stored_client_id = session.pop('oauth_client_id', None)

    error = request.args.get('error')
    if error:
        flash(f"Google authentication was cancelled or returned an error: {error}", 'error')
        return redirect(url_for('login'))

    received_state = request.args.get('state')
    if not stored_state or received_state != stored_state:
        flash("Google authentication state verification failed. Please try again.", 'error')
        return redirect(url_for('login'))

    code = (request.args.get('code') or '').strip()
    if not code:
        flash("Google authentication failed: Missing authorization code.", 'error')
        return redirect(url_for('login'))

    if not is_google_oauth_configured():
        flash("Google OAuth credentials are not configured.", 'error')
        return redirect(url_for('login'))

    client_id, client_secret = get_google_credentials()
    if stored_client_id and stored_client_id != client_id:
        client_id = stored_client_id

    # Ensure the token request uses the exact redirect URI used in the authorization request
    redirect_uri = stored_redirect_uri or get_google_redirect_uri()
    token_url = "https://oauth2.googleapis.com/token"

    try:
        token_payload = urlencode({
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }).encode('utf-8')

        token_headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'User-Agent': 'CampusConnect-OAuth/1.0'
        }

        token_req = urllib.request.Request(
            token_url,
            data=token_payload,
            headers=token_headers,
            method='POST'
        )
        with urllib.request.urlopen(token_req, timeout=10) as token_resp:
            tokens = json.loads(token_resp.read().decode('utf-8'))

        access_token = tokens.get('access_token')
        if not access_token:
            flash("Failed to retrieve access token from Google.", 'error')
            return redirect(url_for('login'))

        userinfo_req = urllib.request.Request(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={
                'Authorization': f"Bearer {access_token}",
                'Accept': 'application/json',
                'User-Agent': 'CampusConnect-OAuth/1.0'
            }
        )
        with urllib.request.urlopen(userinfo_req, timeout=10) as userinfo_resp:
            info = json.loads(userinfo_resp.read().decode('utf-8'))

        google_id = info.get('sub')
        email = (info.get('email') or '').strip().lower()
        name = info.get('name') or (email.split('@')[0] if email else 'User')
        avatar_url = info.get('picture')
        email_verified = bool(info.get('email_verified'))

        if not email or not database.is_valid_email(email):
            flash("Google account did not provide a valid email address.", 'error')
            return redirect(url_for('login'))

        existing_user = database.get_user_by_google_id(google_id)
        if existing_user:
            user_id = existing_user['id']
            if email_verified and not existing_user['is_verified']:
                conn = database.get_db_connection()
                try:
                    with conn:
                        conn.execute("UPDATE users SET is_verified = 1 WHERE id = ?", (user_id,))
                finally:
                    conn.close()
        else:
            existing_user_by_email = database.get_user_by_email(email)
            if existing_user_by_email:
                # CRITICAL SECURITY RULE: Do NOT automatically link an existing account
                # if that account has a password set!
                if existing_user_by_email['password_hash']:
                    flash(
                        "An account with this email already exists using password authentication. "
                        "Please sign in with your password to link your Google account.",
                        'error'
                    )
                    return redirect(url_for('login'))
                else:
                    database.update_user_google_id(existing_user_by_email['id'], google_id, avatar_url)
                    user_id = existing_user_by_email['id']
                    if email_verified and not existing_user_by_email['is_verified']:
                        conn = database.get_db_connection()
                        try:
                            with conn:
                                conn.execute("UPDATE users SET is_verified = 1 WHERE id = ?", (user_id,))
                        finally:
                            conn.close()
            else:
                user_id = database.create_user(
                    email=email,
                    name=name,
                    password_plain=None,
                    google_id=google_id,
                    avatar_url=avatar_url,
                    is_verified=1 if email_verified else 0
                )
                database.create_notification(
                    user_id=user_id,
                    notification_type='welcome',
                    title="Welcome to CampusConnect!",
                    message=f"Welcome, {name}! Your account has been connected with Google.",
                    target_url=url_for('profile')
                )

        logged_user = database.get_user_by_id(user_id)
        display_name = logged_user['name'] if logged_user else name

        session.clear()
        session['user_id'] = user_id
        session['user_email'] = email
        session['user_name'] = display_name
        flash(f"Welcome to CampusConnect, {display_name}!", 'success')
        target = next_url if is_safe_redirect_url(next_url) else url_for('profile')
        return redirect(target)

    except urllib.error.HTTPError as http_err:
        error_code = ""
        error_desc = ""
        try:
            raw_body = http_err.read().decode('utf-8', errors='replace')
            payload = json.loads(raw_body)
            if isinstance(payload, dict):
                error_code = str(payload.get('error', '')).strip()
                error_desc = str(payload.get('error_description', '')).strip()
        except Exception:
            pass

        safe_code = re.sub(r'[^a-zA-Z0-9_\-\. ]', '', error_code)[:50]
        safe_desc = re.sub(r'[^a-zA-Z0-9_\-\.:, ]', '', error_desc)[:200]

        log_summary = f"HTTP {http_err.code}"
        if safe_code:
            log_summary += f" [{safe_code}]"
        if safe_desc:
            log_summary += f": {safe_desc}"
        logging.error("Google OAuth token exchange failed: %s", log_summary)

        if not is_production:
            desc_part = f": {safe_code} - {safe_desc}" if (safe_code or safe_desc) else ""
            hint = ""
            if "client_secret" in safe_desc.lower() or "invalid_client" in safe_code.lower():
                hint = " Please verify your GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env match your Google Cloud Console Web Application credentials."
            elif "redirect_uri" in safe_desc.lower() or "redirect_uri" in safe_code.lower():
                hint = f" Ensure the Authorized redirect URI in Google Cloud Console matches '{redirect_uri}'."

            flash(
                f"Google Sign-In failed during token exchange (HTTP {http_err.code}{desc_part}).{hint}",
                'error'
            )
        else:
            flash("Google sign-in could not be completed. Please try again or sign in with your email.", 'error')
        return redirect(url_for('login'))

    except urllib.error.URLError as url_err:
        logging.error("Google OAuth connection error: %s", str(url_err.reason)[:100])
        flash("Could not connect to Google authentication service. Please check your internet connection.", 'error')
        return redirect(url_for('login'))

    except Exception as e:
        logging.error("Google OAuth callback exception: %s", str(e), exc_info=True)
        flash("An unexpected error occurred during Google sign-in. Please try again.", 'error')
        return redirect(url_for('login'))


# ---------------------------------------------------------------------
# Route: Email Verification
# ---------------------------------------------------------------------
@app.route('/verify-email/<token>')
def verify_email(token):
    """
    Verifies user email address using an expirable, single-use token.
    """
    success, status, user = database.verify_user_email(token)
    if success:
        if user and user['id']:
            database.create_notification(
                user_id=user['id'],
                notification_type='verification_complete',
                title="Email Verified",
                message="Your campus email address has been successfully verified! Your verified campus status is now active.",
                target_url=url_for('profile')
            )
        flash("Email verified successfully! Your CampusConnect account is now verified.", 'success')
        if session.get('user_id'):
            return redirect(url_for('profile'))
        return redirect(url_for('login'))
    elif status == 'expired':
        flash("This verification link has expired. Please sign in and request a new verification link.", 'error')
        return redirect(url_for('profile') if session.get('user_id') else url_for('login'))
    else:
        flash("Invalid or already used verification token.", 'error')
        return redirect(url_for('profile') if session.get('user_id') else url_for('login'))


# ---------------------------------------------------------------------
# Route: Resend Email Verification Token
# ---------------------------------------------------------------------
@app.route('/resend-verification', methods=['GET', 'POST'])
@login_required
@limiter.limit("5 per minute; 15 per hour")
def resend_verification():
    """
    Regenerates and issues a fresh verification token for unverified accounts.
    """
    user = database.get_user_by_id(session['user_id'])
    if not user:
        flash("Account not found. Please sign in again.", 'error')
        return redirect(url_for('login'))

    if user['is_verified']:
        flash("Your email address is already verified.", 'info')
        return redirect(url_for('profile'))

    new_token = secrets.token_urlsafe(32)
    token_expiry = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    database.set_user_verification_token(user['id'], new_token, token_expiry)

    verify_url = url_for('verify_email', token=new_token, _external=True)
    flash(
        f"A fresh verification link has been generated: {verify_url}",
        'info'
    )
    return redirect(url_for('profile'))


# ---------------------------------------------------------------------
# Route: User Profile & Personal Reports Dashboard
# ---------------------------------------------------------------------
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """
    Protected user profile view. Shows user information, verification status,
    allows updating profile name, and displays all personal Lost/Found/Resolved items.
    """
    user = database.get_user_by_id(session['user_id'])
    if not user:
        session.clear()
        flash("Session expired or user not found. Please sign in again.", 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update_profile':
            new_name = request.form.get('name', '').strip()
            if not new_name or len(new_name) < 2 or len(new_name) > 60:
                flash("Name must be between 2 and 60 characters.", 'error')
            else:
                try:
                    database.update_user_profile(user['id'], new_name)
                    session['user_name'] = new_name
                    flash("Your profile name has been updated successfully.", 'success')
                    return redirect(url_for('profile'))
                except ValueError as err:
                    flash(str(err), 'error')

    user_items = database.get_items_for_user(user['id'], user['email'])
    lost_items = [it for it in user_items if it['item_type'] == 'lost' and it['status'] == 'open']
    found_items = [it for it in user_items if it['item_type'] == 'found' and it['status'] == 'open']
    resolved_items = [it for it in user_items if it['status'] == 'resolved']

    return render_template(
        'profile.html',
        user=user,
        user_items=user_items,
        lost_items=lost_items,
        found_items=found_items,
        resolved_items=resolved_items
    )



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
        photo_storage = None
        for key in ('photo_camera', 'photo_file', 'image'):
            candidate = request.files.get(key)
            if candidate and candidate.filename and candidate.filename.strip():
                photo_storage = candidate
                break

        saved_image_filename = None
        if photo_storage:
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
                image_filename=saved_image_filename,
                user_id=session.get('user_id')
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
    initial_form_data = {'item_type': initial_type}
    if session.get('user_id'):
        user = database.get_user_by_id(session['user_id'])
        if user:
            initial_form_data['poster_name'] = user['name']
            initial_form_data['poster_contact'] = user['email']

    return render_template(
        'submit.html',
        categories=CATEGORIES,
        today=today,
        form_data=initial_form_data
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

    # Phase 3: Trigger in-app notification to item owner if owner is reliably known
    owner_id = database.get_owner_user_id_for_item(item)
    if owner_id:
        item_title = item['title'] if item['title'] else 'your listing'
        database.create_notification(
            user_id=owner_id,
            notification_type='inquiry_received',
            title=f"New inquiry on: {item_title[:40]}",
            message=f"{sender_name} sent a message: \"{message[:120]}{'...' if len(message) > 120 else ''}\"",
            target_url=url_for('item_detail', item_id=item_id, _anchor='contactSection')
        )

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

    # Handle repeated submissions safely
    current_status = item['status'] if 'status' in item.keys() else 'open'
    if current_status == target_status:
        flash(
            f"This item is already marked as {target_status.upper()}.",
            'info'
        )
        return redirect(url_for('item_detail', item_id=item_id, _anchor='resolutionControls'))

    # Update in database (never deletes the record, full history preserved)
    database.update_item_status(item_id, target_status)

    # Phase 3: Trigger in-app notification to item owner if owner is reliably known
    owner_id = database.get_owner_user_id_for_item(item)
    if owner_id:
        status_label = "Resolved" if target_status == 'resolved' else "Reopened (Active)"
        item_title = item['title'] if item['title'] else 'your listing'
        database.create_notification(
            user_id=owner_id,
            notification_type='status_changed',
            title=f"Listing status: {status_label}",
            message=f"The status of '{item_title[:40]}' was updated to {status_label.upper()}.",
            target_url=url_for('item_detail', item_id=item_id)
        )
    if target_status == 'resolved':
        flash(
            "Item status successfully updated to 'RESOLVED'! It has been moved to the Resolved Items archive.",
            'success'
        )
    else:
        flash(
            "Item status successfully updated to 'OPEN'! It has been restored to active directory listings.",
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
# Route: Notifications (Phase 3)
# ---------------------------------------------------------------------
@app.route('/notifications')
@login_required
def notifications_page():
    """
    Renders the dedicated notifications management page for the authenticated user.
    Supports filtering by 'all' or 'unread'.
    """
    user_id = session['user_id']
    filter_mode = request.args.get('filter', 'all').strip().lower()
    unread_only = (filter_mode == 'unread')

    notifications = database.get_notifications_for_user(user_id, unread_only=unread_only)
    total_count = len(database.get_notifications_for_user(user_id, unread_only=False))
    unread_count = database.get_unread_notification_count(user_id)

    return render_template(
        'notifications.html',
        notifications=notifications,
        filter_mode=filter_mode,
        total_count=total_count,
        unread_count=unread_count
    )


@app.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    """
    Marks a single notification as read.
    Enforces user isolation: rejects access to other users' notifications with 403.
    """
    user_id = session['user_id']
    notif = database.get_notification_by_id(notification_id)
    if not notif:
        abort(404)
    if notif['user_id'] != user_id:
        abort(403)

    database.mark_notification_as_read(notification_id, user_id)

    next_url = request.form.get('next') or request.args.get('next') or ''
    if next_url and is_safe_redirect_url(next_url):
        return redirect(next_url)
    return redirect(url_for('notifications_page'))


@app.route('/notifications/read-all', methods=['POST'])
@login_required
def mark_all_notifications_read():
    """
    Marks all notifications for the current authenticated user as read.
    """
    user_id = session['user_id']
    count = database.mark_all_notifications_as_read(user_id)
    if count > 0:
        flash(f"{count} notification{'s' if count != 1 else ''} marked as read.", "success")
    else:
        flash("All notifications are already marked as read.", "info")

    next_url = request.form.get('next') or request.args.get('next') or ''
    if next_url and is_safe_redirect_url(next_url):
        return redirect(next_url)
    return redirect(url_for('notifications_page'))


@app.route('/notifications/<int:notification_id>/delete', methods=['POST'])
@login_required
def delete_notification(notification_id):
    """
    Deletes a notification.
    Enforces user isolation: rejects access to other users' notifications with 403.
    """
    user_id = session['user_id']
    notif = database.get_notification_by_id(notification_id)
    if not notif:
        abort(404)
    if notif['user_id'] != user_id:
        abort(403)

    database.delete_notification(notification_id, user_id)
    flash("Notification deleted.", "info")

    next_url = request.form.get('next') or request.args.get('next') or ''
    if next_url and is_safe_redirect_url(next_url):
        return redirect(next_url)
    return redirect(url_for('notifications_page'))


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
