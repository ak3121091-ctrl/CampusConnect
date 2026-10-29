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

        # Filter by category=Electronics with status=resolved (Found Casio Watch is resolved)
        res_cat = self.client.get('/?category=Electronics&status=resolved')
        self.assertEqual(res_cat.status_code, 200)
        self.assertIn('Found Casio Watch', res_cat.data.decode('utf-8'))

        # In default active category listing, resolved watch must NOT appear
        res_cat_active = self.client.get('/?category=Electronics')
        self.assertEqual(res_cat_active.status_code, 200)
        self.assertNotIn('Found Casio Watch', res_cat_active.data.decode('utf-8'))

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

    # ------------------------------------------------------------------
    # 46. Resolved Lost Item Disappears from Active Listings and Appears in Resolved
    # ------------------------------------------------------------------
    def test_46_resolved_lost_item_disappears_from_active_listings_and_appears_in_resolved(self):
        """Verify resolving an open Lost item removes it from the homepage and places it in Resolved."""
        suffix = uuid.uuid4().hex[:6]
        item_title = f"Lost Calculus Calculator {suffix}"
        pin = "2468"

        item_id = database.create_item(
            item_type='lost',
            title=item_title,
            category='Electronics',
            location='Math Building 102',
            event_date=datetime.date.today().strftime('%Y-%m-%d'),
            description='Texas Instruments TI-84 with sticker.',
            poster_name=f'Math Student {suffix}',
            poster_contact='math@campus.edu',
            pin_plain=pin
        )

        # 1. Before resolution: must appear on homepage and Lost section
        res_home = self.client.get('/')
        self.assertEqual(res_home.status_code, 200)
        self.assertIn(item_title, res_home.data.decode('utf-8'))

        res_lost = self.client.get('/?type=lost')
        self.assertEqual(res_lost.status_code, 200)
        self.assertIn(item_title, res_lost.data.decode('utf-8'))

        # Must NOT be in resolved archive yet
        res_resolved_before = self.client.get('/?status=resolved')
        self.assertEqual(res_resolved_before.status_code, 200)
        self.assertNotIn(item_title, res_resolved_before.data.decode('utf-8'))

        # 2. Authorize resolution with valid PIN
        res_resolve = self.client.post(f'/items/{item_id}/status', data={
            'pin': pin,
            'status': 'resolved'
        }, follow_redirects=True)
        self.assertEqual(res_resolve.status_code, 200)
        self.assertIn('RESOLVED', res_resolve.data.decode('utf-8'))

        # 3. After resolution: must DISAPPEAR from active homepage and Lost section
        res_home_after = self.client.get('/')
        self.assertEqual(res_home_after.status_code, 200)
        self.assertNotIn(item_title, res_home_after.data.decode('utf-8'))

        res_lost_after = self.client.get('/?type=lost')
        self.assertEqual(res_lost_after.status_code, 200)
        self.assertNotIn(item_title, res_lost_after.data.decode('utf-8'))

        # 4. Must APPEAR in the dedicated Resolved section
        res_resolved_after = self.client.get('/?status=resolved')
        self.assertEqual(res_resolved_after.status_code, 200)
        html_resolved = res_resolved_after.data.decode('utf-8')
        self.assertIn(item_title, html_resolved)
        self.assertIn('RESOLVED', html_resolved)

        # Database record must preserve full history and details
        record = database.get_item_by_id(item_id)
        self.assertEqual(record['status'], 'resolved')
        self.assertEqual(record['title'], item_title)
        self.assertEqual(record['location'], 'Math Building 102')

    # ------------------------------------------------------------------
    # 47. Resolved Found Item Disappears from Active Listings and Appears in Resolved
    # ------------------------------------------------------------------
    def test_47_resolved_found_item_disappears_from_active_listings_and_appears_in_resolved(self):
        """Verify resolving an open Found item removes it from the homepage and places it in Resolved."""
        suffix = uuid.uuid4().hex[:6]
        item_title = f"Found Stainless Flask {suffix}"
        pin = "1357"

        item_id = database.create_item(
            item_type='found',
            title=item_title,
            category='Clothing & Accessories',
            location='Campus Gym Desk',
            event_date=datetime.date.today().strftime('%Y-%m-%d'),
            description='32oz Hydro Flask found near locker room.',
            poster_name=f'Gym Attendant {suffix}',
            poster_contact='gym@campus.edu',
            pin_plain=pin
        )

        # 1. Before resolution: must appear on active listings
        res_found = self.client.get('/?type=found')
        self.assertIn(item_title, res_found.data.decode('utf-8'))

        # 2. Authorize resolution with valid PIN
        res_resolve = self.client.post(f'/items/{item_id}/status', data={
            'pin': pin,
            'status': 'resolved'
        }, follow_redirects=True)
        self.assertEqual(res_resolve.status_code, 200)

        # 3. After resolution: must DISAPPEAR from active found listings
        res_found_after = self.client.get('/?type=found')
        self.assertNotIn(item_title, res_found_after.data.decode('utf-8'))

        # 4. Must APPEAR in the dedicated Resolved section
        res_resolved = self.client.get('/?status=resolved')
        self.assertIn(item_title, res_resolved.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 48. Dashboard Counters Accurately Reflect Item Resolutions
    # ------------------------------------------------------------------
    def test_48_dashboard_counts_reflect_resolution_accurately(self):
        """Verify dashboard Total, Open Lost, Open Found, and Resolved counts stay accurate without double-counting."""
        stats_start = database.get_statistics()
        pin = "9988"

        # Create 1 open lost and 1 open found item
        lost_id = database.create_item(
            'lost', 'Stats Lost Watch', 'Electronics', 'Pool',
            '2026-10-28', 'Lost digital watch.', 'Owner', 'o@campus.edu', pin
        )
        found_id = database.create_item(
            'found', 'Stats Found Keys', 'Student IDs & Keys', 'Quad',
            '2026-10-28', 'Found room keys.', 'Finder', 'f@campus.edu', pin
        )

        stats_mid = database.get_statistics()
        self.assertEqual(stats_mid['total'], stats_start['total'] + 2)
        self.assertEqual(stats_mid['open_lost'], stats_start['open_lost'] + 1)
        self.assertEqual(stats_mid['open_found'], stats_start['open_found'] + 1)
        self.assertEqual(stats_mid['resolved'], stats_start['resolved'])

        # Resolve the Lost item
        database.update_item_status(lost_id, 'resolved')

        stats_resolved = database.get_statistics()
        self.assertEqual(stats_resolved['total'], stats_start['total'] + 2)
        self.assertEqual(stats_resolved['open_lost'], stats_start['open_lost'])  # decremented by 1 back to start
        self.assertEqual(stats_resolved['open_found'], stats_start['open_found'] + 1)
        self.assertEqual(stats_resolved['resolved'], stats_start['resolved'] + 1)

        # Invariant check: total == open_lost + open_found + resolved
        self.assertEqual(
            stats_resolved['total'],
            stats_resolved['open_lost'] + stats_resolved['open_found'] + stats_resolved['resolved']
        )

        # Verify home page renders accurate counts
        res_home = self.client.get('/')
        html = res_home.data.decode('utf-8')
        self.assertIn(f">{stats_resolved['total']}<", html)
        self.assertIn(f">{stats_resolved['open_lost']}<", html)
        self.assertIn(f">{stats_resolved['open_found']}<", html)
        self.assertIn(f">{stats_resolved['resolved']}<", html)

    # ------------------------------------------------------------------
    # 49. Search and Category Filtering Within Resolved Records
    # ------------------------------------------------------------------
    def test_49_search_and_category_filtering_within_resolved_records(self):
        """Verify searching and category filtering within the dedicated Resolved section."""
        unique_token = f"ResToken_{uuid.uuid4().hex[:6]}"
        pin = "1234"

        # Create and resolve 2 items in different categories
        book_id = database.create_item(
            'lost', f'Organic Chemistry {unique_token}', 'Books & Stationery', 'Science Library',
            '2026-10-28', 'Textbook with notes.', 'Chem Student', 'chem@campus.edu', pin
        )
        phone_id = database.create_item(
            'found', f'Pixel Phone {unique_token}', 'Electronics', 'Bus Stop',
            '2026-10-28', 'Black smartphone.', 'Transit', 'transit@campus.edu', pin
        )

        database.update_item_status(book_id, 'resolved')
        database.update_item_status(phone_id, 'resolved')

        # 1. Search within resolved items
        res_search_book = self.client.get(f'/?q={unique_token}&status=resolved')
        self.assertEqual(res_search_book.status_code, 200)
        html_search = res_search_book.data.decode('utf-8')
        self.assertIn(f'Organic Chemistry {unique_token}', html_search)
        self.assertIn(f'Pixel Phone {unique_token}', html_search)

        # 2. Filter by category within resolved items
        res_cat_book = self.client.get(f'/?category=Books+%26+Stationery&status=resolved')
        self.assertEqual(res_cat_book.status_code, 200)
        html_cat = res_cat_book.data.decode('utf-8')
        self.assertIn(f'Organic Chemistry {unique_token}', html_cat)
        self.assertNotIn(f'Pixel Phone {unique_token}', html_cat)

        # 3. Default active listings must NOT contain either resolved item
        res_active = self.client.get(f'/?q={unique_token}')
        self.assertEqual(res_active.status_code, 200)
        html_active = res_active.data.decode('utf-8')
        self.assertNotIn(f'Organic Chemistry {unique_token}', html_active)
        self.assertNotIn(f'Pixel Phone {unique_token}', html_active)

    # ------------------------------------------------------------------
    # 50. Reopening Workflow Restores Item to Active Directory
    # ------------------------------------------------------------------
    def test_50_reopening_resolved_item_restores_it_to_active_listings(self):
        """Verify reopening an item moves it from Resolved back into the active directory."""
        suffix = uuid.uuid4().hex[:6]
        item_title = f"Dorm Keycard {suffix}"
        pin = "5544"

        item_id = database.create_item(
            'lost', item_title, 'Student IDs & Keys', 'Dining Hall',
            '2026-10-28', 'Red lanyard keycard.', 'Student', 'dorm@campus.edu', pin
        )

        # Resolve item
        database.update_item_status(item_id, 'resolved')
        self.assertNotIn(item_title, self.client.get('/').data.decode('utf-8'))
        self.assertIn(item_title, self.client.get('/?status=resolved').data.decode('utf-8'))

        # Reopen item with authorized PIN
        res_reopen = self.client.post(f'/items/{item_id}/status', data={
            'pin': pin,
            'status': 'open'
        }, follow_redirects=True)
        self.assertEqual(res_reopen.status_code, 200)
        self.assertIn('OPEN', res_reopen.data.decode('utf-8'))

        # Verify it has returned to active listings
        self.assertIn(item_title, self.client.get('/').data.decode('utf-8'))
        self.assertIn(item_title, self.client.get('/?type=lost').data.decode('utf-8'))

        # Verify it has left the resolved section
        self.assertNotIn(item_title, self.client.get('/?status=resolved').data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 51. Repeated Status Updates Handled Safely
    # ------------------------------------------------------------------
    def test_51_repeated_status_updates_handled_safely(self):
        """Verify submitting the same status update twice handles safely without error or data corruption."""
        pin = "6677"
        item_id = database.create_item(
            'found', 'Repeated Resolution Item', 'Other / Miscellaneous', 'Lawn',
            '2026-10-28', 'Item for repeat testing.', 'Finder', 'finder@campus.edu', pin
        )

        # First resolution
        res1 = self.client.post(f'/items/{item_id}/status', data={'pin': pin, 'status': 'resolved'}, follow_redirects=True)
        self.assertEqual(res1.status_code, 200)

        # Second resolution (already resolved)
        res2 = self.client.post(f'/items/{item_id}/status', data={'pin': pin, 'status': 'resolved'}, follow_redirects=True)
        self.assertEqual(res2.status_code, 200)
        self.assertIn('already marked as RESOLVED', res2.data.decode('utf-8'))

        # Record remains safely resolved
        self.assertEqual(database.get_item_by_id(item_id)['status'], 'resolved')

    # ------------------------------------------------------------------
    # 52. Unauthorized Resolution Attempts Fail Safely
    # ------------------------------------------------------------------
    def test_52_unauthorized_resolution_attempts_fail_safely(self):
        """Verify unauthorized status changes with wrong PIN fail and item remains active."""
        item_id = database.create_item(
            'lost', 'Protected Item Against Hack', 'Electronics', 'Classroom 4',
            '2026-10-28', 'Secure item.', 'Owner', 'owner@campus.edu', '7890'
        )

        # Attempt with wrong PIN
        res = self.client.post(f'/items/{item_id}/status', data={
            'pin': '0000',
            'status': 'resolved'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Incorrect Security PIN', res.data.decode('utf-8'))

        # Item must remain open
        record = database.get_item_by_id(item_id)
        self.assertEqual(record['status'], 'open')

        # Must still be visible on active homepage
        res_home = self.client.get('/')
        self.assertIn('Protected Item Against Hack', res_home.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 53. Retake / Change Options Markup and Reopen Camera Choice
    # ------------------------------------------------------------------
    def test_53_retake_options_markup_and_reopen_camera_choice(self):
        """Verify Retake / Change markup provides choices for both reopening camera and browsing files."""
        res = self.client.get('/items/new')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Check Retake button and options menu
        self.assertIn('id="retakeDropdownWrap"', html)
        self.assertIn('id="btnRetakePhoto"', html)
        self.assertIn('id="retakeOptionsMenu"', html)
        self.assertIn('id="btnRetakeCamera"', html)
        self.assertIn('Reopen Camera', html)
        self.assertIn('id="btnRetakeGallery"', html)
        self.assertIn('Browse Files', html)
        self.assertIn('id="btnRemovePhoto"', html)

    # ------------------------------------------------------------------
    # 54. Photo Upload with Both File Inputs Sent (Browser Emulation)
    # ------------------------------------------------------------------
    def test_54_photo_upload_with_both_file_inputs_sent(self):
        """Verify uploading when form submits both empty camera input and populated file input."""
        suffix = uuid.uuid4().hex[:6]
        img_buf = self._create_test_image_bytes(format='PNG', size=(150, 150), color='blue')

        payload = {
            'item_type': 'found',
            'title': f'Found Calculator {suffix}',
            'category': 'Electronics',
            'location': 'Math Hall 101',
            'event_date': datetime.date.today().strftime('%Y-%m-%d'),
            'description': 'TI-84 graphic calculator found on desk.',
            'poster_name': f'Student {suffix}',
            'poster_contact': f'student.{suffix}@campus.edu',
            'pin': '7788',
            'photo_camera': (io.BytesIO(b''), ''),  # empty camera input sent by browser
            'photo_file': (img_buf, 'calc.png')     # populated file input
        }

        res = self.client.post('/items/new', data=payload, content_type='multipart/form-data', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        item_id = int(res.headers['Location'].split('/')[-1])

        item = database.get_item_by_id(item_id)
        self.assertIsNotNone(item['image_filename'])
        self.assertTrue(item['image_filename'].endswith('.png'))

        # Verify image file exists in upload directory
        upload_path = os.path.join(TEST_UPLOAD_DIR, item['image_filename'])
        self.assertTrue(os.path.isfile(upload_path))

    # ------------------------------------------------------------------
    # 55. Empty (0-byte) Photo File Handled Safely
    # ------------------------------------------------------------------
    def test_55_empty_zero_byte_photo_handled_safely(self):
        """Verify submitting a 0-byte file with an image filename does not create an orphaned file."""
        suffix = uuid.uuid4().hex[:6]
        empty_buf = io.BytesIO(b'')

        payload = {
            'item_type': 'lost',
            'title': f'Empty Photo Item {suffix}',
            'category': 'Books & Stationery',
            'location': 'Library 1F',
            'event_date': datetime.date.today().strftime('%Y-%m-%d'),
            'description': 'Item submitted with an empty photo file.',
            'poster_name': f'Student {suffix}',
            'poster_contact': f'student.{suffix}@campus.edu',
            'pin': '4321',
            'photo_file': (empty_buf, 'empty_photo.jpg')
        }

        res = self.client.post('/items/new', data=payload, content_type='multipart/form-data', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        item_id = int(res.headers['Location'].split('/')[-1])

        item = database.get_item_by_id(item_id)
        # Empty file should safely result in no image stored
        self.assertIsNone(item['image_filename'])

    # ------------------------------------------------------------------
    # 56. Image Persistence Across Simulated Server Restart
    # ------------------------------------------------------------------
    def test_56_image_persistence_across_simulated_restart(self):
        """Verify that uploaded images remain persistently accessible across simulated client/server recreation."""
        suffix = uuid.uuid4().hex[:6]
        img_buf = self._create_test_image_bytes(format='JPEG', size=(250, 250), color='green')

        payload = {
            'item_type': 'found',
            'title': f'Green Umbrella {suffix}',
            'category': 'Clothing & Accessories',
            'location': 'Student Union Lobby',
            'event_date': datetime.date.today().strftime('%Y-%m-%d'),
            'description': 'Green compact umbrella found near coat rack.',
            'poster_name': f'Student {suffix}',
            'poster_contact': f'student.{suffix}@campus.edu',
            'pin': '6543',
            'photo_file': (img_buf, 'umbrella.jpg')
        }

        res = self.client.post('/items/new', data=payload, content_type='multipart/form-data', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        item_id = int(res.headers['Location'].split('/')[-1])

        # Simulate fresh client after server restart
        new_client = self.app.test_client()

        # 1. Detail page loads and contains image tag
        res_detail = new_client.get(f'/items/{item_id}')
        self.assertEqual(res_detail.status_code, 200)
        html_detail = res_detail.data.decode('utf-8')
        item = database.get_item_by_id(item_id)
        self.assertIn(f'/uploads/{item["image_filename"]}', html_detail)
        self.assertNotIn('No photo uploaded', html_detail)

        # 2. Image endpoint serves actual bytes successfully with 200 OK
        res_img = new_client.get(f'/uploads/{item["image_filename"]}')
        self.assertEqual(res_img.status_code, 200)
        self.assertGreater(len(res_img.data), 0)

        # 3. Homepage listing card displays the image
        res_home = new_client.get('/')
        self.assertEqual(res_home.status_code, 200)
        html_home = res_home.data.decode('utf-8')
        self.assertIn(f'/uploads/{item["image_filename"]}', html_home)

    # ------------------------------------------------------------------
    # 57. Signup Page Rendering & Glassmorphism Markup
    # ------------------------------------------------------------------
    def test_57_signup_page_rendering(self):
        """Verify /signup renders glassmorphism card, steps, and Google option."""
        res = self.client.get('/signup')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertIn('Create Account', html)
        self.assertIn('CampusConnect', html)
        self.assertIn('id="signupForm"', html)
        self.assertIn('id="signupName"', html)
        self.assertIn('id="signupEmail"', html)
        self.assertIn('id="signupPassword"', html)
        self.assertIn('id="signupConfirmPassword"', html)
        self.assertIn('btn-glass-oauth', html)
        self.assertIn('id="stepIndicator1"', html)
        self.assertIn('id="stepIndicator2"', html)
        self.assertIn('Sign in', html)

    # ------------------------------------------------------------------
    # 58. Signup Success & Session Establishment
    # ------------------------------------------------------------------
    def test_58_signup_success_and_session(self):
        """Verify successful signup hashes password, creates user in DB, and establishes session."""
        suffix = uuid.uuid4().hex[:6]
        email = f"student_{suffix}@campus.edu"
        password = "SecurePassword123!"

        payload = {
            'name': f"Alex {suffix}",
            'email': email,
            'password': password,
            'confirm_password': password
        }

        res = self.client.post('/signup', data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn(f"Welcome to CampusConnect, Alex {suffix}!", html)

        # Verify database record and password hashing
        user = database.get_user_by_email(email)
        self.assertIsNotNone(user)
        self.assertEqual(user['name'], f"Alex {suffix}")
        self.assertNotEqual(user['password_hash'], password)
        self.assertTrue(database.verify_user_password(user, password))

    # ------------------------------------------------------------------
    # 59. Signup Duplicate Email Rejected Safely
    # ------------------------------------------------------------------
    def test_59_signup_duplicate_email_rejected(self):
        """Verify registering with an existing email is rejected without throwing unhandled exceptions."""
        suffix = uuid.uuid4().hex[:6]
        email = f"dup_{suffix}@campus.edu"
        database.create_user(email=email, name="First User", password_plain="Password123!")

        payload = {
            'name': "Second User",
            'email': email,
            'password': "DifferentPassword456!",
            'confirm_password': "DifferentPassword456!"
        }

        res = self.client.post('/signup', data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn("already exists", html)

    # ------------------------------------------------------------------
    # 60. Signup Server-Side Validation Rules
    # ------------------------------------------------------------------
    def test_60_signup_validation_rules(self):
        """Verify server rejects invalid names, malformed emails, short passwords, and mismatched confirms."""
        # 1. Short name
        res1 = self.client.post('/signup', data={
            'name': 'A',
            'email': 'valid@campus.edu',
            'password': 'Password123!',
            'confirm_password': 'Password123!'
        }, follow_redirects=True)
        self.assertIn("Name must be between 2 and 60 characters", res1.data.decode('utf-8'))

        # 2. Malformed email
        res2 = self.client.post('/signup', data={
            'name': 'Valid Name',
            'email': 'not-an-email',
            'password': 'Password123!',
            'confirm_password': 'Password123!'
        }, follow_redirects=True)
        self.assertIn("valid email address", res2.data.decode('utf-8'))

        # 3. Short password (< 8 chars)
        res3 = self.client.post('/signup', data={
            'name': 'Valid Name',
            'email': 'valid@campus.edu',
            'password': 'short',
            'confirm_password': 'short'
        }, follow_redirects=True)
        self.assertIn("Password must be between 8 and 128 characters", res3.data.decode('utf-8'))

        # 4. Mismatched passwords
        res4 = self.client.post('/signup', data={
            'name': 'Valid Name',
            'email': 'valid@campus.edu',
            'password': 'Password123!',
            'confirm_password': 'MismatchPassword!'
        }, follow_redirects=True)
        self.assertIn("Passwords do not match", res4.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 61. Login Page Rendering & Controls
    # ------------------------------------------------------------------
    def test_61_login_page_rendering(self):
        """Verify /login renders glassmorphism layout, email and password inputs, and Google button."""
        res = self.client.get('/login')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertIn('Welcome Back', html)
        self.assertIn('CampusConnect', html)
        self.assertIn('id="loginEmail"', html)
        self.assertIn('id="loginPassword"', html)
        self.assertIn('id="togglePasswordBtn"', html)
        self.assertIn('btn-glass-oauth', html)
        self.assertIn('Create an account', html)

    # ------------------------------------------------------------------
    # 62. Login Success & Session Establishment
    # ------------------------------------------------------------------
    def test_62_login_success_and_session(self):
        """Verify user can authenticate with valid credentials and establish session."""
        suffix = uuid.uuid4().hex[:6]
        email = f"user_{suffix}@campus.edu"
        password = "ValidUserPassword123!"
        database.create_user(email=email, name=f"Morgan {suffix}", password_plain=password)

        res = self.client.post('/login', data={
            'email': email,
            'password': password
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn(f"Welcome back, Morgan {suffix}!", html)

        # Verify session state
        with self.client.session_transaction() as sess:
            self.assertIsNotNone(sess.get('user_id'))
            self.assertEqual(sess.get('user_email'), email)

    # ------------------------------------------------------------------
    # 63. Login Invalid Credentials Rejection
    # ------------------------------------------------------------------
    def test_63_login_invalid_credentials(self):
        """Verify invalid credentials return safe error message without exposing account existence."""
        # Non-existent email
        res1 = self.client.post('/login', data={
            'email': 'nonexistent@campus.edu',
            'password': 'AnyPassword123!'
        }, follow_redirects=True)
        self.assertIn("Invalid email or password", res1.data.decode('utf-8'))

        # Existing email with wrong password
        suffix = uuid.uuid4().hex[:6]
        email = f"real_{suffix}@campus.edu"
        database.create_user(email=email, name="Real User", password_plain="RightPassword123!")

        res2 = self.client.post('/login', data={
            'email': email,
            'password': 'WrongPassword999!'
        }, follow_redirects=True)
        self.assertIn("Invalid email or password", res2.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 64. Logout Clears Session Safely
    # ------------------------------------------------------------------
    def test_64_logout_clears_session(self):
        """Verify /logout clears user credentials from session and redirects with notification."""
        suffix = uuid.uuid4().hex[:6]
        email = f"logout_{suffix}@campus.edu"
        database.create_user(email=email, name="Logout Test", password_plain="Password123!")

        # Log in
        self.client.post('/login', data={'email': email, 'password': 'Password123!'})
        with self.client.session_transaction() as sess:
            self.assertIsNotNone(sess.get('user_id'))

        # Log out
        res = self.client.get('/logout', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn("signed out safely", res.data.decode('utf-8'))

        # Verify session is empty
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))

    # ------------------------------------------------------------------
    # 65. Open Redirect Prevention on Login and Signup
    # ------------------------------------------------------------------
    def test_65_safe_redirect_prevents_open_redirect(self):
        """Verify malicious external next URLs are stripped and redirected safely to index."""
        suffix = uuid.uuid4().hex[:6]
        email = f"redirect_{suffix}@campus.edu"
        database.create_user(email=email, name="Redirect Tester", password_plain="Password123!")

        # Attempt login with external next URL
        res = self.client.post('/login?next=https://malicious-site.com', data={
            'email': email,
            'password': 'Password123!'
        }, follow_redirects=False)

        self.assertEqual(res.status_code, 302)
        # Location header must not point to malicious-site.com
        self.assertFalse(res.headers['Location'].startswith('https://malicious-site.com'))
        self.assertEqual(res.headers['Location'], '/')

    # ------------------------------------------------------------------
    # 66. Google OAuth Unconfigured Handling
    # ------------------------------------------------------------------
    def test_66_google_oauth_unconfigured_graceful_handling(self):
        """Verify accessing /login/google without credentials displays guidance message and does not crash."""
        from unittest.mock import patch
        with patch('app.is_google_oauth_configured', return_value=False):
            res = self.client.get('/login/google', follow_redirects=True)
            self.assertEqual(res.status_code, 200)
            html = res.data.decode('utf-8')
            self.assertIn("Google Sign-In is not currently configured", html)

    # ------------------------------------------------------------------
    # 67. Google OAuth State Verification Guard
    # ------------------------------------------------------------------
    def test_67_google_oauth_callback_state_verification(self):
        """Verify /login/google/callback rejects requests with missing or mismatched OAuth state."""
        res = self.client.get('/login/google/callback?code=mock_code&state=invalid_state', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn("state verification failed", res.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 68. Authenticated User Prefills Submit Form
    # ------------------------------------------------------------------
    def test_68_authenticated_user_prefills_submit_form(self):
        """Verify logged-in user visiting /items/new has their name and email pre-filled."""
        suffix = uuid.uuid4().hex[:6]
        email = f"poster_{suffix}@campus.edu"
        name = f"Poster {suffix}"
        database.create_user(email=email, name=name, password_plain="Password123!")

        self.client.post('/login', data={'email': email, 'password': 'Password123!'})

        res = self.client.get('/items/new')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn(f'value="{name}"', html)
        self.assertIn(f'value="{email}"', html)

    # ------------------------------------------------------------------
    # 69. Email Validation Rejects Whitespace-Padded and Malformed Emails
    # ------------------------------------------------------------------
    def test_69_email_validation_rejects_whitespace_and_malformed(self):
        """Verify signup rejects emails with leading/trailing spaces, missing domains, or invalid characters."""
        # Whitespace-padded email
        res1 = self.client.post('/signup', data={
            'name': 'Padded User',
            'email': '  padded@campus.edu  ',
            'password': 'Password123!',
            'confirm_password': 'Password123!'
        }, follow_redirects=True)
        self.assertIn("properly formatted email address", res1.data.decode('utf-8'))

        # Trailing space email
        res2 = self.client.post('/signup', data={
            'name': 'Trailing Space',
            'email': 'trailing@campus.edu ',
            'password': 'Password123!',
            'confirm_password': 'Password123!'
        }, follow_redirects=True)
        self.assertIn("properly formatted email address", res2.data.decode('utf-8'))

        # Malformed email without TLD
        res3 = self.client.post('/signup', data={
            'name': 'No TLD',
            'email': 'notld@campus',
            'password': 'Password123!',
            'confirm_password': 'Password123!'
        }, follow_redirects=True)
        self.assertIn("properly formatted email address", res3.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 70. Email Verification Token Lifecycle & Single-Use Enforcement
    # ------------------------------------------------------------------
    def test_70_email_verification_token_lifecycle(self):
        """Verify newly created account starts unverified, can be verified via token, and token cannot be reused."""
        suffix = uuid.uuid4().hex[:6]
        email = f"verify_{suffix}@campus.edu"
        password = "Password123!"

        res = self.client.post('/signup', data={
            'name': f"Verify {suffix}",
            'email': email,
            'password': password,
            'confirm_password': password
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        user = database.get_user_by_email(email)
        self.assertIsNotNone(user)
        self.assertEqual(user['is_verified'], 0)
        self.assertIsNotNone(user['verification_token'])

        token = user['verification_token']

        # Access verification link
        verify_res = self.client.get(f'/verify-email/{token}', follow_redirects=True)
        self.assertEqual(verify_res.status_code, 200)
        html = verify_res.data.decode('utf-8')
        self.assertIn("Email verified successfully", html)

        # Check DB state
        updated_user = database.get_user_by_email(email)
        self.assertEqual(updated_user['is_verified'], 1)
        self.assertIsNone(updated_user['verification_token'])

        # Attempt to reuse the token
        reuse_res = self.client.get(f'/verify-email/{token}', follow_redirects=True)
        self.assertIn("Invalid or already used verification token", reuse_res.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 71. Expired Email Verification Token Rejection
    # ------------------------------------------------------------------
    def test_71_expired_email_verification_token(self):
        """Verify that an expired verification token cannot verify an account."""
        suffix = uuid.uuid4().hex[:6]
        email = f"expired_{suffix}@campus.edu"
        past_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')

        user_id = database.create_user(
            email=email,
            name="Expired Tester",
            password_plain="Password123!",
            is_verified=0,
            verification_token=f"expired_token_{suffix}",
            token_expiry=past_time
        )

        res = self.client.get(f'/verify-email/expired_token_{suffix}', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn("expired", res.data.decode('utf-8'))

        user = database.get_user_by_id(user_id)
        self.assertEqual(user['is_verified'], 0)

    # ------------------------------------------------------------------
    # 72. Resend Verification Token for Unverified User
    # ------------------------------------------------------------------
    def test_72_resend_verification_token(self):
        """Verify unverified logged-in user can request a new verification token."""
        suffix = uuid.uuid4().hex[:6]
        email = f"resend_{suffix}@campus.edu"
        user_id = database.create_user(
            email=email,
            name="Resend User",
            password_plain="Password123!",
            is_verified=0,
            verification_token="initial_token_123",
            token_expiry="2026-01-01 00:00:00"
        )

        # Log in
        self.client.post('/login', data={'email': email, 'password': 'Password123!'})

        res = self.client.post('/resend-verification', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn("fresh verification link", res.data.decode('utf-8'))

        updated_user = database.get_user_by_id(user_id)
        self.assertNotEqual(updated_user['verification_token'], "initial_token_123")

    # ------------------------------------------------------------------
    # 73. Footer Hidden on Login & Signup Pages, Present Elsewhere
    # ------------------------------------------------------------------
    def test_73_footer_hidden_on_login_and_signup(self):
        """Verify the global footer is suppressed on /login and /signup, but rendered on other pages."""
        # Login page: No footer
        res_login = self.client.get('/login')
        self.assertNotIn('<footer class="footer">', res_login.data.decode('utf-8'))

        # Signup page: No footer
        res_signup = self.client.get('/signup')
        self.assertNotIn('<footer class="footer">', res_signup.data.decode('utf-8'))

        # Index page: Footer present
        res_index = self.client.get('/')
        self.assertIn('<footer class="footer">', res_index.data.decode('utf-8'))

        # About page: Footer present
        res_about = self.client.get('/about')
        self.assertIn('<footer class="footer">', res_about.data.decode('utf-8'))

    # ------------------------------------------------------------------
    # 74. Navbar Circular Profile Avatar When Authenticated
    # ------------------------------------------------------------------
    def test_74_navbar_circular_profile_avatar(self):
        """Verify navbar displays circular initials avatar and profile link for logged-in user, and Sign In/Sign Up when logged out."""
        # Logged out
        res_out = self.client.get('/')
        html_out = res_out.data.decode('utf-8')
        self.assertIn('Sign In', html_out)
        self.assertIn('Sign Up', html_out)
        self.assertNotIn('nav-profile-avatar-btn', html_out)

        # Log in
        suffix = uuid.uuid4().hex[:6]
        email = f"avatar_{suffix}@campus.edu"
        database.create_user(email=email, name=f"Taylor Swift", password_plain="Password123!")
        self.client.post('/login', data={'email': email, 'password': 'Password123!'})

        res_in = self.client.get('/')
        html_in = res_in.data.decode('utf-8')
        self.assertIn('nav-profile-avatar-btn', html_in)
        self.assertIn('nav-profile-initials', html_in)
        self.assertIn('TS', html_in)
        self.assertIn('/profile', html_in)

    # ------------------------------------------------------------------
    # 75. Profile Protection, Data Isolation & Reports View
    # ------------------------------------------------------------------
    def test_75_profile_protection_and_user_reports_isolation(self):
        """Verify unauthenticated user cannot access /profile and authenticated user only sees their own reports."""
        # Unauthenticated redirect
        res_unauth = self.client.get('/profile', follow_redirects=False)
        self.assertEqual(res_unauth.status_code, 302)
        self.assertIn('/login', res_unauth.headers['Location'])

        # User A setup
        suffix_a = uuid.uuid4().hex[:6]
        email_a = f"usera_{suffix_a}@campus.edu"
        user_a_id = database.create_user(email=email_a, name="User Alpha", password_plain="Password123!")

        # User B setup
        suffix_b = uuid.uuid4().hex[:6]
        email_b = f"userb_{suffix_b}@campus.edu"
        user_b_id = database.create_user(email=email_b, name="User Beta", password_plain="Password123!")

        # Create item for User A
        database.create_item(
            item_type='lost',
            title=f"Alpha Laptop {suffix_a}",
            category='Electronics',
            location='Library 2F',
            event_date='2026-10-25',
            description='Silver MacBook',
            poster_name='User Alpha',
            poster_contact=email_a,
            pin_plain='1234',
            user_id=user_a_id
        )

        # Create item for User B
        database.create_item(
            item_type='found',
            title=f"Beta Umbrella {suffix_b}",
            category='Other / Miscellaneous',
            location='Student Center',
            event_date='2026-10-26',
            description='Blue Umbrella',
            poster_name='User Beta',
            poster_contact=email_b,
            pin_plain='5678',
            user_id=user_b_id
        )

        # Log in as User A
        self.client.post('/login', data={'email': email_a, 'password': 'Password123!'})
        res_prof_a = self.client.get('/profile')
        self.assertEqual(res_prof_a.status_code, 200)
        html_a = res_prof_a.data.decode('utf-8')

        # User A sees their own item, but NOT User B's item
        self.assertIn(f"Alpha Laptop {suffix_a}", html_a)
        self.assertNotIn(f"Beta Umbrella {suffix_b}", html_a)
        self.assertIn(email_a, html_a)
        self.assertIn("User Alpha", html_a)

    # ------------------------------------------------------------------
    # 76. Update User Profile Name
    # ------------------------------------------------------------------
    def test_76_profile_update_display_name(self):
        """Verify user can update their display name from /profile."""
        suffix = uuid.uuid4().hex[:6]
        email = f"editname_{suffix}@campus.edu"
        user_id = database.create_user(email=email, name="Old Name", password_plain="Password123!")

        self.client.post('/login', data={'email': email, 'password': 'Password123!'})

        # Submit name update
        res = self.client.post('/profile', data={
            'action': 'update_profile',
            'name': 'Updated New Name'
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn("Updated New Name", html)

        # Check DB
        user = database.get_user_by_id(user_id)
        self.assertEqual(user['name'], "Updated New Name")

    # ------------------------------------------------------------------
    # 77. Google OAuth Does NOT Auto-Link Password Account
    # ------------------------------------------------------------------
    def test_77_google_oauth_no_auto_link_with_password_account(self):
        """Verify Google OAuth rejects auto-linking when an account already exists with password auth."""
        from unittest.mock import patch, MagicMock

        suffix = uuid.uuid4().hex[:6]
        email = f"pwd_user_{suffix}@campus.edu"
        database.create_user(email=email, name="Password User", password_plain="Password123!")

        with self.client.session_transaction() as sess:
            sess['oauth_state'] = 'test_mock_state'

        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_token_resp = MagicMock()
            mock_token_resp.read.return_value = b'{"access_token": "mock_google_token"}'
            mock_token_resp.__enter__.return_value = mock_token_resp

            mock_userinfo_resp = MagicMock()
            mock_userinfo_resp.read.return_value = (
                f'{{"sub": "google_sub_{suffix}", "email": "{email}", "name": "Google User", "email_verified": true}}'.encode('utf-8')
            )
            mock_userinfo_resp.__enter__.return_value = mock_userinfo_resp

            mock_urlopen.side_effect = [mock_token_resp, mock_userinfo_resp]

            with patch('app.is_google_oauth_configured', return_value=True):
                res = self.client.get('/login/google/callback?code=mock_code&state=test_mock_state', follow_redirects=True)
                self.assertEqual(res.status_code, 200)
                html = res.data.decode('utf-8')
                self.assertIn("already exists using password authentication", html)
                with self.client.session_transaction() as sess:
                    self.assertIsNone(sess.get('user_id'))

    # ------------------------------------------------------------------
    # 78. Google OAuth Creates New Verified User
    # ------------------------------------------------------------------
    def test_78_google_oauth_creates_new_verified_user(self):
        """Verify Google OAuth creates a new account with is_verified=1 when email_verified is true."""
        from unittest.mock import patch, MagicMock

        suffix = uuid.uuid4().hex[:6]
        email = f"new_google_{suffix}@campus.edu"

        with self.client.session_transaction() as sess:
            sess['oauth_state'] = 'test_state_78'

        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_token_resp = MagicMock()
            mock_token_resp.read.return_value = b'{"access_token": "mock_google_token"}'
            mock_token_resp.__enter__.return_value = mock_token_resp

            mock_userinfo_resp = MagicMock()
            mock_userinfo_resp.read.return_value = (
                f'{{"sub": "google_sub_{suffix}", "email": "{email}", "name": "New Google User", "email_verified": true}}'.encode('utf-8')
            )
            mock_userinfo_resp.__enter__.return_value = mock_userinfo_resp

            mock_urlopen.side_effect = [mock_token_resp, mock_userinfo_resp]

            with patch('app.is_google_oauth_configured', return_value=True):
                res = self.client.get('/login/google/callback?code=mock_code&state=test_state_78', follow_redirects=True)
                self.assertEqual(res.status_code, 200)

                user = database.get_user_by_email(email)
                self.assertIsNotNone(user)
                self.assertEqual(user['is_verified'], 1)
                self.assertEqual(user['google_id'], f"google_sub_{suffix}")
                self.assertIsNone(user['password_hash'])

    # ------------------------------------------------------------------
    # 79. Google OAuth HTTPError 401 Handling in Development Mode
    # ------------------------------------------------------------------
    def test_79_google_oauth_token_exchange_http_error_dev_mode(self):
        """Verify HTTPError during token exchange displays parsed OAuth error description in development."""
        import urllib.error
        from unittest.mock import patch

        with self.client.session_transaction() as sess:
            sess['oauth_state'] = 'test_state_79'
            sess['oauth_redirect_uri'] = 'http://127.0.0.1:5000/login/google/callback'

        error_json = b'{"error": "invalid_client", "error_description": "The provided client secret is invalid."}'
        fp = io.BytesIO(error_json)
        http_err = urllib.error.HTTPError(
            url="https://oauth2.googleapis.com/token",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=fp
        )

        with patch('urllib.request.urlopen', side_effect=http_err):
            with patch('app.is_google_oauth_configured', return_value=True):
                with patch('app.is_production', False):
                    res = self.client.get('/login/google/callback?code=mock_code&state=test_state_79', follow_redirects=True)
                    self.assertEqual(res.status_code, 200)
                    html = res.data.decode('utf-8')
                    self.assertIn("HTTP 401", html)
                    self.assertIn("invalid_client", html)
                    self.assertIn("The provided client secret is invalid", html)
                    # Verify no raw authorization codes or mock credentials leaked
                    self.assertNotIn("mock_code", html)

    # ------------------------------------------------------------------
    # 80. Google OAuth HTTPError Handling in Production Mode
    # ------------------------------------------------------------------
    def test_80_google_oauth_token_exchange_http_error_prod_mode(self):
        """Verify HTTPError in production mode displays a generic message without exposing internal details."""
        import urllib.error
        from unittest.mock import patch

        with self.client.session_transaction() as sess:
            sess['oauth_state'] = 'test_state_80'

        error_json = b'{"error": "invalid_client", "error_description": "The provided client secret is invalid."}'
        fp = io.BytesIO(error_json)
        http_err = urllib.error.HTTPError(
            url="https://oauth2.googleapis.com/token",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=fp
        )

        with patch('urllib.request.urlopen', side_effect=http_err):
            with patch('app.is_google_oauth_configured', return_value=True):
                with patch('app.is_production', True):
                    res = self.client.get('/login/google/callback?code=mock_code&state=test_state_80', follow_redirects=True)
                    self.assertEqual(res.status_code, 200)
                    html = res.data.decode('utf-8')
                    self.assertIn("Google sign-in could not be completed", html)
                    self.assertNotIn("invalid_client", html)
                    self.assertNotIn("client secret", html)

    # ------------------------------------------------------------------
    # 81. Google OAuth Redirect URI Exact Matching & Session Persistence
    # ------------------------------------------------------------------
    def test_81_google_oauth_redirect_uri_exact_matching(self):
        """Verify redirect_uri generated in /login/google is recorded and reused in callback."""
        from unittest.mock import patch

        with patch('app.is_google_oauth_configured', return_value=True):
            res = self.client.get('/login/google?next=/items/new', follow_redirects=False)
            self.assertEqual(res.status_code, 302)
            with self.client.session_transaction() as sess:
                stored_redirect = sess.get('oauth_redirect_uri')
                self.assertIsNotNone(stored_redirect)
                self.assertTrue(stored_redirect.endswith('/login/google/callback'))
                self.assertEqual(sess.get('oauth_next'), '/items/new')

    # ------------------------------------------------------------------
    # 82. Credential Quote and Whitespace Stripping Helper
    # ------------------------------------------------------------------
    def test_82_clean_oauth_credential_helper(self):
        """Verify clean_oauth_credential defensively strips quotes, spaces, and newlines."""
        import app as campus_app
        self.assertEqual(campus_app.clean_oauth_credential('  GOCSPX-abc123  \r\n'), 'GOCSPX-abc123')
        self.assertEqual(campus_app.clean_oauth_credential('"GOCSPX-quoted"'), 'GOCSPX-quoted')
        self.assertEqual(campus_app.clean_oauth_credential("'GOCSPX-single'"), 'GOCSPX-single')
        self.assertEqual(campus_app.clean_oauth_credential(None), '')

    # ------------------------------------------------------------------
    # 83. Notifications Database Table & Repeatable Migration
    # ------------------------------------------------------------------
    def test_83_notifications_db_table_and_repeatable_migration(self):
        """Verify notifications table schema, index definitions, and repeatable migration."""
        conn = database.get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(notifications)")
            columns = {row['name']: row['type'].upper() for row in cursor.fetchall()}
            self.assertIn('id', columns)
            self.assertIn('user_id', columns)
            self.assertIn('notification_type', columns)
            self.assertIn('title', columns)
            self.assertIn('message', columns)
            self.assertIn('target_url', columns)
            self.assertIn('is_read', columns)
            self.assertIn('created_at', columns)

            # Repeatable migration check
            applied = database.migrate_db()
            self.assertFalse(applied)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 84. Notifications Database Helpers CRUD
    # ------------------------------------------------------------------
    def test_84_notifications_database_helpers_crud(self):
        """Verify creation, fetching, reading, counting, and deleting notifications via helpers."""
        user_id = database.create_user(
            email="notif_helper@campus.edu",
            name="Notif User",
            password_plain="Password123!",
            is_verified=1
        )

        # Create notifications
        n1 = database.create_notification(
            user_id=user_id,
            notification_type="welcome",
            title="Welcome!",
            message="Welcome to CampusConnect.",
            target_url="/profile"
        )
        n2 = database.create_notification(
            user_id=user_id,
            notification_type="inquiry_received",
            title="New Inquiry",
            message="Someone messaged about your item.",
            target_url="/items/1#contactSection"
        )
        self.assertIsNotNone(n1)
        self.assertIsNotNone(n2)

        # Count unread
        self.assertEqual(database.get_unread_notification_count(user_id), 2)

        # Fetch notifications
        all_notifs = database.get_notifications_for_user(user_id)
        self.assertEqual(len(all_notifs), 2)
        self.assertEqual(all_notifs[0]['id'], n2)  # newest first

        # Mark single as read
        ok = database.mark_notification_as_read(n2, user_id)
        self.assertTrue(ok)
        self.assertEqual(database.get_unread_notification_count(user_id), 1)

        unread_only = database.get_notifications_for_user(user_id, unread_only=True)
        self.assertEqual(len(unread_only), 1)
        self.assertEqual(unread_only[0]['id'], n1)

        # Mark all as read
        marked_count = database.mark_all_notifications_as_read(user_id)
        self.assertEqual(marked_count, 1)
        self.assertEqual(database.get_unread_notification_count(user_id), 0)

        # Delete notification
        deleted = database.delete_notification(n1, user_id)
        self.assertTrue(deleted)
        self.assertEqual(len(database.get_notifications_for_user(user_id)), 1)

    # ------------------------------------------------------------------
    # 85. User Isolation & Security Protections
    # ------------------------------------------------------------------
    def test_85_notifications_user_isolation(self):
        """Verify strict isolation between User A and User B notifications."""
        user_a = database.create_user(email="alice_notif@campus.edu", name="Alice", password_plain="Password123!")
        user_b = database.create_user(email="bob_notif@campus.edu", name="Bob", password_plain="Password123!")

        notif_a = database.create_notification(user_a, "welcome", "For Alice", "Alice's secret message")
        notif_b = database.create_notification(user_b, "welcome", "For Bob", "Bob's private message")

        # User B cannot mark User A's notification as read
        ok = database.mark_notification_as_read(notif_a, user_b)
        self.assertFalse(ok)
        self.assertEqual(database.get_unread_notification_count(user_a), 1)

        # User B cannot delete User A's notification
        del_ok = database.delete_notification(notif_a, user_b)
        self.assertFalse(del_ok)
        self.assertIsNotNone(database.get_notification_by_id(notif_a))

        # Enforced check in get_notification_by_id
        self.assertIsNone(database.get_notification_by_id(notif_a, user_id=user_b))
        self.assertIsNotNone(database.get_notification_by_id(notif_a, user_id=user_a))

    # ------------------------------------------------------------------
    # 86. Item Owner Resolution Helper
    # ------------------------------------------------------------------
    def test_86_get_owner_user_id_for_item(self):
        """Verify resolving registered user ID from item.user_id or poster_contact match."""
        user_id = database.create_user(email="owner_res@campus.edu", name="Owner", password_plain="Password123!")

        # Case 1: Item created with explicit user_id
        item1_id = database.create_item(
            'lost', 'My Laptop', 'Electronics', 'Library', '2026-10-29',
            'Silver laptop', 'Owner', 'owner_res@campus.edu', '1234',
            user_id=user_id
        )
        item1 = database.get_item_by_id(item1_id)
        self.assertEqual(database.get_owner_user_id_for_item(item1), user_id)

        # Case 2: Legacy or guest item with user_id=None, but matching registered email
        item2_id = database.create_item(
            'lost', 'My Umbrella', 'Other / Miscellaneous', 'Dining', '2026-10-29',
            'Blue umbrella', 'Owner', 'owner_res@campus.edu', '1234',
            user_id=None
        )
        item2 = database.get_item_by_id(item2_id)
        self.assertEqual(database.get_owner_user_id_for_item(item2), user_id)

        # Case 3: Anonymous post with unmatched contact info
        item3_id = database.create_item(
            'found', 'Anonymous Keys', 'Student IDs & Keys', 'Gym', '2026-10-29',
            'Room keys', 'Stranger', 'stranger_unknown@example.com', '1234',
            user_id=None
        )
        item3 = database.get_item_by_id(item3_id)
        self.assertIsNone(database.get_owner_user_id_for_item(item3))

    # ------------------------------------------------------------------
    # 87. Notifications Page Authentication Enforcement
    # ------------------------------------------------------------------
    def test_87_notifications_page_unauthenticated_redirect(self):
        """Verify unauthenticated requests to /notifications redirect to /login."""
        res = self.client.get('/notifications', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.headers.get('Location', ''))

    # ------------------------------------------------------------------
    # 88. Notifications Page Authenticated & Filter Tabs
    # ------------------------------------------------------------------
    def test_88_notifications_page_authenticated_filters(self):
        """Verify authenticated notifications page renders all/unread tabs and cards."""
        user_id = database.create_user(email="feed_user@campus.edu", name="Feed User", password_plain="Password123!")

        n1 = database.create_notification(user_id, "welcome", "Welcome Feed", "Welcome message")
        n2 = database.create_notification(user_id, "inquiry_received", "Inquiry Feed", "Inquiry text")
        database.mark_notification_as_read(n1, user_id)

        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['user_email'] = 'feed_user@campus.edu'
            sess['user_name'] = 'Feed User'

        # View All tab
        res_all = self.client.get('/notifications')
        self.assertEqual(res_all.status_code, 200)
        html_all = res_all.data.decode('utf-8')
        self.assertIn('Welcome Feed', html_all)
        self.assertIn('Inquiry Feed', html_all)
        self.assertIn('All (2)', html_all)
        self.assertIn('Unread', html_all)

        # View Unread tab
        res_unread = self.client.get('/notifications?filter=unread')
        self.assertEqual(res_unread.status_code, 200)
        html_unread = res_unread.data.decode('utf-8')
        feed_content = html_unread.split('class="notifications-feed"')[1].split('</main>')[0]
        self.assertIn('Inquiry Feed', feed_content)
        self.assertNotIn('Welcome Feed', feed_content)

    # ------------------------------------------------------------------
    # 89. Mark Notification Read & Read All Routes
    # ------------------------------------------------------------------
    def test_89_mark_notification_read_and_read_all_routes(self):
        """Verify POST routes for marking single notification and all notifications as read."""
        user_1 = database.create_user(email="user1_notif@campus.edu", name="User One", password_plain="Password123!")
        user_2 = database.create_user(email="user2_notif@campus.edu", name="User Two", password_plain="Password123!")

        notif1 = database.create_notification(user_1, "inquiry_received", "Msg 1", "Body 1")
        notif2 = database.create_notification(user_1, "inquiry_received", "Msg 2", "Body 2")
        notif_other = database.create_notification(user_2, "welcome", "Msg Other", "Body Other")

        with self.client.session_transaction() as sess:
            sess['user_id'] = user_1
            sess['user_email'] = 'user1_notif@campus.edu'
            sess['user_name'] = 'User One'

        # Mark single read
        res_single = self.client.post(f'/notifications/{notif1}/read', follow_redirects=True)
        self.assertEqual(res_single.status_code, 200)
        self.assertEqual(database.get_unread_notification_count(user_1), 1)

        # Unauthorized attempt on user 2's notification returns 403
        res_forbidden = self.client.post(f'/notifications/{notif_other}/read')
        self.assertEqual(res_forbidden.status_code, 403)

        # Mark all read
        res_all = self.client.post('/notifications/read-all', follow_redirects=True)
        self.assertEqual(res_all.status_code, 200)
        self.assertEqual(database.get_unread_notification_count(user_1), 0)

    # ------------------------------------------------------------------
    # 90. Delete Notification Route & Cross-User Protection
    # ------------------------------------------------------------------
    def test_90_delete_notification_route(self):
        """Verify deleting notification via route with cross-user 403 protection."""
        user_a = database.create_user(email="del_a@campus.edu", name="Del A", password_plain="Password123!")
        user_b = database.create_user(email="del_b@campus.edu", name="Del B", password_plain="Password123!")

        notif_a = database.create_notification(user_a, "welcome", "Delete Me", "To be deleted")
        notif_b = database.create_notification(user_b, "welcome", "Keep Me", "Should stay")

        with self.client.session_transaction() as sess:
            sess['user_id'] = user_a
            sess['user_email'] = 'del_a@campus.edu'
            sess['user_name'] = 'Del A'

        # Attempt to delete User B's notification -> 403
        res_bad = self.client.post(f'/notifications/{notif_b}/delete')
        self.assertEqual(res_bad.status_code, 403)
        self.assertIsNotNone(database.get_notification_by_id(notif_b))

        # Successfully delete own notification
        res_good = self.client.post(f'/notifications/{notif_a}/delete', follow_redirects=True)
        self.assertEqual(res_good.status_code, 200)
        self.assertIsNone(database.get_notification_by_id(notif_a))

    # ------------------------------------------------------------------
    # 91. CSRF Protection on Notification Actions
    # ------------------------------------------------------------------
    def test_91_notifications_csrf_protection(self):
        """Verify CSRF token is required on notification mutation endpoints when enabled."""
        user_id = database.create_user(email="csrf_notif@campus.edu", name="CSRF User", password_plain="Password123!")
        notif_id = database.create_notification(user_id, "welcome", "CSRF Test", "Testing CSRF")

        try:
            self.app.config['WTF_CSRF_ENABLED'] = True
            with self.client.session_transaction() as sess:
                sess['user_id'] = user_id
                sess['user_email'] = 'csrf_notif@campus.edu'

            # POST without CSRF token must fail with 400
            res = self.client.post(f'/notifications/{notif_id}/read')
            self.assertEqual(res.status_code, 400)
        finally:
            self.app.config['WTF_CSRF_ENABLED'] = False

    # ------------------------------------------------------------------
    # 92. Real Event Triggers: Signup & Email Verification
    # ------------------------------------------------------------------
    def test_92_real_event_triggers_signup_and_verify_email(self):
        """Verify welcome notification on signup and verified notification on email verification."""
        # 1. Signup triggers welcome notification
        res_signup = self.client.post('/signup', data={
            'name': 'New Student',
            'email': 'new_student_notif@campus.edu',
            'password': 'Password123!',
            'confirm_password': 'Password123!'
        }, follow_redirects=True)
        self.assertEqual(res_signup.status_code, 200)

        created_user = database.get_user_by_email('new_student_notif@campus.edu')
        self.assertIsNotNone(created_user)

        user_notifs = database.get_notifications_for_user(created_user['id'])
        self.assertEqual(len(user_notifs), 1)
        self.assertEqual(user_notifs[0]['notification_type'], 'welcome')
        self.assertIn("Welcome to CampusConnect!", user_notifs[0]['title'])

        # 2. Email verification triggers verification_complete notification
        token = created_user['verification_token']
        res_verify = self.client.get(f'/verify-email/{token}', follow_redirects=True)
        self.assertEqual(res_verify.status_code, 200)

        updated_notifs = database.get_notifications_for_user(created_user['id'])
        self.assertEqual(len(updated_notifs), 2)
        # Newest notification should be verification_complete
        self.assertEqual(updated_notifs[0]['notification_type'], 'verification_complete')
        self.assertIn("Email Verified", updated_notifs[0]['title'])

    # ------------------------------------------------------------------
    # 93. Real Event Triggers: Contact Inquiry & Anonymous Safety
    # ------------------------------------------------------------------
    def test_93_real_event_triggers_contact_inquiry_and_anonymous_safety(self):
        """Verify inquiry notification sent to known owner; anonymous reports skip safely."""
        owner_id = database.create_user(email="listing_owner@campus.edu", name="Listing Owner", password_plain="Password123!")
        pin = "1234"

        # Item owned by listing_owner
        item_id = database.create_item(
            'lost', 'Math Calculator', 'Electronics', 'Math Hall', '2026-10-29',
            'TI-84 grapher', 'Listing Owner', 'listing_owner@campus.edu', pin,
            user_id=owner_id
        )

        # 1. Send contact inquiry to owned item
        res_contact = self.client.post(f'/items/{item_id}/contact', data={
            'sender_name': 'Inquirer Sam',
            'sender_contact': 'sam@campus.edu',
            'message': 'I think I saw your calculator at the front desk.'
        }, follow_redirects=True)
        self.assertEqual(res_contact.status_code, 200)

        owner_notifs = database.get_notifications_for_user(owner_id)
        self.assertEqual(len(owner_notifs), 1)
        self.assertEqual(owner_notifs[0]['notification_type'], 'inquiry_received')
        self.assertIn('Inquirer Sam', owner_notifs[0]['message'])

        # 2. Anonymous/legacy item with no registered owner
        anon_item_id = database.create_item(
            'found', 'Blue Umbrella', 'Other / Miscellaneous', 'Cafeteria', '2026-10-29',
            'Found umbrella', 'Anonymous Poster', 'anon_guest_99@example.com', pin,
            user_id=None
        )

        # Submitting inquiry to anonymous item must succeed without crashing
        res_anon_contact = self.client.post(f'/items/{anon_item_id}/contact', data={
            'sender_name': 'Inquirer Alex',
            'sender_contact': 'alex@campus.edu',
            'message': 'Is the umbrella dark blue?'
        }, follow_redirects=True)
        self.assertEqual(res_anon_contact.status_code, 200)

    # ------------------------------------------------------------------
    # 94. Real Event Triggers: Status Update & Anonymous Safety
    # ------------------------------------------------------------------
    def test_94_real_event_triggers_status_update_and_anonymous_safety(self):
        """Verify status change triggers notification for known owner; anonymous reports skip safely."""
        owner_id = database.create_user(email="status_owner@campus.edu", name="Status Owner", password_plain="Password123!")
        pin = "1234"

        item_id = database.create_item(
            'lost', 'Dorm Keys', 'Student IDs & Keys', 'Quad', '2026-10-29',
            'Brass keys on lanyard', 'Status Owner', 'status_owner@campus.edu', pin,
            user_id=owner_id
        )

        # Resolve item
        res_resolve = self.client.post(f'/items/{item_id}/status', data={
            'pin': pin,
            'status': 'resolved'
        }, follow_redirects=True)
        self.assertEqual(res_resolve.status_code, 200)

        notifs = database.get_notifications_for_user(owner_id)
        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0]['notification_type'], 'status_changed')
        self.assertIn('RESOLVED', notifs[0]['message'])

        # Anonymous item status update
        anon_item_id = database.create_item(
            'lost', 'Water Bottle', 'Clothing & Accessories', 'Gym', '2026-10-29',
            'Green bottle', 'Guest', 'guest_stranger@example.com', pin,
            user_id=None
        )
        res_anon_status = self.client.post(f'/items/{anon_item_id}/status', data={
            'pin': pin,
            'status': 'resolved'
        }, follow_redirects=True)
        self.assertEqual(res_anon_status.status_code, 200)

    # ------------------------------------------------------------------
    # 95. Navbar Bell, Badge & Dropdown Markup
    # ------------------------------------------------------------------
    def test_95_navbar_bell_and_badge_and_dropdown_rendering(self):
        """Verify notification bell, unread badge, and dropdown in navbar for authenticated users."""
        # Unauthenticated: no bell rendered
        res_guest = self.client.get('/')
        html_guest = res_guest.data.decode('utf-8')
        self.assertNotIn('id="navBellBtn"', html_guest)

        # Authenticated user
        user_id = database.create_user(email="navbar_user@campus.edu", name="Navbar User", password_plain="Password123!")
        database.create_notification(user_id, "welcome", "Navbar Bell Title", "Testing navbar bell markup")

        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['user_email'] = 'navbar_user@campus.edu'
            sess['user_name'] = 'Navbar User'

        res_auth = self.client.get('/')
        html_auth = res_auth.data.decode('utf-8')
        self.assertIn('id="navBellBtn"', html_auth)
        self.assertIn('id="navBadgeCount"', html_auth)
        self.assertIn('id="navNotificationsDropdown"', html_auth)
        self.assertIn('Navbar Bell Title', html_auth)

    # ------------------------------------------------------------------
    # 96. Safe Target URL Validation Helper
    # ------------------------------------------------------------------
    def test_96_target_url_safety_validation(self):
        """Verify is_safe_target_url accepts relative internal paths and rejects unsafe URLs."""
        self.assertTrue(database.is_safe_target_url('/items/123'))
        self.assertTrue(database.is_safe_target_url('/profile'))
        self.assertTrue(database.is_safe_target_url('/notifications?filter=unread'))
        self.assertTrue(database.is_safe_target_url(None))

        # Rejects external domains and unsafe protocols
        self.assertFalse(database.is_safe_target_url('https://evil.com/phish'))
        self.assertFalse(database.is_safe_target_url('http://evil.com'))
        self.assertFalse(database.is_safe_target_url('//evil.com/hack'))
        self.assertFalse(database.is_safe_target_url('/\\evil.com'))
        self.assertFalse(database.is_safe_target_url('javascript:alert(1)'))
        self.assertFalse(database.is_safe_target_url('data:text/html,<script>'))





if __name__ == '__main__':
    unittest.main(verbosity=2)

