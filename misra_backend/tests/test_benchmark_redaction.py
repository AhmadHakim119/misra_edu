"""Synthetic pixels/PDF objects only; never load actual student papers in tests."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image,ImageDraw
from pypdf import PdfReader,PdfWriter

from services.benchmark_redaction import append_lossless_page,redact_red_ink,redact_reviewed_red_regions
from redact_benchmark import create_pilot


class RedactionDraftTests(unittest.TestCase):
    def test_scoped_mask_protects_red_diagrams_and_outside_regions(self):
        im=Image.new('RGB',(200,300),'white');draw=ImageDraw.Draw(im)
        draw.line((20,30,50,30),fill='red',width=3)
        draw.line((120,100,150,100),fill='red',width=3)
        draw.line((20,240,60,240),fill='red',width=3)
        clean,mask,report=redact_reviewed_red_regions(im,[(0,0,1,.6)],protected_regions=[(.55,.25,.3,.2)])
        self.assertEqual(clean.getpixel((30,30)),(255,255,255))
        self.assertEqual(clean.getpixel((130,100)),im.getpixel((130,100)))
        self.assertEqual(clean.getpixel((30,240)),im.getpixel((30,240)))
        self.assertTrue(report['protected_pixel_preservation_verified'])
        self.assertTrue(report['unmasked_pixel_preservation_verified'])
        self.assertFalse(report['ready_for_inference'])

    def test_scoped_overlap_is_flagged_and_invalid_boxes_rejected(self):
        im=Image.new('RGB',(200,300),'white');draw=ImageDraw.Draw(im)
        draw.line((80,40,80,100),fill='blue',width=3);draw.line((60,60,100,80),fill='red',width=3)
        _,_,report=redact_reviewed_red_regions(im,[(0,0,1,1)])
        self.assertTrue(report['overlap_review_required'])
        for box in [(0,0,2,1),(0,0,float('nan'),1),(0,0,True,1)]:
            with self.subTest(box=box),self.assertRaises(ValueError):redact_reviewed_red_regions(im,[box])

    def test_pilot_requires_checked_cover_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'synthetic.pdf';source.write_bytes(b'synthetic fixture')
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            inventory={'documents':[{'document_id':'doc','original_path':'synthetic.pdf'}],
                'papers':[{'paper_id':year+'-paper','document_id':'doc','original_sha256':digest,
                    'first_page_1based':1,'last_page_1based':11} for year in ('F23','F24','F25')]}
            index=root/'inventory.json';index.write_text(json.dumps(inventory))
            cover=root/'covers.json';cover.write_text('{"covers":[]}')
            output=root/'private'/'pilot'
            with self.assertRaisesRegex(ValueError,'checked cover'):
                create_pilot(root,index,output,cover)
            self.assertEqual(source.read_bytes(),b'synthetic fixture')
            self.assertEqual(list(output.iterdir()),[])
            (output/'review.png').write_bytes(b'preserve this prior review')
            with self.assertRaisesRegex(ValueError,'must be empty'):
                create_pilot(root,index,output,cover)
            self.assertEqual((output/'review.png').read_bytes(),b'preserve this prior review')
            inventory['documents'][0]['original_path']='../outside.pdf'
            index.write_text(json.dumps(inventory))
            with self.assertRaisesRegex(ValueError,'inside the evaluation workspace'):
                create_pilot(root,index,root/'private'/'other',cover)

    def test_red_mask_leaves_every_unmasked_black_blue_and_background_pixel_exact(self):
        image=Image.new('RGB',(200,300),'white');draw=ImageDraw.Draw(image)
        draw.line((20,40,160,40),fill='black',width=3)
        draw.line((20,80,160,80),fill='blue',width=3)
        draw.line((100,130,120,150),fill=(190,50,60),width=2)
        original=np.asarray(image).copy()
        cleaned,mask,report=redact_red_ink(image)
        selected=np.asarray(mask)>0;pixels=np.asarray(cleaned)
        self.assertTrue(np.array_equal(pixels[~selected],original[~selected]))
        self.assertTrue((pixels[selected]==255).all());self.assertTrue(report['pixel_preservation_verified'])
        self.assertTrue(np.array_equal(np.asarray(image),original))
        self.assertFalse(report['overlap_review_required'])

    def test_red_crossing_black_work_is_flagged_without_reconstruction(self):
        image=Image.new('RGB',(200,300),'white');draw=ImageDraw.Draw(image)
        draw.line((80,40,80,100),fill='black',width=3);draw.line((60,60,100,80),fill='red',width=2)
        _,_,report=redact_red_ink(image)
        self.assertTrue(report['overlap_review_required']);self.assertGreater(report['nearby_dark_pixel_count'],0)

    def test_large_red_regions_are_rejected_and_not_whitened_blindly(self):
        with self.assertRaisesRegex(ValueError,'Too much red'):redact_red_ink(Image.new('RGB',(20,20),'red'))

    def test_lossless_pdf_has_only_clean_pixels_and_preserves_page_geometry(self):
        image=Image.new('RGB',(40,60),'white');image.putpixel((8,9),(0,0,200))
        writer=PdfWriter();append_lossless_page(writer,image,595,842)
        buffer=BytesIO();writer.write(buffer);buffer.seek(0);reader=PdfReader(buffer)
        self.assertEqual(len(reader.pages),1)
        page=reader.pages[0]
        self.assertEqual((float(page.mediabox.width),float(page.mediabox.height)),(595,842))
        self.assertFalse(page.get('/Annots'));self.assertEqual(page.extract_text(),'')
        obj=page['/Resources']['/XObject']['/Im0'].get_object()
        self.assertEqual(obj.get_data(),image.tobytes())
        self.assertEqual(obj['/Filter'],'/FlateDecode')


if __name__=='__main__':unittest.main()
