import httpx
import pytest

from updates import LATEST_URL, REPOSITORY, check_update


def release(tag='v0.2.0'):
    name = f'ZenTaoWorklog-{tag}-Windows-x64.zip'
    return {'tag_name': tag, 'assets': [{
        'name': name,
        'browser_download_url': f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}',
    }]}


def transport(data, calls=None):
    def handle(request):
        assert str(request.url) == LATEST_URL
        assert 'Token' not in request.headers
        assert 'Cookie' not in request.headers
        if calls is not None:
            calls.append(request)
        return httpx.Response(200, json=data)
    return httpx.MockTransport(handle)


def test_new_version_links_only_to_official_windows_package():
    calls = []
    result = check_update('0.1.2', transport(release(), calls))
    assert result.version == '0.2.0'
    assert result.download_url.endswith('/v0.2.0/ZenTaoWorklog-v0.2.0-Windows-x64.zip')
    assert len(calls) == 1


@pytest.mark.parametrize('tag', ['v0.1.1', 'v0.1.2'])
def test_old_or_current_release_does_not_prompt_update(tag):
    assert check_update('0.1.2', transport(release(tag))) is None


def test_version_comparison_is_numeric():
    assert check_update('0.9.0', transport(release('v0.10.0'))).version == '0.10.0'


@pytest.mark.parametrize('field', ['draft', 'prerelease'])
def test_unstable_release_is_ignored(field):
    assert check_update('0.1.2', transport({**release(), field: True})) is None


def test_foreign_download_address_is_rejected():
    data = release()
    data['assets'][0]['browser_download_url'] = 'https://example.test/Worklog.zip'
    with pytest.raises(ValueError, match='official Windows package'):
        check_update('0.1.2', transport(data))


def test_unavailable_update_server_returns_failure_without_retry_loop():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(403)
    with pytest.raises(httpx.HTTPStatusError):
        check_update(transport=httpx.MockTransport(handle))
    assert len(calls) == 1
