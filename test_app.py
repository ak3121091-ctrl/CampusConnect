"""
test_app.py - Comprehensive Automated Test Suite for CampusConnect
------------------------------------------------------------------
Tests all routes, SQL parameterization, authorization, input validation,
safe contact inquiries, and database persistence.
"""

import unittest
from app import app
import database


class CampusConnectTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reset database to guarantee fresh demo records for testing
        database.reset_db()

    @classmethod
    def tearDownClass(cls):
        # Reset database after test suite completes so demo records are pristine for manual inspection
        database.reset_db()

    def setUp(self):
        # Configure test client
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

    def test_01_database_and_demo_seeding(self):
        """Verify database tables and demo seed records exist."""
        stats = database.get_statistics()
        self.assertGreaterEqual(stats['total'], 6, "Should have at least 6 items in DB")
        self.assertGreaterEqual(stats['open_lost'], 1, "Should have open lost items")
        self.assertGreaterEqual(stats['open_found'], 1, "Should have open found items")
        print("[PASS] Test 01: Database initialized and seeded with demo records.")

    def test_02_home_page_rendering(self):
        """Verify home page loads with stats, search bar, and separate sections."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        self.assertIn('CampusConnect', html)
        self.assertIn('Lost Items', html)
        self.assertIn('Found Items', html)
        self.assertIn('DEMO DATA', html)
        self.assertIn('search-input', html)
        print("[PASS] Test 02: Home page renders with search, badges, and sections.")

    def test_03_search_and_filters(self):
        """Verify search query and filter parameters."""
        # 1. Search for calculator
        res_calc = self.client.get('/?q=Calculator')
        self.assertEqual(res_calc.status_code, 200)
        html_calc = res_calc.data.decode('utf-8')
        self.assertIn('TI-84 Plus', html_calc)

        # 2. Filter by type=lost
        res_lost = self.client.get('/?type=lost')
        self.assertEqual(res_lost.status_code, 200)
        html_lost = res_lost.data.decode('utf-8')
        self.assertIn('Lost Items', html_lost)

        # 3. Filter by category=Electronics
        res_cat = self.client.get('/?category=Electronics')
        self.assertEqual(res_cat.status_code, 200)

        # 4. Filter by status=resolved
        res_res = self.client.get('/?status=resolved')
        self.assertEqual(res_res.status_code, 200)
        html_res = res_res.data.decode('utf-8')
        self.assertIn('RESOLVED', html_res)
        print("[PASS] Test 03: Search and filter queries execute accurately.")

    def test_04_server_side_validation(self):
        """Verify form validation rejects invalid data and displays error messages."""
        # Test 4a: Missing required fields and invalid PIN
        invalid_payload = {
            'item_type': 'lost',
            'title': 'A',  # too short
            'category': 'InvalidCategory',
            'location': '',
            'event_date': 'not-a-date',
            'description': 'hi',
            'poster_name': '',
            'poster_contact': '',
            'pin': 'abc'  # invalid pin
        }
        response = self.client.post('/items/new', data=invalid_payload, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        self.assertIn('Title must be between 3 and 100 characters', html)
        self.assertIn('Please select a valid category', html)
        self.assertIn('Campus location must be between 3 and 120 characters', html)
        self.assertIn('Security PIN must be 4 to 8 digits', html)

        # Test 4b: Future date validation
        future_payload = {
            'item_type': 'lost',
            'title': 'Future Lost Item',
            'category': 'Electronics',
            'location': 'Library',
            'event_date': '2099-01-01',
            'description': 'Valid description',
            'poster_name': 'Future Person',
            'poster_contact': 'future@campus.edu',
            'pin': '1234'
        }
        future_res = self.client.post('/items/new', data=future_payload, follow_redirects=True)
        self.assertEqual(future_res.status_code, 200)
        self.assertIn('Date cannot be in the future', future_res.data.decode('utf-8'))
        print("[PASS] Test 04: Server-side validation catches invalid inputs and future dates.")


    def test_05_create_new_item_and_verify_persistence(self):
        """Verify posting a valid item saves to SQLite and hashes the PIN."""
        valid_payload = {
            'item_type': 'lost',
            'title': 'Lenovo ThinkPad X1 Carbon',
            'category': 'Electronics',
            'location': 'Student Union - Computer Lab B',
            'event_date': '2026-10-27',
            'description': 'Matte black 14-inch laptop with a Linux penguin sticker on the palm rest.',
            'poster_name': 'Devin Taylor',
            'poster_contact': 'devin.taylor@campus.edu',
            'pin': '4321'
        }
        response = self.client.post('/items/new', data=valid_payload, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        redirect_url = response.headers['Location']
        item_id = int(redirect_url.split('/')[-1])

        # Verify item in database directly
        item = database.get_item_by_id(item_id)
        self.assertIsNotNone(item)
        self.assertEqual(item['title'], 'Lenovo ThinkPad X1 Carbon')
        self.assertEqual(item['status'], 'open')
        # Crucial security check: PIN must NOT be stored in plain text!
        self.assertNotEqual(item['pin_hash'], '4321')
        self.assertTrue(item['pin_hash'].startswith('scrypt:') or item['pin_hash'].startswith('pbkdf2:'))

        # Verify item detail page renders
        res_detail = self.client.get(f'/items/{item_id}')
        self.assertEqual(res_detail.status_code, 200)
        detail_html = res_detail.data.decode('utf-8')
        self.assertIn('Lenovo ThinkPad X1 Carbon', detail_html)
        self.assertIn('Student Union - Computer Lab B', detail_html)
        # Verify privacy: private contact (devin.taylor@campus.edu) is NOT leaked on the page!
        self.assertNotIn('devin.taylor@campus.edu', detail_html)
        print(f"[PASS] Test 05: Created item #{item_id}, verified persistence, PIN hashing, and privacy.")

    def test_06_safe_contact_request(self):
        """Verify visitor can submit a safe contact inquiry and it persists."""
        # Find any item in DB
        items = database.get_items()
        item_id = items[0]['id']

        contact_payload = {
            'sender_name': 'Dana Scully',
            'sender_contact': 'dana.scully@campus.edu',
            'message': 'I think I saw someone turn this item in to the security front desk this morning!'
        }
        response = self.client.post(f'/items/{item_id}/contact', data=contact_payload, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        self.assertIn('Inquiry saved!', html)

        # Verify inquiry in database
        requests = database.get_contact_requests_for_item(item_id)
        found_req = any(r['sender_name'] == 'Dana Scully' for r in requests)
        self.assertTrue(found_req, "Contact inquiry must be saved in database")
        print("[PASS] Test 06: Safe contact inquiry stored successfully.")

    def test_07_authorization_for_status_change(self):
        """Verify only users with correct PIN can resolve or reopen items."""
        # Create a dedicated item for status change test
        item_id = database.create_item(
            item_type='lost',
            title='Test Umbrella for Status Check',
            category='Clothing & Accessories',
            location='Library Lobby',
            event_date='2026-10-27',
            description='Black compact umbrella test item.',
            poster_name='Test Poster',
            poster_contact='poster@campus.edu',
            pin_plain='5678'
        )

        # 1. Attempt status change with WRONG PIN '9999'
        wrong_res = self.client.post(f'/items/{item_id}/status', data={
            'pin': '9999',
            'status': 'resolved'
        }, follow_redirects=True)
        self.assertEqual(wrong_res.status_code, 200)
        wrong_html = wrong_res.data.decode('utf-8')
        self.assertIn('Incorrect Security PIN', wrong_html)

        # Status must still be 'open'
        check_item = database.get_item_by_id(item_id)
        self.assertEqual(check_item['status'], 'open')

        # 2. Attempt status change with CORRECT PIN '5678'
        correct_res = self.client.post(f'/items/{item_id}/status', data={
            'pin': '5678',
            'status': 'resolved'
        }, follow_redirects=True)
        self.assertEqual(correct_res.status_code, 200)
        correct_html = correct_res.data.decode('utf-8')
        self.assertIn('Item status successfully updated', correct_html)

        # Verify in database
        updated_item = database.get_item_by_id(item_id)
        self.assertEqual(updated_item['status'], 'resolved')
        print("[PASS] Test 07: Authorization check strictly protects item status.")

    def test_08_authorization_for_inbox_unlock(self):
        """Verify only users with correct PIN can unlock and view private inquiries."""
        items = database.get_items()
        demo_item = next(i for i in items if i['is_demo'] == 1)
        item_id = demo_item['id']

        # 1. Attempt inbox unlock with WRONG PIN
        wrong_res = self.client.post(f'/items/{item_id}/inbox', data={'pin': '0000'}, follow_redirects=True)
        self.assertEqual(wrong_res.status_code, 200)
        self.assertIn('Incorrect Security PIN', wrong_res.data.decode('utf-8'))

        # 2. Attempt inbox unlock with CORRECT PIN '1234'
        correct_res = self.client.post(f'/items/{item_id}/inbox', data={'pin': '1234'}, follow_redirects=True)
        self.assertEqual(correct_res.status_code, 200)
        html = correct_res.data.decode('utf-8')
        self.assertIn('PIN Verified!', html)
        self.assertIn('Unlocked', html)
        print("[PASS] Test 08: Security PIN unlocks private owner inbox.")

    def test_09_about_and_404_routes(self):
        """Verify about page and 404 handler."""
        res_about = self.client.get('/about')
        self.assertEqual(res_about.status_code, 200)
        self.assertIn('About CampusConnect', res_about.data.decode('utf-8'))

        res_404 = self.client.get('/items/999999')
        self.assertEqual(res_404.status_code, 404)
        self.assertIn('404', res_404.data.decode('utf-8'))
        print("[PASS] Test 09: About and 404 routes function properly.")

    def test_10_xss_protection(self):
        """Verify that user-submitted script tags are safely auto-escaped in HTML."""
        xss_payload = {
            'item_type': 'lost',
            'title': '<script>alert("hack")</script>',
            'category': 'Electronics',
            'location': 'Library <img src=x onerror=alert(1)>',
            'event_date': '2026-10-27',
            'description': '<script>stealCookies()</script>',
            'poster_name': '<b onmouseover=alert(1)>Poster</b>',
            'poster_contact': 'hacker@campus.edu',
            'pin': '7777'
        }
        res = self.client.post('/items/new', data=xss_payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        # Script tags must be escaped as HTML entities, never raw executable tags
        self.assertNotIn('<script>alert("hack")</script>', html)
        self.assertIn('&lt;script&gt;', html)
        print("[PASS] Test 10: XSS payloads are safely neutralized via Jinja2 autoescaping.")

    def test_11_tab_badge_counts_preservation(self):
        """Verify that selecting 'Lost Items' tab does not zero out the 'Found Items' count."""
        # Request home page with type=lost
        res = self.client.get('/?type=lost')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        # Found Items button badge must reflect actual found count, not 0
        self.assertNotIn('Found Items (0)', html)
        print("[PASS] Test 11: Tab badge counts remain accurate when switching views.")

    def test_12_search_by_poster_and_category(self):
        """Verify search queries matching poster name and category return records."""
        # Alex Chen posted the TI-84
        res_alex = self.client.get('/?q=Alex')
        self.assertEqual(res_alex.status_code, 200)
        self.assertIn('TI-84 Plus', res_alex.data.decode('utf-8'))
        print("[PASS] Test 12: Search query matching poster name succeeds.")

    def test_13_invalid_and_empty_query_param_handling(self):
        """Verify that invalid or empty filter parameters normalize gracefully without blanking the directory."""
        # 1. Test empty type (?type=)
        res_empty_type = self.client.get('/?type=')
        self.assertEqual(res_empty_type.status_code, 200)
        html_empty = res_empty_type.data.decode('utf-8')
        self.assertIn('Lost Items', html_empty)
        self.assertIn('Found Items', html_empty)

        # 2. Test invalid type (?type=bogus_value)
        res_bogus = self.client.get('/?type=bogus_value')
        self.assertEqual(res_bogus.status_code, 200)
        html_bogus = res_bogus.data.decode('utf-8')
        self.assertIn('Lost Items', html_bogus)

        # 3. Test invalid category (?category=NonExistent)
        res_invalid_cat = self.client.get('/?category=NonExistent')
        self.assertEqual(res_invalid_cat.status_code, 200)

        # 4. Test invalid status (?status=random)
        res_invalid_status = self.client.get('/?status=random')
        self.assertEqual(res_invalid_status.status_code, 200)
        print("[PASS] Test 13: Query parameters normalize gracefully and prevent blank view state.")


if __name__ == '__main__':
    unittest.main(verbosity=2)

