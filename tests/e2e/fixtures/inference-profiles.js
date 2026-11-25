const fullyLocalProfile = 'local_qwen_all_v1';
const tasks = (provider, model) => Object.fromEntries(['setup', 'grading', 'verification'].map(task => [task, {provider, model}]));
function profileCatalog(selected = fullyLocalProfile) {
  return {selected_profile: selected, profiles: [
    {id: fullyLocalProfile, label: 'Fully local Qwen', verification_enabled: true, text_only_grading: false,
      tasks: {ocr: {provider: 'local', model: 'qwen3-vl:4b-instruct'}, ...tasks('local', 'qwen3:4b-instruct'),
        vision_grading: {provider: 'local', model: 'qwen3-vl:4b-instruct'}}},
    {id: 'configured', label: 'Server configuration', verification_enabled: true, text_only_grading: false,
      tasks: {ocr: {provider: 'gemini', model: 'Synthetic vision model'}, ...tasks('openrouter_free', 'Synthetic assessment model')}},
  ]};
}
module.exports = {fullyLocalProfile, profileCatalog};
