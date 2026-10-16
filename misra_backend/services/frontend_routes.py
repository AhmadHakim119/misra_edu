"""One instructor app, with the retained interface isolated under /legacy/."""
from pathlib import Path
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles


def mount_frontend(app, frontend_dir: Path):
    async def old_native(request: Request, path: str = ''):
        query=f'?{request.url.query}' if request.url.query else ''
        return RedirectResponse(f'/app/{path}{query}',status_code=307)

    async def old_pages(request: Request, path: str = ''):
        query=f'?{request.url.query}' if request.url.query else ''
        return RedirectResponse(f'/legacy/pages/{path}{query}',status_code=307)

    app.add_api_route('/app/next',old_native,include_in_schema=False)
    app.add_api_route('/app/next/{path:path}',old_native,include_in_schema=False)
    app.add_api_route('/app/pages/{path:path}',old_pages,include_in_schema=False)
    # Shared controllers and original assets remain common to both workspaces.
    for folder in ('js','assets','css'):
        app.mount(f'/{folder}',StaticFiles(directory=frontend_dir/folder),name=f'shared-{folder}')
        app.mount(f'/app/{folder}',StaticFiles(directory=frontend_dir/folder),name=f'app-{folder}')
    app.mount('/legacy',StaticFiles(directory=frontend_dir,html=True),name='legacy-frontend')
    app.mount('/app',StaticFiles(directory=frontend_dir/'app',html=True),name='frontend')
