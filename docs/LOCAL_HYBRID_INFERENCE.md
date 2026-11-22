# Local Qwen with Gemini page reading

Open **Settings → AI services** in `/app/account.html`. New requests from the
instructor app default to **Local Qwen + Gemini page reading**. **Save AI setup**
retains the selected profile on this browser. **Local Qwen Vision + Gemini
page reading** uses Ollama `qwen3-vl:4b-instruct` for grading and verification,
including image evidence when the grading policy requests it. Text guide
drafting still uses `qwen3:4b-instruct`. **Server configuration** uses the
existing environment-selected providers.

The profile uses the installed Ollama `qwen3:4b-instruct` for text-based guide
drafting, criterion grading and a separate verification call. Gemini
`gemini-2.5-flash` reads student pages, material pages, recovery images and
image-based exam/key imports. Reading images during setup explicitly uses the
OCR role; it is not a failed local call followed by a hosted fallback.

This is the recorded local grading baseline, not a validated best model.
Every new local grading proposal receives a `local_model_evaluation_pending`
review finding. Instructor review remains necessary even if the verifier agrees.
Existing instructor decisions, grades, approved guides and export logic are
preserved. Similarity scores do not award marks or bypass the model/check stages.
Bounded BM25 and the existing approved-source rules remain unchanged.

## Start and check

1. Keep Ollama running on the MISRA computer, with `qwen3:4b-instruct` installed.
   The Vision setup also needs `qwen3-vl:4b-instruct`. `ollama list` checks
   installation without generating text. No new Python/npm dependencies are required.
2. Keep the existing Gemini credential in the server environment. Credentials
   are never entered into or returned by the new UI.
3. Restart the API and RQ worker to load the new code, then reload the instructor
   app. No database migration or environment-file rewrite is required.
4. Choose **Check local model** in Settings for the selected local setup. This
   authenticated check reads Ollama's `/api/tags` and starts no inference.
   If a paper failed because a text-only grader received images, save the
   Vision setup, open the paper and choose **Grade with current AI setup**.

The default Ollama address is `http://127.0.0.1:11434`. The existing
`LOCAL_AI_BASE_URL` can specify another loopback Ollama port, with optional `/v1`.
Remote hosts, credentials, queries, other paths, redirects and proxy forwarding
are rejected for this profile. Native Ollama `/api/chat` uses JSON output,
temperature 0, seed 42, a 32768-token context and an 8192-token output bound.
A conservative UTF-8 input bound reserves output and overhead space; packages
that exceed it fail rather than losing approved evidence through truncation.

## Evidence and failure boundaries

- The browser sends only an allowlisted profile ID in
  `X-Misra-Inference-Profile`. It cannot supply arbitrary models, URLs or prompts
  through that setting. Requests without the header retain existing server
  configuration, including older clients.
- A request-local context selects the profile without changing `os.environ` or
  another instructor's in-flight request. Accepted jobs store the versioned,
  non-secret profile in existing JSON payloads. Workers restore that exact
  profile on execution/retry; changing the browser choice does not alter an
  already accepted job. Original jobs without a snapshot keep legacy behavior.
- Profile jobs use a versioned worker entry point. A worker with cached older
  routing code fails before inference with a restart/retry instruction rather
  than processing a local request on its old provider. A broken local
  configuration does not block authentication or password recovery.
- The text-only Local Qwen setup rejects images. Image-required grading, image-only reference evidence
  and visual audit modes fail explicitly instead of dropping images, weakening
  a question's policy or sending the grade to Gemini. Check the original work
  and choose a configured vision-capable setup when that evidence is required.
- Verification stays enabled for the local profile regardless of a process-wide
  verifier opt-out. Its findings cannot modify the primary marks. Invalid or
  incomplete output continues through the existing bounded validation/retry
  rules; no invalid grade becomes zero.
- Local failures have no automatic hosted grader fallback. Gemini page reading
  can incur its existing provider charges. Local generation has no hosted
  grading fee, but hardware, energy, latency and human effort still matter.
- Browser-storage failures keep the selected but unsaved choice visible and
  protect navigation. Failed profile loading disables saving and offers reload.

## Recorded checks — 20 November 2026

The installed model inventory contained `qwen3:4b-instruct` and
`qwen3-embedding:0.6b`. The readiness endpoint confirmed the grader was installed
without inference. The embedding model is not used to auto-grade.

One opt-in synthetic software-testing question was graded in isolated in-memory
SQLite using the real local model, with both hosted completion functions blocked.
The run completed in 249.99 seconds, made two local calls, saved one grading run
and required instructor review. This is an integration check, not a grading
accuracy result, a speed advantage or an end-to-end OCR benchmark. It illustrates
the current laptop's substantial local latency.

The final backend regression run passed **808 tests**. The focused browser run
passed **14 tests** across desktop and mobile projects. JavaScript syntax checks
and `git diff --check` also passed. The API and production RQ worker were not
restarted, and the full browser suite was not run because its fixture host was
unreachable in this execution environment.

The backend regression suite and focused browser checks use synthetic fixtures
and mocked provider responses. Browser checks cover profile persistence, request
headers, unsaved/failed saves, reload, unavailable services, model readiness,
keyboard access, desktop/mobile, light/dark and Arabic/RTL. The local test host
could not reach its static-fixture listening port, so the focused browser run
served the actual workspace files through Playwright routes. It did not start
the application, use its real database or make paid inference calls.
