import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from cloud_ocr_experiment import parse_cloud, request_body
from local_ocr import file_hash
from ocr_experiment import redact_page, validate_packet


class ExperimentBoundaries(unittest.TestCase):
    def test_crop_preserves_blue_answer_removes_header_footer_and_red_marks(self):
        image=Image.new("RGB",(200,400),"white")
        image.putpixel((100,40),(0,0,180))
        image.putpixel((100,180),(0,0,180))
        image.putpixel((120,180),(220,0,0))
        image.putpixel((100,390),(0,0,0))
        out,meta=redact_page(image,1)
        x,y,_,_=meta["crop_xyxy"]
        self.assertEqual(out.getpixel((100-x,180-y)),(0,0,180))
        self.assertEqual(out.getpixel((120-x,180-y)),(255,255,255))
        self.assertGreater(y,40)
        self.assertLess(meta["crop_xyxy"][3],390)

    def test_unreviewed_or_tampered_images_cannot_be_uploaded(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/"redacted-v2").mkdir()
            path=root/"redacted-v2/page-01.png"
            Image.new("RGB",(20,20),"white").save(path)
            entry={"path":str(path),"sha256":file_hash(path),"privacy_review":"pending_visual_check"}
            with self.assertRaises(ValueError): validate_packet(root,entry)
            entry["privacy_review"]="checked_by_agent_against_full_page"
            self.assertEqual(validate_packet(root,entry),path.resolve())
            path.write_bytes(b"tampered")
            with self.assertRaises(ValueError): validate_packet(root,entry)

    def test_unredacted_original_cannot_be_uploaded(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/"original.png"
            Image.new("RGB",(20,20),"white").save(path)
            entry={"path":str(path),"sha256":file_hash(path),"privacy_review":"checked_by_agent_against_full_page"}
            with self.assertRaises(ValueError): validate_packet(root,entry)

    def test_cloud_request_has_no_key_answer_key_or_grade_prompt(self):
        body=request_body("google/gemini-2.5-flash",b"synthetic-image",["q1a","q1b","q1c"])
        self.assertEqual(body["provider"]["data_collection"],"deny")
        self.assertFalse(body["provider"]["allow_fallbacks"])
        self.assertNotIn("Authorization",json.dumps(body))
        self.assertEqual(body["model"],"google/gemini-2.5-flash")
        with self.assertRaises(ValueError): request_body("unapproved/model",b"x",["q1a"])

    def response(self):
        rows=[{"question_id":q,"text":"student work","selected_options":[],"cancelled_text":[],
               "legibility":"clear","needs_review":False} for q in ["q1a","q1b","q1c"]]
        return {"choices":[{"finish_reason":"stop","message":{"content":json.dumps({"answers":rows,"notes":[]})}}]}

    def test_complete_exact_question_set_is_required(self):
        good=self.response();parse_cloud(good,["q1a","q1b","q1c"])
        with self.assertRaises(ValueError): parse_cloud(good,["q3a","q3b","q3c"])
        good["choices"][0]["finish_reason"]="length"
        with self.assertRaises(ValueError): parse_cloud(good,["q1a","q1b","q1c"])

    def test_uncertain_transcription_cannot_claim_clear_review_state(self):
        good=self.response();content=json.loads(good["choices"][0]["message"]["content"])
        content["answers"][0]["legibility"]="partial"
        good["choices"][0]["message"]["content"]=json.dumps(content)
        with self.assertRaises(ValueError): parse_cloud(good,["q1a","q1b","q1c"])


if __name__=="__main__":unittest.main()
