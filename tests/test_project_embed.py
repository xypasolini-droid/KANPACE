"""Only explicit local model viewer pages may be embedded by this workstation."""
import unittest
import urllib.request
import test_api


class ProjectEmbedTests(unittest.TestCase):
    setUp = test_api.APITests.setUp
    tearDown = test_api.APITests.tearDown

    def test_only_explicit_viewer_pages_allow_same_origin_embedding(self):
        for path in ('/model/index.html?embed=1', '/project-3d/index.html?project=example&embed=1'):
            with self.subTest(path=path), urllib.request.urlopen(self.url + path) as response:
                self.assertEqual(response.headers['X-Frame-Options'], 'SAMEORIGIN')
                self.assertIn("frame-ancestors 'self'", response.headers['Content-Security-Policy'])
                self.assertEqual(response.status, 200)
        for path in ('/', '/?embed=1', '/bi/index.html?embed=1', '/model/index.html',
                     '/project-3d/index.html?embed=0', '/model/index.html?embed=1&embed=0'):
            with self.subTest(path=path), urllib.request.urlopen(self.url + path) as response:
                self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
                self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])

    def test_model_data_module_is_javascript(self):
        with urllib.request.urlopen(self.url + '/project-3d/scene-data.mjs') as response:
            self.assertIn('javascript', response.headers['Content-Type'])
            self.assertIn(b'export function buildOverview', response.read())


if __name__ == '__main__':
    unittest.main()
