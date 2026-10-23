import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from services.source_location_service import locate_text, parse_page_words, read_page_words


class ScanDisplayGeometryTests(unittest.TestCase):
    def location(self, **box):
        return {'status':'located','method':'vision_grid','bounding_box':box}

    def ink_page(self, size, lines):
        from PIL import Image, ImageDraw
        image=Image.new('RGB',size,'white');draw=ImageDraw.Draw(image)
        for y in lines:
            # Disjoint strokes mimic text, rather than one solid page rule.
            for x in range(round(size[0]*.2),round(size[0]*.7),30):
                draw.line((x,round(y*size[1]),x+6,round((y+.035)*size[1])),fill='black',width=3)
        return image

    def test_clipped_bands_expand_across_page_sizes_without_mutating_saved_geometry(self):
        from copy import deepcopy
        from services.source_location_service import refine_scan_location
        for size in ((600,800),(1200,900),(1200,1600)):
            with self.subTest(size=size):
                original=self.location(x=.1,y=.61,width=.7,height=.01);snapshot=deepcopy(original)
                image=self.ink_page(size,[.6])
                result=refine_scan_location(image,original)
                self.assertEqual(result['status'],'located')
                box=result['bounding_box']
                self.assertLess(box['y'],.6)
                self.assertGreater(box['y']+box['height'],.635)
                self.assertEqual(box['x'],.1);self.assertAlmostEqual(box['width'],.7)
                self.assertEqual(original,snapshot)
                self.assertEqual(result['reported_bounding_box'],snapshot['bounding_box'])

    def test_blank_seed_does_not_move_to_a_nearby_different_answer(self):
        from services.source_location_service import refine_scan_location
        image=self.ink_page((800,1000),[.64])
        result=refine_scan_location(image,self.location(x=.1,y=.6,width=.7,height=.015))
        self.assertEqual(result['status'],'unverified');self.assertNotIn('bounding_box',result)

    def test_rules_alone_do_not_become_answer_boxes(self):
        from PIL import Image,ImageDraw
        from services.source_location_service import refine_scan_location
        image=Image.new('RGB',(800,1000),'white');draw=ImageDraw.Draw(image)
        for y in range(570,660,20):draw.line((0,y,799,y),fill='black',width=2)
        result=refine_scan_location(image,self.location(x=.1,y=.6,width=.7,height=.02))
        self.assertEqual(result['status'],'unverified');self.assertNotIn('bounding_box',result)

    def test_multiline_regions_keep_all_intersecting_bands(self):
        from services.source_location_service import refine_scan_location
        image=self.ink_page((800,1000),[.58,.63])
        result=refine_scan_location(image,self.location(x=.1,y=.59,width=.7,height=.05))
        self.assertEqual(result['status'],'located')
        self.assertLess(result['bounding_box']['y'],.58)
        self.assertGreater(result['bounding_box']['y']+result['bounding_box']['height'],.665)

    def test_native_and_instructor_confirmed_locations_are_never_adjusted(self):
        from services.source_location_service import refine_scan_location
        from PIL import Image
        for method in ('native_pdf_text','instructor_confirmed_area'):
            value={**self.location(x=.2,y=.4,width=.5,height=.15),'method':method}
            self.assertEqual(refine_scan_location(Image.new('RGB',(100,100)),value),value)

    def test_invalid_or_search_edge_geometry_is_unavailable(self):
        from services.source_location_service import refine_scan_location
        image=self.ink_page((800,1000),[.56])
        for box in ({'x':.1,'y':.6,'width':.7,'height':.001},
                    {'x':.8,'y':.6,'width':.7,'height':.01}):
            result=refine_scan_location(image,self.location(**box))
            self.assertEqual(result['status'],'unverified');self.assertNotIn('bounding_box',result)


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
