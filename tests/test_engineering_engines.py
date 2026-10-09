"""Real-engine integration tests; run with .venv-engineering/bin/python.

All files are synthetic and remain under TemporaryDirectory. No production data,
hardware, network inference, or server restart is used by these tests.
"""
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import time
import unittest
import subprocess
import sys

from engineering_engines import EngineeringJobs, EngineeringError, DEFAULT_MODELS, _sandbox_profile, _environment


def raster_fixture(directory):
    from PIL import Image, ImageDraw, ImageFont
    fonts = [Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf'),
             Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]
    fontfile = next((p for p in fonts if p.exists()), None)
    if not fontfile:
        raise RuntimeError('Install a Chinese Unicode font for the raster OCR fixture')
    font = ImageFont.truetype(str(fontfile), 58)
    image = Image.new('RGB', (1500, 660), 'white')
    draw = ImageDraw.Draw(image)
    for n, text in enumerate(['柜体侧板 18mm', '材料 多层板', '数量 2 件', '600 x 450', 'KANPACE TEST A-01']):
        draw.text((80, 35 + n * 115), text, fill='#161616', font=font)
    png = directory / '扫描施工图.png'
    image.save(png)
    pdf = directory / '扫描施工图.pdf'
    # Raster-only PDF: OCR cannot accidentally succeed through a text layer.
    image.save(pdf, 'PDF', resolution=96, save_all=True, append_images=[image])
    image.close()
    return png, pdf


def step_fixture(directory, unit='MM', instance_name=None,
                 dimensions=(10, 20, 30), shape_rotation_degrees=0):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Controller
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.TopLoc import TopLoc_Location
    from OCP.gp import gp_Trsf, gp_Vec, gp_Ax1, gp_Dir, gp_Pnt
    from OCP.TDataStd import TDataStd_Name
    doc = TDocStd_Document(TCollection_ExtendedString('fixture'))
    XCAFDoc_DocumentTool.SetLengthUnit_s(doc, 0.001)
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    assembly = tool.NewShape()
    TDataStd_Name.Set_s(assembly, TCollection_ExtendedString('Synthetic assembly'))
    shape = BRepPrimAPI_MakeBox(*dimensions).Shape()
    if shape_rotation_degrees:
        rotation = gp_Trsf()
        rotation.SetRotation(gp_Ax1(gp_Pnt(), gp_Dir(0, 0, 1)),
                             math.radians(shape_rotation_degrees))
        shape = shape.Moved(TopLoc_Location(rotation))
    part = tool.AddShape(shape, False)
    TDataStd_Name.Set_s(part, TCollection_ExtendedString('Panel-A'))
    tool.AddComponent(assembly, part, TopLoc_Location())
    tr = gp_Trsf()
    tr.SetTranslation(gp_Vec(100, 0, 0))
    second = tool.AddComponent(assembly, part, TopLoc_Location(tr))
    if instance_name:
        TDataStd_Name.Set_s(second, TCollection_ExtendedString(instance_name, True))
    tool.UpdateAssemblies()
    # Writer snapshots conversion settings during construction.
    STEPControl_Controller.Init_s()
    assert Interface_Static.SetCVal_s('write.step.unit', unit)
    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)
    assert writer.Transfer(doc, STEPControl_AsIs)
    path = directory / ('two-instances-' + unit + '.step')
    assert writer.Write(str(path)) == IFSelect_RetDone
    Interface_Static.SetCVal_s('write.step.unit', 'MM')
    return path


class EngineeringJobSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='kanpace-engineering-qa-')
        self.base = Path(self.tmp.name)
        self.a = self.base / 'factory-a'
        self.b = self.base / 'factory-b'
        self.a.mkdir()
        self.b.mkdir()
        self.jobs = EngineeringJobs(self.a)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cross_factory_source_rejected(self):
        path = self.b / 'private.png'
        path.write_bytes(b'not a real image')
        with self.assertRaises(EngineeringError) as caught:
            self.jobs.submit('ocr', path, 'private.png')
        self.assertEqual(caught.exception.code, 'outside_factory')

    def test_symlink_rejected(self):
        source = self.a / 'real.png'
        source.write_bytes(b'fixture')
        link = self.a / 'link.png'
        link.symlink_to(source)
        with self.assertRaises(EngineeringError) as caught:
            self.jobs.submit('ocr', link, 'link.png')
        self.assertEqual(caught.exception.code, 'symlink_rejected')

    def test_other_factory_job_inaccessible(self):
        with self.assertRaises(EngineeringError) as caught:
            EngineeringJobs(self.b).get('eng_' + 'a' * 32)
        self.assertEqual(caught.exception.code, 'not_found')
        with self.assertRaises(EngineeringError):
            self.jobs.get('../factory-b/private')

    def test_list_uses_small_completed_job_summaries_without_loading_results(self):
        identifier = 'eng_' + 'e' * 32
        directory = self.jobs.directory / identifier
        directory.mkdir()
        (directory / 'job.json').write_text(json.dumps({
            'id': identifier, 'kind': 'ocr', 'status': 'completed',
            'created_at': '2026-09-23T00:00:00Z', 'metadata': {'project_id': 'prj_test'},
            'source': {'sha256': 'a' * 64}}))
        (directory / 'result.json').write_text('{invalid large-result placeholder')
        summaries = self.jobs.list()
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]['id'], identifier)
        self.assertNotIn('result', summaries[0])

    def test_list_still_repairs_interrupted_active_worker_state(self):
        identifier = 'eng_' + 'f' * 32
        directory = self.jobs.directory / identifier
        directory.mkdir()
        (directory / 'job.json').write_text(json.dumps({
            'id': identifier, 'kind': 'ocr', 'status': 'running',
            'created_at': '2026-09-23T00:00:00Z', 'metadata': {'project_id': 'prj_test'}}))
        (directory / 'process.json').write_text(json.dumps({'pid': 999999, 'started': 0}))
        summaries = self.jobs.list()
        self.assertEqual(summaries[0]['status'], 'failed')
        self.assertEqual(summaries[0]['error']['code'], 'worker_interrupted')
        self.assertEqual(json.loads((directory / 'job.json').read_text())['status'], 'failed')

    def test_native_solidworks_needs_bridge(self):
        source = self.a / 'part.source'
        source.write_bytes(b'fixture')
        with self.assertRaises(EngineeringError) as caught:
            self.jobs.submit('cad', source, 'part.sldprt')
        self.assertEqual(caught.exception.code, 'unsupported_format')

    def test_invalid_pages_rejected(self):
        source = self.a / 'a.pdf'
        source.write_bytes(b'fixture')
        with self.assertRaises(EngineeringError):
            self.jobs.submit('ocr', source, 'a.pdf', {'pages': [1, 1]})

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS process sandbox')
    def test_os_worker_cannot_read_other_factory_or_connect(self):
        if not self.jobs.python.is_file():
            self.skipTest('optional engineering Python runtime is not installed in this source-only checkout')
        private = self.b / 'private.txt'
        private.write_text('synthetic confidential data')
        job = self.jobs.directory / 'eng-fixture-sandbox'
        job.mkdir()
        code = '''import pathlib,socket,sys
try:
    pathlib.Path(sys.argv[1]).read_text()
    raise AssertionError('Cross-factory read succeeded')
except PermissionError: pass
try:
    pathlib.Path(sys.argv[1]).write_text('overwrite')
    raise AssertionError('Cross-factory write succeeded')
except PermissionError: pass
try:
    connection=socket.socket()
    connection.connect(('127.0.0.1', 1))
    raise AssertionError('Network allowed')
except PermissionError: pass
print('isolated')
'''
        run = subprocess.run(['/usr/bin/sandbox-exec', '-p', _sandbox_profile(self.jobs.python, self.jobs.models, job),
                              str(self.jobs.python), '-c', code, str(private.resolve())],
                             capture_output=True, text=True, cwd=job, env=_environment(job))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('isolated', run.stdout)
        self.assertEqual(private.read_text(), 'synthetic confidential data')


@unittest.skipUnless(importlib.util.find_spec('OCP'), 'Run with .venv-engineering/bin/python')
class RealEngineeringTests(unittest.TestCase):
    setUp = EngineeringJobSafetyTests.setUp
    tearDown = EngineeringJobSafetyTests.tearDown
    def finish(self, job, timeout=180):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.jobs.get(job['id'])
            if state['status'] in ('completed', 'failed'):
                if state['status'] == 'failed':
                    log = self.jobs.directory / job['id'] / 'worker.log'
                    self.fail(json.dumps(state, ensure_ascii=False) + '\n' + log.read_text(errors='replace')[-10000:])
                return state
            time.sleep(.3)
        self.fail('Native worker did not finish')

    def test_actual_step_two_instances_exact_geometry(self):
        path = step_fixture(self.a)
        state = self.finish(self.jobs.submit('cad', path, path.name))
        result = state['result']
        self.assertEqual(result['instance_count'], 2)
        self.assertEqual(result['unique_definition_count'], 1)
        self.assertAlmostEqual(result['totals']['volume_mm3'], 12000, places=4)
        self.assertAlmostEqual(result['totals']['surface_area_mm2'], 4400, places=4)
        self.assertEqual(result['output_length_unit'], 'mm')
        self.assertEqual([p['name'] for p in result['parts']], ['Panel-A', 'Panel-A'])
        self.assertEqual(sorted(round(p['bbox_mm'][0], 4) for p in result['parts']), [0, 100])
        for part in result['parts']:
            self.assertTrue(part['valid'])
            for actual, expected in zip(part['bbox_extents_mm'], [10, 20, 30]):
                self.assertAlmostEqual(actual, expected, places=4)
            for actual, expected in zip(part['oriented_bbox_extents_mm'], [10, 20, 30]):
                self.assertAlmostEqual(actual, expected, places=4)
            self.assertIsNone(part['geometry_form_candidate'])
            self.assertFalse(part['is_manufacturing_dimension'])
            self.assertIsNone(part['weight'])

    def test_actual_step_preserves_meaningful_instance_name(self):
        path = step_fixture(self.a, instance_name='右侧板')
        result = self.finish(self.jobs.submit('cad', path, path.name))['result']
        self.assertEqual(result['unique_definition_count'], 1)
        self.assertEqual([p['name'] for p in result['parts']], ['Panel-A', '右侧板'])

    def test_actual_step_rotated_plate_has_review_only_oriented_box(self):
        path = step_fixture(self.a, dimensions=(1200, 550, 18), shape_rotation_degrees=37)
        result = self.finish(self.jobs.submit('cad', path, path.name))['result']
        self.assertEqual(result['instance_count'], 2)
        for part in result['parts']:
            self.assertGreater(part['bbox_extents_mm'][0], 1200)
            self.assertGreater(part['bbox_extents_mm'][1], 1100)
            for actual, expected in zip(part['oriented_bbox_extents_mm'], (18, 550, 1200)):
                self.assertAlmostEqual(actual, expected, places=3)
            self.assertEqual(part['geometry_form_candidate']['kind'], 'thin_plate_shape')
            self.assertTrue(part['geometry_form_candidate']['review_required'])
            self.assertFalse(part['is_manufacturing_dimension'])
            self.assertIsNone(part['material'])

    def test_optional_oriented_box_failure_returns_none(self):
        from engineering_engines import _cad_oriented_form_hint
        self.assertIsNone(_cad_oriented_form_hint(object(), True, 1))
        self.assertIsNone(_cad_oriented_form_hint(object(), False, 1))
        self.assertIsNone(_cad_oriented_form_hint(object(), True, 2))

    def test_actual_step_inch_unit_conversion(self):
        path = step_fixture(self.a, 'INCH')
        result = self.finish(self.jobs.submit('cad', path, path.name))['result']
        self.assertTrue(any('inch' in unit.lower() for unit in result['source_length_units']))
        # This fixture contains coordinates 10 x 20 x 30 with INCH declared in
        # STEP, hence volume 12000 cubic inches across its two instances.
        self.assertAlmostEqual(result['totals']['volume_mm3'], 12000 * 25.4**3, places=4)
        for part in result['parts']:
            for actual, inches in zip(part['bbox_extents_mm'], (10, 20, 30)):
                self.assertAlmostEqual(actual, inches * 25.4, places=4)
            for actual, inches in zip(part['oriented_bbox_extents_mm'], (10, 20, 30)):
                self.assertAlmostEqual(actual, inches * 25.4, places=4)

    def test_invalid_step_explicit_failure(self):
        source = self.a / 'invalid.step'
        source.write_bytes(b'not a STEP file')
        job = self.jobs.submit('cad', source, source.name)
        for _ in range(100):
            result = self.jobs.get(job['id'])
            if result['status'] == 'failed':
                break
            time.sleep(.1)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error']['code'], 'invalid_step')
        self.assertNotIn(str(self.a), json.dumps(result))

    @unittest.skipUnless((DEFAULT_MODELS / 'manifest.json').exists(), 'Pre-download public OCR models first')
    def test_actual_raster_pdf_ocr_selected_page(self):
        png, pdf = raster_fixture(self.a)
        # Read same bytes from archive .source as production does.
        source = self.a / 'doc_fixture.source'
        source.write_bytes(pdf.read_bytes())
        result = self.finish(self.jobs.submit('ocr', source, pdf.name, {'pages': [2], 'dpi': 144}), 600)['result']
        self.assertEqual(result['page_count'], 2)
        self.assertEqual(result['processed_pages'], [2])
        regions = result['pages'][0]['regions']
        text = '\n'.join(r['text'] for r in regions)
        self.assertIn('柜体', text)
        self.assertIn('600', text)
        self.assertIn('450', text)
        self.assertGreater(len(regions), 3)
        for region in regions:
            self.assertEqual(region['page'], 2)
            self.assertTrue(0 <= region['score'] <= 1)
            self.assertEqual(len(region['bbox']), 4)
            self.assertFalse(region['is_manufacturing_dimension'])
        self.assertTrue(result['local_only'])

    @unittest.skipUnless((DEFAULT_MODELS / 'manifest.json').exists(), 'Pre-download public OCR models first')
    def test_actual_webp_preserves_original_source_page(self):
        from PIL import Image
        png, _ = raster_fixture(self.a)
        webp = self.a / 'cached-original-page.webp'
        with Image.open(png) as image:
            image.save(webp, 'WEBP', lossless=True)
        source_id = 'project-source-verified-fixture'
        job = self.jobs.submit('ocr', webp, webp.name, metadata={
            'project_id': 'qa-project', 'source_id': source_id,
            'source_page': 14, 'source_label': '施工图第 14 页'})
        state = self.finish(job, 300)
        self.assertEqual(state['metadata']['source_id'], source_id)
        page = state['result']['pages'][0]
        self.assertEqual(page['page'], 1)
        self.assertEqual(page['source_page'], 14)
        self.assertTrue((self.jobs.directory / job['id'] / page['preview_filename']).is_file())
        self.assertTrue(all(r['source_page'] == 14 for r in page['regions']))
        self.assertIn('柜体', '\n'.join(r['text'] for r in page['regions']))


if __name__ == '__main__':
    unittest.main()
