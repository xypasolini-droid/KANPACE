"""Exercise material calculations and write guards through the actual HTTP server."""
import unittest
import test_access_http


class MaterialHTTPTests(unittest.TestCase):
    setUp = test_access_http.AccessHTTPTests.setUp
    tearDown = test_access_http.AccessHTTPTests.tearDown
    request = test_access_http.AccessHTTPTests.request
    setup_admin = test_access_http.AccessHTTPTests.setup_admin
    account = test_access_http.AccessHTTPTests.account

    def test_stock_purchase_roundtrip_and_conflict(self):
        with self.store.connect() as con:
            p = self.store.get(con, 'parts', self.part['id'])
            p['review_status'] = 'approved'
            self.store.put(con, 'parts', p)
        status, data, _ = self.request('/api/material-planning?project_id=' + self.project['id'])
        self.assertEqual(status, 200, data)
        r = data['requirements'][0]
        self.assertIsNone(r['shortage_quantity'])
        body = dict(project_id=r['project_id'], requirement_id=r['id'], snapshot=r['snapshot'], expected_version=0,
                    on_hand_quantity=0.2, reserved_quantity=0, note='隔离库存表')
        self.assertEqual(self.request('/api/material-planning/inventory', body)[0], 200)
        self.assertEqual(self.request('/api/material-planning/inventory', body)[0], 409)
        _, data, _ = self.request('/api/material-planning?project_id=' + self.project['id'])
        r = data['requirements'][0]
        self.assertAlmostEqual(r['shortage_quantity'], 0.52)
        purchase = dict(project_id=r['project_id'], requirement_id=r['id'], snapshot=r['snapshot'], expected_version=0)
        status, saved, _ = self.request('/api/material-planning/purchases', purchase)
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved['purchase']['status'], 'draft')
        self.assertTrue(self.request('/api/material-planning/purchases', purchase)[1]['duplicate'])
        with self.store.connect() as con:
            self.assertEqual(self.store.all(con, 'inventory_items')[0]['on_hand_quantity'], 0.2)
            self.assertEqual(self.store.get(con, 'tasks', 'qa_task_own')['status'], 'ready')

    def test_worker_cannot_modify_inventory_or_procurement(self):
        _, cookie = self.account('worker', 'material_worker', 'qa_worker_a')
        for endpoint in ('inventory', 'purchases'):
            self.assertEqual(self.request('/api/material-planning/' + endpoint, {}, cookie)[0], 403)
        self.assertEqual(self.request('/api/material-planning')[0], 401)
        with self.store.connect() as con:
            self.assertEqual(self.store.all(con, 'inventory_items'), [])
            self.assertEqual(self.store.all(con, 'purchase_drafts'), [])


if __name__ == '__main__':
    unittest.main()
