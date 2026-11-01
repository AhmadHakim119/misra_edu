/* Display-only locations. Original OCR/run snapshots remain unchanged. */
(function () {
  'use strict';
  const pending = new Map();
  function validBox(box) {
    if (!box || ![box.x, box.y, box.width, box.height].every(value => typeof value === 'number' && Number.isFinite(value))) return null;
    const { x, y, width, height } = box;
    return x >= 0 && y >= 0 && width > 0 && height > 0 && x + width <= 1.001 && y + height <= 1.001 ? box : null;
  }
  async function pageLocations(submissionId, pageIndex) {
    const key = `${submissionId}:${pageIndex}`;
    if (!pending.has(key)) {
      const request = MisraAPI.sourceLocations(submissionId, pageIndex).then(result => {
        if (result?.page_index !== pageIndex || !result.sources || typeof result.sources !== 'object' || Array.isArray(result.sources)) throw new Error('Invalid location response');
        return result.sources;
      });
      pending.set(key, request);
      request.finally(() => { if (pending.get(key) === request) pending.delete(key); }).catch(() => {});
    }
    return pending.get(key);
  }
  function location(source, locations = {}) {
    const revision=source.area_revision;
    if(revision){
      const box=revision.source_id===source.id&&revision.page_index===source.page_index&&revision.id?validBox(revision.bounding_box):null;
      return {box,verified:false,confirmed:Boolean(box),stale:!box,
        message:box?'Instructor-confirmed answer area. Review the saved extraction and grading run.':'Answer location needs review. Inspect the original page or select the answer area.'};
    }
    const native = locations[source.id];
    if(native?.status==='stale')return {box:null,verified:false,stale:true,message:'Answer location needs review. Inspect the original page or select the answer area.'};
    if(native?.method==='instructor_confirmed_area')return {box:native.status==='located'?validBox(native.bounding_box):null,verified:false,confirmed:native.status==='located'&&Boolean(validBox(native.bounding_box)),
      message:'Instructor-confirmed answer area. Review the saved extraction and grading run.'};
    // A printed choice/value is context, not evidence of the student's response.
    // Apply to numeric/letter answers regardless of question numbering or subject.
    const briefValue=/^(?:\(?[\p{L}]\)?[.)]?|[+\-−]?\d+(?:[.,]\d+)?(?:\s*[\p{L}%°/²³^0-9.\-]+)?)$/u.test((source.extracted_text||'').trim());
    if(native?.method==='native_pdf_text'&&briefValue)return {box:validBox(source.ocr_segment?.bounding_box),verified:false,blockedTextMatch:true,
      message:'Printed text alone does not locate a response mark. Inspect the original page or select the answer area.'};
    const matched = native?.status === 'located' && native?.method === 'native_pdf_text' && validBox(native.bounding_box);
    if(native?.method==='vision_grid')return {
      box:native.status==='located'?validBox(native.bounding_box):null,verified:false,
      message:'AI-located answer region. Check against the original; the highlight does not verify the grade.'};
    return matched
      ? { box: matched, verified: true, message: 'Text matched on the original PDF. The highlight locates the answer; it does not verify its correctness.' }
      : { box: native?.status==='located'?null:validBox(source.ocr_segment?.bounding_box), verified: false,
        message: 'Approximate OCR location — not verified against the page text. Check the complete original answer.' };
  }
  window.MisraEvidence = { validBox, pageLocations, location };
})();
