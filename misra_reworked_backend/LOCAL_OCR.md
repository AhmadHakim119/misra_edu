# Local OCR pilot

`local_ocr.py` adds local extraction to the reworked rubric pilot. It is a CLI
service, not a replacement for the original application's Gemini upload route.
There are no database migrations, UI changes, cloud fallbacks or grade approvals.

Implemented and exercised on this Windows machine:

- PaddleOCR 3.4.1 / PaddlePaddle CPU 3.2.2, with an explicitly selected
  PP-OCRv5 mobile detector and either English or Arabic/English recognition.
- Tesseract 5.5.3.20260724, with pinned `tessdata_best` English and Arabic weights.

The optional dependencies live in `private/local-ocr-20261105/venv/`, separately
from the application environment and the older globally installed Paddle GPU
packages. `requirements-ocr.txt` declares the direct dependencies; the private
`environment-lock.txt` records the complete environment used. Model revisions
and downloaded file hashes are in `private/local-ocr-20261105/models-manifest.json`.
`pip check` checks dependency compatibility; it is not a vulnerability audit.

## Extraction and review

Each new run preserves the original file, every full page, page hashes, raw engine
responses, text boxes, engine scores, selected model hashes and timing. Runs refuse
to overwrite an existing directory. A failure is unscored, never a zero mark.
PDFs are limited to 20 pages / 50 MiB in this pilot; Poppler `pdftoppm` is required.

No model downloads occur during extraction. Both engines receive local image paths
and explicit local weights. Python socket connections are blocked during model
initialization and recognition. This is an application guard, not an OS network
sandbox. Public model downloads happened separately, without paper inputs.

Every extracted span starts with `role=unassigned` and `cancellation=unknown`.
OCR confidence is not a calibrated correctness probability. Neither engine has
a validated strike-through detector here. No OCR draft can directly satisfy the
grading `Answer` contract.

From the repository root in PowerShell:

```powershell
$ocrPython = '.\private\local-ocr-20261105\venv\Scripts\python.exe'
& $ocrPython .\misra_reworked_backend\local_ocr.py extract `
  --input .\private\rubric-pilot-20261104\originals\studentA.pdf `
  --config .\private\local-ocr-20261105\configs\paddle-en.json `
  --output .\private\local-ocr-20261105\runs\my-new-run
```

The installed configurations are `paddle-en.json`, `paddle-ar-en.json`,
`tesseract-en.json` and `tesseract-ar-en.json`. They use absolute local model paths.
For another installation, create the same strict configuration with these fields:

```json
{
  "engine": "paddle",
  "language": "ar+en",
  "detection_model_dir": "ABSOLUTE_LOCAL_PATH/PP-OCRv5_mobile_det",
  "recognition_model_dir": "ABSOLUTE_LOCAL_PATH/arabic_PP-OCRv5_mobile_rec"
}
```

Each Paddle directory needs `inference.json`, `inference.pdiparams` and
`inference.yml`. Download public weights from the official PaddlePaddle Hugging
Face repositories using the revisions recorded in the model manifest. Tesseract
instead needs `tesseract_exe`, `tessdata_dir`, `language` and `tesseract_psm` (3, 6
or 11). Its installed Windows distribution was extracted into a private folder,
without running the installer or changing PATH/system settings.

Generate an unchecked transcription review:

```powershell
& $ocrPython .\misra_reworked_backend\local_ocr.py review-template `
  --extraction .\private\local-ocr-20261105\runs\my-new-run\extraction.json `
  --answer-id paper_a --question-id INSTRUCTOR_QUESTION_ID `
  --output .\private\local-ocr-20261105\my-review.json
```

The instructor checks the preserved page, retains only this question's student
answer, corrects transcription errors, adds missed text with page/bbox evidence,
and explicitly marks active/crossed-out segments. Remove identity, question text,
teacher marks and other answers from the review's segment list. Fill the reviewer
and completeness checks. This does not modify raw extraction or approve a guide.

```powershell
& $ocrPython .\misra_reworked_backend\local_ocr.py export-reviewed `
  --extraction .\private\local-ocr-20261105\runs\my-new-run\extraction.json `
  --review .\private\local-ocr-20261105\my-review.json `
  --output .\private\local-ocr-20261105\checked-answer
```

Export rejects stale extraction hashes, changed source/pages, unknown/wrong-page
span references, unchecked text, unresolved cancellations and invalid boxes. It
produces `answers.json` in the rubric pilot's existing format, with explicit OCR
and review provenance. The question ID must match the guide. Cancelled text stays
in the saved answer but is excluded from Qwen inputs. Original guide approval and
instructor grade review are still separate boundaries.

The JSON review is a trusted local instructor tool, not an authenticated multi-user
review system. The web application must supply its existing authorization boundary
before exposing this through an API.

## Evaluation

`evaluate_local_ocr.py` compares frozen transcriptions against extraction artifacts.
It measures CER, WER, exact transcript match, literal probe presence and recorded
latency. Normalization is NFC and whitespace only: negation, Arabic diacritics,
case, punctuation and mathematical operators remain significant. WER may exceed
1 when there are many insertions. Literal probes are diagnostics, not correctness
tests or grading decisions.

The first experiment uses the two supplied synthetic handwritten papers and three
constructed printed controls: English, Arabic and bilingual. Answer regions for
A/B are manually specified and select spans by their box centers. They are not
automatic question mapping. B's raw reference includes cancelled writing; cancellation
recognition is reported as unavailable, not counted as successful.

```powershell
& $ocrPython .\misra_reworked_backend\evaluate_local_ocr.py `
  --references .\private\local-ocr-20261105\evaluation-references-v2.json `
  --runs .\private\local-ocr-20261105\runs\first `
  --output .\private\local-ocr-20261105\my-evaluation.json
```

Compare language-appropriate configurations. An English-only recognizer on Arabic
is a negative control, not evidence about that engine's Arabic capability. These
five development examples cannot establish general handwriting accuracy, safe
automatic acceptance thresholds, review-routing recall or instructor time savings.
No training/fine-tuning or Qwen calls are involved in this OCR benchmark.

## Other candidates from the supplied list

The list is a candidate list, not an independently verified ranking.

- [PaddleOCR documentation](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html)
  supports local model directories; model versions are explicitly selected here.
- [Tesseract language data documentation](https://tesseract-ocr.github.io/tessdoc/Data-Files)
  describes the best/fast model families. The Windows distribution is linked from
  [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki).
- [Baseer's official page](https://misraj.ai/en/models/baseer) describes the main
  model as commercial and designed for printed documents. Its benchmark is not
  a demonstrated result on these student answers. No paid/private weights used.
- [Current Surya](https://github.com/datalab-to/surya) and
  [HunyuanOCR](https://github.com/Tencent-Hunyuan/HunyuanOCR) offer VLM inference
  paths involving additional local serving/model setup. They have **not** been
  installed or benchmarked here. They remain candidates if these CPU baselines
  do not meet the handwriting requirements; no superiority is assumed.
- Umi-OCR is a desktop workflow around OCR engines; installing it does not provide
  a distinct extraction model for this backend. The Microsoft Store app from the
  pasted list was not integrated or tested.

## Software checks

Run from `misra_reworked_backend/` with an environment containing the experiment
dependencies:

```powershell
..\private\method-comparison-20261105\venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
```

Tests use generated images and mocked engines. They cover draft/review boundaries,
raw-output preservation, no overwrite, malformed geometry/confidence, failures,
network guards, question binding and cancellation filtering. Software passes are
separate from measured OCR quality. Full results and actual counts are recorded in
`private/local-ocr-20261105/RESULTS.md` after the real engine runs finish.
