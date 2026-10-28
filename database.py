"""
database.py - Database Layer for CampusConnect Lost & Found
------------------------------------------------------------
Uses Python's built-in sqlite3 module to manage persistent storage
for items and contact inquiries.

All database queries use parameterized SQL (? placeholders) to
prevent SQL Injection vulnerabilities.
"""

import sqlite3
import os
import shutil
import datetime
from werkzeug.security import generate_password_hash

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'campusconnect.db')


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
    Uses a 10.0-second timeout to prevent 'database is locked' errors on Windows.
    """
    conn = sqlite3.connect(get_db_path(), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def backup_database(backup_path=None):
    """
    Safely creates an atomic backup copy of the current database.
    If backup_path is not specified, generates a timestamped file in the same directory.
    """
    source_path = get_db_path()
    if not os.path.exists(source_path):
        return None

    if not backup_path:
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        base_dir = os.path.dirname(source_path)
        backup_path = os.path.join(base_dir, f'campusconnect_backup_{timestamp}.db')

    # Atomic online SQLite backup
    src_conn = sqlite3.connect(source_path)
    dst_conn = sqlite3.connect(backup_path)
    with dst_conn:
        src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()

    return backup_path


def init_db(seed_demo=False):
    """
    Initializes database tables if they do not exist.
    By default, demo records are NEVER seeded automatically.
    Seeding is only performed if explicitly requested (e.g. for testing)
    or if the CAMPUSCONNECT_SEED_DEMO environment variable is set to '1'.
    """
    conn = get_db_connection()
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

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

    conn.commit()

    should_seed = seed_demo or os.environ.get('CAMPUSCONNECT_SEED_DEMO') == '1'
    if should_seed:
        cursor.execute("SELECT COUNT(*) AS total FROM items")
        count_row = cursor.fetchone()
        if count_row['total'] == 0:
            seed_demo_data(conn)

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
    cursor = conn.cursor()

    # 1. Identify demo records
    cursor.execute("SELECT id, title FROM items WHERE is_demo = 1")
    demo_items = cursor.fetchall()
    demo_item_ids = [row['id'] for row in demo_items]

    demo_inquiries_count = 0
    if demo_item_ids:
        placeholders = ','.join(['?'] * len(demo_item_ids))
        cursor.execute(f"SELECT COUNT(*) AS count FROM contact_requests WHERE item_id IN ({placeholders})", demo_item_ids)
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

    conn.commit()

    # Count remaining genuine records
    cursor.execute("SELECT COUNT(*) AS count FROM items")
    genuine_items_remaining = cursor.fetchone()['count']

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
    conn.execute("DROP TABLE IF EXISTS contact_requests")
    conn.execute("DROP TABLE IF EXISTS items")
    conn.commit()
    conn.close()
    init_db(seed_demo=seed_demo)


def seed_demo_data(conn, is_demo=1):
    """
    Populates sample items for testing environments.
    Items have realistic campus titles without ugly demo tags.
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

    conn.commit()

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
        conn.commit()


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
    cursor = conn.cursor()

    sql = """
        SELECT id, item_type, title, category, location, event_date,
               description, poster_name, status, is_demo, created_at
        FROM items
        WHERE 1=1
    """
    params = []

    if not include_demo:
        sql += " AND is_demo = 0"

    if search_query and search_query.strip():
        clean_q = search_query.strip()
        escaped_q = clean_q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        wildcard = f"%{escaped_q}%"
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
    conn.close()
    return items



def get_item_by_id(item_id):
    """
    Retrieves a single item by its ID.
    Note: poster_contact is kept on the record for internal verification,
    but should not be rendered publicly on public cards or detail headers.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, item_type, title, category, location, event_date,
               description, poster_name, poster_contact, pin_hash,
               status, is_demo, created_at
        FROM items
        WHERE id = ?
    """, (item_id,))
    item = cursor.fetchone()
    conn.close()
    return item


def create_item(item_type, title, category, location, event_date,
                description, poster_name, poster_contact, pin_plain):
    """
    Inserts a newly reported lost or found item.
    The poster's security PIN is securely hashed before storage.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    pin_hash = generate_password_hash(pin_plain)

    cursor.execute("""
        INSERT INTO items (
            item_type, title, category, location, event_date,
            description, poster_name, poster_contact, pin_hash, status, is_demo
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', 0)
    """, (
        item_type, title, category, location, event_date,
        description, poster_name, poster_contact, pin_hash
    ))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id


def update_item_status(item_id, new_status):
    """
    Updates status ('open' or 'resolved') for an item using parameterized query.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE items
        SET status = ?
        WHERE id = ?
    """, (new_status, item_id))
    conn.commit()
    conn.close()


def create_contact_request(item_id, sender_name, sender_contact, message):
    """
    Stores a safe contact inquiry/claim message in the database for the item.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO contact_requests (item_id, sender_name, sender_contact, message)
        VALUES (?, ?, ?, ?)
    """, (item_id, sender_name, sender_contact, message))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id


def get_contact_requests_for_item(item_id):
    """
    Retrieves all contact inquiries for an item.
    Protected: should only be invoked after the poster's PIN is verified.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, sender_name, sender_contact, message, created_at
        FROM contact_requests
        WHERE item_id = ?
        ORDER BY created_at DESC
    """, (item_id,))
    requests = cursor.fetchall()
    conn.close()
    return requests


def get_statistics(include_demo=False):
    """
    Returns quick stats for the dashboard header:
    total items, open lost, open found, total resolved.
    Calculates counters from genuine database records.
    Uses a single aggregate SQL query for efficiency.
    """
    conn = get_db_connection()
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
    conn.close()

    if not row:
        return {'total': 0, 'open_lost': 0, 'open_found': 0, 'resolved': 0}

    return {
        'total': row['total'] or 0,
        'open_lost': row['open_lost'] or 0,
        'open_found': row['open_found'] or 0,
        'resolved': row['resolved'] or 0
    }

