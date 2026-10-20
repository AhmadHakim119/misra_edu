/* Public product introduction. Examples are local illustrations, never AI calls. */
(function(){
  'use strict';
  const $=id=>document.getElementById(id),en={dark:'Dark theme',light:'Light theme',captionRubric:'The approved criteria define the marks available.',captionPaper:'The original answer stays beside its extracted text and proposed marks.',captionReview:'The instructor reviews the proposal and decides the final mark.'};
  document.querySelectorAll('[data-copy]').forEach(el=>{en[el.dataset.copy]??=el.innerHTML;});
  const ar={
    skip:'انتقل إلى المحتوى',navWorkflow:'خطوات العمل',navControl:'دور المدرّس',navResearch:'البحث',signIn:'تسجيل الدخول',dark:'الوضع الداكن',light:'الوضع الفاتح',
    headline:'اختبارات بخط اليد.<br>تصحيح أوضح.',intro:'تصحيح بمساعدة الذكاء الاصطناعي، وفق دليل تصحيحك وبقرارك النهائي.',open:'افتح MISRA',explore:'تعرّف على خطوات العمل',
    illustrative:'مثال ببيانات اصطناعية',rubric:'دليل التصحيح',paper:'الورقة',review:'المراجعة',question:'السؤال',questionText:'احسب الشغل عندما تحرّك قوة مقدارها ٨٢ نيوتن جسمًا مسافة ٣ أمتار.',studentAnswer:'إجابة الطالب',rubricTitle:'دليل التصحيح <span>(درجتان)</span>',method:'الطريقة',methodRule:'استخدام قانون الشغل<br><bdi>W = F × d.</bdi>',result:'الناتج والوحدة',resultRule:'الناتج العددي الصحيح ووحدة الجول (J).',proposed:'الدرجة المقترحة',instructorReview:'مراجعة المدرّس',reviewNote:'الطريقة والناتج صحيحان مع كتابة الوحدة.',
    captionRubric:'تحدّد المعايير المعتمدة الدرجات المتاحة.',captionPaper:'تبقى الإجابة الأصلية بجانب النص المستخرج والدرجات المقترحة.',captionReview:'يراجع المدرّس المقترح ويقرّر الدرجة النهائية.',
    upload:'رفع الأوراق',viewGrade:'العرض والتصحيح',feedback:'التغذية الراجعة',workflowRubric:'أضف الأسئلة والمفتاح ومعايير التصحيح، ثم اعتمد الدليل.',workflowUpload:'ارفع الأوراق الممسوحة، وراجع النص المستخرج وبيانات الطلاب.',workflowGrade:'راجع الدرجات المقترحة بجانب العمل الأصلي. اقبلها أو عدّلها.',workflowFeedback:'راجع ملاحظات الصف وصدّر الدرجات المحفوظة.',
    rolesTitle:'ثلاثة أدوار.<br>والقرار للمدرّس.',rolesIntro:'خطوات واضحة تبقي الكتابة اليدوية وقواعد التصحيح وقرارك النهائي أمامك.',extraction:'الاستخراج',extractionBody:'يقرأ الكتابة اليدوية ويربط الإجابات بالأسئلة. يمكنك مراجعة الأصل وتصحيح أخطاء الاستخراج.',assessment:'التقييم',assessmentBody:'يقترح الدرجات باستخدام الدليل المعتمد ومفتاح الإجابة وقواعد التصحيح وأدلة المقرر المناسبة.',verification:'التحقق',verificationBody:'يراجع المقترح وفق الأدلة نفسها ويشير إلى النقاط التي تستدعي مراجعة المدرّس.',
    controlTitle:'مقرّرك.<br>معاييرك.<br>وقرارك النهائي.',controlIntro:'سياق المقرر جزء من التقييم. والقرار النهائي لك.',courseTitle:'محتوى المقرر معك.',courseBody:'أضف الكتب والفصول مرة واحدة. حدّد فصول كل اختبار وأضف المواد الإضافية عند الحاجة.',evidenceTitle:'الأدلة أمامك.',evidenceBody:'راجع الصفحة الأصلية والنص المستخرج ودرجات المعايير ومقاطع المصادر معًا.',decisionTitle:'قرار واضح ومحفوظ.',decisionBody:'اقبل المقترح أو عدّل الدرجات والملاحظات. يحفظ سجل التصحيح تشغيل الذكاء الاصطناعي الأصلي وقرارات المدرّس.',
    researchTitle:'للتدريس.<br>وللبحث المتأنّي.',researchIntro:'MISRA نموذج محلي لمشروع تخرّج يدرس اتفاق التصحيح بين المدرّس والذكاء الاصطناعي وفائدة استرجاع محتوى المقرر المعتمد.',researchBody:'يستخدم استرجاع المقرر BM25 ضمن مقاطع معتمدة ومحدّدة. يقارن التقييم الدرجات المقترحة بدرجات مستقلة للمدرّس ويدرس أثر أدلة المقرر.',researchNote:'ثقة النموذج غير معايرة. الاستشهادات ونجاح اختبارات البرمجيات لا يثبتان دقة التصحيح.',
    faqTitle:'ما تحتاج إلى معرفته.',faqQ1:'من يقرّر الدرجة النهائية؟',faqA1:'المدرّس. يقترح MISRA الدرجات والتفسيرات، ويراجع المدرّس قراره ويعدّله ويحفظه.',faqQ2:'هل يدعم العربية والإنجليزية؟',faqA2:'تدعم واجهة المدرّس العربية والإنجليزية والاتجاه من اليمين إلى اليسار. وتبقى الإجابات المستخرجة بلغتها الأصلية للمراجعة.',faqQ3:'هل أحتاج إلى فهم إعدادات الذكاء الاصطناعي؟',faqA3:'خطواتك هي إعداد الدليل ورفع الأوراق والمراجعة والتغذية الراجعة. تُدار إعدادات النماذج بشكل منفصل عن مهمة المدرّس.',faqQ4:'أين تتم المعالجة؟',faqA4:'يعمل هذا النموذج محليًا باستخدام مهام خلفية وخدمات ذكاء اصطناعي مُعدّة مسبقًا. قد تستقبل هذه الخدمات محتوى الاختبار. استخدم مواد اصطناعية أو منقّحة للعرض التجريبي.',closingTitle:'ابدأ بدليل تصحيحك.',footer:'الذكاء الاصطناعي يقترح. والمدرّس يقرّر.'
  };
  function read(key,fallback){try{return localStorage.getItem(key)||fallback;}catch(_){return fallback;}}
  let lang=read('misra-language','en')==='ar'?'ar':'en',theme=read('misra-theme','system');
  const media=matchMedia('(prefers-color-scheme: dark)');
  function persist(key,value){try{localStorage.setItem(key,value);}catch(_){/* The current page remains usable without device storage. */}}
  function apply(){
    document.documentElement.lang=lang;document.documentElement.dir=lang==='ar'?'rtl':'ltr';
    const dark=theme==='dark'||theme==='system'&&media.matches;document.documentElement.dataset.theme=dark?'dark':'light';
    $('landing-theme').dataset.copy=dark?'light':'dark';
    document.querySelectorAll('[data-copy]').forEach(el=>{const key=el.dataset.copy;el.innerHTML=lang==='ar'?(ar[key]||en[key]):en[key];});
    $('landing-language').textContent=lang==='ar'?'English':'العربية';$('landing-language').setAttribute('aria-label',lang==='ar'?'Switch to English':'التبديل إلى العربية');
    $('example').setAttribute('aria-label',lang==='ar'?'مثال تصحيح ببيانات اصطناعية':'Synthetic grading example');
    document.title=lang==='ar'?'MISRA EDU · اختبارات بخط اليد. تصحيح أوضح.':'MISRA EDU · Handwritten exams. Clearer grading.';
  }
  $('landing-language').addEventListener('click',()=>{lang=lang==='ar'?'en':'ar';persist('misra-language',lang);apply();});
  $('landing-theme').addEventListener('click',()=>{theme=document.documentElement.dataset.theme==='dark'?'light':'dark';persist('misra-theme',theme);apply();});
  document.querySelectorAll('.example-switch button').forEach(button=>button.addEventListener('click',()=>{
    const stage=button.dataset.stage;$('example').dataset.stage=stage;
    document.querySelectorAll('.example-switch button').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
    $('example-caption').dataset.copy='caption'+stage[0].toUpperCase()+stage.slice(1);apply();
  }));
  media.addEventListener('change',()=>{if(theme==='system')apply();});
  window.addEventListener('storage',event=>{if(['misra-theme','misra-language'].includes(event.key)){lang=read('misra-language','en')==='ar'?'ar':'en';theme=read('misra-theme','system');apply();}});
  apply();$('landing-language').hidden=false;$('landing-theme').hidden=false;document.querySelector('.example-switch').hidden=false;
})();
