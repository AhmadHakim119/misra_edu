import hashlib
import unittest
from unittest.mock import patch

from services.grading_package_service import reference_images


class ReferenceRenderingTests(unittest.TestCase):
    def key(self):
        return {'id': 'key', 'document_refs': [{'path': 'synthetic.pdf',
            'job_id': 'processing-job-secret', 'page_indices': [2], 'media_type': 'application/pdf',
            'sha256': hashlib.sha256(b'approved bytes').hexdigest()}]}

    def test_render_uses_the_verified_bytes_and_selected_page(self):
        with patch('pathlib.Path.read_bytes', return_value=b'approved bytes'), \
             patch('pdf2image.convert_from_bytes', return_value=['synthetic image']) as render:
            content = reference_images(self.key())
        render.assert_called_once_with(b'approved bytes', first_page=3, last_page=3)
        self.assertIn('Not student work', content[0])
        self.assertNotIn('key:', content[0])
        self.assertNotIn('processing-job-secret', content[0])
        self.assertEqual(content[1], 'synthetic image')

    def test_changed_bytes_never_reach_renderer(self):
        with patch('pathlib.Path.read_bytes', return_value=b'changed bytes'), \
             patch('pdf2image.convert_from_bytes') as render:
            with self.assertRaisesRegex(ValueError, 'has changed'):
                reference_images(self.key())
        render.assert_not_called()
