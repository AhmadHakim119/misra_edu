import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from services.source_location_service import locate_text, parse_page_words, read_page_words


def words_xml(words):
    return ('<html><body><page width="600" height="800"><line>' +
            ''.join(f'<word xMin="{60 + i * 30}" yMin="200" xMax="{85 + i * 30}" yMax="212">{word}</word>'
                    for i, word in enumerate(words)) + '</line></page></body></html>').encode()


class SourceLocationTests(unittest.TestCase):
    def test_unique_complete_text_uses_word_geometry_not_ocr_estimate(self):
        words = parse_page_words(words_xml(['W', '=', '1.00', '×', '400', '=', '400', 'J.']))
        result = locate_text('W = 1.00 × 400 = 400 J.', words)
        self.assertEqual(result['method'], 'native_pdf_text')
        box = result['bounding_box']
        self.assertLess(box['y'], 200 / 800)
        self.assertGreater(box['y'] + box['height'], 212 / 800)

    def test_duplicate_text_is_ambiguous_not_arbitrarily_located(self):
        words = parse_page_words(words_xml(['400', 'J', '400', 'J']))
        self.assertEqual(locate_text('400 J', words)['reason'], 'ambiguous_text')

    def test_wrong_numbers_or_signs_never_match(self):
        words = parse_page_words(words_xml(['W', '=', '-', '400', 'J']))
        for text in ['W = 400 J', 'W = -40 J']:
            self.assertEqual(locate_text(text, words)['reason'], 'text_not_found')

    def test_mathematical_grouping_is_not_discarded(self):
        words = parse_page_words(words_xml(['W', '=', '(2', '+', '3)', '*', '4']))
        self.assertEqual(locate_text('W = 2 + 3 * 4', words)['reason'], 'text_not_found')

    def test_multiline_math_whitespace_and_unicode_operators(self):
        words = parse_page_words(words_xml(['W', '=', '2', '×', '3', '=', '6', 'J']))
        self.assertEqual(locate_text('W = 2 \\times 3\n= 6 J', words)['status'], 'located')

    def test_single_choice_does_not_claim_exact_location(self):
        words = parse_page_words(words_xml(['A', 'B', 'C']))
        self.assertEqual(locate_text('B', words)['reason'], 'insufficient_text')

    def test_corrupt_xml_invalid_geometry_and_entity_declarations(self):
        for xml in [b'broken', words_xml(['W']).replace(b'width="600"', b'width="nan"'),
                    words_xml(['W']).replace(b'xMax="85"', b'xMax="999"'),
                    b'<!ENTITY private SYSTEM "file:///private"><page/>']:
            self.assertIsNone(parse_page_words(xml))

    def test_missing_executable_and_timeouts_are_safe_fallbacks(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'synthetic.pdf'
            path.write_bytes(b'synthetic')
            with patch('services.source_location_service.shutil.which', return_value=None):
                self.assertIsNone(read_page_words(path, 0))
            with patch('services.source_location_service.shutil.which', return_value='pdftotext'), \
                 patch('services.source_location_service.subprocess.run', side_effect=subprocess.TimeoutExpired('pdftotext', 5)):
                self.assertIsNone(read_page_words(path, 0))

    def test_scanned_page_with_no_text_has_no_native_match(self):
        self.assertEqual(locate_text('W = 400 J', parse_page_words(words_xml([])))['reason'], 'text_not_found')

    @unittest.skipUnless(shutil.which('pdftotext'), 'Poppler pdftotext is not installed')
    def test_real_poppler_page_positions_including_rotation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'synthetic.pdf'
            writer = PdfWriter()
            for rotation in (0, 90):
                page = writer.add_blank_page(width=612, height=792)
                font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                         NameObject('/Subtype'): NameObject('/Type1'),
                                         NameObject('/BaseFont'): NameObject('/Helvetica')})
                page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
                content = DecodedStreamObject()
                content.set_data(b'BT /F1 12 Tf 60 600 Td (First case: W = 1.00 * 400 = 400 J.) Tj ET')
                page[NameObject('/Contents')] = writer._add_object(content)
                if rotation:
                    page.rotate(rotation)
            writer.write(path)
            for index in (0, 1):
                result = locate_text('First case: W = 1.00 * 400 = 400 J.', read_page_words(path, index))
                self.assertEqual(result['status'], 'located')
                box = result['bounding_box']
                self.assertGreater(box['height'], 0)
                self.assertLessEqual(box['x'] + box['width'], 1)
                self.assertLessEqual(box['y'] + box['height'], 1)
            normal = locate_text('First case: W = 1.00 * 400 = 400 J.', read_page_words(path, 0))['bounding_box']
            self.assertLess(normal['y'], (792 - 600) / 792)
            self.assertGreater(normal['y'] + normal['height'], (792 - 600) / 792)
