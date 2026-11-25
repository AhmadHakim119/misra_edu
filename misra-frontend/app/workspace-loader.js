/* Mount the shared ledger content without replacing the workspace shell. */
MisraWorkspace.mounting = (async function () {
  'use strict';
  const page = MisraWorkspace.page;
  const route = document.body.dataset.workspacePage;
  const url = MisraWorkspace.currentURL();
  if (route === 'dashboard' && !url.searchParams.has('exam_id')) {
    location.replace('dashboard.html');
    return;
  }

  const views = {setup: 'setup', upload: 'upload', grading: 'papers', results: 'export', feedback: 'insights'};
  window.MisraWorkspacePage = route;
  if (views[route]) {
    url.searchParams.set('view', views[route]);
    MisraWorkspace.replaceRoute(url);
  }

  async function templateDocument() {
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const response = await fetch('workspace-template.html', {cache: 'no-store', signal: page.signal});
        if (!response.ok) throw Error('The workspace could not load. Reload to retry.');
        return new DOMParser().parseFromString(await response.text(), 'text/html');
      } catch (error) {
        if (page.signal.aborted || attempt) throw error;
        await new Promise(resolve => setTimeout(resolve, 200));
      }
    }
  }

  try {
    const template = MisraWorkspace.preparedTemplate || await templateDocument();
    if (page.signal.aborted) return;
    MisraWorkspace.replacePageContent(template, false);
    const nav = document.createElement('nav');
    nav.className = 'exam-navigation';
    nav.id = 'native-exam-navigation';
    nav.setAttribute('aria-label', 'Exam workflow');
    document.querySelector(route === 'grading' ? '.ledger-layout' : 'main').prepend(nav);
    MisraWorkspace.addStyles(template);
    for (const script of template.head.querySelectorAll('script[src]')) {
      await MisraWorkspace.loadScript(script.getAttribute('src').split('?')[0], page);
    }
    await MisraWorkspace.loadScript('workspace-navigation.js', page);
    window.MisraLocale?.apply();
  } catch (error) {
    if (!page.signal.aborted) MisraWorkspace.showLoadError(error.message);
  }
})();
