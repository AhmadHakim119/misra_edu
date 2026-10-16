"""Static routing uses no database, accounts, provider or private records."""
import asyncio
import unittest
from pathlib import Path
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

    def test_main_app_assets_and_legacy_bookmarks(self):
        app=FastAPI()
        mount_frontend(app,Path(__file__).resolve().parents[2]/'misra-frontend')
        async def exercise():
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                for path in ['/app/','/app/landing.html','/app/landing.css','/app/landing.js','/app/setup.html','/app/workspace-template.html','/app/js/api.js','/js/api.js','/assets/logo.png','/assets/landing-equation.png','/app/ledger.css','/legacy/pages/login.html','/legacy/js/api.js']:
                    response=await client.get(path)
                    self.assertEqual(response.status_code,200,path)
                self.assertIn('workspace-loader.js',(await client.get('/app/index.html')).text)
                response=await client.get('/app/next/setup.html?exam_id=synthetic')
                self.assertEqual(response.status_code,307)
                self.assertEqual(response.headers['location'],'/app/setup.html?exam_id=synthetic')
                response=await client.get('/app/pages/dashboard.html?exam_id=synthetic')
                self.assertEqual(response.headers['location'],'/legacy/pages/dashboard.html?exam_id=synthetic')
                self.assertEqual((await client.get('/app/pages')).status_code,404)
        asyncio.run(exercise())
