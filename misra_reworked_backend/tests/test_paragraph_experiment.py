from copy import deepcopy
import unittest

from ocr_quality_experiment import errors
from paragraph_experiment import context_eligible,group_lines,local_answers,nli_input_pairs,train_thresholds
from test_rubric_pilot import fixture


class ParagraphExperiments(unittest.TestCase):
    def test_full_answer_context_is_checked_without_truncation(self):
        count=lambda a,b:len(a.split())+(len(b.split()) if b else 0)+3
        pairs=nli_input_pairs("one two three four five","reference claim",["a claim"])
        self.assertFalse(context_eligible(pairs,count,limit=8))
        self.assertTrue(context_eligible(pairs,count,limit=20))
        self.assertEqual(pairs[0][0],"one two three four five")
    def test_word_boxes_are_grouped_before_prompt_matching(self):
        spans=[{"id":f"s{i}","text":t,"engine_confidence":.8,
                "bbox":{"x0":x,"y0":y,"x1":x+25,"y1":y+12}}
               for i,(t,x,y) in enumerate([("world",40,10),("hello",5,10),("next",5,40)])]
        rows=group_lines(spans)
        self.assertEqual([r["text"] for r in rows],["hello world","next"])
        self.assertEqual(set(rows[0]["source_span_ids"]),{"s0","s1"})

    def test_unknown_mapping_is_not_a_blank_or_incorrect_answer(self):
        config={"anchors":{"1":[["q1b","Second prompt",.25,.5],["q1c","Third prompt",.5,.75]]}}
        rows=local_answers([],1,100,200,config)
        self.assertEqual(len(rows),3)
        self.assertTrue(all(r["text"] is None for r in rows))
        self.assertEqual(local_answers([],2,100,200,config),[])

    def test_private_config_maps_answers_and_excludes_printed_prompts(self):
        config={
            "anchors":{"1":[["q1b","Second prompt",.25,.5],["q1c","Third prompt",.5,.75]]},
            "prompt_endings":{"q1a":"First prompt","q1b":"Second prompt","q1c":"Third prompt"},
        }
        spans=[
            {"id":f"s{i}","text":text,"engine_confidence":.8,
             "bbox":{"x0":0,"y0":y,"x1":70,"y1":y+8}}
            for i,(text,y) in enumerate([
                ("First prompt",10),("One",26),("Second prompt",62),("Two",78),
                ("Third prompt",122),("Three",140),
            ])
        ]
        self.assertEqual([r["text"] for r in local_answers(spans,1,100,200,config)],["One","Two","Three"])

    def test_content_ocr_metrics_keep_negation_and_do_not_compare_semantic_correctness(self):
        self.assertEqual(errors("User needs.","user needs",content=True)["cer"],0)
        self.assertGreater(errors("not correct","correct",content=True)["wer"],0)
        self.assertGreater(errors("3 + 8","3 - 8",content=True)["cer"],0)
        blank=errors("","spurious",content=True)
        self.assertIsNone(blank["cer"])
        self.assertGreater(blank["character_errors"],0)

    def train_fixture(self):
        guide,_,_=fixture()
        guide=guide.model_copy(update={"question_id":"q1a","approval_status":"approved"})
        manifest={"groups":[{"paper_id":"a","split":"train"},{"paper_id":"b","split":"train"},{"paper_id":"test","split":"test"}]}
        labels=[{"paper_id":p,"question_id":"q1a","instructor_checked":True,
                 "instructor_levels":{"setup":"full" if p=="a" else "zero","calculation":"full"}} for p in ["a","b"]]
        scores=[{"id":p,"paper_id":p,"question_id":"q1a","source":"synthetic",
                 "scores":{"cosine":s}} for p,s in [("a",.9),("b",.8)]]
        return guide,manifest,labels,scores

    def test_fit_requires_checked_labels_and_approved_guide(self):
        guide,manifest,labels,scores=self.train_fixture()
        fitted=train_thresholds(scores,labels,manifest,{"q1a":guide})
        self.assertEqual(fitted["q1a"]["synthetic"]["cosine"],.9)
        bad=deepcopy(labels);bad[0]["instructor_checked"]=False
        with self.assertRaises(ValueError):train_thresholds(scores,bad,manifest,{"q1a":guide})
        with self.assertRaises(ValueError):train_thresholds(scores,labels,manifest,{"q1a":guide.model_copy(update={"approval_status":"draft"})})

    def test_test_labels_nulls_unknown_criteria_and_duplicates_cannot_train(self):
        guide,manifest,labels,scores=self.train_fixture()
        cases=[]
        bad=deepcopy(labels);bad[0]["paper_id"]="test";cases.append(bad)
        bad=deepcopy(labels);bad[0]["instructor_levels"]["setup"]=None;cases.append(bad)
        bad=deepcopy(labels);bad[0]["instructor_levels"]={"made_up":"full"};cases.append(bad)
        cases.append(labels+[labels[0]])
        for bad in cases:
            with self.subTest(bad=bad),self.assertRaises(ValueError):train_thresholds(scores,bad,manifest,{"q1a":guide})


if __name__=="__main__":unittest.main()
