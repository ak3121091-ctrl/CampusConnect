"""
app.py - CampusConnect Lost & Found Flask Application
------------------------------------------------------
A beginner-friendly, secure, and privacy-preserving web application
built for university campus lost and found management.

Runs locally with zero external paid APIs, using Python's built-in
sqlite3 database.
"""

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, abort, session
)
from werkzeug.security import check_password_hash
import re
import os
import datetime
import database

app = Flask(__name__)
# Secret key from environment variable with secure fallback for local dev
app.secret_key = os.environ.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY') or 'campusconnect-dev-key-change-in-production-2026'

CATEGORIES = [
    'Electronics',
    'Student IDs & Keys',
    'Books & Stationery',
    'Bags & Backpacks',
    'Clothing & Accessories',
    'Other / Miscellaneous'
]


# Ensure tables are ready on startup (clean initialization, no demo data auto-seeding)
with app.app_context():
    database.init_db(seed_demo=False)


# ---------------------------------------------------------------------
# Route: Home Page (Search, Filters, Separate Lost & Found Sections)
# ---------------------------------------------------------------------
@app.route('/')
def index():
    search_query = request.args.get('q', '').strip()
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
    # Displays up to 8 items matching the current active tab and filter criteria
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
# Route: Submit a New Lost or Found Item
# ---------------------------------------------------------------------
@app.route('/items/new', methods=['GET', 'POST'])
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
            except ValueError:
                errors.append("Invalid date format. Please use YYYY-MM-DD.")

        if not description or len(description) < 5 or len(description) > 2000:
            errors.append("Description must be between 5 and 2000 characters.")

        if not poster_name or len(poster_name) < 2 or len(poster_name) > 60:
            errors.append("Your name must be between 2 and 60 characters.")

        if not poster_contact or len(poster_contact) < 5 or len(poster_contact) > 100:
            errors.append("Please provide a contact email or phone number (maximum 100 characters).")

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

        # Insert item securely into SQLite
        new_item_id = database.create_item(
            item_type=item_type,
            title=title,
            category=category,
            location=location,
            event_date=event_date,
            description=description,
            poster_name=poster_name,
            poster_contact=poster_contact,
            pin_plain=pin
        )

        flash(
            f"Success! Your {item_type.upper()} item was listed. "
            f"Please remember your Security PIN ({pin}) to resolve or view inquiries later.",
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
def submit_contact_request(item_id):
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
    if not sender_contact or len(sender_contact) < 5 or len(sender_contact) > 100:
        errors.append("Please provide your email address or phone number (between 5 and 100 characters).")
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
def update_status(item_id):
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

    # Security Check: Verify PIN hash
    if not check_password_hash(item['pin_hash'], submitted_pin):
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
def view_inbox(item_id):
    item = database.get_item_by_id(item_id)
    if not item:
        abort(404)

    if request.method == 'GET':
        return redirect(url_for('item_detail', item_id=item_id, _anchor='posterInbox'))

    submitted_pin = request.form.get('pin', '').strip()

    # Security Check: Verify PIN hash
    if not check_password_hash(item['pin_hash'], submitted_pin):
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
# Error Handlers
# ---------------------------------------------------------------------
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


if __name__ == '__main__':
    # Local development server on port 5000
    print("Starting CampusConnect Lost & Found on http://127.0.0.1:5000")
    app.run(host='127.0.0.1', port=5000, debug=True)
