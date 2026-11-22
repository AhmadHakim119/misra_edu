const localProfile = 'local_qwen_gemini_v1';
const visionProfile = 'local_qwen_vision_gemini_v1';
const tasks = (provider, model) => Object.fromEntries(['setup', 'grading', 'verification'].map(task => [task, {provider, model}]));
function profileCatalog(selected = localProfile) {
  return {selected_profile: selected, profiles: [
    {id: localProfile, label: 'Local Qwen + Gemini page reading', verification_enabled: true, text_only_grading: true,
      tasks: {ocr: {provider: 'gemini', model: 'gemini-2.5-flash'}, ...tasks('local', 'qwen3:4b-instruct')}},
    {id: visionProfile, label: 'Local Qwen Vision + Gemini page reading', verification_enabled: true, text_only_grading: false,
      tasks: {ocr: {provider: 'gemini', model: 'gemini-2.5-flash'}, ...tasks('local', 'qwen3-vl:4b-instruct'),
        setup: {provider: 'local', model: 'qwen3:4b-instruct'}}},
    {id: 'configured', label: 'Server configuration', verification_enabled: true, text_only_grading: false,
      tasks: {ocr: {provider: 'gemini', model: 'Synthetic vision model'}, ...tasks('openrouter_free', 'Synthetic assessment model')}},
  ]};
}
module.exports = {localProfile, visionProfile, profileCatalog};
