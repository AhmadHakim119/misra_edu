(function () {
  'use strict';

  const list = document.getElementById('instructor-list');
  const listCopy = document.getElementById('instructor-list-copy');
  const createForm = document.getElementById('create-instructor-form');
  const createMessage = document.getElementById('create-instructor-message');
  const escapeHTML = window.MisraUI.escapeHTML;
  let instructors = [];
  let openResetId = null;

  function formMessage(element, text, tone = '') {
    element.textContent = text;
    element.dataset.tone = tone;
  }

  function render() {
    listCopy.textContent = `${instructors.length} instructor account${instructors.length === 1 ? '' : 's'}`;
    if (!instructors.length) {
      list.innerHTML = window.MisraUI.emptyState('No instructor accounts yet', 'Create the first instructor account for this institution.', window.MisraUI.icons.instructors);
      return;
    }
    list.innerHTML = `<div class="instructor-list">${instructors.map((instructor) => `
      <article class="instructor-row" data-instructor-id="${escapeHTML(instructor.id)}">
        <div class="instructor-identity"><strong>${escapeHTML(instructor.full_name || instructor.email)}</strong><span>${escapeHTML(instructor.email)}</span></div>
        <div class="instructor-state">
          ${window.MisraUI.badge(instructor.is_active ? 'Active' : 'Disabled', instructor.is_active ? 'success' : 'danger')}
          ${instructor.must_change_password ? window.MisraUI.badge('Password change required', 'warning') : ''}
        </div>
        <div class="instructor-actions">
          <button class="btn btn-secondary" type="button" data-reset-toggle>${openResetId === instructor.id ? 'Cancel reset' : 'Reset password'}</button>
          <button class="btn btn-secondary" type="button" data-toggle-active>${instructor.is_active ? 'Disable' : 'Enable'}</button>
        </div>
        <form class="instructor-reset-form" data-reset-form ${openResetId === instructor.id ? '' : 'hidden'}>
          <div><strong>Set a temporary password</strong><p>The instructor will be signed out everywhere and must replace this password at next sign-in.</p></div>
          <div class="field"><label for="reset-${escapeHTML(instructor.id)}">Temporary password</label><input class="input" type="password" id="reset-${escapeHTML(instructor.id)}" name="temporary_password" minlength="10" maxlength="1024" autocomplete="new-password" required></div>
          <button class="btn btn-primary" type="submit">Apply reset</button>
        </form>
      </article>`).join('')}</div>`;
  }

  async function load() {
    try {
      const user = await window.MisraAPI.currentUser();
      if (user.role !== 'admin') throw Object.assign(new Error('Administrator access is required to manage instructor accounts.'), { status: 403 });
      instructors = await window.MisraAPI.instructors();
      render();
    } catch (error) {
      listCopy.textContent = 'Access unavailable';
      list.innerHTML = window.MisraUI.errorState(error.message || 'Could not load instructor accounts.');
    }
  }

  createForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    formMessage(createMessage, '');
    const values = Object.fromEntries(new FormData(createForm));
    values.full_name = values.full_name.trim();
    values.email = values.email.trim();
    if (!values.full_name || !values.email) {
      formMessage(createMessage, 'Enter the instructor’s name and institutional email.', 'error');
      return;
    }
    if (values.temporary_password.length < 10) {
      formMessage(createMessage, 'The temporary password must contain at least 10 characters.', 'error');
      return;
    }
    if (values.temporary_password !== values.confirm_password) {
      formMessage(createMessage, 'The temporary passwords do not match.', 'error');
      return;
    }
    const button = createForm.querySelector('[type="submit"]');
    button.disabled = true;
    button.textContent = 'Creating instructor…';
    try {
      const created = await window.MisraAPI.createInstructor({ full_name: values.full_name, email: values.email, temporary_password: values.temporary_password });
      instructors.push(created);
      instructors.sort((a, b) => (a.full_name || a.email).localeCompare(b.full_name || b.email));
      render();
      createForm.reset();
      formMessage(createMessage, 'Instructor created. Share the temporary password securely.', 'success');
    } catch (error) {
      formMessage(createMessage, error.message || 'Could not create the instructor.', 'error');
    } finally {
      button.disabled = false;
      button.textContent = 'Create instructor';
    }
  });

  list.addEventListener('click', async (event) => {
    const row = event.target.closest('[data-instructor-id]');
    if (!row) return;
    const instructor = instructors.find((item) => item.id === row.dataset.instructorId);
    if (!instructor) return;
    if (event.target.closest('[data-reset-toggle]')) {
      openResetId = openResetId === instructor.id ? null : instructor.id;
      render();
      if (openResetId) list.querySelector(`[data-instructor-id="${CSS.escape(openResetId)}"] input`)?.focus();
      return;
    }
    const toggle = event.target.closest('[data-toggle-active]');
    if (!toggle) return;
    const nextActive = !instructor.is_active;
    toggle.disabled = true;
    toggle.textContent = nextActive ? 'Enabling…' : 'Disabling…';
    try {
      const updated = await window.MisraAPI.updateInstructor(instructor.id, { is_active: nextActive });
      instructors = instructors.map((item) => item.id === updated.id ? updated : item);
      render();
      window.showToast(nextActive ? 'Instructor access enabled.' : 'Instructor access disabled and existing sessions closed.', 'success');
    } catch (error) {
      toggle.disabled = false;
      toggle.textContent = instructor.is_active ? 'Disable' : 'Enable';
      window.showToast(error.message || 'Could not update instructor access.', 'error');
    }
  });

  list.addEventListener('submit', async (event) => {
    const form = event.target.closest('[data-reset-form]');
    if (!form) return;
    event.preventDefault();
    const row = form.closest('[data-instructor-id]');
    const password = form.temporary_password.value;
    if (password.length < 10) {
      window.showToast('The temporary password must contain at least 10 characters.', 'error');
      return;
    }
    const button = form.querySelector('[type="submit"]');
    button.disabled = true;
    button.textContent = 'Resetting…';
    try {
      const updated = await window.MisraAPI.resetInstructorPassword(row.dataset.instructorId, { temporary_password: password });
      instructors = instructors.map((item) => item.id === updated.id ? updated : item);
      openResetId = null;
      render();
      window.showToast('Temporary password set. Existing sessions were closed.', 'success');
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Apply reset';
      window.showToast(error.message || 'Could not reset this password.', 'error');
    }
  });

  load();
})();
