"""Exact display-pixel keys, without source deletion or fuzzy image matching."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import drawing_media as media
try:
    from PIL import Image, PngImagePlugin
except ImportError:
    Image = None


@unittest.skipUnless(Image, 'Pillow is required for exact pixel hashes')
class MediaDedupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / 'drawing-previews/assets'
        self.assets.mkdir(parents=True)
        self.uploads = self.root / 'uploads'
        self.uploads.mkdir()
        media._pixel_hash_cached.cache_clear()

    def image(self, name, image=None, **options):
        path = self.assets / name
        (image or Image.new('RGB', (8, 6), 'teal')).save(path, **options)
        return path

    def entry(self, path, **extra):
        return {'id': path.stem, 'url': '/api/drawing-media/assets/' + path.name, **extra}

    def manifest(self, project):
        path = self.root / 'drawing-previews/manifest.json'
        path.write_text(json.dumps({'projects': {'a': project}}))
        return path

    def test_metadata_and_lossless_container_changes_have_same_key(self):
        original = self.image('a' * 64 + '.png')
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('source', '不同的来源文件')
        duplicate = self.image('b' * 64 + '.png', pnginfo=metadata)
        webp = self.image('c' * 64 + '.webp', lossless=True)
        self.assertNotEqual(original.read_bytes(), duplicate.read_bytes())
        self.assertEqual(media.content_hash(original), media.content_hash(duplicate))
        self.assertEqual(media.content_hash(original), media.content_hash(webp))
        self.assertEqual(len(media.content_hash(original)), 64)

    def test_exif_orientation_is_normalized(self):
        image = Image.new('RGB', (2, 3))
        image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (250, 120, 0), (0, 180, 170), (90, 20, 130)])
        original = self.image('a' * 64 + '.png', image)
        stored = image.transpose(Image.Transpose.ROTATE_90)
        exif = Image.Exif()
        exif[274] = 6
        rotated = self.image('b' * 64 + '.png', stored, exif=exif)
        self.assertEqual(media.content_hash(original), media.content_hash(rotated))

    def test_one_pixel_alpha_or_dimensions_change_does_not_merge(self):
        image = Image.new('RGBA', (8, 6), (1, 2, 3, 255))
        original = self.image('a' * 64 + '.png', image)
        changed = image.copy()
        changed.putpixel((0, 0), (1, 2, 4, 255))
        pixel = self.image('b' * 64 + '.png', changed)
        changed = image.copy()
        changed.putpixel((0, 0), (1, 2, 3, 254))
        alpha = self.image('c' * 64 + '.png', changed)
        size = self.image('d' * 64 + '.png', Image.new('RGBA', (6, 8), (1, 2, 3, 255)))
        self.assertEqual(len({media.content_hash(p) for p in (original, pixel, alpha, size)}), 4)

    def test_cached_pixels_not_decoded_again_and_change_invalidates_key(self):
        path = self.image('a' * 64 + '.png')
        with patch.object(Image, 'open', wraps=Image.open) as opened:
            before = media.content_hash(path)
            self.assertEqual(media.content_hash(path), before)
            self.assertEqual(opened.call_count, 1)
            self.image(path.name, Image.new('RGB', (8, 6), 'red'))
            os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1000000))
            self.assertNotEqual(media.content_hash(path), before)
            self.assertEqual(opened.call_count, 2)

    def test_project_media_preserves_all_evidence_and_never_mutates_manifest(self):
        path = self.image('a' * 64 + '.png')
        first = self.entry(path, sheet='Sheet1', cell='C8', title='原柜')
        second = self.entry(path, sheet='Sheet1', cell='C28', title='补单柜')
        source = self.manifest({'parts': {'item': [first, second]}, 'renders': [first, second], 'sources': [first]})
        before = source.read_bytes()
        result = media.project_media(self.root, 'a')
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(len(result['parts']['item']), 2)
        self.assertEqual([e['cell'] for e in result['parts']['item']], ['C8', 'C28'])
        self.assertEqual(len({e['content_hash'] for e in result['parts']['item']}), 1)
        self.assertEqual(result['sources'][0]['content_hash'], result['renders'][0]['content_hash'])

    def test_uploaded_and_cached_same_pixels_get_same_key_without_cross_project_leak(self):
        path = self.image('a' * 64 + '.png')
        upload = self.uploads / 'doc_a.source'
        upload.write_bytes(path.read_bytes())
        self.manifest({'parts': {}, 'renders': [self.entry(path)]})
        doc = {'id': 'doc_a', 'project_id': 'a', 'purpose': 'render', 'filename': '效果.png', 'storage_name': upload.name, 'image': {'width': 8, 'height': 6}, 'created_at': '2026-01-01'}
        foreign = {**doc, 'id': 'doc_foreign', 'project_id': 'b'}
        result = media.project_media(self.root, 'a', [doc, foreign])
        self.assertEqual(len(result['renders']), 2)
        self.assertEqual(result['renders'][0]['content_hash'], result['renders'][1]['content_hash'])
        self.assertEqual(result['renders'][0]['document_id'], 'doc_a')
        self.assertNotIn('doc_foreign', json.dumps(result))

    def test_invalid_remote_or_unregistered_paths_do_not_receive_forged_hash(self):
        self.manifest({'parts': {}, 'renders': [
            {'id': 'missing', 'url': '/api/drawing-media/assets/' + 'a' * 64 + '.png', 'content_hash': 'forged'},
            {'id': 'remote', 'url': 'https://example.com/asset.png'},
            {'id': 'escape', 'url': '/api/drawing-media/assets/../../outside.png'},
            {'id': 'foreign', 'url': '/api/documents/not-registered/image'},
        ]})
        for entry in media.project_media(self.root, 'a')['renders']:
            self.assertNotIn('content_hash', entry)

    def test_corrupt_and_animated_images_stay_separate(self):
        corrupt = self.assets / ('a' * 64 + '.png')
        corrupt.write_bytes(b'not an image')
        animation = self.assets / ('b' * 64 + '.png')
        Image.new('RGB', (2, 2), 'red').save(animation, save_all=True, append_images=[Image.new('RGB', (2, 2), 'blue')], duration=100)
        self.assertIsNone(media.content_hash(corrupt))
        self.assertIsNone(media.content_hash(animation))

    def test_uploaded_path_traversal_and_symlink_escape_are_not_read(self):
        path = self.image('a' * 64 + '.png')
        symlink = self.uploads / 'outside.source'
        symlink.symlink_to(path)
        for name in [str(path), '../drawing-previews/assets/' + path.name, symlink.name]:
            doc = {'id': 'bad', 'project_id': 'a', 'purpose': 'render', 'filename': '效果.png', 'storage_name': name, 'image': {'width': 8, 'height': 6}}
            self.assertNotIn('content_hash', media.project_media(self.root, 'a', [doc])['renders'][0])


if __name__ == '__main__':
    unittest.main()
