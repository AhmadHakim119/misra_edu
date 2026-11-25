/* The authenticated workspace keeps its header while route controllers mount and dispose. */
(function () {
  'use strict';

  const mainRoutes = {
    dashboard: 'Dashboard', assessments: 'Exams', 'course-library': 'Course library',
    reviews: 'Review', activity: 'Activity', account: 'Settings', admin: 'Administration'
  };
  const examRoutes = ['setup', 'upload', 'extraction', 'grading', 'feedback', 'results', 'identities'];
  const parentPages = {
    ...Object.fromEntries(examRoutes.map(name => [name, 'assessments'])),
    index: 'assessments', history: 'reviews', evaluation: 'reviews', pilot: 'reviews',
    'marking-survey': 'account'
  };
  const ledgerRoutes = new Set(['index', 'setup', 'upload', 'grading', 'feedback', 'results']);
  const softNavigation = 'NavigationPrecommitController' in window;
  const appRoot = new URL('./', document.currentScript.src);
  const recordParam = name => name === 'id' || name.endsWith('_id') || name === 'rubric_question';
  let recordContext = null;
  function routeURL(href, state) {
    const url = new URL(href, location.href);
    const context = state?.misraRecordContext;
    if (context?.path === url.pathname) {
      for (const [name, value] of new URLSearchParams(context.query)) {
        if (recordParam(name) && !url.searchParams.has(name)) url.searchParams.set(name, value);
      }
    }
    return url;
  }
  const currentURL = () => routeURL(location.href, history.state);

  function replaceRoute(href) {
    const url = new URL(href, location.href);
    if (!routeName(url)) return;
    const query = new URLSearchParams();
    for (const [name, value] of [...url.searchParams]) {
      if (!recordParam(name)) continue;
      query.set(name, value);
      url.searchParams.delete(name);
    }
    const context = query.size ? {path: url.pathname, query: query.toString()} : null;
    const previous = history.state?.misraRecordContext;
    recordContext = context;
    if (location.href === url.href && previous?.path === context?.path && previous?.query === context?.query) return;
    // Keep record selections private to this history entry, including reload and traversal.
    history.replaceState({...history.state, misraRecordContext: context}, '', url);
    const entry = window.navigation?.currentEntry;
    if (entry) window.navigation.updateCurrentEntry({state: {...entry.getState(), misraRecordContext: context}});
  }

  window.addEventListener('hashchange', event => {
    const before = new URL(event.oldURL), after = new URL(event.newURL);
    if (!history.state?.misraRecordContext && before.pathname === after.pathname &&
        before.search === after.search && recordContext?.path === after.pathname) {
      replaceRoute(routeURL(after, {misraRecordContext: recordContext}));
    }
  });
  function routeName(url) {
    if (url.origin !== appRoot.origin || !url.pathname.startsWith(appRoot.pathname)) return null;
    const file = url.pathname.slice(appRoot.pathname.length) || 'index.html';
    if (!file.endsWith('.html')) return null;
    const name = file.slice(0, -5);
    return Object.hasOwn(mainRoutes, name) || Object.hasOwn(parentPages, name) ? name : null;
  }

  const initialNodes = [...document.body.childNodes];
  const outlet = document.createElement('div');
  outlet.id = 'workspace-content';
  outlet.append(...initialNodes);
  const header = document.createElement('header');
  header.className = 'app-bar workspace-header';
  header.innerHTML = `<a class="brand" href="dashboard.html" aria-label="MISRA EDU home"><img class="logo-light" src="../assets/logo-transparent.png" alt="MISRA EDU"><img class="logo-dark" src="../assets/logo-white.png" alt="" aria-hidden="true"></a>
    <nav aria-label="Workspace"><span class="workspace-selection" aria-hidden="true" hidden></span></nav>
    <div class="account"><button id="app-theme" type="button">Dark theme</button><button id="native-sign-out" type="button">Sign out</button></div>`;
  const nav = header.querySelector('nav');
  for (const [name, title] of Object.entries(mainRoutes)) {
    const anchor = document.createElement('a');
    anchor.href = name + '.html';
    anchor.dataset.route = name;
    anchor.textContent = title;
    anchor.hidden = name === 'admin';
    nav.append(anchor);
  }
  const indicator = nav.querySelector('.workspace-selection');
  const theme = header.querySelector('#app-theme');
  const signOut = header.querySelector('#native-sign-out');
  const notice = document.createElement('p');
  notice.className = 'workspace-route-notice';
  notice.setAttribute('role', 'status');
  notice.hidden = true;
  document.body.classList.add('workspace-app');
  document.body.append(header, notice, outlet);

  function ask(message, {title='Confirm action', action='Continue', field=''}={}) {
    const dismissed=field?null:false;
    if (document.querySelector('.workspace-dialog[open]')) return Promise.resolve(dismissed);
    const signal=page.signal;
    if(signal.aborted)return Promise.resolve(dismissed);
    const dialog = document.createElement('dialog');
    dialog.className = 'workspace-dialog';
    dialog.setAttribute('aria-labelledby','workspace-dialog-title');
    dialog.setAttribute('aria-describedby','workspace-dialog-description');
    dialog.innerHTML = `<form method="dialog" novalidate><h2 id="workspace-dialog-title"></h2><p id="workspace-dialog-description"></p>
      <label hidden><span></span><input type="text" maxlength="500" aria-describedby="workspace-dialog-error"></label><p id="workspace-dialog-error" role="alert" hidden></p>
      <div class="workspace-dialog-actions"><button type="submit" value="cancel" formnovalidate autofocus>Cancel</button>
      <button type="submit" value="confirm" class="primary"></button></div></form>`;
    const input=dialog.querySelector('input'), form=dialog.querySelector('form');
    dialog.querySelector('h2').textContent=translate(title);
    dialog.querySelector('p').textContent=translate(message);
    dialog.querySelector('[value=confirm]').textContent=translate(action);
    const label=input.closest('label');
    label.hidden=!field;
    input.disabled=!field;
    input.required=Boolean(field);
    label.querySelector('span').textContent=translate(field);
    const origin=document.activeElement;
    document.body.append(dialog);
    return new Promise(resolve=>{
      const abort=()=>dialog.close('cancel');
      signal.addEventListener('abort',abort,{once:true});
      dialog.addEventListener('close',()=>{
        signal.removeEventListener('abort',abort);
        const value=!signal.aborted && dialog.returnValue==='confirm' ? (field ? input.value.trim() : true) : dismissed;
        dialog.remove();
        if(!signal.aborted && origin?.isConnected)origin.focus({preventScroll:true});
        resolve(value);
      },{once:true});
      form.addEventListener('submit',event=>{
        if(field && event.submitter?.value==='confirm' && !input.value.trim()){
          event.preventDefault();input.setAttribute('aria-invalid','true');input.focus();
          const error=dialog.querySelector('#workspace-dialog-error');
          error.textContent=translate('Enter a value to continue.');error.hidden=false;
        }
      });
      input.addEventListener('keydown',event=>{
        if(event.key==='Enter' && !event.isComposing){event.preventDefault();form.requestSubmit(form.querySelector('[value=confirm]'));}
      });
      input.addEventListener('input',()=>{
        input.removeAttribute('aria-invalid');dialog.querySelector('#workspace-dialog-error').hidden=true;
      });
      dialog.showModal();
      if(field)input.focus();
    });
  }

  function createPage() {
    const controller = new AbortController();
    const timers = new Set(), guards = [];
    const signal = controller.signal;
    return {
      signal,
      listen(target, type, listener, options) {
        const settings = typeof options === 'boolean' ? {capture: options} : options;
        target.addEventListener(type, listener, {...settings, signal});
      },
      later(callback, delay) {
        if (signal.aborted) return;
        const id = setTimeout(() => {
          timers.delete(id);
          callback();
        }, delay);
        timers.add(id);
        return id;
      },
      cancelTimer(id) {
        clearTimeout(id);
        timers.delete(id);
      },
      guard(isBusy, hasUnsaved) {
        guards.push({isBusy, hasUnsaved});
      },
      needsLeaveCheck() { return guards.some(guard => guard.isBusy() || guard.hasUnsaved()); },
      async canLeave() {
        if (guards.some(guard => guard.isBusy())) {
          announce('Wait for the current operation to finish.');
          return false;
        }
        return !guards.some(guard => guard.hasUnsaved())
          || await ask('Leave without saving your changes?', {title:'Discard unsaved changes?',action:'Leave page'});
      },
      result(value) {
        if (typeof value?.then !== 'function') return value;
        // A completed read from a disposed route must never resume that route's controller.
        return new Promise((resolve, reject) => {
          value.then(result => { if (!signal.aborted) resolve(result); },
            error => { if (!signal.aborted) reject(error); });
        });
      },
      dispose() {
        controller.abort();
        timers.forEach(clearTimeout);
        timers.clear();
      }
    };
  }

  let page = createPage();
  let rendered = currentURL();
  let preparedTemplate;
  let entryKey = window.navigation?.currentEntry?.key;
  let restoreKey = null;
  let booting = true, changing = false, leavingSession = false;
  let api, selectionFrame;
  const assetRetries = new Map();
  const pageGlobals = [
    'MisraApp', 'MisraCurrentUser', 'MisraWorkspacePage', 'MisraLedger', 'MisraLedgerWorkflows',
    'MisraLedgerEditors', 'MisraLedgerExport', 'MisraAssessmentGuide', 'MisraAssessmentSources',
    'MisraAnswerKeys', 'MisraMaterials', 'MisraTeaching', 'MisraInstructorPreferences',
    'MisraPaperHighlights', 'MisraExtraction'
  ];

  function translate(message) {
    return window.MisraLocale?.text(message) || message;
  }

  function announce(message) {
    notice.textContent = translate(message);
    notice.hidden = !message;
  }

  function positionSelection() {
    const target = nav.querySelector('[aria-current]');
    indicator.hidden = !target || target.hidden;
    if (indicator.hidden) return;
    const region = nav.getBoundingClientRect(), link = target.getBoundingClientRect();
    indicator.style.setProperty('--selection-x', `${link.left - region.left}px`);
    indicator.style.setProperty('--selection-y', `${link.top - region.top}px`);
    indicator.style.width = `${link.width}px`;
    indicator.style.height = `${link.height}px`;
  }

  function selectRoute(url) {
    const name = routeName(url);
    const section = name === 'index' && !url.searchParams.has('exam_id') ? 'dashboard' : (parentPages[name] || name);
    for (const link of nav.querySelectorAll('[data-route]')) {
      if (link.dataset.route === section) {
        link.setAttribute('aria-current', name === section ? 'page' : 'location');
      } else {
        link.removeAttribute('aria-current');
      }
    }
    const ledger = ledgerRoutes.has(name) && (name !== 'index' || url.searchParams.has('exam_id'));
    theme.id = ledger ? 'theme' : 'app-theme';
    signOut.id = ledger ? 'sign-out' : 'native-sign-out';
    positionSelection();
    cancelAnimationFrame(selectionFrame);
    selectionFrame = requestAnimationFrame(() => {
      positionSelection();
      nav.classList.add('workspace-nav-ready');
    });
  }

  new ResizeObserver(() => {
    document.documentElement.style.setProperty('--app-bar-height', `${header.offsetHeight}px`);
    positionSelection();
  }).observe(header);
  document.fonts?.ready.then(positionSelection);
  window.addEventListener('misra:language', () => {
    refreshThemeLabel();
    requestAnimationFrame(positionSelection);
  });

  function refreshThemeLabel() {
    const dark = document.documentElement.dataset.theme === 'dark';
    const label = dark ? 'Light theme' : 'Dark theme';
    theme.textContent = label;
    if (theme.id === 'theme') theme.setAttribute('aria-label', translate(dark ? 'Switch to light theme' : 'Switch to dark theme'));
    else theme.removeAttribute('aria-label');
    window.MisraLocale?.apply();
  }
  theme.addEventListener('click', () => {
    window.MisraTheme?.set(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    refreshThemeLabel();
  });
  const themeObserver = new MutationObserver(refreshThemeLabel);
  themeObserver.observe(document.documentElement, {attributeFilter: ['data-theme']});

  signOut.addEventListener('click', async () => {
    if (booting || changing || leavingSession || !window.MisraAPI || !await page.canLeave()) return;
    leavingSession = true;
    signOut.disabled = true;
    try {
      await window.MisraAPI.logout();
      page.dispose();
      outlet.replaceChildren();
      location.replace('login.html');
    } catch {
      leavingSession = false;
      signOut.disabled = false;
      announce('Could not sign out. Try again.');
    }
  });

  function scopeAPI() {
    api ||= window.MisraAPI;
    const owner = page;
    window.MisraAPI = new Proxy(api, {
      get(target, property) {
        const value = target[property];
        return typeof value === 'function' ? (...args) => {
          if (owner.signal.aborted) return;
          return owner.result(value.apply(target, args));
        } : value;
      }
    });
  }

  const stableScripts = new Set(['../js/app.js', '../js/api.js', 'locale.js', 'workspace-shell.js']);
  const stableStyles = new Set(['ledger.css', 'app.css', 'workspace-shell.css']);
  const scriptKey = source => source.split('?')[0];
  const usedScripts = new Set(['workspace-shell.js']);
  document.addEventListener('DOMContentLoaded', async () => {
    await window.MisraWorkspace.mounting;
    for (const source of ['../js/app.js', '../js/api.js', 'locale.js']) {
      if (document.head.querySelector(`script[src^="${source}"]`)) usedScripts.add(source);
    }
    refreshThemeLabel();
    booting = false;
  }, {once: true});

  function assertLocalAsset(source, extension) {
    const url = new URL(source, appRoot);
    if (url.origin !== appRoot.origin || url.username || url.password || !url.pathname.endsWith(extension)) {
      throw Error('The workspace could not load. Refresh to retry.');
    }
    return url;
  }

  function assetURL(source, extension) {
    const url = assertLocalAsset(source, extension);
    const retry = assetRetries.get(url.href);
    if (retry) url.searchParams.set('_misra_retry', retry);
    return url;
  }

  async function loadScript(source, owner = page) {
    if (owner.signal.aborted) return;
    const key = scriptKey(source);
    if (stableScripts.has(key) && usedScripts.has(key)) return;
    const canonical = assertLocalAsset(source, '.js');
    const address = assetRetries.has(canonical.href) ? assetURL(source, '.js').href : source;
    for (let attempt = 0; attempt < 2; attempt++) {
      const script = document.createElement('script');
      script.src = address;
      if (!stableScripts.has(key)) script.dataset.workspaceScript = '';
      try {
        await new Promise((resolve, reject) => {
          script.onload = resolve;
          script.onerror = () => reject(Error('A workspace module failed to load. Reload to retry.'));
          document.head.append(script);
        });
        if (stableScripts.has(key)) usedScripts.add(key);
        return;
      } catch (error) {
        script.remove();
        if (owner.signal.aborted || attempt) throw error;
        await new Promise(resolve => setTimeout(resolve, 200));
      } finally {
        script.onload = script.onerror = null;
      }
    }
  }

  function addStyles(source) {
    for (const link of source.head.querySelectorAll('link[rel="stylesheet"][href]')) {
      const href = link.getAttribute('href');
      const key = scriptKey(href);
      const font = href.startsWith('https://fonts.googleapis.com/css2?');
      const url = font ? new URL(href) : assetURL(href, '.css');
      if ([...document.styleSheets].some(sheet => sheet.href && scriptKey(sheet.href) === scriptKey(url.href))
          || [...document.head.querySelectorAll('link[rel="stylesheet"]')].some(sheet => sheet.href === url.href)) continue;
      const stylesheet = document.createElement('link');
      stylesheet.rel = 'stylesheet';
      stylesheet.href = url.href;
      if (!font && !stableStyles.has(key)) stylesheet.dataset.workspaceStyle = '';
      document.head.append(stylesheet);
    }
  }

  for (const link of document.head.querySelectorAll('link[rel="stylesheet"]')) {
    if (!stableStyles.has(scriptKey(link.getAttribute('href'))) && new URL(link.href).origin === location.origin) link.dataset.workspaceStyle = '';
  }
  for (const script of document.head.querySelectorAll('script[src]')) {
    if (!stableScripts.has(scriptKey(script.getAttribute('src')))) script.dataset.workspaceScript = '';
  }

  function setUser(user) {
    nav.querySelector('[data-route="admin"]').hidden = user.role !== 'admin' || user.must_change_password;
    positionSelection();
  }

  function replacePageContent(source, syncAttributes = true) {
    // Workspace templates contain trusted local markup. Runtime scripts are loaded separately.
    const nodes = [...source.body.childNodes].filter(node => node.nodeName !== 'SCRIPT');
    outlet.replaceChildren(...nodes.map(node => document.importNode(node, true)));
    if (syncAttributes) {
      for (const key of Object.keys(document.body.dataset)) delete document.body.dataset[key];
      Object.assign(document.body.dataset, source.body.dataset);
    }
  }

  function showLoadError(message) {
    const region = document.createElement('main');
    region.className = 'page-main workspace-error-panel';
    const error = document.createElement('p');
    error.setAttribute('role', 'alert');
    error.textContent = translate(message);
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.textContent = translate('Refresh');
    retry.addEventListener('click', () => location.reload());
    region.append(error, retry);
    outlet.replaceChildren(region);
  }

  function setChanging(value) {
    changing = value;
    outlet.inert = value;
    outlet.setAttribute('aria-busy', String(value));
  }

  function isSoftLink(event) {
    if (!softNavigation || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
    const link = event.target.closest('a[href]');
    if (!link || link.hasAttribute('download') || link.target && link.target !== '_self') return false;
    const url = new URL(link.href);
    if (!routeName(url) || url.searchParams.get('required') === '1') return false;
    return url.pathname !== location.pathname || url.search !== location.search || !url.hash;
  }

  // Anchor clicks are checked before the browser starts navigation. Programmatic
  // transitions after saved operations already check their own prerequisites.
  document.addEventListener('click', event => {
    if(event.defaultPrevented || event.button!==0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)return;
    const link=event.target.closest('a[href]');
    if(!link || link.hasAttribute('download') || link.target && link.target!=='_self')return;
    const url=new URL(link.href);
    if(url.pathname===location.pathname && url.search===location.search && url.hash)return;
    if(!['http:','https:'].includes(url.protocol))return;
    if (booting || changing || leavingSession || page.needsLeaveCheck()) {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (booting || changing || leavingSession) return;
      const origin=page, destination=url.href;
      origin.canLeave().then(allowed=>{ if(allowed && page===origin)location.assign(destination); });
    }
  }, true);

  window.addEventListener('pagehide', event => {
    page.dispose();
    if (event.persisted) outlet.hidden = true;
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted) location.reload();
  });

  async function readPage(url, signal) {
    const response = await fetch(url, {cache: 'no-store', credentials: 'same-origin', redirect: 'error', signal});
    if (!response.ok || !response.headers.get('Content-Type')?.includes('text/html')) {
      throw Error('The workspace could not load. Refresh to retry.');
    }
    const source = new DOMParser().parseFromString(await response.text(), 'text/html');
    if (!source.body.querySelector('main')) throw Error('The workspace could not load. Refresh to retry.');
    return source;
  }

  function preloadAsset(source, type, signal, links) {
    signal.throwIfAborted();
    const extension = type === 'script' ? '.js' : '.css';
    const canonical = assertLocalAsset(source, extension).href;
    const href = assetURL(source, extension).href;
    if (links.has(href)) return links.get(href).ready;
    const link = document.createElement('link');
    link.rel = 'preload';
    link.as = type;
    link.href = href;
    const ready = new Promise((resolve, reject) => {
      const finish = error => {
        signal.removeEventListener('abort', abort);
        link.onload = link.onerror = null;
        if (error) reject(error);
        else resolve();
      };
      const abort = () => finish(signal.reason);
      link.onload = () => finish();
      link.onerror = () => {
        // Browsers can retain a failed preload for a URL within the same document.
        assetRetries.set(canonical, (assetRetries.get(canonical) || 0) + 1);
        finish(Error('The workspace could not load. Refresh to retry.'));
      };
      signal.addEventListener('abort', abort, {once: true});
      document.head.append(link);
    });
    links.set(href, {link, ready});
    return ready;
  }

  async function preparePage(url, signal) {
    const source = await readPage(url, signal);
    const hasLedger = !!source.head.querySelector('script[src="workspace-loader.js"]');
    const template = hasLedger ? await readPage(new URL('workspace-template.html', appRoot), signal) : null;
    const scripts = [...source.head.querySelectorAll('script[src]')].map(node => node.getAttribute('src'));
    if (template) {
      scripts.push(...[...template.head.querySelectorAll('script[src]')].map(node => scriptKey(node.getAttribute('src'))));
      scripts.push('workspace-navigation.js');
    }
    const links = new Map();
    const dispose = () => links.forEach(({link}) => link.remove());
    try {
      const pending = scripts.filter(src => !usedScripts.has(scriptKey(src)))
        .map(src => preloadAsset(src, 'script', signal, links));
      for (const doc of [source, template].filter(Boolean)) {
        for (const element of doc.head.querySelectorAll('link[rel="stylesheet"][href]')) {
          const href = element.getAttribute('href');
          if (href.startsWith('https://fonts.googleapis.com/css2?') || stableStyles.has(scriptKey(href))) continue;
          pending.push(preloadAsset(href, 'style', signal, links));
        }
      }
      await Promise.all(pending);
      signal.addEventListener('abort', dispose, {once: true});
      return {source, template, dispose};
    } catch (error) {
      dispose();
      throw error;
    }
  }

  function fragmentTarget(hash) {
    try {
      return document.getElementById(decodeURIComponent(hash.slice(1)));
    } catch {
      return null;
    }
  }

  let loadingRoute = null;
  function startNavigation(owner) {
    loadingRoute = owner;
    setChanging(true);
    announce('');
  }

  function finishNavigation(owner) {
    if (loadingRoute !== owner) return;
    setChanging(false);
    loadingRoute = null;
  }

  async function mount(prepared, destination, event) {
    const {source, template} = prepared;
    page.dispose();
    pageGlobals.forEach(key => { delete window[key]; });
    document.head.querySelectorAll('[data-workspace-script],[data-workspace-style]').forEach(node => node.remove());
    page = createPage();
    rendered = destination;
    replaceRoute(destination);
    entryKey = window.navigation.currentEntry.key;
    selectRoute(destination);
    replacePageContent(source);
    document.title = source.title;
    document.body.style.overflow = '';
    signOut.disabled = false;
    announce('');
    preparedTemplate = template;
    try {
      addStyles(source);
      for (const node of source.head.querySelectorAll('script[src]')) {
        await loadScript(node.getAttribute('src'));
        if (node.getAttribute('src') === 'workspace-loader.js') await window.MisraWorkspace.mounting;
      }
      window.MisraTheme?.apply();
      refreshThemeLabel();
      window.MisraLocale?.apply();
      finishNavigation(event);
      const target = destination.hash ? fragmentTarget(destination.hash) : null;
      if (target) target.scrollIntoView();
      else if (event.navigationType !== 'traverse') window.scrollTo(0, 0);
      const focus = target || outlet.querySelector('h1, main');
      if (focus && !outlet.contains(document.activeElement)) {
        if (!focus.hasAttribute('tabindex')) focus.tabIndex = -1;
        focus.focus({preventScroll: true});
      }
    } catch {
      showLoadError('A workspace module failed to load. Reload to retry.');
    } finally {
      preparedTemplate = null;
      prepared.dispose();
      finishNavigation(event);
    }
  }

  async function restoreEntry() {
    restoreKey = entryKey;
    try {
      await window.navigation.traverseTo(entryKey).finished;
    } catch {
      location.reload();
    }
  }

  function navigate(event) {
    const traverse = event.navigationType === 'traverse';
    const original = new URL(event.destination.url);
    const destination = routeURL(original, traverse ? event.destination.getState() : null);
    const name = routeName(destination);
    if (!name || !event.canIntercept || event.hashChange || event.downloadRequest !== null
        || event.formData || event.navigationType === 'reload') return;
    if (name === 'account' && destination.searchParams.get('required') === '1') return;
    if (!traverse && event.destination.sameDocument) return; // In-page URL updates use replaceState.
    if (restoreKey === event.destination.key) {
      restoreKey = null;
      event.intercept();
      return;
    }
    if (booting && routeName(rendered) === 'index' && !rendered.searchParams.has('exam_id')) return;
    if (booting || changing || leavingSession) {
      if (event.cancelable) event.preventDefault();
      else if (event.destination.sameDocument && entryKey) {
        event.intercept({handler: restoreEntry});
      }
      return;
    }
    if (traverse && !event.destination.sameDocument) return;
    if (traverse && destination.pathname === rendered.pathname && destination.search === currentURL().search) return;
    if (name === 'index' && !destination.searchParams.has('exam_id')) destination.pathname = appRoot.pathname + 'dashboard.html';
    let prepared;
    const options = {
      ...(event.cancelable ? {async precommitHandler(commit) {
        if (traverse && page.needsLeaveCheck() && !await page.canLeave()) throw new DOMException('Navigation canceled', 'AbortError');
        startNavigation(event);
        try {
          prepared = await preparePage(destination, event.signal);
          if (destination.pathname !== original.pathname) commit.redirect(destination.href);
        } catch (error) {
          finishNavigation(event);
          if (!event.signal.aborted) announce('The page could not load. Try opening it again.');
          throw error;
        }
      }} : {}),
      async handler() {
        if (!prepared) {
          if (traverse && page.needsLeaveCheck() && !await page.canLeave()) { await restoreEntry(); return; }
          startNavigation(event);
          try { prepared = await preparePage(destination, event.signal); }
          catch {
            finishNavigation(event);
            if (!event.signal.aborted) {
              await restoreEntry();
              announce('The page could not load. Try opening it again.');
            }
            return;
          }
        }
        await mount(prepared, destination, event);
      },
      focusReset: 'manual',
      scroll: traverse ? 'after-transition' : 'manual'
    };
    event.intercept(options);
  }

  replaceRoute(rendered);
  selectRoute(rendered);
  window.MisraWorkspace = {
    get page() { return page; },
    get preparedTemplate() { return preparedTemplate; },
    currentURL, replaceRoute, replacePageContent, loadScript, addStyles, scopeAPI, showLoadError, setUser, refreshThemeLabel, isSoftLink, confirm:ask
  };
  if (softNavigation) window.navigation?.addEventListener('navigate', navigate);
})();
