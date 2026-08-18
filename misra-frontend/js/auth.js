/* ==========================================================================
   MISRA EDU — Auth forms (client-side validation + pluggable API layer)

   SECURITY NOTE FOR DEVELOPERS:
   This file intentionally contains NO password hashing, NO token storage
   logic, and NO real authentication. Wiring real auth is explicitly
   deferred per the project brief. Before connecting this to a backend:

     1. Implement the backend endpoints called below and return only an
        httpOnly session cookie, never a browser-managed bearer token.
     2. Never store raw passwords or JWTs in localStorage — use an
        httpOnly, Secure, SameSite=Strict cookie set by the server.
     3. Enforce institution-issued-account verification server-side.
        Client-side email domain checks (below) are a UX nicety only,
        never a security boundary — validate on the server.
     4. Add CSRF protection once cookies are in play.
     5. Add rate limiting / lockout on the login endpoint server-side.

   See AUTH_INTEGRATION.md in the project root for the full checklist.
   ========================================================================== */

(function () {
  'use strict';

  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  /* ---- Real API boundary. The backend may defer auth, but this UI never
     simulates a successful identity or stores a fake session. ---- */
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
      if (!response.ok) {
        return {
          ok: false,
          error: response.status === 404
            ? 'Authentication is not enabled on this backend yet.'
            : (data.detail || 'Authentication failed. Try again.'),
        };
      }
      return { ok: true, ...data };
    } catch (_error) {
      return { ok: false, error: 'Could not reach the MISRA backend.' };
    }
  }

  const api = {
    async login({ email, password }) {
      if (!email || !password) {
        return { ok: false, error: 'Enter your institutional email and password.' };
      }
      return authRequest('/auth/login', { email, password });
    },
    async signup({ name, email, institutionCode, password }) {
      if (!name || !email || !institutionCode || !password) {
        return { ok: false, error: 'All fields are required.' };
      }
      return authRequest('/auth/signup', { name, email, institution_code: institutionCode, password });
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
      const result = await api.login({ email, password });
      setLoading(submitBtn, false, idleLabel);

      if (!result.ok) {
        window.showToast(result.error || 'Sign in failed. Check your details.', 'error');
        return;
      }
      window.showToast('Signed in securely.', 'success');
      setTimeout(() => {
        window.location.href = 'dashboard.html';
      }, 700);
    });
  }

  /* ---- Signup form ---- */
  const signupForm = document.querySelector('[data-signup-form]');
  if (signupForm) {
    const nameField = signupForm.querySelector('[data-field="name"]');
    const emailField = signupForm.querySelector('[data-field="email"]');
    const codeField = signupForm.querySelector('[data-field="institutionCode"]');
    const passwordField = signupForm.querySelector('[data-field="password"]');
    const termsField = signupForm.querySelector('[data-field="terms"]');
    const submitBtn = signupForm.querySelector('[type="submit"]');
    const idleLabel = submitBtn ? submitBtn.textContent : 'Create account';

    signupForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      [nameField, emailField, codeField, passwordField, termsField].forEach(clearFieldError);

      const name = signupForm.name.value.trim();
      const email = signupForm.email.value.trim();
      const institutionCode = signupForm.institutionCode.value.trim();
      const password = signupForm.password.value;
      const termsChecked = signupForm.terms.checked;

      let hasError = false;

      if (name.length < 2) {
        setFieldError(nameField, 'Enter your full name.');
        hasError = true;
      }
      if (!EMAIL_RE.test(email)) {
        setFieldError(emailField, 'Enter a valid email address.');
        hasError = true;
      }
      if (!institutionCode) {
        setFieldError(codeField, 'Enter the institution code from your school.');
        hasError = true;
      }
      if (password.length < 8) {
        setFieldError(passwordField, 'Use at least 8 characters.');
        hasError = true;
      }
      if (!termsChecked) {
        setFieldError(termsField, 'You must accept the terms to continue.');
        hasError = true;
      }
      if (hasError) return;

      setLoading(submitBtn, true, idleLabel);
      const result = await api.signup({ name, email, institutionCode, password });
      setLoading(submitBtn, false, idleLabel);

      if (!result.ok) {
        window.showToast(result.error || 'Could not create your account.', 'error');
        return;
      }
      window.showToast('Account created. Redirecting…', 'success');
      setTimeout(() => {
        window.location.href = 'login.html';
      }, 900);
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
