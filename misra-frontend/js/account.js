(function () {
  'use strict';

  const facts = document.getElementById('account-facts');
  const requiredNotice = document.getElementById('password-required');
  const form = document.getElementById('change-password-form');
  const message = document.getElementById('change-password-message');

  function setMessage(text, tone = '') {
    message.textContent = text;
    message.dataset.tone = tone;
  }

  window.MisraAPI.currentUser().then((user) => {
    facts.innerHTML = `
      <div><dt>Name</dt><dd>${window.MisraUI.escapeHTML(user.full_name || 'Not recorded')}</dd></div>
      <div><dt>Email</dt><dd>${window.MisraUI.escapeHTML(user.email)}</dd></div>
      <div><dt>Access</dt><dd>${user.role === 'admin' ? 'Institution administrator' : 'Instructor'}</dd></div>`;
    requiredNotice.hidden = !(user.must_change_password || new URLSearchParams(window.location.search).get('required') === '1');
  }).catch(() => {});

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    setMessage('');
    const currentPassword = form.current_password.value;
    const newPassword = form.new_password.value;
    const confirmation = form.confirm_password.value;
    if (!currentPassword) {
      setMessage('Enter your current password.', 'error');
      form.current_password.focus();
      return;
    }
    if (newPassword.length < 10) {
      setMessage('The new password must contain at least 10 characters.', 'error');
      form.new_password.focus();
      return;
    }
    if (newPassword !== confirmation) {
      setMessage('The new passwords do not match.', 'error');
      form.confirm_password.focus();
      return;
    }
    if (newPassword === currentPassword) {
      setMessage('Choose a password different from the current one.', 'error');
      form.new_password.focus();
      return;
    }

    const button = form.querySelector('[type="submit"]');
    button.disabled = true;
    button.textContent = 'Changing password…';
    try {
      await window.MisraAPI.changePassword({ current_password: currentPassword, new_password: newPassword });
      setMessage('Password changed. Redirecting you to sign in…', 'success');
      setTimeout(() => window.location.replace('login.html'), 900);
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Change password';
      setMessage(error.message || 'Could not change your password. Try again.', 'error');
    }
  });
})();
