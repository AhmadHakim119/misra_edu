"""Non-secret setup information and an explicit, inference-free readiness check."""
from fastapi import APIRouter, Depends
from typing import Literal
from services.auth_dependencies import require_instructor
from services.inference_profiles import LOCAL_PROFILE, LOCAL_PROFILES, VISION_PROFILE, active_profile, local_profile, profile_scope
from services.inference_service import configuration, verification_enabled, _ollama_json

router = APIRouter(prefix='/api/inference-profiles', tags=['inference'], dependencies=[Depends(require_instructor)])


@router.get('')
def profiles():
    selected = active_profile()
    with profile_scope(None):
        configured = {task: configuration(task) for task in ('ocr', 'setup', 'grading', 'verification')}
        configured_verifier = verification_enabled()
    return {'selected_profile': selected['id'] if selected else 'configured', 'profiles': [
        {'id': LOCAL_PROFILE, 'label': 'Local Qwen + Gemini page reading', 'tasks': local_profile()['tasks'],
         'verification_enabled': True, 'text_only_grading': True},
        {'id': VISION_PROFILE, 'label': 'Local Qwen Vision + Gemini page reading',
         'tasks': local_profile(VISION_PROFILE)['tasks'], 'verification_enabled': True, 'text_only_grading': False},
        {'id': 'configured', 'label': 'Server configuration', 'tasks': configured,
         'verification_enabled': configured_verifier, 'text_only_grading': False},
    ]}


@router.get('/local-status')
def local_status(profile_id: Literal['local_qwen_gemini_v1', 'local_qwen_vision_gemini_v1'] | None = None):
    profile = active_profile()
    selected = profile_id or (profile['id'] if profile else LOCAL_PROFILE)
    model = LOCAL_PROFILES[selected]
    try:
        payload = _ollama_json('/api/tags')
        installed = any(isinstance(item, dict) and item.get('name') == model
                        for item in payload.get('models', []))
        return {'available': installed, 'model': model, 'inference_started': False,
                'message': 'Local Qwen is installed. This check does not measure grading quality.' if installed else
                    f'Ollama is running, but {model} is not installed. Install that model, then check again.'}
    except Exception:
        return {'available': False, 'model': model, 'inference_started': False,
                'message': 'Cannot reach local Ollama. Start Ollama on the MISRA computer, then check again.'}
