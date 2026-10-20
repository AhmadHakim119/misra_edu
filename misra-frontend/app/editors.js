/* Native authoring uses existing version/approval APIs, never mutable run history. */
(function () {
  'use strict';
  const $=id=>document.getElementById(id), esc=value=>MisraUI.escapeHTML(String(value ?? ''));
  const clone=value=>structuredClone(value), lines=value=>String(value || '').split('\n').map(v=>v.trim()).filter(Boolean);
  let exam=null, questions=[], question=null, versions=[], version=null, rubric=null, epoch=0, requestId=0;
  let busy=false, loading=false, dirty=false, loaded=false, uncertain=false, view='', failure='', notice='', mode='adaptive', profile=null, renderKey='', usePreferences=true, preferencesKnown=true, preferenceUserId='', blankDraft='';
  const reminderKey=()=>`misra-rubric-survey-later:${preferenceUserId}`;
  function reminder(){return !profile&&!sessionStorage.getItem(reminderKey())?'<aside class="survey-reminder"><div><strong data-i18n>Personalize your marking rules · Optional</strong><p data-i18n>Continue with standard rules, or use your survey preferences.</p><button type="button" data-author-survey>Take survey</button></div><button type="button" data-author-survey-later>Not now</button></aside>':'';}
  function applyProfile(){
    if(!preferencesKnown)throw Error('Could not load marking settings. Reload before creating a draft.');
    if(!profile||!usePreferences)return;
    for(const [key,value] of Object.entries(profile.derived_proposal || {})){
      if(key==='custom_instructions'){if(value&&!rubric.policy[key]?.includes(value))rubric.policy[key]=[rubric.policy[key],value].filter(Boolean).join('\n');}
      else if(value!=null)rubric.policy[key]=value;
    }
  }
  const policyChoices={
    assessment_scope:['Assessment scope',[['paper','Grade from this paper'],['external','Assessed outside MISRA — computer/practical']]],
    grading_approach:['Approach',[['balanced','Balanced'],['lenient','Lenient'],['strict','Strict'],['custom','Custom']]],
    method_credit:['Method credit',[['none','None'],['partial','Partial'],['full_if_valid','Full if valid']]],
    arithmetic_error_policy:['Arithmetic errors',[['single_penalty','Penalize the original error once'],['penalize_each','Penalize each occurrence'],['criterion_specific','Follow each criterion']]],
    units_policy:['Units',[['required_when_applicable','Required when applicable'],['required','Required'],['do_not_penalize','Do not penalize']]],
    notation_policy:['Notation',[['equivalent_allowed','Accept equivalent notation'],['standard_required','Require standard notation'],['do_not_penalize','Do not penalize']]],
    evidence_requirement:['Evidence required',[['key_steps','Key steps'],['final_answer_only','Final answer only'],['complete_reasoning','Complete reasoning'],['custom','Custom']]],
    illegible_response_policy:['Illegible responses',[['manual_review','Instructor review'],['grade_visible_only','Grade visible work only'],['zero','Zero credit']]],
    language_quality_policy:['Language quality',[['criterion_specific','Follow each criterion'],['ignore_unless_assessed','Ignore unless assessed'],['assess','Assess language quality']]],
    error_carried_forward:['Carried-forward errors',[['criterion_specific','Follow each criterion'],['single_penalty','Penalize the original error once'],['penalize_each','Penalize each affected step']]],
    handwritten_syntax_policy:['Handwritten syntax',[['criterion_specific','Follow each criterion'],['accept_unambiguous','Accept unambiguous intent'],['require_correct','Require correct syntax']]]
  };
  const editable=()=>Boolean(rubric && (!version || version.status==='draft'));
  const deletable=()=>!question?.id || Boolean(versions.length && !question.active_rubric_version_id && versions.every(v=>v.status==='draft'&&!v.approved_at&&!v.approved_by));
  const isBusy=()=>busy || MisraAnswerKeys.isBusy() || MisraMaterials.isBusy() || Boolean(window.MisraAssessmentGuide?.isBusy());
  const hasUnsaved=()=>dirty || isBusy() || MisraAnswerKeys.hasUnsaved() || MisraMaterials.hasUnsaved();
  function canLeave() {
    if(isBusy()) {window.showToast('Wait for the current marking-guide operation to finish.','info');return false;}
    return MisraAnswerKeys.canLeave() && MisraMaterials.canLeave() && (!dirty || confirm('Discard unsaved question or rubric edits?'));
  }
  function reset(value) {
    ++epoch;++requestId;exam=value;questions=[];question=null;versions=[];version=rubric=null;dirty=busy=loading=loaded=uncertain=false;view='';failure=notice=renderKey='';profile=null;
    MisraAnswerKeys.reset();MisraMaterials.reset();$('native-authoring').hidden=true;$('native-library').hidden=true;
    $('author-question').innerHTML='';$('rubric-workspace').innerHTML='';$('answer-key-panel').innerHTML='';$('question-material-host').innerHTML='';$('library-material-host').innerHTML='';
  }
  function normalize(raw,max) {
    const value=clone(raw || {});value.schema_version=2;value.max_score=Number(value.max_score ?? max);
    value.criteria=(value.criteria || []).map(c=>({...c,id:c.id || 'criterion_'+crypto.randomUUID().replaceAll('-','').slice(0,12),title:c.title || c.description || 'Criterion',description:c.description || '',points:Number(c.points),scoring_type:c.scoring_type || 'scaled',partial_credit_allowed:c.scoring_type==='binary' ? false : c.partial_credit_allowed!==false,performance_levels:c.performance_levels || [],common_errors:c.common_errors || [],alternative_methods:c.alternative_methods || [],required_evidence:c.required_evidence || []}));
    value.policy={...Object.fromEntries(Object.entries(policyChoices).map(([key,[,options]])=>[key,options[0][0]])),alternative_methods_allowed:true,rounding_tolerance_percent:null,custom_instructions:null,...value.policy};
    value.policy.grading_approach=raw?.policy?.grading_approach || raw?.grading_approach || 'balanced';return value;
  }
  function field(id,label,control) {return `<div class="field"><label for="${id}">${label}</label>${control}</div>`;}
  function input(id,value,attrs='') {return `<input id="${id}" value="${esc(value)}" ${attrs}>`;}
  function select(id,value,options,attrs='') {return `<select id="${id}" ${attrs}>${options.map(([key,title])=>`<option value="${esc(key)}" ${key===value ? 'selected' : ''}>${esc(title)}</option>`).join('')}</select>`;}
  function textarea(id,value,attrs='') {return `<textarea id="${id}" dir="auto" rows="3" ${attrs}>${esc(value)}</textarea>`;}
  function creditDetails(c,i) {
    return `<details class="author-credit-details"><summary>Detailed credit &amp; common mistakes</summary>
      <div class="author-grid">${field(`ac-${i}-scoring`,'Scoring',select(`ac-${i}-scoring`,c.scoring_type,[['scaled','Scaled — partial credit'],['binary','Binary — full or zero']],'data-rubric-edit data-criterion-field="scoring_type"'))}${field(`ac-${i}-evidence`,'Required evidence (one per line)',textarea(`ac-${i}-evidence`,c.required_evidence.join('\n'),'data-rubric-edit data-criterion-field="required_evidence"'))}</div>
      ${field(`ac-${i}-partial`,'Partial credit allowed',select(`ac-${i}-partial`,String(c.partial_credit_allowed),[['true','Yes'],['false','No']],'data-rubric-edit data-criterion-field="partial_credit_allowed"'))}
      <h4>Credit levels</h4>${c.performance_levels.map((level,j)=>`<div class="author-credit-row" data-credit-level><div class="author-grid">${field(`al-${i}-${j}-label`,'Level name',input(`al-${i}-${j}-label`,level.label,'data-rubric-edit data-level-field="label" maxlength="100"'))}${field(`al-${i}-${j}-points`,'Marks at this level',input(`al-${i}-${j}-points`,level.points_earned,'data-rubric-edit data-level-field="points_earned" type="number" min="0" step="any"'))}</div>${field(`al-${i}-${j}-description`,'Work that earns this level',textarea(`al-${i}-${j}-description`,level.description,'data-rubric-edit data-level-field="description"'))}${editable() ? `<button type="button" data-detail-remove="performance_levels" data-detail-index="${j}">Remove credit level ${j+1}</button>` : ''}</div>`).join('')}
      ${editable() ? '<button type="button" data-detail-add="performance_levels">Add credit level</button>' : ''}
      <h4>Common mistakes</h4>${c.common_errors.map((error,j)=>`<div class="author-credit-row" data-common-error>${field(`ae-${i}-${j}-description`,'Mistake to look for',textarea(`ae-${i}-${j}-description`,error.description,'data-rubric-edit data-error-field="description"'))}${field(`ae-${i}-${j}-guidance`,'How it affects credit',textarea(`ae-${i}-${j}-guidance`,error.guidance,'data-rubric-edit data-error-field="guidance"'))}${editable() ? `<button type="button" data-detail-remove="common_errors" data-detail-index="${j}">Remove common mistake ${j+1}</button>` : ''}</div>`).join('')}
      ${editable() ? '<button type="button" data-detail-add="common_errors">Add common mistake</button>' : ''}
      ${field(`ac-${i}-alternatives`,'Alternative methods (one per line)',textarea(`ac-${i}-alternatives`,c.alternative_methods.join('\n'),'data-rubric-edit data-criterion-field="alternative_methods"'))}</details>`;
  }
  function setControls() {
    $('author-foundations').disabled=busy || loading;
    $('author-question').disabled=busy || loading || uncertain || !questions.length;$('author-new-question').disabled=busy || loading || uncertain;$('author-reload').disabled=busy || loading;
    $('rubric-workspace').setAttribute('aria-busy',String(busy));
    $('rubric-workspace').querySelectorAll('button,input,select,textarea').forEach(el=>el.disabled=busy || uncertain || (el.hasAttribute('data-rubric-edit') && !editable()) || (el.hasAttribute('data-author-delete')&&!deletable()));
  }
  function updateState() {
    $('author-state')?.replaceChildren(document.createTextNode(uncertain ? 'Change not confirmed. Reload questions before another write.' : dirty ? 'Unsaved changes — not used for grading' : notice || (version?.status==='approved' ? 'Approved version is read-only. Create a draft to change future grading.' : 'Saved draft — not used for grading')));
    const total=rubric?.criteria?.reduce((sum,c)=>sum+c.points,0);if($('author-total')) $('author-total').textContent=`${Number.isFinite(total) ? Number(total.toFixed(2)) : 'Invalid'} / ${rubric.max_score} marks assigned`;
    $('rubric-workspace').querySelectorAll('[data-criterion-panel]').forEach(panel=>{
      const c=rubric?.criteria.find(c=>c.id===panel.dataset.criterionPanel);if(!c)return;
      panel.querySelector('[data-criterion-title]').textContent=c.title || 'Untitled criterion';
      panel.querySelector('[data-criterion-marks]').textContent=`${Number.isFinite(c.points) ? c.points : 'Invalid'} marks`;
      panel.querySelector('[data-criterion-rule]').textContent=c.scoring_type==='binary' || !c.partial_credit_allowed ? 'Full credit or zero' : 'Partial credit allowed';
    });
  }
  function render() {
    const host=$('rubric-workspace');
    if(loading) {host.innerHTML='<p role="status">Loading approved definitions and drafts…</p>';setControls();return;}
    if(!rubric) {host.innerHTML=`${failure ? `<p role="alert" class="form-error">${esc(failure)}</p>` : reminder()+'<p>Add a question to start your marking guide.</p>'}`;setControls();return;}
    const key=question?.id || 'new';
    const detailKey=el=>el.dataset.authorSection || (el.dataset.criterionPanel ? 'criterion:'+el.dataset.criterionPanel : el.closest('[data-author-criterion]') ? 'credit:'+rubric.criteria[Number(el.closest('[data-author-criterion]').dataset.authorCriterion)]?.id : el.querySelector('summary')?.textContent.split('·')[0].trim());
    const opened=renderKey===key ? new Map([...host.querySelectorAll('details')].map(el=>[detailKey(el),el.open])) : null;
    renderKey=key;
    const isNew=!question?.id;
    host.innerHTML=`<header class="author-savebar"><div><h3>${isNew ? 'New question' : `Question ${esc(question.question_number)} <span class="author-question-marks">${rubric.max_score} marks</span>`}</h3><p id="author-state" role="status"></p></div><div class="author-actions">${editable() ? '<button type="button" class="primary" data-author-save>Save draft</button>' : '<button type="button" class="primary" data-author-draft>Create editable draft</button>'}${question?.id||isNew?`<button type="button" class="author-delete" data-author-delete ${!deletable()?'disabled aria-describedby="question-delete-help"':''}>${isNew?'Discard question':'Delete question'}</button>`:''}</div></header>
      ${!deletable()?'<p id="question-delete-help" class="muted" data-i18n>Only unused draft questions can be deleted.</p>':''}
      <p id="author-error" role="alert" class="form-error" ${failure ? '' : 'hidden'}>${esc(failure)}</p>
      ${reminder()}
      ${isNew ? `<div class="author-grid">${field('author-number','Question number',input('author-number',question.question_number,'data-rubric-edit required maxlength="40"'))}${field('author-max','Total marks',input('author-max',rubric.max_score,'data-rubric-edit type="number" min="0.01" step="any" required'))}${field('author-language','Language',select('author-language',question.language,[['en','English'],['ar','Arabic'],['mixed','Mixed']],'data-rubric-edit'))}</div>` : ''}
      <div class="field author-question-stem"><label for="author-question-text">Question students are asked</label>${textarea('author-question-text',question.question_text,`maxlength="50000" ${isNew ? 'data-rubric-edit required' : 'readonly'}`)}</div>
      <section class="author-criteria" aria-labelledby="author-criteria-title"><header class="author-criteria-heading"><h4 id="author-criteria-title">Marking criteria</h4><span id="author-total"></span></header>
      ${rubric.criteria.map((c,i)=>`<details class="author-criterion-panel" data-criterion-panel="${esc(c.id)}" ${i===0 ? 'open' : ''}><summary><span class="author-criterion-index">${i+1}</span><span data-criterion-title dir="auto">${esc(c.title || 'Untitled criterion')}</span><span data-criterion-marks>${esc(c.points)} marks</span></summary><fieldset class="author-criterion" data-author-criterion="${i}" aria-label="Criterion ${i+1}"><div class="author-grid author-credit-basics">${field(`ac-${i}-title`,'Criterion title',input(`ac-${i}-title`,c.title,'data-rubric-edit data-criterion-field="title" maxlength="160" dir="auto"'))}${field(`ac-${i}-points`,'Marks',input(`ac-${i}-points`,c.points,'data-rubric-edit data-criterion-field="points" type="number" min="0.01" step="any"'))}</div>${field(`ac-${i}-description`,'What earns credit',textarea(`ac-${i}-description`,c.description,'data-rubric-edit data-criterion-field="description"'))}<p class="author-credit-rule" data-criterion-rule></p>${creditDetails(c,i)}${editable() ? `<button class="author-remove" type="button" data-author-remove="${i}">Remove criterion ${i+1}</button>` : ''}</fieldset></details>`).join('')}
      ${editable() ? '<button type="button" data-author-add>Add criterion</button>' : ''}</section>
      <details class="author-section author-options" data-author-section="options"><summary>Question settings <span>${esc(rubric.policy.grading_approach)} policy${!isNew ? ` · ${versions.length} rubric version(s)` : ''}</span></summary>
      ${profile && editable() ? `<div class="author-section"><h4>Your saved marking preferences</h4><p>Use your approved profile as a starting point for this draft, then review the scoring rules.</p><button type="button" data-author-profile>Use my approved profile</button></div>` : ''}<details class="author-section" data-author-section="policy"><summary>Scoring policy · ${esc(rubric.policy.grading_approach)}</summary><p>These rules apply to future grading after approval. External practical work is excluded from paper totals.</p><div class="author-grid">${Object.entries(policyChoices).map(([key,[label,options]])=>field('ap-'+key,label,select('ap-'+key,rubric.policy[key],options,`data-rubric-edit data-policy-field="${key}"`))).join('')}${field('ap-alternatives','Allow alternative methods',select('ap-alternatives',String(rubric.policy.alternative_methods_allowed),[['true','Yes'],['false','No']],'data-rubric-edit data-policy-field="alternative_methods_allowed"'))}${field('ap-rounding','Rounding tolerance (%) — optional',input('ap-rounding',rubric.policy.rounding_tolerance_percent,'type="number" min="0" max="100" step="any" data-rubric-edit data-policy-field="rounding_tolerance_percent"'))}</div>${field('ap-custom','Custom instructions',textarea('ap-custom',rubric.policy.custom_instructions,'data-rubric-edit data-policy-field="custom_instructions"'))}</details>
      <details class="author-section"><summary>Retained reference context &amp; notes</summary><p>Legacy reference fields are preserved. Independently approved answer keys are managed below.</p>${['reference_context','notes','acceptable_answers'].map(key=>field('ar-'+key,key.replaceAll('_',' '),textarea('ar-'+key,key==='acceptable_answers' ? (rubric[key] || []).join('\n') : rubric[key],`data-rubric-edit data-reference-field="${key}"`))).join('')}</details>
      ${!isNew ? `<details class="author-section"><summary>Grading input · ${esc(mode.replaceAll('_',' '))}</summary><p>This routing setting is saved separately from rubric approval; historical runs keep their evidence snapshots.</p>${field('author-mode','Evidence source',select('author-mode',mode,[['adaptive','Adaptive'],['image_text_required','Image + text required'],['text_only','Text only']]))}<button type="button" data-author-mode>Save grading input</button></details>
      <details class="author-section"><summary>Rubric version history · ${versions.length}</summary>${versions.map(v=>`<div class="version-row"><button type="button" data-author-version="${esc(v.id)}">Version ${v.version_number} · ${esc(v.status)}</button><span>${esc(v.change_summary)}</span></div>`).join('')}</details>` : ''}</details>
      ${!isNew ? `<details class="author-section" data-author-section="ai"><summary>AI rubric suggestion</summary><p>Generate a draft using this question and its saved context, then review the proposed criteria.</p><form id="author-ai-form">${field('author-ai-context','Additional context — not approved authority',textarea('author-ai-context','','name="answer_key"'))}${field('author-ai-method','Expected method',input('author-ai-method','','name="expected_method"'))}${field('author-ai-level','Course level',input('author-ai-level','','name="course_level"'))}${field('author-ai-notes','Instructor notes',input('author-ai-notes','','name="instructor_notes"'))}<button type="submit">Generate AI draft</button></form></details>` : '<p>Save the question to add an answer key and source exceptions.</p>'}`;
    $('author-key-section').hidden=isNew;$('author-question-sources').hidden=isNew;
    if(opened) host.querySelectorAll('details').forEach(el=>{if(opened.has(detailKey(el))) el.open=opened.get(detailKey(el));});
    updateState();setControls();
  }
  function sync() {
    if(!editable()) return;
    if(!question.id) {question.question_number=$('author-number').value.trim();question.question_text=$('author-question-text').value.trim();question.language=$('author-language').value;rubric.max_score=$('author-max').value==='' ? NaN : Number($('author-max').value);}
    $('rubric-workspace').querySelectorAll('[data-author-criterion]').forEach(row=>{
      const c=rubric.criteria[Number(row.dataset.authorCriterion)];
      row.querySelectorAll('[data-criterion-field]').forEach(el=>{const key=el.dataset.criterionField;c[key]=key==='points' ? el.value==='' ? NaN : Number(el.value) : key==='partial_credit_allowed' ? el.value==='true' : ['required_evidence','alternative_methods'].includes(key) ? lines(el.value) : el.value;});
      c.performance_levels=[...row.querySelectorAll('[data-credit-level]')].map(level=>Object.fromEntries([...level.querySelectorAll('[data-level-field]')].map(el=>[el.dataset.levelField,el.dataset.levelField==='points_earned' ? el.value==='' ? NaN : Number(el.value) : el.value.trim()])));
      c.common_errors=[...row.querySelectorAll('[data-common-error]')].map(error=>Object.fromEntries([...error.querySelectorAll('[data-error-field]')].map(el=>[el.dataset.errorField,el.value.trim()])));
      if(c.scoring_type==='binary') c.partial_credit_allowed=false;
    });
    $('rubric-workspace').querySelectorAll('[data-policy-field]').forEach(el=>{const key=el.dataset.policyField;rubric.policy[key]=key==='rounding_tolerance_percent' ? el.value==='' ? null : Number(el.value) : key==='alternative_methods_allowed' ? el.value==='true' : el.value || null;});
    $('rubric-workspace').querySelectorAll('[data-reference-field]').forEach(el=>rubric[el.dataset.referenceField]=el.dataset.referenceField==='acceptable_answers' ? lines(el.value) : el.value || null);
  }
  function validate() {
    sync();
    if(!Number.isFinite(rubric.max_score) || rubric.max_score<=0) throw new Error('Enter a positive total mark.');
    if(!rubric.criteria.length || rubric.criteria.some(c=>!c.title.trim() || !c.description.trim() || !Number.isFinite(c.points) || c.points<=0)) throw new Error('Each criterion needs a title, credit description and positive marks.');
    const total=rubric.criteria.reduce((s,c)=>s+c.points,0);if(Math.abs(total-rubric.max_score)>.01) throw new Error(`Criteria total ${total}, but this question is worth ${rubric.max_score}.`);
    for(const c of rubric.criteria) {
      const labels=new Set();
      for(const level of c.performance_levels) {const name=level.label.trim().toLowerCase();if(!name || !level.description.trim() || !Number.isFinite(level.points_earned) || level.points_earned<0 || level.points_earned>c.points || labels.has(name) || c.scoring_type==='binary' && ![0,c.points].includes(level.points_earned)) throw new Error('Credit levels need unique names, descriptions and valid marks within the criterion. Binary levels award zero or full credit.');labels.add(name);}
      if(c.common_errors.some(e=>!e.description.trim() || !e.guidance.trim())) throw new Error('Every common mistake needs a description and credit guidance.');
    }
    if(rubric.policy.grading_approach==='custom' && !rubric.policy.custom_instructions?.trim()) throw new Error('Add instructions for the custom grading policy.');
    if(!question.id && (!question.question_number || !question.question_text)) throw new Error('Enter the question number and complete wording.');
  }
  async function definitions(id) {
    const current=epoch,sequence=++requestId;loading=true;failure=notice='';render();
    try {
      const [active,list,routing]=await Promise.all([MisraAPI.rubric(id).catch(e=>{if(e.status===409) return {rubric:{}};throw e;}),MisraAPI.rubricVersions(id),MisraAPI.gradingPolicy(id).catch(e=>{if(e.status===404) return null;throw e;})]);
      if(current!==epoch || sequence!==requestId) return;
      if(!Array.isArray(list)) throw new Error('Invalid version history; reload before editing.');
      versions=list;uncertain=false;version=list.find(v=>v.status==='draft') || list.find(v=>v.id===active.rubric_version_id) || list.find(v=>v.status==='approved') || null;
      rubric=normalize(version?.rubric_json || active.rubric,question.max_score);mode=routing?.mode || 'adaptive';dirty=false;
    } catch(e) {if(current===epoch && sequence===requestId) {rubric=null;failure=e.message;}}
    finally {if(current===epoch && sequence===requestId) {loading=false;render();}}
  }
  async function choose(id,unguarded=false) {
    if(!unguarded && !await saveEdits()) {$('author-question').value=question?.id || '';return;}
    question=questions.find(q=>q.id===id);if(!question) return;
    $('author-question').value=id;MisraMaterials.reset();MisraAnswerKeys.reset();
    $('answer-key-panel').innerHTML='<p role="status">Loading this question’s answer key…</p>';
    $('question-material-host').innerHTML='<p role="status">Loading this question’s sources…</p>';
    const current=epoch;await definitions(id);if(current!==epoch || question?.id!==id || view!=='questions') return;
    const keys=MisraAnswerKeys.load(exam.id,id);MisraAnswerKeys.mount($('answer-key-panel'));await keys;
    if(current!==epoch || question?.id!==id || view!=='questions') return;
    await MisraMaterials.load(exam.course_id,id,rubric?.criteria || []);if(current===epoch && question?.id===id && view==='questions') MisraMaterials.mount($('question-material-host'));
  }
  async function load(preferred) {
    const current=epoch;loading=true;loaded=false;render();setControls();
    try {const list=await MisraAPI.questions(exam.id);if(current!==epoch || view!=='questions') return;if(!Array.isArray(list)) throw new Error('Question list is incomplete. Reload before editing.');questions=list;loaded=true;
      $('author-question').innerHTML=list.map(q=>`<option value="${esc(q.id)}">Question ${esc(q.question_number)} · ${esc(q.max_score)} marks</option>`).join('');
      const user=await (window.MisraCurrentUser || MisraAPI.currentUser());preferenceUserId=user.id;
      profile=await MisraAPI.instructorPreferenceVersions();if(current!==epoch || view!=='questions') return;
      if(!Array.isArray(profile))throw Error('Could not load marking preferences. Reload to retry.');
      profile=profile.find(v=>v.status==='approved') || null;usePreferences=true;preferencesKnown=true;
      if(profile){try{const settings=await MisraAPI.accountSettings();if(typeof settings?.use_marking_preferences!=='boolean')throw Error('Could not read saved marking settings. Reload to retry.');if(current!==epoch)return;usePreferences=settings.use_marking_preferences;}catch(e){if(current!==epoch)return;preferencesKnown=false;failure=e.message;}}
      loading=false;if(list.length) await choose(list.some(q=>q.id===preferred) ? preferred : list[0].id,true);else {rubric=null;question=null;render();setControls();}
    } catch(e) {if(current===epoch) {loading=false;failure=e.message;render();setControls();}}
  }
  async function show(next='questions',preferred) {
    if(!exam) return;
    if(view===next && (next==='library' || loaded && (!preferred || preferred===question?.id))) return;
    if(view && view!==next && !canLeave()) return;
    if(view!==next) {++requestId;loading=false;MisraMaterials.reset();MisraAnswerKeys.reset();dirty=false;}
    const changed=view!==next;
    view=next;$('native-authoring').hidden=next!=='questions';$('native-library').hidden=next!=='library';
    $('ledger-setup-checks').open=false;document.querySelector('.source-defaults').open=false;
    $('author-rubrics').setAttribute('aria-pressed',String(next==='questions'));$('manage-course-library').setAttribute('aria-pressed',String(next==='library'));
    if(next==='library') {MisraMaterials.mount($('library-material-host'));await MisraMaterials.load(exam.course_id,null,[]);}
    else if(!loaded || !rubric) await load(preferred);else if(changed || preferred && preferred!==question?.id) await choose(preferred || question?.id,true);
  }
  async function action(fn) {
    if(isBusy() || loading) return;
    const current=epoch;busy=true;failure='';setControls();
    try {await fn(current);}
    catch(e) {if(current===epoch) {failure=e.message;window.showToast(e.message,'error');}}
    finally {if(current===epoch) {busy=false;render();}}
  }
  async function save(approve) {
    if(!editable() || uncertain) return;
    try {validate();}catch(e) {failure=e.message;$('author-error').hidden=false;$('author-error').textContent=failure;$('author-error').scrollIntoView({block:'center'});window.showToast(e.message,'error');return;}
    if(approve && !confirm('Approve this rubric and scoring policy for future grading? Historical runs are unchanged. Answer keys and source approvals are separate.')) return;
    await action(async current=>{
      if(!question.id) {
        const body={approve_initial_rubric:false,question_number:question.question_number,question_text:question.question_text,max_score:rubric.max_score,language:question.language,criteria:rubric.criteria,policy:rubric.policy,grading_approach:rubric.policy.grading_approach,acceptable_answers:rubric.acceptable_answers,notes:rubric.notes,reference_context:rubric.reference_context};
        let result;
        try {result=await MisraAPI.createQuestion(exam.id,body);if(!result?.id && !result?.question?.id) throw new Error('Question response is incomplete.');}
        catch(e) {if(!e.status || e.status>=500) uncertain=true;throw e;}
        if(current!==epoch) return;dirty=false;loaded=false;notice='Question saved as a draft. Approve its marking foundations separately.';busy=false;await load(result.question?.id || result.id);
      } else {
        if(!version) {version=await MisraAPI.createRubricVersion(question.id,{rubric,source:'manual',change_summary:'Edited in assessment workspace.'});}
        else version=await MisraAPI.updateRubric(version.id,{rubric,change_summary:'Edited in assessment workspace.'});
        if(current!==epoch) return;dirty=false;notice='Draft saved — not used for grading.';
        if(approve) {try {await MisraAPI.approveRubric(version.id);}catch(e) {if(!e.status || e.status>=500) uncertain=true;throw e;}if(current!==epoch) return;version={...version,status:'approved'};notice='Rubric approved for future grading. Historical results are unchanged.';window.dispatchEvent(new CustomEvent('misra:rubric-approved'));}
        const list=await MisraAPI.rubricVersions(question.id);if(current!==epoch) return;versions=list;
      }
      window.dispatchEvent(new CustomEvent('misra:ledger-foundations-changed'));
    });
  }
  async function removeQuestion(){
    if(isBusy()||loading||uncertain||!deletable())return;
    const saved=Boolean(question?.id);
    const prompt=saved?'Delete this question and its draft guide? Unsaved edits will be discarded.':'Discard this unsaved question?';
    if(!confirm(MisraLocale.text(prompt)))return;
    let removed=false;
    await action(async current=>{
      if(saved){try{await MisraAPI.deleteQuestion(question.id);}catch(e){if(!e.status||e.status>=500)uncertain=true;throw e;}}
      if(current!==epoch)return;
      removed=true;dirty=false;MisraAnswerKeys.reset();MisraMaterials.reset();
      question=version=rubric=null;loaded=false;versions=[];blankDraft='';
      await load();
    });
    if(removed){window.showToast(MisraLocale.text(saved?'Question deleted.':'Unsaved question discarded.'),'success');window.dispatchEvent(new CustomEvent('misra:guide-question-removed'));window.dispatchEvent(new CustomEvent('misra:ledger-foundations-changed'));}
  }
  $('author-question').addEventListener('change',e=>choose(e.target.value));
  $('author-reload').addEventListener('click',()=>{if(canLeave()) {MisraMaterials.reset();MisraAnswerKeys.reset();load(question?.id);}});
  $('author-new-question').addEventListener('click',()=>{
    if(!canLeave()) return;if(!preferencesKnown){window.showToast('Reload marking settings before creating a draft.','error');return;}window.dispatchEvent(new CustomEvent('misra:guide-editor-opened'));MisraMaterials.reset();MisraAnswerKeys.reset();question={question_number:String(questions.length+1),question_text:'',language:'en'};version=null;versions=[];rubric=normalize({criteria:[{id:'criterion_'+crypto.randomUUID().replaceAll('-','').slice(0,12),title:'',description:'',points:1}]},1);applyProfile();blankDraft=JSON.stringify({question,rubric});dirty=true;failure='';notice=profile&&usePreferences?'Survey preferences applied. Review before approval.':'';render();$('author-question').value='';$('author-question-text').focus();
  });
  $('setup-overview').addEventListener('click',e=>{const b=e.target.closest('[data-author-question]');if(b) show('questions',b.dataset.authorQuestion);});
  $('rubric-workspace').addEventListener('input',e=>{if(editable() && e.target.matches('[data-rubric-edit]')) {sync();dirty=true;updateState();}});
  $('rubric-workspace').addEventListener('click',async e=>{
    const target=e.target.closest('button');if(!target || isBusy()) return;
    if(target.hasAttribute('data-author-delete')){await removeQuestion();return;}
    if(target.hasAttribute('data-author-survey-later')){sessionStorage.setItem(reminderKey(),'1');target.closest('.survey-reminder').remove();}
    if(target.hasAttribute('data-author-survey')){
      const untouchedNew=!question?.id&&blankDraft===JSON.stringify({question,rubric})&&!MisraAnswerKeys.hasUnsaved()&&!MisraMaterials.hasUnsaved();
      if(untouchedNew)dirty=false;
      if(untouchedNew||await saveEdits())location.assign(`marking-survey.html?return_exam_id=${encodeURIComponent(exam.id)}`);
    }
    if(target.hasAttribute('data-author-save')) save(false);
    if(target.hasAttribute('data-author-approve')) save(true);
    if(target.hasAttribute('data-author-add')) {sync();rubric.criteria.push(normalize({criteria:[{id:'criterion_'+crypto.randomUUID().replaceAll('-','').slice(0,12),title:'',description:'',points:1}]},1).criteria[0]);dirty=true;render();const added=$('rubric-workspace').querySelectorAll('[data-criterion-panel]')[rubric.criteria.length-1];added.open=true;$(`ac-${rubric.criteria.length-1}-title`).focus();}
    if(target.hasAttribute('data-author-remove')) {sync();const index=Number(target.dataset.authorRemove);rubric.criteria.splice(index,1);dirty=true;render();const next=$('rubric-workspace').querySelectorAll('[data-criterion-panel]')[Math.min(index,rubric.criteria.length-1)];(next?.querySelector('summary') || $('rubric-workspace').querySelector('[data-author-add]')).focus();}
    if(target.dataset.detailAdd || target.dataset.detailRemove) {sync();const c=rubric.criteria[Number(target.closest('[data-author-criterion]').dataset.authorCriterion)];if(target.dataset.detailAdd) c[target.dataset.detailAdd].push(target.dataset.detailAdd==='performance_levels' ? {label:'',description:'',points_earned:0} : {description:'',guidance:''});else c[target.dataset.detailRemove].splice(Number(target.dataset.detailIndex),1);dirty=true;render();const panel=$('rubric-workspace').querySelectorAll('[data-author-criterion]')[rubric.criteria.indexOf(c)].querySelector('details');panel.open=true;}
    if(target.hasAttribute('data-author-draft')) action(async current=>{const value=await MisraAPI.createRubricVersion(question.id,{rubric,source:'manual',apply_instructor_preferences:true,change_summary:'Instructor editing draft; saved account preference defaults requested.'});if(current!==epoch) return;version=value;rubric=normalize(value.rubric_json,question.max_score);versions.unshift(value);notice=profile&&usePreferences?'Survey preferences applied. Review before approval.':'Editable draft created. Review before approval.';});
    if(target.dataset.authorVersion) {if(!canLeave()) return;const selected=versions.find(v=>v.id===target.dataset.authorVersion);if(selected) {version=selected;rubric=normalize(selected.rubric_json,question.max_score);dirty=false;failure=notice='';render();}}
    if(target.hasAttribute('data-author-profile') && confirm('Replace this draft’s preference fields with your approved profile? Nothing is saved until you save or approve.')) {sync();for(const key of ['method_credit','alternative_methods_allowed','handwritten_syntax_policy','notation_policy','error_carried_forward','language_quality_policy','arithmetic_error_policy','units_policy','rounding_tolerance_percent','evidence_requirement','illegible_response_policy']) {const value=profile?.derived_proposal?.[key];if(value!=null) rubric.policy[key]=value;}const guidance=profile?.derived_proposal?.custom_instructions;if(guidance&&!rubric.policy.custom_instructions?.includes(guidance))rubric.policy.custom_instructions=[rubric.policy.custom_instructions,guidance].filter(Boolean).join('\n');dirty=true;render();}
    if(target.hasAttribute('data-author-mode')) {const selected=$('author-mode').value;action(async current=>{await MisraAPI.updateGradingPolicy(question.id,{mode:selected});if(current!==epoch) return;mode=selected;notice='Grading input saved separately for future jobs.';});}
  });
  $('rubric-workspace').addEventListener('submit',e=>{
    if(e.target.id!=='author-ai-form') return;e.preventDefault();if(isBusy()) return;
    if(dirty && !confirm('Generate an AI draft without saving the current rubric edits?')) return;
    const body=Object.fromEntries([...new FormData(e.target)].filter(([,v])=>String(v).trim()));body.grading_approach=rubric.policy.grading_approach;body.policy=clone(rubric.policy);
    action(async current=>{await MisraAPI.suggestRubric(question.id,body);if(current!==epoch) return;dirty=false;busy=false;await definitions(question.id);notice='AI draft created. It is not approved.';});
  });
  async function saveEdits(){
    if(isBusy() || uncertain)return false;
    if(dirty)await save(false);
    if(dirty || uncertain)return false;
    if(!await MisraAnswerKeys.saveDraft())return false;
    if(!await MisraMaterials.saveDraft())return false;
    return !hasUnsaved();
  }
  window.MisraLedgerEditors={reset,show,hasUnsaved,canLeave,isBusy,saveEdits,hide(){ $('native-authoring').hidden=true;$('native-library').hidden=true; }};
})();
