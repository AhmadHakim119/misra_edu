"""Non-secret setup information and an explicit, inference-free readiness check."""
from fastapi import APIRouter, Depends
from typing import Literal
from services.auth_dependencies import require_instructor
from services.free_model_gateway import paid_fallback_enabled
from services.inference_profiles import FULL_LOCAL_PROFILE, LOCAL_PROFILES, active_profile, local_profile, profile_scope
from services.inference_service import configuration, verification_enabled, _ollama_json

router = APIRouter(prefix='/api/inference-profiles', tags=['inference'], dependencies=[Depends(require_instructor)])


@router.get('')
def profiles():
    selected = active_profile()
    with profile_scope(None):
        configured = {task: configuration(task) for task in ('ocr', 'setup', 'grading', 'verification')}
        configured_verifier = verification_enabled()
    return {'selected_profile': selected['id'] if selected else 'configured', 'profiles': [
        {'id': FULL_LOCAL_PROFILE, 'label': 'Fully local Qwen', 'tasks': local_profile(FULL_LOCAL_PROFILE)['tasks'],
         'verification_enabled': True, 'text_only_grading': False},
        {'id': 'configured', 'label': 'Server configuration', 'tasks': configured,
         'verification_enabled': configured_verifier, 'text_only_grading': False,
         'paid_fallback_enabled': paid_fallback_enabled()},
    ]}


@router.get('/local-status')
def local_status(profile_id: Literal['local_qwen_gemini_v1', 'local_qwen_vision_gemini_v1', 'local_qwen_all_v1'] | None = None):
    profile = active_profile()
    selected = profile_id or (profile['id'] if profile else FULL_LOCAL_PROFILE)
    models = list(dict.fromkeys(task['model'] for task in local_profile(selected)['tasks'].values()
                                if task['provider'] == 'local'))
    model = LOCAL_PROFILES[selected]
    try:
        payload = _ollama_json('/api/tags')
        installed = {item.get('name') for item in payload.get('models', []) if isinstance(item, dict)}
        missing = [name for name in models if name not in installed]
        return {'available': not missing, 'model': model, 'models': models, 'inference_started': False,
                'message': 'Local Qwen is installed. This check does not measure grading quality.' if not missing else
                    f'Ollama is running. Install the missing models and check again: {", ".join(missing)}.'}
    except Exception:
        return {'available': False, 'model': model, 'inference_started': False,
                'message': 'Cannot reach local Ollama. Start Ollama on the MISRA computer, then check again.'}
