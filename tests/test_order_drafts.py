"""Real-order extraction stays a traceable draft and cannot become dispatched work."""
import unittest
import test_api


def payload():
    return {'order_key': 'DEMO-TEST', 'source_revision': '施工图 R2',
            'project': {'name': '真实订单拆单试验', 'client': '测试客户', 'quantity': None},
            'sources': [{'source_path': '/synthetic-orders/订单/图纸.pdf', 'kind': '施工图', 'pages': 3}],
            'issues': ['核对改单与原订单差异'], 'parts': [
                {'id': 'A01', 'name': '墙柜 A', 'item_level': 'assembly', 'quantity': None,
                 'quantity_unit': '台', 'material': '木作、金属、玻璃',
                 'specification': '1200×400×2400', 'overall_dimensions': {'length_mm': 1200, 'width_mm': 400, 'height_mm': 2400},
                 'thickness_mm': 2400, 'evidence': [{'source_path': '/synthetic-orders/订单/图纸.pdf', 'page': 2, 'quote': '墙柜A 1200×400×2400'}],
                 'review_questions': ['板厚未标明'], 'work_scopes': [{'trade': '木工', 'title': '柜体结构拆分', 'basis': '图纸木作柜体'}]}]}


class OrderDraftAPITests(unittest.TestCase):
    setUp = test_api.APITests.setUp
    tearDown = test_api.APITests.tearDown
    request = test_api.APITests.request
    state = test_api.APITests.state

    def imported(self, body=None):
        status, result = self.request('/api/order-drafts/import', body or payload())
        self.assertEqual(status, 200, result)
        return result

    def test_missing_quantity_and_cabinet_height_do_not_become_production_facts(self):
        result = self.imported()
        p = result['parts'][0]
        self.assertIsNone(result['project']['quantity'])
        self.assertIsNone(p['quantity'])
        self.assertIsNone(p['thickness'])
        self.assertEqual(p['overall_dimensions']['height_mm'], 2400)
        self.assertEqual(p['evidence'][0]['page'], 2)
        self.assertTrue(p['draft_only'])
        self.assertEqual(p['review_status'], 'pending')
        self.assertEqual(p['work_scopes'][0]['status'], 'suggested')
        self.assertIn('数量未确认', p['review_questions'])
        self.assertFalse(self.state()['tasks'])

    def test_repeat_import_is_idempotent_and_versions_stay_separate(self):
        first = self.imported()
        again = self.imported()
        self.assertTrue(again['duplicate'])
        self.assertEqual(first['project']['id'], again['project']['id'])
        self.assertEqual(first['parts'][0]['id'], again['parts'][0]['id'])
        other = payload(); other['source_revision'] = '施工图 R1'
        earlier = self.imported(other)
        self.assertNotEqual(earlier['project']['id'], first['project']['id'])
        self.assertEqual(len(self.state()['projects']), 2)

    def test_revision_reimport_archives_old_extract_and_keeps_source(self):
        first = self.imported()
        changed = payload(); changed['parts'][0]['quantity'] = 2
        result = self.imported(changed)
        self.assertFalse(result['duplicate'])
        self.assertEqual(first['project']['id'], result['project']['id'])
        state = self.state()
        self.assertEqual(len([p for p in state['parts'] if not p['archived']]), 1)
        self.assertEqual(len([p for p in state['parts'] if p['archived']]), 1)
        self.assertEqual(len(state['documents']), 2)
        source = result['project']['order_draft']['sources'][0]
        self.assertEqual(source['source_path'], '/synthetic-orders/订单/图纸.pdf')
        self.assertFalse((self.store.uploads / '图纸.pdf').exists())

    def test_drafts_cannot_be_approved_generated_or_released(self):
        result = self.imported()
        project = result['project']['id']; part = result['parts'][0]['id']
        code, body = self.request('/api/parts/' + part + '/review', {'approved': True,
            'edits': {'material': '多层板', 'category': 'wood', 'length': 1200, 'width': 400, 'thickness': 18, 'quantity': 2, 'finish': '免漆'}})
        self.assertEqual(code, 409)
        for action in ('generate', 'release'):
            self.assertEqual(self.request('/api/projects/' + project + '/' + action, {})[0], 409)
        self.assertFalse(self.state()['tasks'])

    def test_invalid_source_or_negative_quantity_rolls_back(self):
        for field, value in [('quantity', -1), ('item_level', 'cabinet')]:
            bad = payload(); bad['parts'][0][field] = value
            self.assertEqual(self.request('/api/order-drafts/import', bad)[0], 400)
        bad = payload(); bad['sources'][0]['source_path'] = '../private.pdf'
        self.assertEqual(self.request('/api/order-drafts/import', bad)[0], 400)
        self.assertFalse(self.state()['projects'])

    def test_procurement_reference_retains_decimal_quantity_and_parent(self):
        body = payload()
        body['parts'][0].update(item_level='material', quantity=1.5, quantity_unit='米',
                                parent_reference='展柜 A 灯带', procurement_reference_only=True)
        result = self.imported(body)
        p = result['parts'][0]
        self.assertTrue(p['procurement_reference_only'])
        self.assertEqual((p['quantity'], p['quantity_unit'], p['parent_reference']), (1.5, '米', '展柜 A 灯带'))
        self.assertFalse(self.state()['tasks'])

    def test_export_contains_source_and_scope_metadata(self):
        result = self.imported()
        code, exported = self.request('/api/projects/' + result['project']['id'] + '/export?format=json')
        self.assertEqual(code, 200)
        self.assertEqual(exported['parts'][0]['evidence'][0]['page'], 2)
        self.assertEqual(exported['project']['order_draft']['source_revision'], '施工图 R2')
        self.assertEqual(exported['tasks'], [])
