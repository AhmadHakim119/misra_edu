"""Private, script-free crop review artifact for an offline OCR experiment."""
import base64
from hashlib import sha256
from html import escape
import json
from pathlib import Path

from services.ocr_verification import grading_gate
from services.ocr_review_triage import review_queue


def render_review_packet(comparisons, image_paths, *, root, component_reviews=None):
    """Embed only hash-matching PNG crops inside a local evidence directory.

    Decisions are recorded separately through the experiment's trusted local
    boundary. Viewing a packet cannot approve evidence or trigger grading.
    """
    gate = grading_gate(comparisons)
    triage = review_queue(comparisons, component_reviews) if component_reviews is not None else None
    triaged = {r['region_id']: r for r in triage['regions']} if triage else {}
    if triage:
        indexed = {r['region']['region_id']: r for r in comparisons}
        comparisons = [indexed[r['region_id']] for r in triage['regions']]
    root = Path(root).resolve()
    sections = []
    for row in comparisons:
        identifier = row['region']['region_id']
        path = (root / image_paths[identifier]).resolve()
        if not path.is_relative_to(root) or path.suffix.lower() != '.png':
            raise ValueError('Review crop must be a PNG inside the evidence directory.')
        data = path.read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or sha256(data).hexdigest() != row['region']['crop_sha256']:
            raise ValueError('Review image changed; regenerate the comparison.')
        alternatives = ''.join(
            '<div><strong>'+escape(a['reader_id'])+'</strong><pre>'+escape(a['text'])+'</pre><p>'+
            escape('; '.join(a['uncertainties']) or ('No uncertainty field supplied by this specialist' if a['reader_family']=='paddle-formula' else 'No uncertainty reported'))+
            '</p></div>' for a in row['alternatives'])
        reasons = ', '.join(row['review_reasons']) or 'Readers agree; agreement does not prove correctness'
        source_note = '; '.join(row['region']['source_warnings'])
        reviewed = triaged.get(identifier)
        confirmed = ''
        if reviewed:
            confirmed = '<p>Queue: '+escape(reviewed['priority'])+'</p>'
            if reviewed['confirmed_components']:
                confirmed += '<p>Previously confirmed components (partial review only):</p><ul>'+''.join(
                    '<li>'+escape(reply['actor_role'])+': '+escape(reply['confirmed_component'])+'</li>'
                    for reply in reviewed['confirmed_components'])+'</ul>'
                confirmed += '<p>These replies do not approve every character in the line.</p>'
        box = row['region']['bounding_box']
        sections.append('<section id="'+escape(identifier, quote=True)+'"><h2>'+escape(identifier)+
            '</h2>'+confirmed+'<p>Recorded review signals: '+escape(reasons)+'</p><p>'+escape(source_note)+'</p><img alt="Student writing crop '+escape(identifier, quote=True)+
            '" src="data:image/png;base64,'+base64.b64encode(data).decode()+'"><div class="alternatives">'+alternatives+
            '</div><details><summary>Evidence location and revision</summary><pre>'+escape(json.dumps({
                'page_index':row['region']['page_index'],'bounding_box':box,'evidence_digest':row['evidence_digest']},indent=2))+
            '</pre></details></section>')
    pending = len(gate['pending_region_ids'])
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+\
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'+\
        '<title>Physics extraction review</title><style>body{font:16px system-ui;max-width:1100px;margin:30px auto;padding:0 18px;color:#182b2b;background:#f4f7f7}section{background:white;padding:20px;margin:24px 0;border:1px solid #bacbcb;border-radius:8px}img{max-width:100%;height:auto;border:1px solid #ccc}.alternatives{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:15px}h1,h2{color:#126a65}p{line-height:1.5}details{font-size:13px}</style>'+\
        '<h1>Review the writing before grading</h1><p>'+str(pending)+' of '+str(len(comparisons))+\
        ' regions need review. Compare the crop with each literal reading. Preserve student mistakes. Choose or enter a transcription; keep unreadable symbols unresolved.</p>'+\
        '<p>This private packet sends no data and cannot save an approval or start grading. Instructor decisions must be saved separately with the displayed evidence digest. Full pages remain preserved locally.</p>'+''.join(sections)+'</html>'
