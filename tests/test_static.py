import mimetypes
import re

import pytest
from fastapi.testclient import TestClient

from backend import app as module


@pytest.mark.parametrize(('extension', 'expected'), [
    ('.js', 'application/javascript'),
    ('.css', 'text/css'),
])
def test_built_assets_ignore_system_mime_mapping(monkeypatch, extension, expected):
    if not (module.DIST / 'index.html').is_file():
        pytest.skip('Run npm run build to test the actual frontend bundle')
    mimetypes.init()
    monkeypatch.setitem(mimetypes.types_map, extension, 'text/plain')
    with TestClient(module.app, base_url='http://127.0.0.1') as client:
        html = client.get('/')
        asset = re.search(r'(?:src|href)="([^"]+' + re.escape(extension) + r')"', html.text)
        assert asset, f'No {extension} asset referenced by the built homepage'
        response = client.get(asset.group(1))
        assert response.status_code == 200
        assert response.headers['content-type'].split(';')[0] == expected
        assert response.headers['x-content-type-options'] == 'nosniff'
        head = client.head(asset.group(1))
        assert head.headers['content-type'].split(';')[0] == expected
        assert head.content == b''
