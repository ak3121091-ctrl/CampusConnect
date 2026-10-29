"""
manage_db.py - Safe Database Management CLI for CampusConnect
-------------------------------------------------------------
Usage:
    python manage_db.py status      - View item and inquiry counts (genuine vs demo)
    python manage_db.py backup      - Create a safe atomic backup copy of the database
    python manage_db.py clean       - Safely back up and remove all demo records
    python manage_db.py init        - Initialize tables if they do not exist (no seeding)
    python manage_db.py migrate     - Safely add new columns (e.g. image_filename) preserving data
    python manage_db.py reset-empty - Back up and reset database to clean empty state
    python manage_db.py seed        - Seed sample testing records (flagged is_demo = 1)
"""

import sys
import os
import sqlite3
import database


def print_status():
    """Prints current database status, breakdown of genuine vs demo records."""
    db_path = database.get_db_path()
    print(f"Database File: {db_path}")
    if not os.path.exists(db_path):
        print("Status: Database file does not exist yet. Run 'init' to create.")
        return

    conn = database.get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) AS total FROM items")
        total_items = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) AS genuine FROM items WHERE is_demo = 0")
        genuine_items = cursor.fetchone()['genuine']

        cursor.execute("SELECT COUNT(*) AS demo FROM items WHERE is_demo = 1")
        demo_items = cursor.fetchone()['demo']

        cursor.execute("SELECT COUNT(*) AS inquiries FROM contact_requests")
        total_inquiries = cursor.fetchone()['inquiries']

        stats = database.get_statistics(include_demo=False)

        print("\n--- CampusConnect Database Breakdown ---")
        print(f"  Total Items in DB:        {total_items}")
        print(f"  Genuine User Reports:     {genuine_items} (Active in Directory)")
        print(f"  Demo / Sample Items:      {demo_items}")
        print(f"  Contact Inquiries:        {total_inquiries}")
        print("\n--- Active Dashboard Statistics (Genuine Only) ---")
        print(f"  Total:     {stats['total']}")
        print(f"  Open Lost: {stats['open_lost']}")
        print(f"  Open Found:{stats['open_found']}")
        print(f"  Resolved:  {stats['resolved']}")
        print("----------------------------------------\n")
    except sqlite3.OperationalError as e:
        print(f"Database Error: {e}. Tables might not be initialized.")
    finally:
        conn.close()


def do_backup():
    """Creates a timestamped backup."""
    backup_path = database.backup_database()
    if backup_path:
        print(f"[SUCCESS] Database safely backed up to:\n  {backup_path}")
    else:
        print("[WARNING] Source database file not found. Nothing to back up.")


def do_clean():
    """Backs up database and safely purges all is_demo=1 records."""
    print("Initiating safe demo data cleanup...")
    summary = database.cleanup_demo_records(backup=True)
    if summary['backup_path']:
        print(f"1. Pre-cleanup backup created: {summary['backup_path']}")
    print(f"2. Demo items removed:          {summary['demo_items_removed']}")
    print(f"3. Demo inquiries removed:      {summary['demo_inquiries_removed']}")
    print(f"4. Genuine user items retained: {summary['genuine_items_remaining']}")
    print("[SUCCESS] Cleanup complete. Database is prepared for real campus use.")


def do_init():
    """Initializes tables without seeding demo data."""
    database.init_db(seed_demo=False)
    print(f"[SUCCESS] Database initialized at: {database.get_db_path()}")
    print("Tables ready. No demo data was seeded.")


def do_migrate():
    """Applies safe database migrations."""
    db_path = database.get_db_path()
    if not os.path.exists(db_path):
        print("Database does not exist yet. Initializing...")
        database.init_db()
        print("[SUCCESS] Database initialized with latest schema.")
        return
    backup_path = database.backup_database()
    if backup_path:
        print(f"Pre-migration backup created at: {backup_path}")
    migrated = database.migrate_db()
    if migrated:
        print("[SUCCESS] Database migrated successfully. 'image_filename' column added.")
    else:
        print("[INFO] Database schema is already up to date. No migration needed.")


def do_reset_empty():
    """Backs up and resets database to an empty state."""
    db_path = database.get_db_path()
    if os.path.exists(db_path):
        backup_path = database.backup_database()
        if backup_path:
            print(f"Pre-reset backup created at: {backup_path}")
    database.reset_db(seed_demo=False)
    print("[SUCCESS] Database tables reset to a clean, empty state with 0 items.")


def do_seed():
    """Seeds sample items for testing."""
    conn = database.get_db_connection()
    database.seed_demo_data(conn)
    conn.close()
    print("[SUCCESS] Sample items seeded with is_demo = 1.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1].strip().lower()
    if cmd == 'status':
        print_status()
    elif cmd == 'backup':
        do_backup()
    elif cmd == 'clean':
        do_clean()
    elif cmd == 'init':
        do_init()
    elif cmd == 'migrate':
        do_migrate()
    elif cmd == 'reset-empty':
        do_reset_empty()
    elif cmd == 'seed':
        do_seed()
    else:
        print(f"Unknown command: '{cmd}'")
        print(__doc__)


if __name__ == '__main__':
    main()
