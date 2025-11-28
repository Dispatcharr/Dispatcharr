from django.test import TestCase, Client
from django.urls import reverse

class OutputM3UTest(TestCase):
    def setUp(self):
        self.client = Client()
    
    def test_generate_m3u_response(self):
        """
        Test that the M3U endpoint returns a valid M3U file.
        """
        url = reverse('output:generate_m3u')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("#EXTM3U", content)

    def test_generate_m3u_response_post_empty_body(self):
        """
        Test that a POST request with an empty body returns 200 OK.
        """
        url = reverse('output:generate_m3u')

        response = self.client.post(url, data=None, content_type='application/x-www-form-urlencoded')
        content = response.content.decode()

        self.assertEqual(response.status_code, 200, "POST with empty body should return 200 OK")
        self.assertIn("#EXTM3U", content)

    def test_generate_m3u_response_post_with_body(self):
        """
        Test that a POST request with a non-empty body returns 403 Forbidden.
        """
        url = reverse('output:generate_m3u')

        response = self.client.post(url, data={'evilstring': 'muhahaha'})

        self.assertEqual(response.status_code, 403, "POST with body should return 403 Forbidden")
        self.assertIn("POST requests with body are not allowed, body is:", response.content.decode())
