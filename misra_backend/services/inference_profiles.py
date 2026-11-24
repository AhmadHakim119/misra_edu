"""Request-scoped, versioned inference choices; never mutate process settings."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import os
from urllib.parse import urlparse

LOCAL_PROFILE = 'local_qwen_gemini_v1'
LOCAL_MODEL = 'qwen3:4b-instruct'
VISION_PROFILE = 'local_qwen_vision_gemini_v1'
VISION_MODEL = 'qwen3-vl:4b-instruct'
FULL_LOCAL_PROFILE = 'local_qwen_all_v1'
LOCAL_PROFILES = {LOCAL_PROFILE: LOCAL_MODEL, VISION_PROFILE: VISION_MODEL, FULL_LOCAL_PROFILE: LOCAL_MODEL}
PROFILE_HEADER = 'X-Misra-Inference-Profile'
TEXT_ONLY_IMAGE_ERROR = 'Local Qwen grades text only. Required images cannot be omitted. Review the original work or choose a configured vision-capable setup.'
_active = ContextVar('misra_inference_profile', default=None)
_cpu_vision = ContextVar('misra_cpu_vision', default=False)


def loopback_url(value):
    parsed = urlparse(value)
    if (parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.rstrip('/') not in {'', '/v1'}):
        raise ValueError('Local inference requires a loopback Ollama URL without credentials or query parameters.')
    # Accessing port also rejects malformed port strings before any network call.
    parsed.port
    return value.rstrip('/').removesuffix('/v1')


def _profile(base_url, profile_id):
    return {
        'id': profile_id, 'version': 1,
        'tasks': {
            'ocr': ({'provider': 'local', 'model': VISION_MODEL} if profile_id == FULL_LOCAL_PROFILE
                    else {'provider': 'gemini', 'model': 'gemini-2.5-flash'}),
            'setup': {'provider': 'local', 'model': LOCAL_MODEL},
            **{task: {'provider': 'local', 'model': LOCAL_PROFILES[profile_id]}
               for task in ('grading', 'verification')},
            **({'vision_grading': {'provider': 'local', 'model': VISION_MODEL}}
               if profile_id == FULL_LOCAL_PROFILE else {}),
        },
        'verification_enabled': True,
        'setup_images_use_ocr': True,
        'local_base_url': loopback_url(base_url),
        'context_tokens': 32768, 'max_output_tokens': 8192,
    }


def local_profile(profile_id=LOCAL_PROFILE):
    return _profile(os.getenv('LOCAL_AI_BASE_URL', 'http://127.0.0.1:11434/v1'), profile_id)


def validate_snapshot(snapshot):
    if snapshot is None:
        return None
    if not isinstance(snapshot, dict):
        raise ValueError('Invalid saved inference profile.')
    profile_id = snapshot.get('id')
    if not isinstance(profile_id, str) or profile_id not in LOCAL_PROFILES:
        raise ValueError('Unknown saved inference profile.')
    expected = _profile(snapshot.get('local_base_url', ''), profile_id)
    if snapshot != expected:
        raise ValueError('Unknown or altered saved inference profile. No inference was started.')
    return deepcopy(snapshot)


def active_profile():
    return deepcopy(_active.get())


def activate(snapshot):
    return _active.set(validate_snapshot(snapshot)), _cpu_vision.set(False)


def reset(tokens):
    token, cpu_token = tokens
    _cpu_vision.reset(cpu_token)
    _active.reset(token)


def vision_cpu_only():
    return _cpu_vision.get()


def use_vision_cpu():
    _cpu_vision.set(True)


@contextmanager
def profile_scope(snapshot):
    token = activate(snapshot)
    try:
        yield
    finally:
        reset(token)


def install_profile_middleware(app):
    from fastapi.responses import JSONResponse

    @app.middleware('http')
    async def selected_inference_profile(request, call_next):
        if request.url.path.startswith('/api/auth/'):
            # A local model misconfiguration must never block sign-in/recovery.
            with profile_scope(None):
                return await call_next(request)
        selected = request.headers.get(PROFILE_HEADER, 'configured')
        if selected != 'configured' and selected not in LOCAL_PROFILES:
            return JSONResponse(status_code=422, content={'detail': 'Unknown AI setup. Reload Settings and choose an available setup.'})
        try:
            snapshot = local_profile(selected) if selected in LOCAL_PROFILES else None
            token = activate(snapshot)
        except (ValueError, TypeError):
            return JSONResponse(status_code=503, content={'detail': 'The local AI setup is invalid. Check the loopback Ollama configuration.'})
        try:
            return await call_next(request)
        finally:
            reset(token)


def execute_profile_job(processing_job_id):
    """Versioned RQ target: an old worker must fail before sending any evidence."""
    from services import grading_service, inference_service, job_execution_service
    if not all(getattr(module, 'PROFILE_SUPPORT_VERSION', 0) == version for module, version in (
        (grading_service, 2), (inference_service, 6), (job_execution_service, 3)
    )):
        from database import SessionLocal
        from models import ProcessingJob
        with SessionLocal() as db:
            job = db.get(ProcessingJob, processing_job_id)
            if job and job.status not in {'completed', 'failed'}:
                job.status = 'failed'
                job.error_message = 'Restart the API and RQ worker, then retry this job. No inference was started; the worker has older AI-routing code.'
                job.progress_message = 'Worker restart required'
                db.commit()
        raise ValueError('Worker restart required before running a saved local AI setup.')
    return job_execution_service.execute_processing_job(processing_job_id)
