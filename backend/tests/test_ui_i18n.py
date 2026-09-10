from html.parser import HTMLParser
import re

from httpx import ASGITransport, AsyncClient
import pytest


class VisibleCopy(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden = tag

    def handle_endtag(self, tag):
        if tag == self.hidden:
            self.hidden = None

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


@pytest.mark.parametrize('language', ['zh', 'en'])
async def test_all_workspace_pages_render_in_selected_language(language):
    from backend.main import app
    routes = ['/login', '/search', '/tasks-list', '/tasks/new', '/tasks/1/detail',
              '/settings', '/criteria-page', '/library', '/library/1', '/protocols', '/protocols/1', '/guide']
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', headers={'accept':'text/html'}, cookies={'geo_ui_lang': language}) as client:
        for route in routes:
            response = await client.get(route)
            assert response.status_code == 200, route
            assert f'<html lang="{language}"' in response.text
            assert 'setUiLanguage' in response.text
            parser = VisibleCopy(); parser.feed(response.text)
            visible = ''.join(parser.parts).replace('中文', '')
            if language == 'en':
                assert not re.search('[\u4e00-\u9fff]', visible), (route, visible)
            elif route == '/settings':
                assert '模型与连接' in visible and '当前使用的模型' in visible


async def test_invalid_language_uses_chinese_and_navigation_is_current():
    from backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', cookies={'geo_ui_lang': '<script>'}) as client:
        response = await client.get('/protocols/1')
        assert '<html lang="zh"' in response.text
        assert '<a href="/protocols" aria-current="page">' in response.text


def test_translation_does_not_modify_research_text_or_schema_keys():
    from backend.ui_i18n import ui_context
    from backend.protocol_schema import COLUMNS
    from starlette.requests import Request
    context = ui_context(Request({'type':'http', 'headers':[(b'cookie',b'geo_ui_lang=en')]}))
    paper = '用户定义的方案：细胞 A + 3 uM CHIR99021'
    assert context['t'](paper) == paper
    assert all(context['t'](column) == column for column in COLUMNS)
