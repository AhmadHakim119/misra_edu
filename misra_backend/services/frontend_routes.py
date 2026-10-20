"""Serve the instructor app and redirect retired interface bookmarks."""
from pathlib import Path
from urllib.parse import urlencode
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

RETIRED_PAGES = {
    'account.html': 'account.html',
    'admin-operations.html': 'admin.html',
    'assessments.html': 'assessments.html',
    'dashboard.html': 'dashboard.html',
    'evaluation.html': 'evaluation.html',
    'forgot-password.html': 'forgot-password.html',
    'grade-results.html': 'grading.html',
    'grades.html': 'results.html',
    'instructors.html': 'admin.html',
    'login.html': 'login.html',
    'reset-password.html': 'reset-password.html',
    'reviews.html': 'reviews.html',
    'rubric-studio.html': 'setup.html',
    'submission.html': 'extraction.html',
    'submissions.html': 'grading.html',
    'upload.html': 'upload.html',
}


def mount_frontend(app, frontend_dir: Path):
    async def old_native(request: Request, path: str = ''):
        query=f'?{request.url.query}' if request.url.query else ''
        return RedirectResponse(f'/app/{path}{query}',status_code=307)

    async def old_pages(request: Request, path: str = ''):
        destination = RETIRED_PAGES.get(path)
        if destination is None:
            raise HTTPException(status_code=404, detail='Unknown retired page')
        parameters = list(request.query_params.multi_items())
        if path in {'submission.html', 'grade-results.html'}:
            # Earlier paper links called the submission parameter "id".
            has_submission = 'submission_id' in request.query_params
            parameters = [(('submission_id' if key == 'id' else key), value)
                          for key, value in parameters if key != 'id' or not has_submission]
        query = '?' + urlencode(parameters) if parameters else ''
        return RedirectResponse(f'/app/{destination}{query}',status_code=307)

    app.add_api_route('/app/next',old_native,include_in_schema=False)
    app.add_api_route('/app/next/{path:path}',old_native,include_in_schema=False)
    app.add_api_route('/app/pages/{path:path}',old_pages,include_in_schema=False)
    app.add_api_route('/legacy/pages/{path:path}',old_pages,include_in_schema=False)
    # The current app still uses these shared controllers and assets.
    for folder in ('js','assets','css'):
        app.mount(f'/{folder}',StaticFiles(directory=frontend_dir/folder),name=f'shared-{folder}')
        app.mount(f'/app/{folder}',StaticFiles(directory=frontend_dir/folder),name=f'app-{folder}')
    app.mount('/app',StaticFiles(directory=frontend_dir/'app',html=True),name='frontend')
