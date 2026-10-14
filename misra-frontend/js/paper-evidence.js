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
        if (result?.page_index !== pageIndex || !result.sources || typeof result.sources !== 'object') throw new Error('Invalid location response');
        return result.sources;
      });
      pending.set(key, request);
      request.finally(() => { if (pending.get(key) === request) pending.delete(key); }).catch(() => {});
    }
    return pending.get(key);
  }
  function location(source, locations = {}) {
    const native = locations[source.id];
    const matched = native?.status === 'located' && native?.method === 'native_pdf_text' && validBox(native.bounding_box);
    return matched
      ? { box: matched, verified: true, message: 'Text matched on the original PDF. The highlight locates the answer; it does not verify its correctness.' }
      : { box: validBox(source.ocr_segment?.bounding_box), verified: false,
        message: 'Approximate OCR location — not verified against the page text. Check the complete original answer.' };
  }
  window.MisraEvidence = { validBox, pageLocations, location };
})();
