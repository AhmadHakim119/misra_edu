/* ==========================================================================
   MISRA EDU — Instructor authentication forms.
   ========================================================================== */

(function () {
  'use strict';

  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  /* The server owns the session cookie; this page never stores a password or token. */
  const sameOriginApi = window.location.pathname.startsWith('/app/') ? `${window.location.origin}/api` : 'http://127.0.0.1:8000/api';
  const API_BASE = (window.MISRA_API_BASE || sameOriginApi).replace(/\/$/, '');

  async function authRequest(path, payload) {
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) return { ok: false, error: data.detail || 'Authentication failed. Try again.' };
      return { ok: true, ...data };
    } catch (_error) {
      return { ok: false, error: 'Could not reach the MISRA backend.' };
    }
  }

  const api = {
    async login({ email, password, remember }) {
      if (!email || !password) {
        return { ok: false, error: 'Enter your institutional email and password.' };
      }
      return authRequest('/auth/login', { email, password, remember });
    },
    forgotPassword(email) {
      return authRequest('/auth/forgot-password', { email });
    },
    resetPassword(token, newPassword) {
      return authRequest('/auth/reset-password', { token, new_password: newPassword });
    },
  };

  function setFieldError(fieldEl, message) {
    if (!fieldEl) return;
    fieldEl.classList.add('is-invalid');
    const errorEl = fieldEl.querySelector('.field-error span');
    if (errorEl && message) errorEl.textContent = message;
  }

  function clearFieldError(fieldEl) {
    if (!fieldEl) return;
    fieldEl.classList.remove('is-invalid');
  }

  function setLoading(button, isLoading, idleLabel) {
    if (!button) return;
    button.disabled = isLoading;
    button.textContent = isLoading ? 'Please wait…' : idleLabel;
  }

  /* ---- Login form ---- */
  const loginForm = document.querySelector('[data-login-form]');
  if (loginForm) {
    const emailField = loginForm.querySelector('[data-field="email"]');
    const passwordField = loginForm.querySelector('[data-field="password"]');
    const submitBtn = loginForm.querySelector('[type="submit"]');
    const idleLabel = submitBtn ? submitBtn.textContent : 'Sign in';

    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearFieldError(emailField);
      clearFieldError(passwordField);

      const email = loginForm.email.value.trim();
      const password = loginForm.password.value;

      let hasError = false;
      if (!EMAIL_RE.test(email)) {
        setFieldError(emailField, 'Enter a valid email address.');
        hasError = true;
      }
      if (!password) {
        setFieldError(passwordField, 'Password is required.');
        hasError = true;
      }
      if (hasError) return;

      setLoading(submitBtn, true, idleLabel);
      const result = await api.login({ email, password, remember: loginForm.remember.checked });
      setLoading(submitBtn, false, idleLabel);

      if (!result.ok) {
        window.showToast(result.error || 'Sign in failed. Check your details.', 'error');
        return;
      }
      window.showToast('Signed in securely.', 'success');
      setTimeout(() => {
        if (result.user?.must_change_password) {
          window.location.href = 'account.html?required=1';
          return;
        }
        const requested = new URLSearchParams(window.location.search).get('next');
        window.location.href = requested && requested.startsWith('/app/pages/') ? requested : 'dashboard.html';
      }, 700);
    });
  }

  /* ---- Forgot password form ---- */
  const forgotForm = document.querySelector('[data-forgot-password-form]');
  if (forgotForm) {
    const emailField = forgotForm.querySelector('[data-field="email"]');
    const submitBtn = forgotForm.querySelector('[type="submit"]');
    const idleLabel = submitBtn.textContent;
    forgotForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      clearFieldError(emailField);
      const email = forgotForm.email.value.trim();
      if (!EMAIL_RE.test(email)) {
        setFieldError(emailField, 'Enter a valid email address.');
        return;
      }
      setLoading(submitBtn, true, idleLabel);
      const result = await api.forgotPassword(email);
      setLoading(submitBtn, false, idleLabel);
      if (!result.ok) {
        window.showToast(result.error || 'Could not request a reset link. Try again.', 'error');
        return;
      }
      forgotForm.hidden = true;
      const confirmation = document.querySelector('[data-forgot-confirmation]');
      if (confirmation) confirmation.hidden = false;
    });
  }

  /* ---- Reset password form ---- */
  const resetForm = document.querySelector('[data-reset-password-form]');
  if (resetForm) {
    const token = new URLSearchParams(window.location.search).get('token') || '';
    const newField = resetForm.querySelector('[data-field="new-password"]');
    const confirmField = resetForm.querySelector('[data-field="confirm-password"]');
    const submitBtn = resetForm.querySelector('[type="submit"]');
    const idleLabel = submitBtn.textContent;
    if (!token) {
      resetForm.hidden = true;
      const invalid = document.querySelector('[data-reset-invalid]');
      if (invalid) invalid.hidden = false;
    }
    resetForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      clearFieldError(newField);
      clearFieldError(confirmField);
      const newPassword = resetForm.new_password.value;
      const confirmation = resetForm.confirm_password.value;
      let invalid = false;
      if (newPassword.length < 10) {
        setFieldError(newField, 'Use at least 10 characters.');
        invalid = true;
      }
      if (newPassword !== confirmation) {
        setFieldError(confirmField, 'The passwords do not match.');
        invalid = true;
      }
      if (invalid) return;
      setLoading(submitBtn, true, idleLabel);
      const result = await api.resetPassword(token, newPassword);
      setLoading(submitBtn, false, idleLabel);
      if (!result.ok) {
        window.showToast(result.error || 'This reset link could not be used.', 'error');
        return;
      }
      resetForm.hidden = true;
      const success = document.querySelector('[data-reset-success]');
      if (success) success.hidden = false;
    });
  }

  /* ---- Password visibility toggle (shared) ---- */
  document.querySelectorAll('[data-toggle-password]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-toggle-password');
      const input = document.getElementById(targetId);
      if (!input) return;
      const showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      btn.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
      btn.innerHTML = showing ? ICON_EYE : ICON_EYE_OFF;
    });
  });

  const ICON_EYE = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>';
  const ICON_EYE_OFF = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 3l18 18"/><path d="M10.6 10.6a2 2 0 0 0 2.8 2.8"/><path d="M9.9 5.2A9.8 9.8 0 0 1 12 5c6.5 0 10 7 10 7a13.2 13.2 0 0 1-3.1 3.9M6.2 6.2A13.4 13.4 0 0 0 2 12s3.5 7 10 7a9.7 9.7 0 0 0 4.2-.9"/></svg>';
})();
