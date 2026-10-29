"""
database.py - Database Layer for CampusConnect Lost & Found
------------------------------------------------------------
Uses Python's built-in sqlite3 module to manage persistent storage
for items and contact inquiries.

All database queries use parameterized SQL (? placeholders) to
prevent SQL Injection vulnerabilities.
Configures WAL (Write-Ahead Logging) mode and foreign keys for high
reliability and safe concurrency.
"""

import sqlite3
import os
import re
import datetime
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, 'campusconnect.db')
BACKUPS_DIR = os.path.join(BASE_DIR, 'backups')

# Strict email format validation regex
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')


def is_valid_email(email):
    """
    Validates email format rigorously:
    1. Must be non-empty string.
    2. Must not contain leading or trailing whitespace.
    3. Must adhere to valid standard email regex pattern.
    4. Must have length between 5 and 100 characters.
    """
    if not email or not isinstance(email, str):
        return False
    if email != email.strip():
        return False
    clean = email.strip()
    if len(clean) < 5 or len(clean) > 100:
        return False
    return bool(EMAIL_REGEX.match(clean))


def get_db_path():
    """
    Returns the active SQLite database path. Supports an override
    via the CAMPUSCONNECT_DB environment variable for testing or production.
    """
    return os.environ.get('CAMPUSCONNECT_DB') or DEFAULT_DB_PATH


def get_db_connection():
    """
    Establishes and returns a connection to the SQLite database.
    sqlite3.Row allows column access by name (e.g., row['title']).
    Enables foreign keys and WAL mode for enhanced write concurrency.
    Uses a 15.0-second timeout to prevent 'database is locked' errors.
    """
    conn = sqlite3.connect(get_db_path(), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        # WAL mode enables concurrent readers while writing
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass
    return conn


def backup_database(backup_path=None):
    """
    Safely creates an atomic backup copy of the current database.
    If backup_path is not specified, generates a timestamped file in the backups/ directory.
    """
    source_path = get_db_path()
    if not os.path.exists(source_path):
        return None

    if not backup_path:
        os.makedirs(BACKUPS_DIR, exist_ok=True)
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(BACKUPS_DIR, f'campusconnect_backup_{timestamp}.db')
    else:
        dest_dir = os.path.dirname(backup_path)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)

    # Atomic online SQLite backup
    src_conn = sqlite3.connect(source_path)
    dst_conn = sqlite3.connect(backup_path)
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    return backup_path


def init_db(seed_demo=False):
    """
    Initializes database tables and performance indexes if they do not exist.
    By default, demo records are NEVER seeded automatically.
    Seeding is only performed if explicitly requested (e.g. for testing)
    or if the CAMPUSCONNECT_SEED_DEMO environment variable is set to '1'.
    Safe to run repeatedly without affecting existing data.
    """
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            # Table: items
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_type TEXT NOT NULL CHECK(item_type IN ('lost', 'found')),
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    location TEXT NOT NULL,
                    event_date TEXT NOT NULL,
                    description TEXT NOT NULL,
                    poster_name TEXT NOT NULL,
                    poster_contact TEXT NOT NULL,
                    pin_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'resolved')),
                    is_demo INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    image_filename TEXT DEFAULT NULL,
                    user_id INTEGER DEFAULT NULL
                )
            """)

            # Repeatable migration: Ensure image_filename & user_id columns exist on existing databases
            cursor.execute("PRAGMA table_info(items)")
            cols = [row['name'] for row in cursor.fetchall()]
            if 'image_filename' not in cols:
                cursor.execute("ALTER TABLE items ADD COLUMN image_filename TEXT DEFAULT NULL")
            if 'user_id' not in cols:
                cursor.execute("ALTER TABLE items ADD COLUMN user_id INTEGER DEFAULT NULL")

            # Table: contact_requests (Safe inquiry inbox)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contact_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    sender_name TEXT NOT NULL,
                    sender_contact TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (item_id) REFERENCES items (id) ON DELETE CASCADE
                )
            """)

            # Table: users (Authenticated Campus Accounts with Email Verification)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    password_hash TEXT DEFAULT NULL,
                    google_id TEXT DEFAULT NULL,
                    avatar_url TEXT DEFAULT NULL,
                    is_verified INTEGER NOT NULL DEFAULT 0,
                    verification_token TEXT DEFAULT NULL,
                    verification_token_expires_at TIMESTAMP DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Table: notifications (User In-App Notifications - Phase 3)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    notification_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    target_url TEXT DEFAULT NULL,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)

            # Ensure verification columns exist on existing users table
            cursor.execute("PRAGMA table_info(users)")
            user_cols = [row['name'] for row in cursor.fetchall()]
            if 'is_verified' not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0")
            if 'verification_token' not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN verification_token TEXT DEFAULT NULL")
            if 'verification_token_expires_at' not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN verification_token_expires_at TIMESTAMP DEFAULT NULL")

            # Indexes for performant filtering, sorting, and joins
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_items_type_status 
                ON items (item_type, status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_items_created_at 
                ON items (created_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_contact_requests_item_id 
                ON contact_requests (item_id)
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email 
                ON users (email)
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id 
                ON users (google_id) WHERE google_id IS NOT NULL
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_notifications_user_unread 
                ON notifications (user_id, is_read, created_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_notifications_user_all 
                ON notifications (user_id, created_at DESC)
            """)

            should_seed = seed_demo or os.environ.get('CAMPUSCONNECT_SEED_DEMO') == '1'
            if should_seed:
                cursor.execute("SELECT COUNT(*) AS total FROM items")
                count_row = cursor.fetchone()
                if count_row['total'] == 0:
                    seed_demo_data(conn)
    finally:
        conn.close()


def migrate_db():
    """
    Safely migrates the SQLite schema to include image_filename, user_id, and users table if absent.
    Safe to run repeatedly and preserves all existing records.
    Returns True if migration was applied, False if already up to date.
    """
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            migrated = False

            cursor.execute("PRAGMA table_info(items)")
            cols = [row['name'] for row in cursor.fetchall()]
            if 'image_filename' not in cols:
                cursor.execute("ALTER TABLE items ADD COLUMN image_filename TEXT DEFAULT NULL")
                migrated = True
            if 'user_id' not in cols:
                cursor.execute("ALTER TABLE items ADD COLUMN user_id INTEGER DEFAULT NULL")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    password_hash TEXT DEFAULT NULL,
                    google_id TEXT DEFAULT NULL,
                    avatar_url TEXT DEFAULT NULL,
                    is_verified INTEGER NOT NULL DEFAULT 0,
                    verification_token TEXT DEFAULT NULL,
                    verification_token_expires_at TIMESTAMP DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email 
                ON users (email)
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id 
                ON users (google_id) WHERE google_id IS NOT NULL
            """)

            cursor.execute("PRAGMA table_info(users)")
            user_cols = [row['name'] for row in cursor.fetchall()]
            if 'is_verified' not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0")
            if 'verification_token' not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN verification_token TEXT DEFAULT NULL")
            if 'verification_token_expires_at' not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN verification_token_expires_at TIMESTAMP DEFAULT NULL")

            # Table: notifications (User In-App Notifications - Phase 3)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    notification_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    target_url TEXT DEFAULT NULL,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_notifications_user_unread 
                ON notifications (user_id, is_read, created_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_notifications_user_all 
                ON notifications (user_id, created_at DESC)
            """)

            return migrated
    finally:
        conn.close()


def cleanup_demo_records(backup=True):
    """
    Explicitly and safely removes all known demo records (is_demo = 1)
    and their associated contact inquiries from the active database.
    
    Preserves all genuine user-created records (is_demo = 0).
    Performs an automatic database backup prior to deletion.
    Returns a summary dictionary of the cleanup operation.
    """
    backup_file = None
    if backup:
        backup_file = backup_database()

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            # 1. Identify demo records
            cursor.execute("SELECT id, title FROM items WHERE is_demo = 1")
            demo_items = cursor.fetchall()
            demo_item_ids = [row['id'] for row in demo_items]

            demo_inquiries_count = 0
            if demo_item_ids:
                placeholders = ','.join(['?'] * len(demo_item_ids))
                cursor.execute(
                    f"SELECT COUNT(*) AS count FROM contact_requests WHERE item_id IN ({placeholders})",
                    demo_item_ids
                )
                demo_inquiries_count = cursor.fetchone()['count']

                # Delete inquiries for demo items
                cursor.execute(f"DELETE FROM contact_requests WHERE item_id IN ({placeholders})", demo_item_ids)

                # Delete demo items
                cursor.execute(f"DELETE FROM items WHERE id IN ({placeholders})", demo_item_ids)

            # 2. Defensive cleanup: if any genuine record had '[DEMO DATA]' in title, strip it
            cursor.execute("""
                UPDATE items 
                SET title = TRIM(REPLACE(title, '[DEMO DATA]', ''))
                WHERE title LIKE '%[DEMO DATA]%'
            """)

            # Count remaining genuine records
            cursor.execute("SELECT COUNT(*) AS count FROM items")
            genuine_items_remaining = cursor.fetchone()['count']
    finally:
        conn.close()

    return {
        'backup_path': backup_file,
        'demo_items_removed': len(demo_items),
        'demo_inquiries_removed': demo_inquiries_count,
        'genuine_items_remaining': genuine_items_remaining
    }


def reset_db(seed_demo=False):
    """
    Cleans and re-initializes tables.
    Useful for testing and administrative resets.
    By default creates clean empty tables without demo records.
    """
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("DROP TABLE IF EXISTS notifications")
            conn.execute("DROP TABLE IF EXISTS contact_requests")
            conn.execute("DROP TABLE IF EXISTS items")
            conn.execute("DROP TABLE IF EXISTS users")
    finally:
        conn.close()
    init_db(seed_demo=seed_demo)


def seed_demo_data(conn, is_demo=1):
    """
    Populates sample items for testing environments.
    Demo PIN for all sample items is '1234'.
    """
    cursor = conn.cursor()
    demo_pin_hash = generate_password_hash("1234")

    sample_items = [
        (
            'lost',
            'TI-84 Plus CE Graphing Calculator',
            'Electronics',
            'Science & Engineering Hall - Room 302',
            '2026-10-25',
            'Black casing with a yellow NASA sticker on the battery cover. Left on desk after Physics 201 lecture.',
            'Alex Chen',
            'alex.chen@campus.edu',
            demo_pin_hash,
            'open',
            is_demo
        ),
        (
            'found',
            'Blue Hydro Flask Water Bottle (32oz)',
            'Clothing & Accessories',
            'Main Campus Recreation Center - Bleachers',
            '2026-10-26',
            'Dark blue bottle with small dent on bottom rim and multiple outdoor stickers.',
            'Morgan Reed',
            'm.reed@campus.edu',
            demo_pin_hash,
            'open',
            is_demo
        ),
        (
            'lost',
            'Student ID Card & Dorm Keycard',
            'Student IDs & Keys',
            'University Dining Commons / Quad walkway',
            '2026-10-24',
            'Campus ID for "Taylor Smith" attached to a crimson lanyard with a bronze dorm room key.',
            'Taylor Smith',
            'tsmith@campus.edu',
            demo_pin_hash,
            'open',
            is_demo
        ),
        (
            'found',
            'Apple AirPods Pro Case (White)',
            'Electronics',
            'Library 2nd Floor Silent Study Pods',
            '2026-10-26',
            'Found on pod desk #14. The charging case has a silicone teal protective sleeve.',
            'Campus Security Desk',
            'library-lostfound@campus.edu',
            demo_pin_hash,
            'open',
            is_demo
        ),
        (
            'lost',
            'Organic Chemistry 8th Edition Textbook',
            'Books & Stationery',
            'Student Center Cafe Booths',
            '2026-10-23',
            'Hardcover textbook with highlighted pages in chapter 4 and 5. Has notes on sticky bookmarks.',
            'Jordan Patel',
            'jordan.p@campus.edu',
            demo_pin_hash,
            'open',
            is_demo
        ),
        (
            'found',
            'Black North Face Backpack',
            'Bags & Backpacks',
            'Bus Stop #4 - North Campus Circle',
            '2026-10-22',
            'Black Borealis backpack containing spiral notebooks and a spiral umbrella. Turned into security.',
            'Transit Safety Officer Dave',
            'transit-dispatch@campus.edu',
            demo_pin_hash,
            'resolved',
            is_demo
        )
    ]

    cursor.executemany("""
        INSERT INTO items (
            item_type, title, category, location, event_date,
            description, poster_name, poster_contact, pin_hash,
            status, is_demo
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, sample_items)

    # Add a sample contact inquiry on the first sample item for testing inbox
    cursor.execute("SELECT id FROM items WHERE title LIKE '%TI-84 Plus%' LIMIT 1")
    first_item = cursor.fetchone()
    if first_item:
        cursor.execute("""
            INSERT INTO contact_requests (item_id, sender_name, sender_contact, message)
            VALUES (?, ?, ?, ?)
        """, (
            first_item['id'],
            'Sam TA',
            'sam99@campus.edu',
            'Hi Alex, I think the teaching assistant picked up a calculator from Room 302 and left it at the departmental office desk!'
        ))


# =====================================================================
# Database Query Helper Functions (All Parameterized!)
# =====================================================================

def get_items(search_query=None, item_type=None, category=None, status=None, include_demo=False):
    """
    Queries items with optional search and filter criteria.
    Uses parameterized SQL to guarantee protection against SQL injection.
    By default, only genuine user reports (is_demo = 0) are returned.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        sql = """
            SELECT id, item_type, title, category, location, event_date,
                   description, poster_name, status, is_demo, created_at,
                   image_filename
            FROM items
            WHERE 1=1
        """
        params = []

        if not include_demo:
            sql += " AND is_demo = 0"

        if search_query and search_query.strip():
            clean_q = search_query.strip()
            # Enforce max 100 chars and at most 6 search terms to prevent query DoS
            if len(clean_q) > 100:
                clean_q = clean_q[:100]
            terms = [t for t in clean_q.split() if t][:6]
            if terms:
                for term in terms:
                    escaped_t = term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                    wildcard = f"%{escaped_t}%"
                    sql += """ AND (
                        title LIKE ? ESCAPE '\\' OR 
                        description LIKE ? ESCAPE '\\' OR 
                        location LIKE ? ESCAPE '\\' OR 
                        poster_name LIKE ? ESCAPE '\\' OR 
                        category LIKE ? ESCAPE '\\'
                    )"""
                    params.extend([wildcard, wildcard, wildcard, wildcard, wildcard])

        if item_type and item_type in ('lost', 'found'):
            sql += " AND item_type = ?"
            params.append(item_type)

        if category and category.strip() and category != 'All':
            sql += " AND category = ?"
            params.append(category.strip())

        if status and status in ('open', 'resolved'):
            sql += " AND status = ?"
            params.append(status)

        sql += " ORDER BY created_at DESC"

        cursor.execute(sql, tuple(params))
        items = cursor.fetchall()
        return items
    finally:
        conn.close()


def get_item_by_id(item_id):
    """
    Retrieves a single item by its ID.
    Note: poster_contact is kept on the record for internal verification,
    but should not be rendered publicly on public cards or detail headers.
    """
    try:
        clean_id = int(item_id)
    except (ValueError, TypeError):
        return None

    if clean_id <= 0:
        return None

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, item_type, title, category, location, event_date,
                   description, poster_name, poster_contact, pin_hash,
                   status, is_demo, created_at, image_filename
            FROM items
            WHERE id = ?
        """, (clean_id,))
        item = cursor.fetchone()
        return item
    finally:
        conn.close()


def create_item(item_type, title, category, location, event_date,
                description, poster_name, poster_contact, pin_plain, is_demo=0,
                image_filename=None, user_id=None):
    """
    Inserts a newly reported lost or found item.
    The poster's security PIN is securely hashed before storage.
    Optionally stores image_filename and associated authenticated user_id.
    """
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            pin_hash = generate_password_hash(pin_plain)

            cursor.execute("""
                INSERT INTO items (
                    item_type, title, category, location, event_date,
                    description, poster_name, poster_contact, pin_hash, status, is_demo,
                    image_filename, user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
            """, (
                item_type, title, category, location, event_date,
                description, poster_name, poster_contact, pin_hash, is_demo,
                image_filename, user_id
            ))
            new_id = cursor.lastrowid
            return new_id
    finally:
        conn.close()


def update_item_status(item_id, new_status):
    """
    Updates status ('open' or 'resolved') for an item using parameterized query.
    Returns True if a row was updated, False otherwise.
    """
    try:
        clean_id = int(item_id)
    except (ValueError, TypeError):
        return False

    if clean_id <= 0 or new_status not in ('open', 'resolved'):
        return False

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE items
                SET status = ?
                WHERE id = ?
            """, (new_status, clean_id))
            return cursor.rowcount > 0
    finally:
        conn.close()


def create_contact_request(item_id, sender_name, sender_contact, message):
    """
    Stores a safe contact inquiry/claim message in the database for the item.
    """
    try:
        clean_id = int(item_id)
    except (ValueError, TypeError):
        return None

    if clean_id <= 0:
        return None

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO contact_requests (item_id, sender_name, sender_contact, message)
                VALUES (?, ?, ?, ?)
            """, (clean_id, sender_name, sender_contact, message))
            new_id = cursor.lastrowid
            return new_id
    finally:
        conn.close()


def get_contact_requests_for_item(item_id):
    """
    Retrieves all contact inquiries for an item.
    Protected: should only be invoked after the poster's PIN is verified.
    """
    try:
        clean_id = int(item_id)
    except (ValueError, TypeError):
        return []

    if clean_id <= 0:
        return []

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, sender_name, sender_contact, message, created_at
            FROM contact_requests
            WHERE item_id = ?
            ORDER BY created_at DESC
        """, (clean_id,))
        requests = cursor.fetchall()
        return requests
    finally:
        conn.close()


def get_statistics(include_demo=False):
    """
    Returns quick stats for the dashboard header:
    total items, open lost, open found, total resolved.
    Calculates counters from genuine database records.
    Uses a single aggregate SQL query for efficiency and consistency.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        where_clause = "WHERE 1=1" if include_demo else "WHERE is_demo = 0"

        cursor.execute(f"""
            SELECT 
                COUNT(*) AS total,
                SUM(CASE WHEN item_type = 'lost' AND status = 'open' THEN 1 ELSE 0 END) AS open_lost,
                SUM(CASE WHEN item_type = 'found' AND status = 'open' THEN 1 ELSE 0 END) AS open_found,
                SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) AS resolved
            FROM items
            {where_clause}
        """)
        row = cursor.fetchone()

        if not row:
            return {'total': 0, 'open_lost': 0, 'open_found': 0, 'resolved': 0}

        return {
            'total': row['total'] or 0,
            'open_lost': row['open_lost'] or 0,
            'open_found': row['open_found'] or 0,
            'resolved': row['resolved'] or 0
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------
# User Account Operations (Authentication, Identity & Verification)
# ---------------------------------------------------------------------
def create_user(email, name, password_plain=None, google_id=None, avatar_url=None,
                is_verified=0, verification_token=None, token_expiry=None):
    """
    Creates and stores a new user account in SQLite.
    Normalizes email to lowercase and strips leading/trailing spaces.
    Validates format strictly to prevent malformed or whitespace-padded emails.
    Hashes password using Werkzeug's secure password hash if provided.
    Raises ValueError if email format is invalid or already registered.
    """
    if not email or not isinstance(email, str) or not is_valid_email(email):
        raise ValueError("Invalid email format. Please provide a valid email address.")

    clean_email = email.strip().lower()
    clean_name = (name or '').strip()

    if not clean_name or len(clean_name) < 2 or len(clean_name) > 60:
        raise ValueError("Name must be between 2 and 60 characters.")

    password_hash = None
    if password_plain:
        if len(password_plain) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        password_hash = generate_password_hash(password_plain)

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (
                    email, name, password_hash, google_id, avatar_url,
                    is_verified, verification_token, verification_token_expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                clean_email, clean_name, password_hash, google_id, avatar_url,
                1 if is_verified else 0, verification_token, token_expiry
            ))
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("An account with this email address already exists.")
    finally:
        conn.close()


def get_user_by_email(email):
    """
    Retrieves a user by normalized email address. Returns sqlite3.Row or None.
    """
    if not email or not isinstance(email, str):
        return None
    clean_email = email.strip().lower()

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, email, name, password_hash, google_id, avatar_url,
                   is_verified, verification_token, verification_token_expires_at,
                   created_at
            FROM users
            WHERE email = ?
        """, (clean_email,))
        return cursor.fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id):
    """
    Retrieves a user by integer user ID. Returns sqlite3.Row or None.
    """
    try:
        clean_id = int(user_id)
    except (ValueError, TypeError):
        return None

    if clean_id <= 0:
        return None

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, email, name, password_hash, google_id, avatar_url,
                   is_verified, verification_token, verification_token_expires_at,
                   created_at
            FROM users
            WHERE id = ?
        """, (clean_id,))
        return cursor.fetchone()
    finally:
        conn.close()


def get_user_by_google_id(google_id):
    """
    Retrieves a user by their Google OAuth subject/ID.
    """
    if not google_id:
        return None
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, email, name, password_hash, google_id, avatar_url,
                   is_verified, verification_token, verification_token_expires_at,
                   created_at
            FROM users
            WHERE google_id = ?
        """, (str(google_id),))
        return cursor.fetchone()
    finally:
        conn.close()


def update_user_google_id(user_id, google_id, avatar_url=None):
    """
    Associates a Google OAuth ID with an existing user account.
    """
    try:
        clean_id = int(user_id)
    except (ValueError, TypeError):
        return False

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            if avatar_url:
                cursor.execute("""
                    UPDATE users
                    SET google_id = ?, avatar_url = ?
                    WHERE id = ?
                """, (str(google_id), avatar_url, clean_id))
            else:
                cursor.execute("""
                    UPDATE users
                    SET google_id = ?
                    WHERE id = ?
                """, (str(google_id), clean_id))
            return cursor.rowcount > 0
    finally:
        conn.close()


def verify_user_email(token):
    """
    Verifies a user's email using a secure token.
    Enforces expiration and nullifies the token upon success to prevent reuse.
    Returns (success: bool, status: str, user: Row or None).
    """
    if not token or not isinstance(token, str):
        return False, "invalid", None

    clean_token = token.strip()
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, email, name, is_verified, verification_token_expires_at
                FROM users
                WHERE verification_token = ?
            """, (clean_token,))
            user = cursor.fetchone()

            if not user:
                return False, "invalid", None

            expires_at = user['verification_token_expires_at']
            if expires_at and expires_at < now_iso:
                return False, "expired", user

            cursor.execute("""
                UPDATE users
                SET is_verified = 1,
                    verification_token = NULL,
                    verification_token_expires_at = NULL
                WHERE id = ?
            """, (user['id'],))

            cursor.execute("SELECT * FROM users WHERE id = ?", (user['id'],))
            updated_user = cursor.fetchone()
            return True, "verified", updated_user
    finally:
        conn.close()


def set_user_verification_token(user_id, token, expires_at):
    """
    Sets or refreshes a verification token and expiration for an unverified user.
    """
    try:
        clean_id = int(user_id)
    except (ValueError, TypeError):
        return False

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users
                SET verification_token = ?,
                    verification_token_expires_at = ?
                WHERE id = ? AND is_verified = 0
            """, (token, expires_at, clean_id))
            return cursor.rowcount > 0
    finally:
        conn.close()


def update_user_profile(user_id, name):
    """
    Updates the display name for a user account.
    """
    try:
        clean_id = int(user_id)
    except (ValueError, TypeError):
        return False

    clean_name = (name or '').strip()
    if not clean_name or len(clean_name) < 2 or len(clean_name) > 60:
        raise ValueError("Name must be between 2 and 60 characters.")

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users
                SET name = ?
                WHERE id = ?
            """, (clean_name, clean_id))
            return cursor.rowcount > 0
    finally:
        conn.close()


def get_items_for_user(user_id, email):
    """
    Retrieves all lost, found, and resolved items posted by this user.
    Matches by user_id or normalized contact email.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        clean_email = (email or '').strip().lower()
        cursor.execute("""
            SELECT *
            FROM items
            WHERE (user_id IS NOT NULL AND user_id = ?)
               OR (poster_contact IS NOT NULL AND LOWER(poster_contact) = ?)
            ORDER BY created_at DESC
        """, (user_id, clean_email))
        return cursor.fetchall()
    finally:
        conn.close()


def verify_user_password(user, password_plain):
    """
    Safely verifies a plain text password against a user's password_hash.
    Returns False if user has no password_hash (e.g. Google-only sign-up).
    """
    if not user or not user['password_hash'] or not password_plain:
        return False
    return check_password_hash(user['password_hash'], password_plain)


def is_safe_target_url(target_url):
    """
    Validates that a notification target URL is a safe internal relative path.
    Prevents open redirect attacks and external links.
    """
    if not target_url:
        return True
    target = str(target_url).strip()
    if target.startswith('/') and not target.startswith('//') and not target.startswith('/\\'):
        if not any(target.lower().startswith(prefix) for prefix in ('javascript:', 'data:', 'vbscript:')):
            return True
    return False


def create_notification(user_id, notification_type, title, message, target_url=None):
    """
    Creates an in-app notification for a registered user.
    Validates user existence, sanitizes inputs, and ensures target_url is a safe internal relative path.
    Returns the newly created notification id, or None if creation was skipped.
    """
    try:
        clean_user_id = int(user_id)
    except (ValueError, TypeError):
        return None

    clean_type = (notification_type or 'info').strip()[:50]
    clean_title = (title or '').strip()[:150]
    clean_message = (message or '').strip()[:1000]

    if not clean_title or not clean_message:
        return None

    safe_target = None
    if target_url:
        target_str = str(target_url).strip()
        if is_safe_target_url(target_str):
            safe_target = target_str[:255]

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            # Verify user exists
            cursor.execute("SELECT id FROM users WHERE id = ?", (clean_user_id,))
            if not cursor.fetchone():
                return None

            cursor.execute("""
                INSERT INTO notifications (user_id, notification_type, title, message, target_url, is_read, created_at)
                VALUES (?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
            """, (clean_user_id, clean_type, clean_title, clean_message, safe_target))
            return cursor.lastrowid
    finally:
        conn.close()


def get_notifications_for_user(user_id, limit=None, unread_only=False):
    """
    Retrieves notifications for a given user, newest first.
    Optionally filters by unread_only and applies limit.
    """
    try:
        clean_user_id = int(user_id)
    except (ValueError, TypeError):
        return []

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM notifications WHERE user_id = ?"
        params = [clean_user_id]

        if unread_only:
            query += " AND is_read = 0"

        query += " ORDER BY created_at DESC, id DESC"

        if limit is not None:
            try:
                query += " LIMIT ?"
                params.append(int(limit))
            except (ValueError, TypeError):
                pass

        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        conn.close()


def get_unread_notification_count(user_id):
    """
    Returns the count of unread notifications for a user.
    """
    try:
        clean_user_id = int(user_id)
    except (ValueError, TypeError):
        return 0

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) AS unread_count
            FROM notifications
            WHERE user_id = ? AND is_read = 0
        """, (clean_user_id,))
        row = cursor.fetchone()
        return row['unread_count'] if row else 0
    finally:
        conn.close()


def get_notification_by_id(notification_id, user_id=None):
    """
    Retrieves a single notification by id.
    If user_id is provided, enforces that the notification belongs to that user.
    """
    try:
        clean_notif_id = int(notification_id)
    except (ValueError, TypeError):
        return None

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if user_id is not None:
            try:
                clean_user_id = int(user_id)
                cursor.execute("""
                    SELECT * FROM notifications
                    WHERE id = ? AND user_id = ?
                """, (clean_notif_id, clean_user_id))
            except (ValueError, TypeError):
                return None
        else:
            cursor.execute("SELECT * FROM notifications WHERE id = ?", (clean_notif_id,))
        return cursor.fetchone()
    finally:
        conn.close()


def mark_notification_as_read(notification_id, user_id):
    """
    Marks a notification as read if it belongs to user_id.
    Returns True if updated, False otherwise.
    """
    try:
        clean_notif_id = int(notification_id)
        clean_user_id = int(user_id)
    except (ValueError, TypeError):
        return False

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE notifications
                SET is_read = 1
                WHERE id = ? AND user_id = ?
            """, (clean_notif_id, clean_user_id))
            return cursor.rowcount > 0
    finally:
        conn.close()


def mark_all_notifications_as_read(user_id):
    """
    Marks all notifications for user_id as read.
    Returns the count of notifications marked as read.
    """
    try:
        clean_user_id = int(user_id)
    except (ValueError, TypeError):
        return 0

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE notifications
                SET is_read = 1
                WHERE user_id = ? AND is_read = 0
            """, (clean_user_id,))
            return cursor.rowcount
    finally:
        conn.close()


def delete_notification(notification_id, user_id):
    """
    Deletes a notification if it belongs to user_id.
    Returns True if deleted, False otherwise.
    """
    try:
        clean_notif_id = int(notification_id)
        clean_user_id = int(user_id)
    except (ValueError, TypeError):
        return False

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM notifications
                WHERE id = ? AND user_id = ?
            """, (clean_notif_id, clean_user_id))
            return cursor.rowcount > 0
    finally:
        conn.close()


def get_owner_user_id_for_item(item):
    """
    Safely resolves the registered user ID for an item's owner.
    Checks item['user_id'] first.
    If None, attempts to resolve by matching item['poster_contact'] with users.email.
    Returns user_id (int) if resolved, or None if owner cannot be reliably determined (e.g. guest report).
    """
    if not item:
        return None

    # 1. Direct user_id association on item
    try:
        raw_uid = item['user_id']
        if raw_uid is not None:
            return int(raw_uid)
    except (KeyError, IndexError, ValueError, TypeError):
        pass

    # 2. Match by poster_contact email
    contact = None
    try:
        contact = item['poster_contact']
    except (KeyError, IndexError, TypeError):
        pass

    if not contact or '@' not in contact:
        return None

    clean_email = str(contact).strip().lower()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE LOWER(email) = ?", (clean_email,))
        row = cursor.fetchone()
        if row:
            return row['id']
        return None
    finally:
        conn.close()

