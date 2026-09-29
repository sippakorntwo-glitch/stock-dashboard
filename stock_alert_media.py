"""Publish public stock-briefing images to immutable, verified GitHub URLs.

The caller supplies a GitHub API client and public market data only. LINE
credentials and recipient details never enter this module. A separate branch
keeps generated media out of the application branch; each delivery references
its commit so later publications cannot change a reserved LINE message.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
import time
import urllib.error
import urllib.parse
import urllib.request

MEDIA_BRANCH = 'line-alert-media'
ORIGINAL_PATH = 'briefing.png'
PREVIEW_PATH = 'briefing-preview.png'
DATA_PATH = 'briefing.json'
ORIGINAL_LIMIT = 10_000_000
PREVIEW_LIMIT = 1_000_000
DATA_LIMIT = 900_000
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
_SHA = re.compile(r'[0-9a-f]{40}')
_REPOSITORY = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
_PUBLIC_PATH = re.compile(
    r'/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[0-9a-f]{40}/'
    r'(briefing\.png|briefing-preview\.png)')


class MediaError(RuntimeError):
    """Credential-free error suitable for public workflow logs."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _validate_png(raw, limit):
    if (not isinstance(raw, bytes) or len(raw) >= limit or len(raw) < 33
            or not raw.startswith(PNG_SIGNATURE)
            or raw[8:16] != b'\x00\x00\x00\rIHDR'):
        raise MediaError('Invalid briefing PNG or image size limit exceeded')
    width, height = struct.unpack('>II', raw[16:24])
    if not width or not height or width > 10_000 or height > 10_000:
        raise MediaError('Invalid briefing PNG dimensions')


def _sha(response):
    value = response.get('sha') if isinstance(response, dict) else None
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise MediaError('Invalid GitHub media object response')
    return value


def _repository(store):
    base = getattr(store, 'base', '')
    prefix = 'https://api.github.com/repos/'
    if not isinstance(base, str) or not base.startswith(prefix):
        raise MediaError('Invalid GitHub media repository')
    repo = base[len(prefix):]
    if not _REPOSITORY.fullmatch(repo):
        raise MediaError('Invalid GitHub media repository')
    return repo


def verify_public_png(url, expected_bytes, *, opener=None, sleep=time.sleep):
    """Confirm unauthenticated availability and exact bytes, without redirects.

    At most three requests are made with a ten-second socket timeout each.
    Only temporary availability failures retry, after one and two seconds.
    The response body is read once and bounded by the expected file size.
    """
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'raw.githubusercontent.com'
            or parsed.query or parsed.fragment or not _PUBLIC_PATH.fullmatch(parsed.path)):
        raise MediaError('Invalid public briefing image URL')
    limit = PREVIEW_LIMIT if parsed.path.endswith('/' + PREVIEW_PATH) else ORIGINAL_LIMIT
    _validate_png(expected_bytes, limit)
    expected_digest = hashlib.sha256(expected_bytes).digest()
    opener = opener or urllib.request.build_opener(_NoRedirect())
    for attempt in range(3):
        if attempt:
            sleep(attempt)
        # No Authorization header or GitHub credentials are sent to this host.
        request = urllib.request.Request(
            url, method='GET',
            headers={'Accept': 'image/png', 'User-Agent': 'StockDashboard-Briefing/1'})
        try:
            response = opener.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            if code in (404, 429, 500, 502, 503, 504) and attempt < 2:
                continue
            raise MediaError(f'Public briefing image unavailable (HTTP {code})') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < 2:
                continue
            raise MediaError('Public briefing image verification timed out or failed') from None
        try:
            with response:
                if response.geturl() != url or response.getcode() != 200:
                    raise MediaError('Unexpected public briefing image response')
                content_type = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                if content_type != 'image/png':
                    raise MediaError('Public briefing image has an invalid content type')
                declared_size = response.headers.get('Content-Length')
                if declared_size is not None:
                    if not declared_size.isdigit() or int(declared_size) != len(expected_bytes):
                        raise MediaError('Public briefing image size does not match')
                received = response.read(len(expected_bytes) + 1)
                if (len(received) != len(expected_bytes)
                        or hashlib.sha256(received).digest() != expected_digest):
                    raise MediaError('Public briefing image bytes do not match')
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < 2:
                continue
            raise MediaError('Public briefing image could not be read') from None
        return
    raise MediaError('Public briefing image verification failed')


def publish_briefing(store, original_png, preview_png, briefing, *, verify=verify_public_png):
    """Commit three generated files, preserve other files, verify both PNGs.

    ``store`` supplies ``base`` and ``call(method, path, body=None,
    missing=False)`` as implemented by ``line_alerts.GitHubState``. No delivery
    may proceed if this function raises, including after a successful commit.
    """
    repo = _repository(store)
    _validate_png(original_png, ORIGINAL_LIMIT)
    _validate_png(preview_png, PREVIEW_LIMIT)
    if not isinstance(briefing, dict):
        raise MediaError('Invalid public briefing data')
    try:
        metadata = json.dumps(briefing, ensure_ascii=False, allow_nan=False,
                              sort_keys=True, separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError, UnicodeError):
        raise MediaError('Invalid public briefing data') from None
    if len(metadata) >= DATA_LIMIT:
        raise MediaError('Public briefing data exceeds size limit')

    branch = store.call('GET', '/git/ref/heads/' + MEDIA_BRANCH, missing=True)
    parents = []
    tree_body = {'tree': []}
    if branch is not None:
        head = _sha(branch.get('object')) if isinstance(branch, dict) else _sha(None)
        commit = store.call('GET', '/git/commits/' + head)
        tree_body['base_tree'] = _sha(commit.get('tree')) if isinstance(commit, dict) else _sha(None)
        parents = [head]

    for path, raw in ((ORIGINAL_PATH, original_png), (PREVIEW_PATH, preview_png),
                      (DATA_PATH, metadata)):
        blob = store.call('POST', '/git/blobs',
                          {'encoding': 'base64', 'content': base64.b64encode(raw).decode('ascii')})
        tree_body['tree'].append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': _sha(blob)})
    tree = store.call('POST', '/git/trees', tree_body)
    commit = store.call('POST', '/git/commits',
                        {'message': 'Publish public stock briefing [skip ci]',
                         'tree': _sha(tree), 'parents': parents})
    commit_sha = _sha(commit)
    if branch is None:
        store.call('POST', '/git/refs', {'ref': 'refs/heads/' + MEDIA_BRANCH, 'sha': commit_sha})
    else:
        store.call('PATCH', '/git/refs/heads/' + MEDIA_BRANCH, {'sha': commit_sha, 'force': False})

    prefix = f'https://raw.githubusercontent.com/{repo}/{commit_sha}/'
    original_url, preview_url = prefix + ORIGINAL_PATH, prefix + PREVIEW_PATH
    verify(original_url, original_png)
    verify(preview_url, preview_png)
    return {'original_url': original_url, 'preview_url': preview_url, 'commit_sha': commit_sha}
