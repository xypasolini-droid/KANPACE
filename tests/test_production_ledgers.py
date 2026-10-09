"""Commercial and material ledgers: version, evidence and quantity invariants."""
import unittest
import test_api


class ProductionLedgerTests(unittest.TestCase):
    setUp = test_api.APITests.setUp
    tearDown = test_api.APITests.tearDown
    request = test_api.APITests.request
    project = test_api.APITests.project
    state = test_api.APITests.state

    def test_materials_reference_and_task_reservation_are_distinct_and_versioned(self):
        project = self.project()
        data = {'project_id': project['id'], 'name': '长周期玻璃', 'required_quantity': 12, 'accepted_quantity': 2, 'unit': '块', 'task_ids': []}
        code, result = self.request('/api/production/materials', data)
        self.assertEqual(code, 200, result)
        material = result['material']
        self.assertEqual((material['shortage_quantity'], material['status']), (10, 'shortage'))
        update = dict(data, id=material['id'], expected_version=1, accepted_quantity=12, note='到货检验通过，留给本项目')
        self.assertEqual(self.request('/api/production/materials', update)[0], 200)
        self.assertEqual(self.request('/api/production/materials', update)[0], 409)
        self.assertEqual(self.request('/api/production/materials', dict(update, expected_version=2, accepted_quantity=13))[0], 400)
        with self.store.connect() as con:
            self.assertEqual(len(self.store.all(con, 'material_movements')), 2)

    def test_change_approval_requires_confirmed_amounts_and_document_and_is_immutable(self):
        project = self.project()
        data = {'project_id': project['id'], 'scope': '三层 A 区', 'title': '业主调整灯位', 'status': 'pending',
                'amount': None, 'estimated_cost': None, 'note': '待核量后向业主签认', 'task_ids': []}
        code, result = self.request('/api/production/changes', data)
        self.assertEqual(code, 200, result)
        row = result['change']
        approve = dict(data, id=row['id'], expected_version=1, status='approved')
        self.assertEqual(self.request('/api/production/changes', approve)[0], 400)
        approve.update(decision_reference='签证 V-2026-015', amount=1200, estimated_cost=600)
        code, result = self.request('/api/production/changes', approve)
        self.assertEqual(code, 200, result)
        self.assertEqual(self.request('/api/production/changes', dict(approve, expected_version=2, amount=1800))[0], 409)
        body = self.request('/api/production?project_id=' + project['id'])[1]
        self.assertIsNone(body['economics'][0]['forecast_profit'])
        self.assertEqual(body['costs'], [])

    def test_contract_milestone_records_partial_cash_without_closing_project(self):
        project = self.project()
        data = {'project_id': project['id'], 'scope': '设备 KP-026', 'name': '现场验收款', 'amount': 10000,
                'received_amount': 0, 'due_date': '2026-09-15', 'status': 'planned', 'note': '合同第二节点'}
        code, result = self.request('/api/production/milestones', data)
        self.assertEqual(code, 200, result)
        row = result['milestone']
        update = dict(data, id=row['id'], expected_version=1, status='invoiced', reference='INVOICE-01')
        self.assertEqual(self.request('/api/production/milestones', update)[0], 409)
        for index, status in enumerate(('accepted', 'claimed', 'invoiced'), 1):
            update.update(expected_version=index, status=status, reference='节点凭据 ' + str(index))
            self.assertEqual(self.request('/api/production/milestones', update)[0], 200)
        update.update(expected_version=4, received_amount=4000)
        self.assertEqual(self.request('/api/production/milestones', update)[0], 200)
        update.update(expected_version=5, status='paid')
        self.assertEqual(self.request('/api/production/milestones', update)[0], 400)
        update['received_amount'] = 10000
        self.assertEqual(self.request('/api/production/milestones', update)[0], 200)
        self.assertEqual(next(p for p in self.state()['projects'] if p['id'] == project['id'])['fulfillment_status'], 'active')

    def test_unknown_costs_and_partial_delivery_do_not_create_profit_or_completed_order(self):
        project = self.project()
        code, body = self.request('/api/production?project_id=' + project['id'])
        self.assertEqual(code, 200)
        self.assertIsNone(body['economics'][0]['forecast_profit'])
        self.assertEqual(body['economics'][0]['cost_record_count'], 0)
        cost = {'project_id': project['id'], 'category': 'outsourcing', 'amount': 800, 'occurred_on': '2026-09-05', 'note': '外协玻璃对账单 P-01'}
        self.assertEqual(self.request('/api/production/costs', cost)[0], 200)
        finance = {'project_id': project['id'], 'expected_version': 0, 'contract_amount': 5000, 'approved_change_amount': 0,
                   'budget_cost': 2500, 'remaining_cost': 2000, 'received_amount': 1000, 'note': '合同及采购报价核对'}
        self.assertEqual(self.request('/api/production/financials', finance)[0], 200)
        body = self.request('/api/production?project_id=' + project['id'])[1]
        self.assertEqual(body['economics'][0]['forecast_profit'], 2200)
        self.assertEqual(body['economics'][0]['unreceived_amount'], 4000)
        self.assertTrue(any(a['type'] == 'cost' for a in body['actions']))
        delivery = {'project_id': project['id'], 'scope': 'G01-G18', 'quantity': 18, 'unit': '柜', 'delivered_on': '2026-09-05', 'reference': '运单 F-01'}
        self.assertEqual(self.request('/api/production/deliveries', delivery)[0], 200)
        self.assertEqual(next(p for p in self.state()['projects'] if p['id'] == project['id'])['fulfillment_status'], 'active')

    def test_lost_response_retry_does_not_double_book_cost_and_changed_retry_rejects(self):
        project = self.project()
        cost = {'project_id': project['id'], 'category': 'material', 'amount': 800, 'occurred_on': '2026-09-05',
                'note': '采购单 P-01', 'request_id': 'stable-form-request'}
        first = self.request('/api/production/costs', cost)[1]['cost']
        code, result = self.request('/api/production/costs', cost)
        self.assertEqual(code, 200, result)
        self.assertTrue(result['duplicate'])
        self.assertEqual(result['cost']['id'], first['id'])
        self.assertEqual(self.request('/api/production/costs', dict(cost, amount=900))[0], 409)
        rows = self.request('/api/production?project_id=' + project['id'])[1]['costs']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['amount'], 800)


if __name__ == '__main__':
    unittest.main()
