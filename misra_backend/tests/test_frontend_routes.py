"""Static routing uses no database, accounts, provider or private records."""
import asyncio
import unittest
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from services.frontend_routes import mount_frontend


class FrontendRoutesTests(unittest.TestCase):
    def test_server_home_serves_public_landing(self):
        from main import read_root
        response=read_root()
        self.assertEqual(response.status_code,200)
        self.assertEqual(Path(response.path).name,'landing.html')
        self.assertIn('Handwritten exams.',Path(response.path).read_text(encoding='utf-8'))

    def test_main_app_assets_and_retired_bookmarks(self):
        app=FastAPI()
        mount_frontend(app,Path(__file__).resolve().parents[2]/'misra-frontend')
        async def exercise():
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                for path in ['/app/','/app/landing.html','/app/landing.css','/app/landing.js','/app/setup.html','/app/workspace-template.html','/app/js/api.js','/js/api.js','/assets/logo.png','/assets/landing-equation.png','/app/ledger.css']:
                    response=await client.get(path)
                    self.assertEqual(response.status_code,200,path)
                self.assertIn('workspace-loader.js',(await client.get('/app/index.html')).text)
                response=await client.get('/app/next/setup.html?exam_id=synthetic')
                self.assertEqual(response.status_code,307)
                self.assertEqual(response.headers['location'],'/app/setup.html?exam_id=synthetic')
                response=await client.get('/app/pages/dashboard.html?exam_id=synthetic')
                self.assertEqual(response.headers['location'],'/app/dashboard.html?exam_id=synthetic')
                for prefix in ['/app/pages/', '/legacy/pages/']:
                    for old, current in [('rubric-studio.html','setup.html'), ('grade-results.html','grading.html'),
                                         ('submission.html','extraction.html'), ('grades.html','results.html'),
                                         ('instructors.html','admin.html'), ('login.html','login.html')]:
                        response = await client.get(prefix + old)
                        self.assertEqual(response.status_code,307)
                        self.assertEqual(response.headers['location'],'/app/' + current)
                    self.assertEqual((await client.get(prefix+'unknown.html')).status_code,404)
                self.assertEqual((await client.get('/legacy/js/api.js')).status_code,404)
                self.assertEqual((await client.get('/legacy/app/index.html')).status_code,404)
                self.assertEqual((await client.get('/app/pages')).status_code,404)
        asyncio.run(exercise())

    def test_paper_bookmarks_preserve_scope_and_translate_submission_parameter(self):
        app=FastAPI()
        mount_frontend(app,Path(__file__).resolve().parents[2]/'misra-frontend')
        async def exercise():
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                response = await client.get('/legacy/pages/submission.html?id=synthetic-paper&exam_id=synthetic-exam&tag=a&tag=b')
                target=urlparse(response.headers['location'])
                self.assertEqual(target.path,'/app/extraction.html')
                self.assertEqual(parse_qs(target.query),{'submission_id':['synthetic-paper'],'exam_id':['synthetic-exam'],'tag':['a','b']})
                response = await client.get('/app/pages/grade-results.html?id=stale&submission_id=current&exam_id=exam')
                self.assertEqual(parse_qs(urlparse(response.headers['location']).query),{'submission_id':['current'],'exam_id':['exam']})
        asyncio.run(exercise())

    def test_fresh_checkout_needs_no_retired_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('app','js','assets','css'):(root/name).mkdir()
            (root/'app/index.html').write_text('Synthetic current app',encoding='utf8')
            app=FastAPI();mount_frontend(app,root)
            async def exercise():
                async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                    self.assertEqual((await client.get('/app/')).text,'Synthetic current app')
                    response=await client.get('/legacy/pages/dashboard.html?exam_id=synthetic')
                    self.assertEqual(response.headers['location'],'/app/dashboard.html?exam_id=synthetic')
            asyncio.run(exercise())
