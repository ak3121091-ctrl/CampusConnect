"""
test_app.py - Comprehensive Automated Test Suite for CampusConnect
------------------------------------------------------------------
Tests all routes, SQL parameterization, authorization, input validation,
CSRF protection, rate limiting, safe contact inquiries, error handling,
security headers, and database persistence.

Uses an isolated temporary database with dynamic fixtures that do not
rely on hardcoded demo data or static PINs.
"""

import os
import re
import tempfile
import unittest
import uuid
import datetime
import io
import shutil
from PIL import Image

# Configure isolated temporary SQLite test database
TEST_DB_DIR = tempfile.mkdtemp(prefix="campusconnect_test_")
TEST_DB_PATH = os.path.join(TEST_DB_DIR, f"test_{uuid.uuid4().hex}.db")
os.environ['CAMPUSCONNECT_DB'] = TEST_DB_PATH
os.environ['FLASK_ENV'] = 'testing'
os.environ['CAMPUSCONNECT_SEED_DEMO'] = '0'

TEST_UPLOAD_DIR = tempfile.mkdtemp(prefix="campusconnect_test_uploads_")
os.environ['CAMPUSCONNECT_UPLOAD_DIR'] = TEST_UPLOAD_DIR

import database
from app import app, limiter


class CampusConnectTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Initialize tables on clean isolated test database with NO demo data
        database.reset_db(seed_demo=False)

    @classmethod
    def tearDownClass(cls):
        # Safely clean up temporary test database files
        for suffix in ('', '-wal', '-shm'):
            fpath = TEST_DB_PATH + suffix
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception:
                    pass
        if os.path.exists(TEST_DB_DIR):
            try:
                os.rmdir(TEST_DB_DIR)
            except Exception:
                pass
        if os.path.exists(TEST_UPLOAD_DIR):
            try:
                shutil.rmtree(TEST_UPLOAD_DIR, ignore_errors=True)
            except Exception:
                pass

    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        # Default: disable CSRF for functional unit tests unless explicitly testing CSRF
        self.app.config['WTF_CSRF_ENABLED'] = False
        # Disable rate limiting for standard tests unless explicitly testing rate limits
        limiter.enabled = False
        self.client = self.app.test_client()

    # ------------------------------------------------------------------
    # 1. Empty Database & Dashboard Stats Tests
    # ------------------------------------------------------------------
    def test_01_empty_database_and_stats(self):
        """Verify empty database loads with 0 counts and clean welcoming empty state."""
        stats = database.get_statistics()
        self.assertEqual(stats['total'], 0)
        self.assertEqual(stats['open_lost'], 0)
        self.assertEqual(stats['open_found'], 0)
        self.assertEqual(stats['resolved'], 0)

        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        self.assertIn('No items yet', html)
        self.assertIn('CampusConnect', html)
        self.assertIn('Report Lost Item', html)

    # ------------------------------------------------------------------
    # 2. Dynamic Item Creation & Persistence
    # ------------------------------------------------------------------
    def test_02_create_dynamic_item_and_verify_persistence(self):
        """Verify submitting an item stores to SQLite, hashes the PIN, and redirects."""
        unique_suffix = uuid.uuid4().hex[:6]
        item_title = f"Test Laptop {unique_suffix}"
        item_pin = "8520"

        payload = {
            'item_type': 'lost',
            'title': item_title,
            'category': 'Electronics',
            'location': f'Hall Room {unique_suffix}',
            'event_date': datetime.date.today().strftime('%Y-%m-%d'),
            'description': f'A unique black laptop for testing {unique_suffix}.',
            'poster_name': f'Tester {unique_suffix}',
            'poster_contact': f'tester.{unique_suffix}@campus.edu',
            'pin': item_pin
        }

        res = self.client.post('/items/new', data=payload, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        new_item_id = int(res.headers['Location'].split('/')[-1])

        # Verify record directly in database
        item = database.get_item_by_id(new_item_id)
        self.assertIsNotNone(item)
        self.assertEqual(item['title'], item_title)
        self.assertEqual(item['status'], 'open')
        self.assertEqual(item['item_type'], 'lost')

        # Crucial security check: PIN must NOT be stored in plain text
        self.assertNotEqual(item['pin_hash'], item_pin)
        self.assertTrue(item['pin_hash'].startswith('scrypt:') or item['pin_hash'].startswith('pbkdf2:'))

    # ------------------------------------------------------------------
    # 3. Item Detail & Privacy Check
    # ------------------------------------------------------------------
    def test_03_item_detail_privacy_protection(self):
        """Verify item detail page renders details but NEVER reveals private poster contact."""
        unique_pin = "4815"
        unique_email = f"private.{uuid.uuid4().hex[:6]}@campus.edu"
        item_id = database.create_item(
            item_type='found',
            title='Found Stainless Water Bottle',
            category='Clothing & Accessories',
            location='Campus Gym Bleachers',
            event_date='2026-10-28',
            description='Silver bottle with mountain decals.',
            poster_name='Fitness Staff',
            poster_contact=unique_email,
            pin_plain=unique_pin
        )

        res = self.client.get(f'/items/{item_id}')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertIn('Found Stainless Water Bottle', html)
        self.assertIn('Fitness Staff', html)
        self.assertIn('Campus Gym Bleachers', html)

        # PRIVACY GUARANTEE: Private contact info must NEVER be exposed publicly
        self.assertNotIn(unique_email, html)

    # ------------------------------------------------------------------
    # 4. Search Functionality
    # ------------------------------------------------------------------
    def test_04_search_filters_and_queries(self):
        """Verify keyword search across titles, locations, and categories."""
        unique_key = uuid.uuid4().hex[:5]
        item_id = database.create_item(
            item_type='lost',
            title=f'Golden Fountain Pen {unique_key}',
            category='Books & Stationery',
            location=f'Law Library Pod {unique_key}',
            event_date='2026-10-27',
            description='Gold-nib fountain pen engraved with initials.',
            poster_name=f'Scholar {unique_key}',
            poster_contact=f'scholar{unique_key}@campus.edu',
            pin_plain='3344'
        )

        # 1. Search by title
        res_title = self.client.get(f'/?q=Pen+{unique_key}')
        self.assertEqual(res_title.status_code, 200)
        self.assertIn(f'Golden Fountain Pen {unique_key}', res_title.data.decode('utf-8'))

        # 2. Search by location
        res_loc = self.client.get(f'/?q=Law+Library+{unique_key}')
        self.assertEqual(res_loc.status_code, 200)
        self.assertIn(f'Golden Fountain Pen {unique_key}', res_loc.data.decode('utf-8'))

        # 3. Search non-matching query
        res_nomatch = self.client.get('/?q=NOMATCHINGSTRINGXYZ789')
        self.assertEqual(res_nomatch.status_code, 200)
        self.assertIn('No matching items found', res_nomatch.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 5. Search Wildcard & SQL Escaping
    # ------------------------------------------------------------------
    def test_05_search_wildcard_escaping(self):
        """Verify searching for %, _, quotes, and backslashes executes safely."""
        for q in ('%25', '_', "' OR '1'='1", '\\', '"><script>'):
            res = self.client.get(f'/?q={q}')
            self.assertEqual(res.status_code, 200)

    # ------------------------------------------------------------------
    # 6. Type, Category, and Status Filters
    # ------------------------------------------------------------------
    def test_06_filter_by_type_category_and_status(self):
        """Verify filtering by lost/found, categories, and resolution status."""
        lost_id = database.create_item(
            item_type='lost',
            title='Lost Blue Umbrella',
            category='Clothing & Accessories',
            location='Library Vestibule',
            event_date='2026-10-27',
            description='Compact folding umbrella.',
            poster_name='Umbrella Owner',
            poster_contact='owner@campus.edu',
            pin_plain='1122'
        )

        found_id = database.create_item(
            item_type='found',
            title='Found Casio Watch',
            category='Electronics',
            location='Cafeteria Table 4',
            event_date='2026-10-28',
            description='Black digital sports watch.',
            poster_name='Cafe Worker',
            poster_contact='worker@campus.edu',
            pin_plain='1122'
        )

        # Mark watch resolved
        database.update_item_status(found_id, 'resolved')

        # Filter by type=lost
        res_lost = self.client.get('/?type=lost')
        self.assertEqual(res_lost.status_code, 200)
        html_lost = res_lost.data.decode('utf-8')
        self.assertIn('Lost Blue Umbrella', html_lost)

        # Filter by status=resolved
        res_res = self.client.get('/?status=resolved')
        self.assertEqual(res_res.status_code, 200)
        html_res = res_res.data.decode('utf-8')
        self.assertIn('Found Casio Watch', html_res)

        # Filter by category=Electronics
        res_cat = self.client.get('/?category=Electronics')
        self.assertEqual(res_cat.status_code, 200)
        self.assertIn('Found Casio Watch', res_cat.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 7. Server-Side Input Validation
    # ------------------------------------------------------------------
    def test_07_server_side_validation(self):
        """Verify server rejects malformed submissions with informative error messages."""
        # 1. Missing fields and invalid lengths
        invalid_data = {
            'item_type': 'lost',
            'title': 'A',  # too short (< 3)
            'category': 'BogusCategory',
            'location': 'X',  # too short (< 3)
            'event_date': '2099-01-01',  # future date
            'description': 'hi',  # too short (< 5)
            'poster_name': '',
            'poster_contact': 'bad',  # invalid contact
            'pin': 'abc'  # invalid non-numeric PIN
        }

        res = self.client.post('/items/new', data=invalid_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('Title must be between 3 and 100 characters', html)
        self.assertIn('Please select a valid category', html)
        self.assertIn('Date cannot be in the future', html)
        self.assertIn('Security PIN must be 4 to 8 digits', html)
        self.assertIn('valid contact email address or phone number', html)

        # 2. Pre-2000 date validation
        old_date_data = dict(invalid_data, title='Valid Title', category='Electronics',
                              location='Valid Location', event_date='1980-05-15',
                              description='Valid description text', poster_name='Valid Name',
                              poster_contact='valid@campus.edu', pin='1234')
        res_old = self.client.post('/items/new', data=old_date_data, follow_redirects=True)
        self.assertEqual(res_old.status_code, 200)
        self.assertIn('year 2000 or later', res_old.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 8. Safe Contact Inquiry Submission
    # ------------------------------------------------------------------
    def test_08_safe_contact_inquiry_submission(self):
        """Verify visitor can submit a private inquiry without exposing poster email."""
        item_id = database.create_item(
            item_type='lost',
            title='Lost Graphing Notebook',
            category='Books & Stationery',
            location='Engineering Lounge',
            event_date='2026-10-27',
            description='Grid notebook with circuits diagrams.',
            poster_name='Eng Student',
            poster_contact='eng.student@campus.edu',
            pin_plain='9988'
        )

        inquiry_data = {
            'sender_name': 'Good Samaritan',
            'sender_contact': 'samaritan@campus.edu',
            'message': 'I saw your notebook on the round table in the student lounge!'
        }

        res = self.client.post(f'/items/{item_id}/contact', data=inquiry_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Inquiry saved!', res.data.decode('utf-8'))

        # Verify persisted in database
        inquiries = database.get_contact_requests_for_item(item_id)
        self.assertEqual(len(inquiries), 1)
        self.assertEqual(inquiries[0]['sender_name'], 'Good Samaritan')
        self.assertEqual(inquiries[0]['message'], 'I saw your notebook on the round table in the student lounge!')

    # ------------------------------------------------------------------
    # 9. Contact Inquiry Validation & Draft Preservation
    # ------------------------------------------------------------------
    def test_09_contact_draft_preserved_on_error(self):
        """Verify draft text is preserved if contact inquiry validation fails."""
        item_id = database.create_item(
            item_type='lost',
            title='Lost USB Flash Drive',
            category='Electronics',
            location='Lab B',
            event_date='2026-10-27',
            description='Red 64GB flash drive.',
            poster_name='Lab Tech',
            poster_contact='tech@campus.edu',
            pin_plain='7766'
        )

        draft_message = "I picked this up from the computer lab desk."
        invalid_inquiry = {
            'sender_name': 'A',  # too short
            'sender_contact': 'valid.finder@campus.edu',
            'message': draft_message
        }

        res = self.client.post(f'/items/{item_id}/contact', data=invalid_inquiry, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('between 2 and 60 characters', html)
        # Verify drafted message is preserved
        self.assertIn(draft_message, html)

    # ------------------------------------------------------------------
    # 10. Status Change PIN Authorization
    # ------------------------------------------------------------------
    def test_10_status_change_pin_authorization(self):
        """Verify only the poster with the correct PIN can resolve or reopen items."""
        correct_pin = "6543"
        item_id = database.create_item(
            item_type='lost',
            title='Lost Blue Backpack',
            category='Bags & Backpacks',
            location='Bus Stop 2',
            event_date='2026-10-27',
            description='Backpack with chemistry notebooks.',
            poster_name='Student B',
            poster_contact='student.b@campus.edu',
            pin_plain=correct_pin
        )

        # 1. Attempt status change with WRONG PIN
        res_wrong = self.client.post(f'/items/{item_id}/status', data={
            'pin': '0000',
            'status': 'resolved'
        }, follow_redirects=True)
        self.assertEqual(res_wrong.status_code, 200)
        self.assertIn('Incorrect Security PIN', res_wrong.data.decode('utf-8'))
        self.assertEqual(database.get_item_by_id(item_id)['status'], 'open')

        # 2. Attempt status change with CORRECT PIN
        res_correct = self.client.post(f'/items/{item_id}/status', data={
            'pin': correct_pin,
            'status': 'resolved'
        }, follow_redirects=True)
        self.assertEqual(res_correct.status_code, 200)
        self.assertIn('successfully updated to', res_correct.data.decode('utf-8'))
        self.assertEqual(database.get_item_by_id(item_id)['status'], 'resolved')

        # 3. Reopen status with CORRECT PIN
        res_reopen = self.client.post(f'/items/{item_id}/status', data={
            'pin': correct_pin,
            'status': 'open'
        }, follow_redirects=True)
        self.assertEqual(res_reopen.status_code, 200)
        self.assertEqual(database.get_item_by_id(item_id)['status'], 'open')

    # ------------------------------------------------------------------
    # 11. Inbox Unlock PIN Authorization
    # ------------------------------------------------------------------
    def test_11_inbox_unlock_pin_authorization(self):
        """Verify only poster with correct PIN can unlock and view private inquiries."""
        owner_pin = "9876"
        item_id = database.create_item(
            item_type='found',
            title='Found Car Keys',
            category='Student IDs & Keys',
            location='Parking Lot D',
            event_date='2026-10-28',
            description='Honda key on a red lanyard.',
            poster_name='Lot Attendant',
            poster_contact='attendant@campus.edu',
            pin_plain=owner_pin
        )

        # Add an inquiry
        secret_message = "These are my Honda keys! My phone number is 555-0199."
        database.create_contact_request(item_id, 'Claimant Car Owner', 'owner@campus.edu', secret_message)

        # 1. Visitor viewing page without unlock should NOT see inquiries
        res_public = self.client.get(f'/items/{item_id}')
        self.assertEqual(res_public.status_code, 200)
        self.assertNotIn(secret_message, res_public.data.decode('utf-8'))

        # 2. Attempt unlock with WRONG PIN
        res_wrong = self.client.post(f'/items/{item_id}/inbox', data={'pin': '1111'}, follow_redirects=True)
        self.assertEqual(res_wrong.status_code, 200)
        self.assertIn('Incorrect Security PIN', res_wrong.data.decode('utf-8'))
        self.assertNotIn(secret_message, res_wrong.data.decode('utf-8'))

        # 3. Attempt unlock with CORRECT PIN
        res_correct = self.client.post(f'/items/{item_id}/inbox', data={'pin': owner_pin}, follow_redirects=True)
        self.assertEqual(res_correct.status_code, 200)
        html_correct = res_correct.data.decode('utf-8')
        self.assertIn('PIN Verified!', html_correct)
        self.assertIn(secret_message, html_correct)

    # ------------------------------------------------------------------
    # 12. CSRF Protection Enforcement
    # ------------------------------------------------------------------
    def test_12_csrf_protection_enforcement(self):
        """Verify state-changing POST requests without CSRF tokens are rejected when CSRF is enabled."""
        csrf_app = app
        csrf_app.config['WTF_CSRF_ENABLED'] = True
        csrf_client = csrf_app.test_client()

        # Attempt POST without CSRF token
        res_unprotected = csrf_client.post('/items/new', data={
            'item_type': 'lost',
            'title': 'CSRF Attack Attempt',
            'category': 'Electronics',
            'location': 'Library',
            'event_date': '2026-10-28',
            'description': 'Malicious forged request.',
            'poster_name': 'Attacker',
            'poster_contact': 'attacker@campus.edu',
            'pin': '1234'
        })
        self.assertEqual(res_unprotected.status_code, 400)
        self.assertIn('400 BAD REQUEST', res_unprotected.data.decode('utf-8'))

        # Now extract valid CSRF token from GET form
        res_get = csrf_client.get('/items/new')
        self.assertEqual(res_get.status_code, 200)
        html = res_get.data.decode('utf-8')
        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        self.assertIsNotNone(match, "CSRF token hidden input must be rendered in form")
        valid_token = match.group(1)

        # POST with valid CSRF token should succeed
        res_protected = csrf_client.post('/items/new', data={
            'csrf_token': valid_token,
            'item_type': 'lost',
            'title': 'Legitimate Item With CSRF Token',
            'category': 'Electronics',
            'location': 'Student Union',
            'event_date': '2026-10-28',
            'description': 'Legitimate submission with proper CSRF token.',
            'poster_name': 'Authorized User',
            'poster_contact': 'authorized@campus.edu',
            'pin': '1234'
        }, follow_redirects=False)
        self.assertEqual(res_protected.status_code, 302)

    # ------------------------------------------------------------------
    # 13. Rate Limiting Abuse Prevention
    # ------------------------------------------------------------------
    def test_13_rate_limiting_protection(self):
        """Verify rate limiter blocks rapid repeated submissions to prevent abuse."""
        rate_app = app
        rate_app.config['TESTING'] = True
        rate_app.config['WTF_CSRF_ENABLED'] = False
        limiter.enabled = True
        limiter.reset()
        rate_client = rate_app.test_client()

        item_id = database.create_item(
            item_type='lost',
            title='Rate Limit Test Item',
            category='Electronics',
            location='Test Hall',
            event_date='2026-10-28',
            description='Rate limiting test item.',
            poster_name='Tester',
            poster_contact='tester@campus.edu',
            pin_plain='5555'
        )

        hit_429 = False
        # Limit on status update is 15 per minute
        for i in range(25):
            res = rate_client.post(f'/items/{item_id}/status', data={
                'pin': '9999',
                'status': 'resolved'
            })
            if res.status_code == 429:
                hit_429 = True
                self.assertIn('429 RATE LIMIT EXCEEDED', res.data.decode('utf-8'))
                break

        self.assertTrue(hit_429, "Rate limiter should trigger 429 on excessive rapid requests")
        limiter.enabled = False

    # ------------------------------------------------------------------
    # 14. Invalid IDs and Malformed Inputs
    # ------------------------------------------------------------------
    def test_14_invalid_ids_and_nonexistent_records(self):
        """Verify invalid or nonexistent item IDs return 404."""
        for invalid_id in (-1, 0, 999999):
            res = self.client.get(f'/items/{invalid_id}')
            self.assertEqual(res.status_code, 404)
            self.assertIn('Page Not Found', res.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 15. Query Parameter Normalization
    # ------------------------------------------------------------------
    def test_15_query_parameter_normalization(self):
        """Verify bogus or empty query params normalize without crashing."""
        for url in ('/?type=', '/?type=nonsense', '/?category=', '/?category=Invalid', '/?status=', '/?status=invalid'):
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200)

    # ------------------------------------------------------------------
    # 16. XSS Protection
    # ------------------------------------------------------------------
    def test_16_xss_autoescaping_protection(self):
        """Verify HTML/Script injection in user fields is auto-escaped by Jinja2."""
        xss_payload = {
            'item_type': 'lost',
            'title': '<script>alert("XSS")</script>',
            'category': 'Electronics',
            'location': '<img src=x onerror=alert(1)>',
            'event_date': '2026-10-28',
            'description': '<script>document.cookie</script>',
            'poster_name': '<b>BoldPoster</b>',
            'poster_contact': 'xss@campus.edu',
            'pin': '1234'
        }

        res = self.client.post('/items/new', data=xss_payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertNotIn('<script>alert("XSS")</script>', html)
        self.assertIn('&lt;script&gt;alert(&#34;XSS&#34;)&lt;/script&gt;', html)

    # ------------------------------------------------------------------
    # 17. Action Endpoints GET Redirection
    # ------------------------------------------------------------------
    def test_17_action_endpoints_redirect_on_get(self):
        """Verify GET requests to POST-only action endpoints redirect safely without 405 errors."""
        item_id = database.create_item(
            item_type='found',
            title='Test Redirect Item',
            category='Electronics',
            location='Library',
            event_date='2026-10-28',
            description='Test item.',
            poster_name='Tester',
            poster_contact='test@campus.edu',
            pin_plain='1234'
        )

        for endpoint in ('status', 'contact', 'inbox'):
            res = self.client.get(f'/items/{item_id}/{endpoint}')
            self.assertEqual(res.status_code, 302)
            self.assertIn(f'/items/{item_id}', res.headers['Location'])

    # ------------------------------------------------------------------
    # 18. Dashboard Count Consistency Invariant
    # ------------------------------------------------------------------
    def test_18_dashboard_counts_invariant(self):
        """Verify stats total == open_lost + open_found + resolved invariant holds."""
        stats = database.get_statistics()
        self.assertEqual(stats['total'], stats['open_lost'] + stats['open_found'] + stats['resolved'])

    # ------------------------------------------------------------------
    # 19. Security Response Headers
    # ------------------------------------------------------------------
    def test_19_security_response_headers(self):
        """Verify security headers are attached to every response."""
        res = self.client.get('/')
        self.assertEqual(res.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(res.headers.get('X-Frame-Options'), 'SAMEORIGIN')
        self.assertEqual(res.headers.get('Referrer-Policy'), 'strict-origin-when-cross-origin')
        self.assertIn("default-src 'self'", res.headers.get('Content-Security-Policy', ''))

    # ------------------------------------------------------------------
    # 20. Responsive CSS Rules Verification
    # ------------------------------------------------------------------
    def test_20_responsive_css_rules(self):
        """Verify mobile breakpoints, overflow protection, and touch target styles exist."""
        css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'css', 'styles.css')
        with open(css_path, 'r', encoding='utf-8') as f:
            css = f.read()

        # Breakpoints
        self.assertIn('@media (max-width: 1023px)', css)
        self.assertIn('@media (max-width: 767px)', css)
        self.assertIn('@media (max-width: 480px)', css)
        self.assertIn('@media (max-width: 375px)', css)
        self.assertIn('@media (max-width: 330px)', css)

        # Overflow protection
        self.assertIn('overflow-x: hidden', css)
        self.assertIn('min-height: 44px', css)


    # ------------------------------------------------------------------
    # 21. Repeated Submissions & Multiple Inquiries
    # ------------------------------------------------------------------
    def test_21_repeated_submissions_and_multiple_inquiries(self):
        """Verify multiple separate contact inquiries persist and appear in descending chronological order."""
        item_pin = "4321"
        item_id = database.create_item(
            item_type='lost',
            title='Lost Black Umbrella',
            category='Clothing & Accessories',
            location='Campus Center Lobby',
            event_date='2026-10-28',
            description='Black umbrella with wooden curved handle.',
            poster_name='Umbrella Owner',
            poster_contact='owner.umbrella@campus.edu',
            pin_plain=item_pin
        )

        # Submit inquiry 1
        res1 = self.client.post(f'/items/{item_id}/contact', data={
            'sender_name': 'Inquirer One',
            'sender_contact': 'inq1@campus.edu',
            'message': 'First message about the umbrella location.'
        }, follow_redirects=True)
        self.assertEqual(res1.status_code, 200)

        # Submit inquiry 2
        res2 = self.client.post(f'/items/{item_id}/contact', data={
            'sender_name': 'Inquirer Two',
            'sender_contact': 'inq2@campus.edu',
            'message': 'Second message checking if it was recovered.'
        }, follow_redirects=True)
        self.assertEqual(res2.status_code, 200)

        # Unlock inbox with PIN
        res_inbox = self.client.post(f'/items/{item_id}/inbox', data={'pin': item_pin}, follow_redirects=True)
        self.assertEqual(res_inbox.status_code, 200)
        html = res_inbox.data.decode('utf-8')
        self.assertIn('2 inquiry message(s)', html)
        self.assertIn('Inquirer One', html)
        self.assertIn('Inquirer Two', html)
        self.assertIn('First message about the umbrella location.', html)
        self.assertIn('Second message checking if it was recovered.', html)

    # ------------------------------------------------------------------
    # 22. Malformed PIN Formats
    # ------------------------------------------------------------------
    def test_22_malformed_pin_formats_rejected(self):
        """Verify non-numeric, too short (< 4), and too long (> 8) PINs are rejected."""
        base_payload = {
            'item_type': 'lost',
            'title': 'Test Item PIN Format',
            'category': 'Electronics',
            'location': 'Library Pod 4',
            'event_date': '2026-10-28',
            'description': 'Valid test description.',
            'poster_name': 'Tester',
            'poster_contact': 'tester@campus.edu',
        }

        # 1. Too short (3 digits)
        res_short = self.client.post('/items/new', data=dict(base_payload, pin='123'), follow_redirects=True)
        self.assertIn('Security PIN must be 4 to 8 digits', res_short.data.decode('utf-8'))

        # 2. Too long (9 digits)
        res_long = self.client.post('/items/new', data=dict(base_payload, pin='123456789'), follow_redirects=True)
        self.assertIn('Security PIN must be 4 to 8 digits', res_long.data.decode('utf-8'))

        # 3. Alphanumeric / Letters
        res_letters = self.client.post('/items/new', data=dict(base_payload, pin='12ab'), follow_redirects=True)
        self.assertIn('Security PIN must be 4 to 8 digits', res_letters.data.decode('utf-8'))

        # 4. Spaces inside PIN
        res_spaces = self.client.post('/items/new', data=dict(base_payload, pin='12 34'), follow_redirects=True)
        self.assertIn('Security PIN must be 4 to 8 digits', res_spaces.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 23. Boundary Field Length Validation
    # ------------------------------------------------------------------
    def test_23_input_boundary_lengths_enforced(self):
        """Verify inputs exceeding maximum character limits are rejected."""
        valid_payload = {
            'item_type': 'lost',
            'title': 'Normal Title',
            'category': 'Electronics',
            'location': 'Normal Hall Room 101',
            'event_date': '2026-10-28',
            'description': 'Normal valid description text.',
            'poster_name': 'Alex Chen',
            'poster_contact': 'alex@campus.edu',
            'pin': '1234'
        }

        # Title > 100 characters
        res_title = self.client.post('/items/new', data=dict(valid_payload, title='T' * 101), follow_redirects=True)
        self.assertIn('Title must be between 3 and 100 characters', res_title.data.decode('utf-8'))

        # Location > 120 characters
        res_loc = self.client.post('/items/new', data=dict(valid_payload, location='L' * 121), follow_redirects=True)
        self.assertIn('Campus location must be between 3 and 120 characters', res_loc.data.decode('utf-8'))

        # Description > 2000 characters
        res_desc = self.client.post('/items/new', data=dict(valid_payload, description='D' * 2001), follow_redirects=True)
        self.assertIn('Description must be between 5 and 2000 characters', res_desc.data.decode('utf-8'))

        # Poster Name > 60 characters
        res_name = self.client.post('/items/new', data=dict(valid_payload, poster_name='N' * 61), follow_redirects=True)
        self.assertIn('Your name must be between 2 and 60 characters', res_name.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 24. Database Layer Defensive Methods
    # ------------------------------------------------------------------
    def test_24_database_layer_defensive_methods(self):
        """Verify database helper functions gracefully handle invalid inputs without exceptions."""
        # Non-numeric or invalid string IDs
        self.assertIsNone(database.get_item_by_id("non_numeric"))
        self.assertIsNone(database.get_item_by_id(-99))
        self.assertIsNone(database.get_item_by_id(0))

        # Status update with invalid ID or invalid status
        self.assertFalse(database.update_item_status("bad_id", "resolved"))
        self.assertFalse(database.update_item_status(1, "invalid_status_value"))

        # Contact requests with invalid ID
        self.assertIsNone(database.create_contact_request("not_an_int", "Name", "email@campus.edu", "Msg"))
        self.assertEqual(database.get_contact_requests_for_item("invalid"), [])
        self.assertEqual(database.get_contact_requests_for_item(-5), [])

    # ------------------------------------------------------------------
    # 25. Safe Repeated Database Initialization
    # ------------------------------------------------------------------
    def test_25_repeated_database_init_safety(self):
        """Verify init_db() can run repeatedly without resetting or deleting genuine data."""
        item_id = database.create_item(
            item_type='found',
            title='Persistent Item Test',
            category='Electronics',
            location='Library Desk',
            event_date='2026-10-28',
            description='Item that must survive init_db calls.',
            poster_name='Persistent Poster',
            poster_contact='poster@campus.edu',
            pin_plain='9900'
        )

        # Call init_db multiple times
        database.init_db(seed_demo=False)
        database.init_db(seed_demo=False)

        # Verify item still exists unchanged
        item = database.get_item_by_id(item_id)
        self.assertIsNotNone(item)
        self.assertEqual(item['title'], 'Persistent Item Test')

    # ------------------------------------------------------------------
    # 26. Production Secret Key Rejection on Insecure Placeholder
    # ------------------------------------------------------------------
    def test_26_production_secret_key_rejection(self):
        """Verify that running in production without a valid secret key fails safely."""
        import subprocess
        import sys

        cmd = [
            sys.executable,
            "-c",
            "import os; os.environ['FLASK_ENV']='production'; os.environ['SECRET_KEY']='your-production-secret-key-replace-with-at-least-32-characters'; import app"
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("CRITICAL SECURITY CONFIGURATION ERROR", proc.stderr)

    # ------------------------------------------------------------------
    # 27. Bogus Status Value Rejected
    # ------------------------------------------------------------------
    def test_27_bogus_status_value_rejected(self):
        """Verify that updating an item with a bogus status is rejected."""
        item_id = database.create_item(
            item_type='lost',
            title='Test Status Item',
            category='Electronics',
            location='Hall 1',
            event_date='2026-10-28',
            description='Test item.',
            poster_name='Tester',
            poster_contact='test@campus.edu',
            pin_plain='1234'
        )

        res = self.client.post(f'/items/{item_id}/status', data={
            'pin': '1234',
            'status': 'invalid_bogus_status'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Invalid status selected', res.data.decode('utf-8'))
        self.assertEqual(database.get_item_by_id(item_id)['status'], 'open')

    # ------------------------------------------------------------------
    # 28. Filter Tabs and itemsResults Anchor Integration
    # ------------------------------------------------------------------
    def test_28_filter_tabs_and_items_results_anchor(self):
        """Verify itemsResults anchor, form action, and tab aria-selected state."""
        # Check base homepage
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Form action must include #itemsResults
        self.assertIn('action="/#itemsResults"', html)
        self.assertIn('id="filterForm"', html)

        # Stable results container must exist
        self.assertIn('id="itemsResults"', html)

        # Tab buttons must have correct IDs, roles, and controls
        self.assertIn('id="tabAllItems"', html)
        self.assertIn('id="tabLostItems"', html)
        self.assertIn('id="tabFoundItems"', html)
        self.assertIn('aria-controls="itemsResults"', html)

        # On default visit (type=all), All tab is active
        self.assertIn('id="tabAllItems"\n                            class="type-tab-btn active"', html)

        # Test type=lost
        res_lost = self.client.get('/?type=lost')
        self.assertEqual(res_lost.status_code, 200)
        html_lost = res_lost.data.decode('utf-8')
        self.assertIn('id="tabLostItems"\n                            class="type-tab-btn tab-lost active"', html_lost)

        # Test type=found
        res_found = self.client.get('/?type=found')
        self.assertEqual(res_found.status_code, 200)
        html_found = res_found.data.decode('utf-8')
        self.assertIn('id="tabFoundItems"\n                            class="type-tab-btn tab-found active"', html_found)

    # ------------------------------------------------------------------
    # 29. Clear Search Preserves Selected Filters
    # ------------------------------------------------------------------
    def test_29_clear_search_preserves_other_filters(self):
        """Verify clear search link clears ONLY q parameter while keeping type, category, status."""
        # Access with all filter parameters active
        res = self.client.get('/?q=calculator&type=lost&category=Electronics&status=open')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Clear search button must be present
        self.assertIn('id="clearSearchBtn"', html)
        self.assertIn('class="search-clear-btn"', html)

        # Extract clear search href
        match = re.search(r'id="clearSearchBtn"[^>]*href="([^"]+)"', html)
        if not match:
            match = re.search(r'href="([^"]+)"[^>]*id="clearSearchBtn"', html)
        self.assertIsNotNone(match, "clearSearchBtn must have an href")
        clear_href = match.group(1)

        # Must preserve category, type, status and anchor to #itemsResults
        self.assertIn('type=lost', clear_href)
        self.assertIn('category=Electronics', clear_href)
        self.assertIn('status=open', clear_href)
        self.assertIn('#itemsResults', clear_href)

        # Must NOT contain the q query parameter
        self.assertNotIn('q=', clear_href)

    # ------------------------------------------------------------------
    # 30. Active Filter Banner Displays All Variants and Individual Clears
    # ------------------------------------------------------------------
    def test_30_active_filter_banner_all_variants_and_individual_clears(self):
        """Verify active filter banner displays Type, Query, Category, Status tags and individual clear links."""
        # 1. Type: Lost banner
        res_lost = self.client.get('/?type=lost')
        html_lost = res_lost.data.decode('utf-8')
        self.assertIn('class="active-filter-banner"', html_lost)
        self.assertIn('Type: Lost', html_lost)
        self.assertIn('tag-type-lost', html_lost)
        self.assertIn('aria-label="Remove Lost filter"', html_lost)

        # 2. Type: Found banner
        res_found = self.client.get('/?type=found')
        html_found = res_found.data.decode('utf-8')
        self.assertIn('class="active-filter-banner"', html_found)
        self.assertIn('Type: Found', html_found)
        self.assertIn('tag-type-found', html_found)
        self.assertIn('aria-label="Remove Found filter"', html_found)

        # 3. Combined filters: Query + Category + Status
        res_comb = self.client.get('/?q=keys&type=found&category=Student+IDs+%26+Keys&status=open')
        html_comb = res_comb.data.decode('utf-8')
        self.assertIn('Type: Found', html_comb)
        self.assertIn('Query: "keys"', html_comb)
        self.assertIn('Category: Student IDs &amp; Keys', html_comb)
        self.assertIn('Status: Open', html_comb)

        # Clear All link must reset to #itemsResults
        self.assertIn('id="clearAllFiltersBtn"', html_comb)
        self.assertIn('href="/#itemsResults"', html_comb)

    # ------------------------------------------------------------------
    # 31. Search and Filter Combinations & Counts Consistency
    # ------------------------------------------------------------------
    def test_31_search_and_filter_combinations_and_counts_consistency(self):
        """Verify filter combinations return consistent counts across tabs and empty states."""
        # Create dataset with unique token to isolate from other test cases
        unique_token = f"Combo_{uuid.uuid4().hex[:6]}"
        database.create_item('lost', f'Dell XPS {unique_token}', 'Electronics', 'Library 2F', '2026-10-28', 'Silver laptop.', 'Student 1', 's1@campus.edu', '1234')
        database.create_item('lost', f'HP Charger {unique_token}', 'Electronics', 'Student Center', '2026-10-28', 'Black cable.', 'Student 2', 's2@campus.edu', '1234')
        database.create_item('found', f'Sony Headphones {unique_token}', 'Electronics', 'Gym', '2026-10-28', 'Black over-ear.', 'Student 3', 's3@campus.edu', '1234')
        database.create_item('lost', f'Calculus Book {unique_token}', 'Books & Stationery', 'Hall B', '2026-10-28', 'Hardcover.', 'Student 4', 's4@campus.edu', '1234')

        # 1. Filter by unique query: 4 items total (3 lost, 1 found)
        res_q = self.client.get(f'/?q={unique_token}')
        html_q = res_q.data.decode('utf-8')
        self.assertIn('All Items (4)', html_q)
        self.assertIn('Lost Items (3)', html_q)
        self.assertIn('Found Items (1)', html_q)

        # 2. Filter by unique query AND type=lost
        res_lost = self.client.get(f'/?q={unique_token}&type=lost')
        html_lost = res_lost.data.decode('utf-8')
        # Tab counts still reflect breakdown for this query
        self.assertIn('All Items (4)', html_lost)
        self.assertIn('Lost Items (3)', html_lost)
        self.assertIn('Found Items (1)', html_lost)
        # Lost items are rendered
        self.assertIn(f'Dell XPS {unique_token}', html_lost)
        self.assertIn(f'HP Charger {unique_token}', html_lost)
        # Found item is not rendered
        self.assertNotIn(f'Sony Headphones {unique_token}', html_lost)

        # 3. Filter by unique query AND category=Electronics (3 items: 2 lost, 1 found)
        res_cat = self.client.get(f'/?q={unique_token}&category=Electronics')
        html_cat = res_cat.data.decode('utf-8')
        self.assertIn('All Items (3)', html_cat)
        self.assertIn('Lost Items (2)', html_cat)
        self.assertIn('Found Items (1)', html_cat)

        # 4. Filter with no matching results
        res_none = self.client.get('/?q=NonExistentRandomWordXYZ')
        html_none = res_none.data.decode('utf-8')
        # Must show filtered empty state
        self.assertIn('No matching items found', html_none)
        self.assertIn('Reset Filters', html_none)
        self.assertIn('href="/#itemsResults"', html_none)
        # Must NOT show global empty database message
        self.assertNotIn('No items yet', html_none)

    # ------------------------------------------------------------------
    # 32. Complete Link and Control Audit
    # ------------------------------------------------------------------
    def test_32_complete_link_and_control_audit(self):
        """Audit all visible links, buttons, and error routes."""
        item_id = database.create_item(
            'lost', 'Audit Test Item', 'Electronics', 'Room 101', '2026-10-28',
            'Audit description.', 'Auditor', 'audit@campus.edu', '1234'
        )

        # 1. Detail page breadcrumb back-link
        res_detail = self.client.get(f'/items/{item_id}')
        self.assertEqual(res_detail.status_code, 200)
        self.assertIn('href="/#itemsResults"', res_detail.data.decode('utf-8'))

        # 2. Submit page Cancel button
        res_submit = self.client.get('/items/new')
        self.assertEqual(res_submit.status_code, 200)
        self.assertIn('href="/"', res_submit.data.decode('utf-8'))

        # 3. About page links
        res_about = self.client.get('/about')
        self.assertEqual(res_about.status_code, 200)
        self.assertIn('href="/"', res_about.data.decode('utf-8'))
        self.assertIn('href="/items/new"', res_about.data.decode('utf-8'))

        # 4. Invalid item IDs return 404
        res_404_id = self.client.get('/items/9999999')
        self.assertEqual(res_404_id.status_code, 404)
        html_404 = res_404_id.data.decode('utf-8')
        self.assertIn('404 ERROR', html_404)
        self.assertIn('Page Not Found', html_404)

        res_invalid_str = self.client.get('/items/invalid-slug')
        self.assertEqual(res_invalid_str.status_code, 404)

        res_neg = self.client.get('/items/-5')
        self.assertEqual(res_neg.status_code, 404)

        # 5. Invalid action routes return 404 or redirect safely
        res_bad_status = self.client.get(f'/items/{item_id}/status')
        self.assertEqual(res_bad_status.status_code, 302)  # Redirects to item detail on GET

        res_bad_inbox = self.client.get(f'/items/{item_id}/inbox')
        self.assertEqual(res_bad_inbox.status_code, 302)

        res_bad_contact = self.client.get(f'/items/{item_id}/contact')
        self.assertEqual(res_bad_contact.status_code, 302)

    # ------------------------------------------------------------------
    # 33. Accessibility and Semantic Markup Attributes
    # ------------------------------------------------------------------
    def test_33_accessibility_and_semantic_markup_attributes(self):
        """Verify ARIA attributes, tab roles, and keyboard readiness."""
        res = self.client.get('/?q=search&type=lost')
        html = res.data.decode('utf-8')

        # Tablist and role=tab
        self.assertIn('role="tablist"', html)
        self.assertIn('role="tab"', html)
        self.assertIn('aria-selected="true"', html)
        self.assertIn('aria-controls="itemsResults"', html)

        # Clear buttons have role="button" and aria-labels
        self.assertIn('role="button"', html)
        self.assertIn('aria-label="Clear search query"', html)
        self.assertIn('aria-label="Remove Lost filter"', html)

        # Mobile toggle controls
        self.assertIn('aria-controls="navMenu"', html)
        self.assertIn('aria-expanded="false"', html)

    # ------------------------------------------------------------------
    # Helper to generate in-memory test images
    # ------------------------------------------------------------------
    def _create_test_image_bytes(self, format='JPEG', size=(200, 200), color='blue', exif=None):
        img = Image.new('RGB' if format == 'JPEG' else 'RGBA', size, color=color)
        buf = io.BytesIO()
        save_kwargs = {'format': format}
        if exif:
            save_kwargs['exif'] = exif
        img.save(buf, **save_kwargs)
        buf.seek(0)
        return buf

    # ------------------------------------------------------------------
    # 34. Camera & Upload Options, File Input & Preview UI Elements
    # ------------------------------------------------------------------
    def test_34_submit_form_has_camera_file_picker_and_preview_markup(self):
        """Verify report form contains camera capture, file picker, and preview markup."""
        res = self.client.get('/items/new')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Form must support file uploads
        self.assertIn('enctype="multipart/form-data"', html)

        # Mobile camera input with environment capture
        self.assertIn('capture="environment"', html)
        self.assertIn('id="cameraInput"', html)
        self.assertIn('name="photo_camera"', html)

        # File picker fallback input
        self.assertIn('id="fileInput"', html)
        self.assertIn('name="photo_file"', html)

        # Accept image types
        self.assertIn('accept="image/jpeg,image/png,image/webp,image/*"', html)

        # Action buttons
        self.assertIn('Take Photo', html)
        self.assertIn('Upload Photo', html)

        # Client preview, retake, and remove controls
        self.assertIn('id="photoPreviewCard"', html)
        self.assertIn('id="photoPreviewImg"', html)
        self.assertIn('id="btnRetakePhoto"', html)
        self.assertIn('id="btnRemovePhoto"', html)

    # ------------------------------------------------------------------
    # 35. Valid JPEG Upload and Persistence
    # ------------------------------------------------------------------
    def test_35_valid_jpeg_upload_and_persistence(self):
        """Verify submitting an item with a valid JPEG stores the image and serves it."""
        suffix = uuid.uuid4().hex[:6]
        img_buf = self._create_test_image_bytes(format='JPEG', size=(300, 300), color='red')

        payload = {
            'item_type': 'lost',
            'title': f'Lost Jacket {suffix}',
            'category': 'Clothing & Accessories',
            'location': 'Quad Bench',
            'event_date': datetime.date.today().strftime('%Y-%m-%d'),
            'description': 'Warm red fleece jacket left on bench.',
            'poster_name': f'Student {suffix}',
            'poster_contact': f'student.{suffix}@campus.edu',
            'pin': '5678',
            'photo_file': (img_buf, 'jacket.jpg')
        }

        res = self.client.post('/items/new', data=payload, content_type='multipart/form-data', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        item_id = int(res.headers['Location'].split('/')[-1])

        # Verify database record
        item = database.get_item_by_id(item_id)
        self.assertIsNotNone(item['image_filename'])
        self.assertTrue(item['image_filename'].endswith('.jpg'))

        # Verify image file exists on disk
        saved_file_path = os.path.join(TEST_UPLOAD_DIR, item['image_filename'])
        self.assertTrue(os.path.isfile(saved_file_path))

        # Verify image can be fetched via /uploads/<filename>
        img_res = self.client.get(f"/uploads/{item['image_filename']}")
        self.assertEqual(img_res.status_code, 200)

        # Verify detail page renders the photo
        detail_res = self.client.get(f'/items/{item_id}')
        self.assertIn(f"/uploads/{item['image_filename']}", detail_res.data.decode('utf-8'))

        # Verify index page renders the photo
        index_res = self.client.get('/')
        self.assertIn(f"/uploads/{item['image_filename']}", index_res.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 36. Valid Camera Photo and PNG / WebP Formats
    # ------------------------------------------------------------------
    def test_36_valid_camera_photo_and_png_webp_formats(self):
        """Verify uploading PNG and WebP via both camera and file inputs."""
        # 1. PNG via photo_camera input
        png_buf = self._create_test_image_bytes(format='PNG', size=(250, 250), color='green')
        payload_png = {
            'item_type': 'found',
            'title': 'Found Umbrella Camera Capture',
            'category': 'Clothing & Accessories',
            'location': 'Student Union Lobby',
            'event_date': datetime.date.today().strftime('%Y-%m-%d'),
            'description': 'Green folding umbrella turned in to security.',
            'poster_name': 'Union Desk Staff',
            'poster_contact': 'union@campus.edu',
            'pin': '1234',
            'photo_camera': (png_buf, 'captured_photo.png')
        }
        res_png = self.client.post('/items/new', data=payload_png, content_type='multipart/form-data', follow_redirects=False)
        self.assertEqual(res_png.status_code, 302)
        png_id = int(res_png.headers['Location'].split('/')[-1])
        item_png = database.get_item_by_id(png_id)
        self.assertTrue(item_png['image_filename'].endswith('.png'))

        # 2. WebP via photo_file input
        webp_buf = self._create_test_image_bytes(format='WEBP', size=(250, 250), color='purple')
        payload_webp = {
            'item_type': 'lost',
            'title': 'Lost Notebook WebP',
            'category': 'Books & Stationery',
            'location': 'Science Hall 101',
            'event_date': datetime.date.today().strftime('%Y-%m-%d'),
            'description': 'Purple spiral notebook with lab notes.',
            'poster_name': 'Lab Student',
            'poster_contact': 'student@campus.edu',
            'pin': '4321',
            'photo_file': (webp_buf, 'notes.webp')
        }
        res_webp = self.client.post('/items/new', data=payload_webp, content_type='multipart/form-data', follow_redirects=False)
        self.assertEqual(res_webp.status_code, 302)
        webp_id = int(res_webp.headers['Location'].split('/')[-1])
        item_webp = database.get_item_by_id(webp_id)
        self.assertTrue(item_webp['image_filename'].endswith('.webp'))

    # ------------------------------------------------------------------
    # 37. Image Resizing and EXIF Stripping
    # ------------------------------------------------------------------
    def test_37_image_resizing_and_exif_stripping(self):
        """Verify large images are resized and EXIF metadata is stripped."""
        # Create image with dimension > 1200 and custom EXIF
        big_img = Image.new('RGB', (2400, 1600), color='teal')
        exif_data = big_img.getexif()
        exif_data[270] = "Camera Serial 987654321 - Location GPS Test"
        buf = io.BytesIO()
        big_img.save(buf, format='JPEG', exif=exif_data)
        buf.seek(0)

        payload = {
            'item_type': 'lost',
            'title': 'High Res DSLR Photo Item',
            'category': 'Electronics',
            'location': 'Engineering Lab',
            'event_date': datetime.date.today().strftime('%Y-%m-%d'),
            'description': 'Item with large camera photo.',
            'poster_name': 'Camera Owner',
            'poster_contact': 'dslr@campus.edu',
            'pin': '9999',
            'photo_file': (buf, 'dslr_capture.jpg')
        }

        res = self.client.post('/items/new', data=payload, content_type='multipart/form-data', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        item_id = int(res.headers['Location'].split('/')[-1])
        item = database.get_item_by_id(item_id)

        # Inspect saved file on disk
        saved_path = os.path.join(TEST_UPLOAD_DIR, item['image_filename'])
        with Image.open(saved_path) as saved_img:
            # 1. Dimension must be downscaled (max dimension <= 1200)
            self.assertLessEqual(max(saved_img.width, saved_img.height), 1200)
            # 2. Aspect ratio maintained
            self.assertEqual(round(saved_img.width / saved_img.height, 2), round(2400 / 1600, 2))
            # 3. EXIF metadata must be stripped
            self.assertEqual(len(saved_img.getexif()), 0)

    # ------------------------------------------------------------------
    # 38. Corrupt Image Upload Rejected Without Orphaned Files
    # ------------------------------------------------------------------
    def test_38_corrupt_image_upload_rejected_without_orphaned_files(self):
        """Verify corrupt files disguised as images are rejected and leave no orphans."""
        before_files = set(os.listdir(TEST_UPLOAD_DIR))

        corrupt_buf = io.BytesIO(b"JFIF\x00\x00NotAnActualImageCorruptedContentData123456789")
        payload = {
            'item_type': 'lost',
            'title': 'Corrupt File Test Item',
            'category': 'Electronics',
            'location': 'Campus Lawn',
            'event_date': datetime.date.today().strftime('%Y-%m-%d'),
            'description': 'Attempting upload with corrupted image.',
            'poster_name': 'Attacker',
            'poster_contact': 'attacker@campus.edu',
            'pin': '1111',
            'photo_file': (corrupt_buf, 'broken.jpg')
        }

        res = self.client.post('/items/new', data=payload, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # User-friendly error message presented
        self.assertTrue('corrupt' in html.lower() or 'not a valid image' in html.lower() or 'valid photo' in html.lower())

        # No item created in database
        items = database.get_items(search_query='Corrupt File Test Item')
        self.assertEqual(len(items), 0)

        # No orphaned file created on disk
        after_files = set(os.listdir(TEST_UPLOAD_DIR))
        self.assertEqual(before_files, after_files)

    # ------------------------------------------------------------------
    # 39. Unsupported Image Formats Rejected
    # ------------------------------------------------------------------
    def test_39_unsupported_image_formats_rejected(self):
        """Verify non-allowed image formats (e.g. GIF, BMP, SVG, TXT) are rejected."""
        before_files = set(os.listdir(TEST_UPLOAD_DIR))

        # Create a real GIF image
        gif_img = Image.new('RGB', (100, 100), color='yellow')
        gif_buf = io.BytesIO()
        gif_img.save(gif_buf, format='GIF')
        gif_buf.seek(0)

        payload = {
            'item_type': 'found',
            'title': 'GIF Format Test Item',
            'category': 'Other / Miscellaneous',
            'location': 'Dining Commons',
            'event_date': datetime.date.today().strftime('%Y-%m-%d'),
            'description': 'Testing rejection of GIF format.',
            'poster_name': 'Tester',
            'poster_contact': 'tester@campus.edu',
            'pin': '2222',
            'photo_file': (gif_buf, 'animation.gif')
        }

        res = self.client.post('/items/new', data=payload, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertIn('Unsupported image format', html)

        # No orphaned file
        after_files = set(os.listdir(TEST_UPLOAD_DIR))
        self.assertEqual(before_files, after_files)

    # ------------------------------------------------------------------
    # 40. Oversized File Upload Rejected
    # ------------------------------------------------------------------
    def test_40_oversized_file_rejected(self):
        """Verify files larger than 5 MB are rejected server-side."""
        before_files = set(os.listdir(TEST_UPLOAD_DIR))

        # 5.3 MB of dummy bytes
        big_buf = io.BytesIO(b'X' * (5 * 1024 * 1024 + 300000))
        payload = {
            'item_type': 'lost',
            'title': 'Oversized Photo Test Item',
            'category': 'Electronics',
            'location': 'Library 3rd Floor',
            'event_date': datetime.date.today().strftime('%Y-%m-%d'),
            'description': 'Attempting upload with oversized photo.',
            'poster_name': 'Tester',
            'poster_contact': 'tester@campus.edu',
            'pin': '3333',
            'photo_file': (big_buf, 'huge.jpg')
        }

        res = self.client.post('/items/new', data=payload, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertIn('exceeds the 5 MB limit', html)

        # No orphaned files
        after_files = set(os.listdir(TEST_UPLOAD_DIR))
        self.assertEqual(before_files, after_files)

    # ------------------------------------------------------------------
    # 41. Missing Photo Submission (Optional Upload)
    # ------------------------------------------------------------------
    def test_41_missing_photo_optional_submission(self):
        """Verify report form succeeds when no photo is attached, showing clean placeholders."""
        payload = {
            'item_type': 'lost',
            'title': 'Item Without Any Photo Attached',
            'category': 'Student IDs & Keys',
            'location': 'Gym Entrance',
            'event_date': datetime.date.today().strftime('%Y-%m-%d'),
            'description': 'Lanyard with dorm keys, no photo available.',
            'poster_name': 'Key Loser',
            'poster_contact': 'keys@campus.edu',
            'pin': '7777'
        }

        res = self.client.post('/items/new', data=payload, content_type='multipart/form-data', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        item_id = int(res.headers['Location'].split('/')[-1])

        item = database.get_item_by_id(item_id)
        self.assertIsNone(item['image_filename'])

        # Detail page must render clean placeholder
        detail_res = self.client.get(f'/items/{item_id}')
        detail_html = detail_res.data.decode('utf-8')
        self.assertIn('No photo uploaded', detail_html)
        self.assertIn('detail-photo-placeholder', detail_html)

        # Index page must render clean placeholder on item card
        index_res = self.client.get('/')
        index_html = index_res.data.decode('utf-8')
        self.assertIn('card-img-placeholder', index_html)

    # ------------------------------------------------------------------
    # 42. Existing Records Without Images Render Safely
    # ------------------------------------------------------------------
    def test_42_existing_records_without_images_render_safely(self):
        """Verify legacy database records with NULL image_filename render without errors."""
        legacy_id = database.create_item(
            item_type='found',
            title='Legacy Found Textbook Record',
            category='Books & Stationery',
            location='Library Annex',
            event_date='2026-10-20',
            description='Legacy item created before photo feature existed.',
            poster_name='Librarian',
            poster_contact='librarian@campus.edu',
            pin_plain='8888',
            image_filename=None
        )

        # Detail page
        res = self.client.get(f'/items/{legacy_id}')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('Legacy Found Textbook Record', html)
        self.assertIn('No photo uploaded', html)

        # Index page
        res_index = self.client.get('/')
        self.assertEqual(res_index.status_code, 200)
        self.assertIn('Legacy Found Textbook Record', res_index.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 43. Path Traversal Prevention on Uploads
    # ------------------------------------------------------------------
    def test_43_path_traversal_prevention_on_uploads(self):
        """Verify /uploads/ route blocks directory traversal and non-existent files."""
        # 1. Path traversal attempts
        res1 = self.client.get('/uploads/../campusconnect.db')
        self.assertEqual(res1.status_code, 404)

        res2 = self.client.get('/uploads/..%2f..%2fapp.py')
        self.assertEqual(res2.status_code, 404)

        # 2. Subdirectory traversal attempt
        res3 = self.client.get('/uploads/subdir/image.jpg')
        self.assertEqual(res3.status_code, 404)

        # 3. Non-existent file
        res4 = self.client.get('/uploads/nonexistent_file_12345.jpg')
        self.assertEqual(res4.status_code, 404)

    # ------------------------------------------------------------------
    # 44. Safe Failure & Atomic Cleanup on Database Error
    # ------------------------------------------------------------------
    def test_44_atomic_cleanup_on_database_failure(self):
        """Verify uploaded image is deleted immediately if database insertion fails."""
        before_files = set(os.listdir(TEST_UPLOAD_DIR))

        img_buf = self._create_test_image_bytes(format='JPEG', size=(200, 200), color='orange')
        payload = {
            'item_type': 'lost',
            'title': 'Item destined to trigger DB failure',
            'category': 'Electronics',
            'location': 'Test Lab',
            'event_date': datetime.date.today().strftime('%Y-%m-%d'),
            'description': 'Testing atomic cleanup when database creation throws.',
            'poster_name': 'Tester',
            'poster_contact': 'tester@campus.edu',
            'pin': '9999',
            'photo_file': (img_buf, 'test_cleanup.jpg')
        }

        # Temporarily mock create_item to raise an error
        orig_create_item = database.create_item
        def mock_failing_create(*args, **kwargs):
            raise Exception("Simulated SQLite database failure during item insertion")

        database.create_item = mock_failing_create
        try:
            res = self.client.post('/items/new', data=payload, content_type='multipart/form-data', follow_redirects=True)
            self.assertEqual(res.status_code, 200)
            self.assertIn('database error occurred', res.data.decode('utf-8'))

            # Crucial assertion: No orphaned image file left on disk!
            after_files = set(os.listdir(TEST_UPLOAD_DIR))
            self.assertEqual(before_files, after_files)
        finally:
            database.create_item = orig_create_item

    # ------------------------------------------------------------------
    # 45. Database Migration Repeatability
    # ------------------------------------------------------------------
    def test_45_database_migration_repeatability(self):
        """Verify database.migrate_db() can be run repeatedly without errors or data corruption."""
        # 1. Calling migrate on an already migrated database returns False (no-op)
        result1 = database.migrate_db()
        self.assertFalse(result1)

        result2 = database.migrate_db()
        self.assertFalse(result2)

        # 2. Check table schema directly with PRAGMA
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(items)")
        columns = [row['name'] for row in cursor.fetchall()]
        conn.close()

        self.assertIn('image_filename', columns)


if __name__ == '__main__':
    unittest.main(verbosity=2)

