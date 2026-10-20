from pathlib import Path
import hashlib
import tempfile
import unittest

from services.ocr_review_packet import render_review_packet
from services.ocr_verification import compare_regions


class OCRReviewPacketTests(unittest.TestCase):
    def test_escapes_provider_content_and_embeds_only_matching_crops(self):
        # Synthetic PNG header is sufficient here; rendering/image validity belongs
        # to preparation. The artifact must verify the exact reviewed byte hash.
        data=b'\x89PNG\r\n\x1a\nsynthetic'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'crop.png';path.write_bytes(data)
            region={'region_id':'R1','page_index':0,'page_sha256':'a'*64,
                    'crop_sha256':hashlib.sha256(data).hexdigest(),
                    'bounding_box':{'x':0,'y':0,'width':1,'height':1}}
            reading={'region_id':'R1','crop_sha256':region['crop_sha256'],'reader_id':'reader',
                     'reader_family':'family','status':'read','text':'<script>alert(1)</script>',
                     'uncertainties':[],'blind_to_other_readings_and_key':True}
            comparisons=compare_regions([region],[reading])
            html=render_review_packet(comparisons,{'R1':'crop.png'},root=folder)
            self.assertNotIn('<script>',html)
            self.assertIn('&lt;script&gt;',html)
            self.assertIn("default-src 'none'",html)
            self.assertIn('data:image/png;base64,',html)
            self.assertIn('1 of 1 regions need review',html)
            reply={'region_id':'R1','component_id':'sign','evidence_digest':comparisons[0]['evidence_digest'],
                   'actor_role':'project_user','confirmed_component':'<confirmed +>'}
            annotated=render_review_packet(comparisons,{'R1':'crop.png'},root=folder,component_reviews=[reply])
            self.assertIn('&lt;confirmed +&gt;',annotated)
            self.assertNotIn('<confirmed +>',annotated)
            self.assertIn('partial review only',annotated)
            self.assertIn('1 of 1 regions need review',annotated)
            with self.assertRaises(ValueError):
                render_review_packet(comparisons,{'R1':'crop.png'},root=folder,
                                     component_reviews=[{**reply,'evidence_digest':'f'*64}])
            with self.assertRaises(ValueError):
                render_review_packet(comparisons,{'R1':'../outside.png'},root=folder)
            path.write_bytes(data+b'changed')
            with self.assertRaises(ValueError):
                render_review_packet(comparisons,{'R1':'crop.png'},root=folder)


if __name__=='__main__':unittest.main()
