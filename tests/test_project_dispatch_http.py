"""Actual HTTP authorization/transactions; no physical transport or persistent data."""
import unittest
from tests import test_daily_workflow as daily_fixture
DAY = daily_fixture.DAY


class ProjectDispatchHTTPTests(unittest.TestCase):
    setUp = daily_fixture.DailyWorkflowTests.setUp
    tearDown = daily_fixture.DailyWorkflowTests.tearDown
    request = daily_fixture.DailyWorkflowTests.request

    def test_authorization_date_preview_request_retry_and_versioned_stop(self):
        self.server.project_dispatch.close()
        self.server.device_bridge._secrets = {'api_badge_a': {}, 'api_badge_b': {}}
        _, _, headers = self.request('/api/access/setup', {'username': 'dispatch_admin', 'name': '管理员', 'password': 'isolated-admin-password'})
        admin = headers['Set-Cookie']
        path = '/api/projects/' + self.project['id']
        self.assertEqual(self.request(path + '/dispatch-preview')[0], 401)
        code, _, _ = self.request('/api/access/users', {'username': 'dispatch_worker', 'name': '工人', 'role': 'worker',
            'person_id': 'person_a', 'password': 'isolated-worker-password'}, admin)
        self.assertEqual(code, 200)
        _, _, headers = self.request('/api/access/login', {'username': 'dispatch_worker', 'password': 'isolated-worker-password'})
        worker = headers['Set-Cookie']
        payload = {'person_id': 'person_a', 'device_id': 'api_badge_a', 'expected_version': 0}
        self.assertEqual(self.request('/api/device-bindings', payload, worker)[0], 403)
        self.assertEqual(self.request('/api/device-bindings', payload, admin, 'https://foreign.test')[0], 403)
        self.assertEqual(self.request('/api/device-bindings', payload, admin)[0], 200)
        self.assertEqual(self.request('/api/device-bindings', dict(payload, person_id='person_b'), admin)[0], 409)
        self.assertEqual(self.request('/api/device-bindings', dict(payload, person_id='person_b', device_id='api_badge_b'), admin)[0], 200)
        code, preview, _ = self.request(path + '/dispatch-preview?date=' + DAY, cookie=admin)
        self.assertEqual(code, 200, preview)
        self.assertEqual((preview['date'], preview['summary']['task_count'], preview['summary']['connected_count']), (DAY, 2, 0))
        self.assertEqual(self.request(path + '/dispatch-preview?date=not-a-date', cookie=admin)[0], 400)
        data = {'request_id': 'api_dispatch_1', 'expected_revision': 1, 'date': DAY}
        self.assertEqual(self.request(path + '/dispatch', data, worker)[0], 403)
        code, result, _ = self.request(path + '/dispatch', data, admin)
        self.assertEqual(code, 200, result)
        job = result['dispatch']
        self.assertTrue(self.request(path + '/dispatch', data, admin)[1]['duplicate'])
        self.assertEqual(self.request(path + '/dispatch', dict(data, date='2026-09-15'), admin)[0], 409)
        route = '/api/project-dispatches/' + job['id']
        self.assertEqual(self.request(route + '/cancel', {'expected_version': job['version']}, worker)[0], 403)
        self.assertEqual(self.request(route + '/cancel', {'expected_version': 0}, admin)[0], 409)
        code, result, _ = self.request(route + '/cancel', {'expected_version': job['version']}, admin)
        self.assertEqual(code, 200, result)
        self.assertEqual(result['dispatch']['status'], 'cancelled')
        self.assertTrue(self.request(route + '/cancel', {'expected_version': job['version']}, admin)[1]['duplicate'])
        self.assertEqual(self.request(route + '/retry', {}, admin)[0], 409)
        self.assertEqual(self.request('/api/device/deliveries', cookie=admin)[1]['deliveries'], [])
