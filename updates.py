"""Check public release metadata only; never install or execute downloaded code."""
import re
from dataclasses import dataclass

import httpx

from backend.version import VERSION


REPOSITORY = 'kive231/zentao-worklog'
LATEST_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'


@dataclass(frozen=True)
class Update:
    version: str
    download_url: str


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+\.\d+\.\d+', value):
        raise ValueError('Unsupported release version')
    return tuple(int(part) for part in value.removeprefix('v').split('.'))


def check_update(current=VERSION, transport=None):
    with httpx.Client(timeout=8, follow_redirects=False, transport=transport) as client:
        response = client.get(LATEST_URL, headers={
            'Accept': 'application/vnd.github+json',
            'User-Agent': f'ZenTaoWorklog/{VERSION}',
        })
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            raise ValueError('Release metadata too large')
        release = response.json()
    if not isinstance(release, dict):
        raise ValueError('Invalid release metadata')
    if release.get('draft') or release.get('prerelease'):
        return None
    tag = release.get('tag_name', '')
    if version_tuple(tag) <= version_tuple(current):
        return None
    filename = f'ZenTaoWorklog-{tag}-Windows-x64.zip'
    expected_url = f'https://github.com/{REPOSITORY}/releases/download/{tag}/{filename}'
    for asset in release.get('assets', []):
        if asset.get('name') == filename and asset.get('browser_download_url') == expected_url:
            return Update(tag.removeprefix('v'), expected_url)
    raise ValueError('Release has no official Windows package')
