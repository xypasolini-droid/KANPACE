"""Reference imports never mutate live tasks. All fixtures and DBs are temporary."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import io
from pathlib import Path
import unittest
from urllib.parse import quote
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

import test_api
import schedule_reference as ref


HEADERS = ['出货时间', '客户等级', '序号', '客户名称', '店铺信息', '单号', '下单日期', '营销要求日期',
           '技术员', '拆单日期', '木作', '油漆', '五金', '外协', '安装', '拍摄', '包装', '件数', '方数', '包装方式', '备注', '工厂价']


def serial(iso):
    return (date.fromisoformat(iso) - date(1899, 12, 30)).days


def worksheet(rows, merges=(), bad_dimension=False, headers=None):
    headers = headers or HEADERS
    cells = [(2, i + 1, v) for i, v in enumerate(headers)]
    for row, values in rows.items():
        cells.extend((row, headers.index(k) + 1, v) for k, v in values.items())
    nodes = {}
    for row, col, value in cells:
        cell = ref.column_name(col) + str(row)
        if isinstance(value, tuple):
            kind, value = value
        else:
            kind = 'number' if isinstance(value, (int, float)) else 'text'
        if kind == 'formula':
            content = '<f>' + escape(str(value)) + '</f><v>46268</v>'
            attrs = ''
        elif kind in ('number', 'serial'):
            content = '<v>' + str(value) + '</v>'
            attrs = ' s="1"' if kind == 'serial' else ''
        elif kind == 'date':
            content, attrs = '<v>' + str(value) + '</v>', ' t="d"'
        else:
            content, attrs = '<is><t>' + escape(str(value)) + '</t></is>', ' t="inlineStr"'
        nodes.setdefault(row, []).append('<c r="' + cell + '"' + attrs + '>' + content + '</c>')
    return ('<worksheet xmlns="' + ref.NS['m'] + '"><dimension ref="' + ('A1:A1' if bad_dimension else 'A1:XFD1000') + '"/>'
            '<sheetData>' + ''.join('<row r="' + str(row) + '">' + ''.join(cs) + '</row>' for row, cs in sorted(nodes.items())) + '</sheetData>'
            '<mergeCells>' + ''.join('<mergeCell ref="' + merge + '"/>' for merge in merges) + '</mergeCells></worksheet>')


def xlsx(sheets, active=0):
    output = io.BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('xl/workbook.xml', '<workbook xmlns="' + ref.NS['m'] + '" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><bookViews><workbookView activeTab="' + str(active) + '"/></bookViews><sheets>' + ''.join('<sheet name="' + escape(name) + '" sheetId="' + str(i) + '" r:id="rId' + str(i) + '"/>' for i, (name, _) in enumerate(sheets, 1)) + '</sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join('<Relationship Id="rId' + str(i) + '" Target="worksheets/sheet' + str(i) + '.xml"/>' for i in range(1, len(sheets) + 1)) + '</Relationships>')
        archive.writestr('xl/styles.xml', '<styleSheet xmlns="' + ref.NS['m'] + '"><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>')
        for i, (_, sheet) in enumerate(sheets, 1):
            archive.writestr('xl/worksheets/sheet' + str(i) + '.xml', sheet)
    return output.getvalue()


def order(**updates):
    values = {'客户名称': '客户A', '店铺信息': '北区综合展示柜', '单号': '商务二部-001', '技术员': '技术员甲', '序号': 1,
              '下单日期': ('serial', serial('2026-08-01')), '拆单日期': ('serial', serial('2026-08-03')),
              '木作': ('serial', serial('2026-08-06')), '油漆': ('serial', serial('2026-08-07')),
              '五金': ('serial', serial('2026-08-06')), '外协': ('serial', serial('2026-08-08')),
              '安装': ('serial', serial('2026-08-09')), '包装': ('serial', serial('2026-08-11'))}
    values.update(updates)
    return values


class ReferenceTests(unittest.TestCase):
    setUp = test_api.APITests.setUp
    tearDown = test_api.APITests.tearDown
    request = test_api.APITests.request
    state = test_api.APITests.state
    project = test_api.APITests.project

    def upload(self, content=None, filename='生产排程20260813.xlsx'):
        content = content or xlsx([('排程会议 0813', worksheet({4: order()}))])
        code, body = self.request('/api/schedule-reference/import', {'filename': filename, 'content_base64': base64.b64encode(content).decode()})
        self.assertEqual(code, 200, body)
        return body

    def grid(self, query=''):
        code, body = self.request('/api/schedule-reference' + query)
        self.assertEqual(code, 200, body)
        return body

    def stat(self, node, grid=None):
        return next(s for s in (grid or self.grid())['stats'] if s['node_id'] == node)

    def test_empty_and_invalid_imports_leave_business_unchanged(self):
        before = self.state()
        self.assertEqual(self.grid()['rows'], [])
        self.assertIsNone(self.stat('wood')['p50'])
        for payload in ({'filename': '../a.xlsx', 'content_base64': 'abcd'}, {'filename': 'a.xlsx', 'content_base64': '#'},
                        {'filename': 'a.xlsx', 'content_base64': base64.b64encode(b'not excel').decode()},
                        {'filename': 'a.xls', 'content_base64': 'AAAA'}):
            self.assertEqual(self.request('/api/schedule-reference/import', payload)[0], 422)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.grid()['sources'], [])

    def test_import_is_reference_only_with_registered_original_and_name_suggestions(self):
        project = self.project('北区综合展示柜')
        before = self.state()
        content = xlsx([('排程会议 0813', worksheet({4: order(木作='OK')}))])
        result = self.upload(content)
        self.assertEqual(self.state(), before)
        grid = self.grid()
        self.assertEqual(grid['rows'][0]['nodes']['wood']['kind'], 'status')
        self.assertEqual(grid['rows'][0]['suggestions'][0]['project_id'], project['id'])
        self.assertEqual(grid['rows'][0]['row_role'], 'unknown')
        self.assertEqual(grid['rows'][0]['identity']['tech'], '技术员甲')
        self.assertEqual(grid['rows'][0]['nodes']['split'], grid['rows'][0]['nodes']['technical'])
        self.assertEqual(self.request('/api/schedule-reference/' + result['source']['id'] + '/download', raw=True), (200, content))
        self.assertEqual(self.request('/api/schedule-reference/unknown/download')[0], 404)
        self.assertEqual(self.request('/api/schedule-reference?sheet=' + quote('不存在'))[0], 404)

    def test_duplicates_concurrent_import_and_filename_versions(self):
        content = xlsx([('排程会议 0813', worksheet({4: order()}))])
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.upload(content), range(2)))
        self.assertEqual(sorted(r['duplicate'] for r in results), [False, True])
        second = self.upload(xlsx([('排程会议 0813', worksheet({4: order(备注='更新')}))]))
        self.assertEqual(second['source']['snapshot_version'], 2)
        self.assertEqual(len(self.grid()['sources']), 2)
        self.assertEqual(self.stat('wood')['n'], 1)

    def test_header_semantics_dimensions_photography_and_financial_ignored(self):
        self.upload(xlsx([('排程会议 0813', worksheet({4: order(方数=('serial', 12.26), 拍摄='2026-08-10', 工厂价=123456)}, bad_dimension=True))]))
        grid = self.grid()
        self.assertEqual(len(grid['rows']), 1)
        self.assertEqual(grid['rows'][0]['cells']['volume']['value'], 12.26)
        self.assertIsNone(grid['rows'][0]['cells']['volume']['date'])
        self.assertEqual(grid['rows'][0]['nodes']['photography']['date'], '2026-08-10')
        self.assertNotIn('工厂价', str(grid['columns']))
        self.assertNotIn('123456', str(grid['rows']))

    def test_two_original_rows_not_cross_joined_and_category_merges_do_not_group_orders(self):
        rows = {4: order(木作='OK'), 5: {'木作': ('serial', serial('2026-08-08'))},
                6: order(序号=2, 单号='商务二部-002', 店铺信息='南区综合展示柜', 客户名称='')}
        merges = ['D4:D6', 'E4:E5', 'F4:F5', 'A4:A6']
        self.upload(xlsx([('排程会议 0813', worksheet(rows, merges))]))
        grid = self.grid()
        self.assertEqual([r['row_number'] for r in grid['rows']], [4, 5, 6])
        self.assertEqual(grid['rows'][0]['group_row_numbers'], [4, 5])
        self.assertEqual(grid['rows'][2]['group_row_numbers'], [6])
        self.assertIsNone(grid['rows'][1]['cells']['actual_split']['date'])
        self.assertEqual(self.stat('wood')['n'], 1)  # Only separate order on row 6.

    def test_original_year_typed_serial_partial_and_formula_not_today(self):
        self.upload(xlsx([('排程会议 0813', worksheet({4: order(下单日期=('date', '2025-08-01'), 拆单日期=('date', '2025-08-03'), 木作='8/6', 油漆=('formula', 'TODAY()'))}))]))
        row = self.grid()['rows'][0]
        self.assertEqual(row['cells']['order_date']['date'], '2025-08-01')
        self.assertEqual(row['nodes']['technical']['date_origin'], 'typed_date')
        # Mixed explicit 2025/2026 years means no single inferred year.
        self.assertIsNone(row['nodes']['wood']['date'])
        self.assertEqual(row['nodes']['wood']['month_day'], '08-06')
        self.assertEqual(row['nodes']['paint']['kind'], 'formula')
        self.assertIsNone(row['nodes']['paint']['date'])
        self.assertEqual(self.stat('wood')['n'], 0)

    def test_select_latest_trustworthy_tab_and_conflicting_filename_date_flag(self):
        self.upload(xlsx([('4.1', worksheet({4: order()})), ('排程会议 0813', worksheet({4: order()})),
                          ('6.22', worksheet({4: order()})), ('会议记录', '<worksheet xmlns="' + ref.NS['m'] + '"/>')], active=3))
        self.assertEqual(self.grid()['selected']['sheet'], '排程会议 0813')
        untrusted = self.upload(xlsx([('6.22', worksheet({4: order()}))]), '排程20260617.xlsx')
        grid = self.grid('?source_id=' + untrusted['source']['id'])
        self.assertFalse(grid['source']['date_trusted'])
        self.assertTrue(grid['warnings'])
        self.assertEqual(self.grid()['source']['filename'], '生产排程20260813.xlsx')

    def test_stats_dedup_latest_dates_quantiles_and_zero_negative_anomalies(self):
        self.upload(xlsx([('8.10', worksheet({4: order()})), ('8.13', worksheet({4: order(木作='2026-08-07'),
                       5: order(单号='2', 木作='2026-08-03'), 6: order(单号='3', 木作='2026-08-01')}))]))
        stat = self.stat('wood')
        self.assertEqual((stat['n'], stat['p25'], stat['p50'], stat['p75']), (2, 1, 2, 3))
        self.assertEqual(stat['n_same_day'], 1)
        self.assertEqual(stat['anomalies'], {'negative_interval': 1})
        self.assertEqual(stat['source_examples'][0]['sheet'], '8.13')

    def test_latest_stock_state_prevents_older_valid_sample_and_same_date_conflict(self):
        self.upload(xlsx([('8.10', worksheet({4: order()})), ('8.13', worksheet({4: order(出货时间='库存')}))]))
        self.assertEqual(self.stat('wood')['n'], 0)
        self.assertEqual(self.stat('wood')['anomalies'], {'stock_or_hold': 1})
        self.upload(xlsx([('8.13', worksheet({4: order(单号='2')}))]), '副本20260813.xlsx')
        self.upload(xlsx([('8.13', worksheet({4: order(单号='2', 木作='2026-08-07')}))]), '删减20260813.xlsx')
        self.assertEqual(self.stat('wood')['n'], 0)
        self.assertEqual(self.stat('wood')['anomalies']['same_date_snapshot_conflict'], 1)

    def test_unlabeled_rows_conflict_assembly_missing_branch_and_placeholder_not_zero(self):
        self.upload(xlsx([('8.13', worksheet({4: order(外协='/'), 5: order(木作='2026-08-07', 店铺信息='', 单号='', 客户名称='')}, ['D4:D5', 'E4:E5', 'F4:F5']))]))
        self.assertEqual(self.stat('wood')['n'], 0)
        self.assertEqual(self.stat('wood')['anomalies'], {'unlabeled_row_variants_conflict': 1})
        # Row 5 has a complete branch set and remains a valid original row.
        self.assertEqual(self.stat('assembly')['n'], 1)
        self.assertIsNone(self.grid()['rows'][0]['nodes']['outsourcing']['date'])

    def test_registered_original_symlink_is_rejected(self):
        source = self.upload()['source']
        folder = Path(self.temp.name) / 'schedule-references'
        path = folder / (source['sha256'] + '.xlsx')
        path.unlink()
        target = Path(self.temp.name) / 'outside.txt'
        target.write_text('not an original')
        path.symlink_to(target)
        self.assertEqual(self.request('/api/schedule-reference/' + source['id'] + '/download')[0], 404)

    def test_positive_negative_conflicts_not_resolved_by_filtering_out_negative(self):
        self.upload(xlsx([('8.13', worksheet({4: order(木作='2026-08-01'), 5: order(木作='2026-08-07', 店铺信息='', 单号='', 客户名称='')}, ['D4:D5', 'E4:E5', 'F4:F5']))]))
        self.assertEqual(self.stat('wood')['n'], 0)
        self.assertEqual(self.stat('wood')['anomalies'], {'unlabeled_row_variants_conflict': 1})
        self.upload(xlsx([('8.13', worksheet({4: order(单号='2', 木作='2026-08-01')}))]), '副本20260813.xlsx')
        self.upload(xlsx([('8.13', worksheet({4: order(单号='2', 木作='2026-08-07')}))]), '删减20260813.xlsx')
        self.assertEqual(self.stat('wood')['n'], 0)
        self.assertEqual(self.stat('wood')['anomalies']['same_date_snapshot_conflict'], 1)

    def test_explicit_revisions_deduplicate_but_g_suffix_alone_does_not(self):
        self.upload(xlsx([('8.10', worksheet({4: order(单号='商务二部-100'), 5: order(单号='商务二部-200')})),
                          ('8.13', worksheet({4: order(单号='商务二部-100G1', 店铺信息='北区综合展示柜-改01', 木作='2026-08-07'),
                                             5: order(单号='商务二部-200G1', 店铺信息='独立分批柜')}))]))
        stat = self.stat('wood')
        self.assertEqual(stat['n'], 3)
        self.assertEqual(stat['revision_groups_merged'], 1)
        self.assertEqual(sum(s['order_no'] == '商务二部-100' for s in stat['source_examples']), 0)

    def test_historical_fallback_is_explicit_and_same_day_is_not_zero_labor(self):
        self.upload(xlsx([('8.10', worksheet({4: order(木作='2026-08-03')})), ('8.13', worksheet({4: order(木作='OK')}))]))
        stat = self.stat('wood')
        self.assertEqual((stat['n'], stat['n_same_day'], stat['p50']), (1, 1, 0))
        self.assertEqual(stat['historical_fallback_count'], 1)
        self.assertTrue(stat['source_examples'][0]['is_historical_fallback'])
        self.assertEqual(stat['latest_snapshot_issues'], {'missing_dates': 1})
        self.assertNotIn('photography', {s['node_id'] for s in self.grid()['stats']})

    def test_parser_upgrade_rebuilds_cache_without_new_snapshot_or_business_change(self):
        content = xlsx([('8.13', worksheet({4: order()}))])
        source = self.upload(content)['source']
        with self.store.connect() as con:
            old = self.store.get(con, ref.KIND, source['id'])
            old['parser_version'] = 0
            old['stat_candidates'] = []
            self.store.put(con, ref.KIND, old)
        before = self.state()
        result = self.upload(content)
        self.assertTrue(result['duplicate'])
        self.assertTrue(result['reparsed'])
        self.assertEqual(result['source']['snapshot_version'], 1)
        self.assertEqual(self.stat('wood')['n'], 1)
        self.assertEqual(self.state(), before)


if __name__ == '__main__':
    unittest.main()
