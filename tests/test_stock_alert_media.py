import base64
from email.message import Message
import io
import struct
import unittest
import urllib.error

from stock_alert_media import (DATA_PATH, MEDIA_BRANCH, MediaError, ORIGINAL_PATH,
                               PNG_SIGNATURE, PREVIEW_PATH, publish_briefing,
                               verify_public_png)

PNG = PNG_SIGNATURE + b'\x00\x00\x00\rIHDR' + struct.pack('>II', 100, 100) + b'\x08\x02\x00\x00\x00' + b'crc!'
URL = 'https://raw.githubusercontent.com/owner/repo/' + 'c' * 40 + '/briefing.png'


class Store:
    base = 'https://api.github.com/repos/owner/repo'

    def __init__(self, exists=True):
        self.exists = exists
        self.calls = []

    def call(self, method, path, body=None, missing=False):
        self.calls.append((method, path, body, missing))
        if method == 'GET' and path.startswith('/git/ref/'):
            return {'object': {'sha': 'a' * 40}} if self.exists else None
        if method == 'GET' and path.startswith('/git/commits/'):
            return {'tree': {'sha': 'b' * 40}}
        if path == '/git/blobs':
            return {'sha': 'd' * 40}
        if path == '/git/trees':
            return {'sha': 'e' * 40}
        if path == '/git/commits':
            return {'sha': 'c' * 40}
        return {}


class Response(io.BytesIO):
    def __init__(self, data=PNG, url=URL, content_type='image/png', content_length=None):
        super().__init__(data)
        self.url = url
        self.headers = Message()
        self.headers['Content-Type'] = content_type
        if content_length is not None:
            self.headers['Content-Length'] = content_length
        self.read_limits = []

    def geturl(self):
        return self.url

    def getcode(self):
        return 200

    def read(self, size=-1):
        self.read_limits.append(size)
        return super().read(size)


class Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class PublishingTests(unittest.TestCase):
    def test_existing_branch_preserves_base_and_publishes_before_verifying(self):
        store, verified = Store(), []

        def verify(url, expected):
            self.assertEqual(store.calls[-1][:2], ('PATCH', '/git/refs/heads/' + MEDIA_BRANCH))
            verified.append((url, expected))

        result = publish_briefing(store, PNG, PNG, {'public': 'ข่าว'}, verify=verify)
        tree = next(x[2] for x in store.calls if x[1] == '/git/trees')
        self.assertEqual(tree['base_tree'], 'b' * 40)
        self.assertEqual([x['path'] for x in tree['tree']], [ORIGINAL_PATH, PREVIEW_PATH, DATA_PATH])
        self.assertTrue(all(x['sha'] and x['type'] == 'blob' for x in tree['tree']))
        commit = next(x[2] for x in store.calls if x[1] == '/git/commits')
        self.assertEqual(commit['parents'], ['a' * 40])
        self.assertEqual(store.calls[-1][2], {'sha': 'c' * 40, 'force': False})
        self.assertEqual(result['original_url'], URL)
        self.assertEqual(len(verified), 2)
        blob = [x[2] for x in store.calls if x[1] == '/git/blobs'][-1]
        self.assertEqual(base64.b64decode(blob['content']).decode(), '{"public":"ข่าว"}')

    def test_missing_branch_initializes_orphan(self):
        store = Store(False)
        publish_briefing(store, PNG, PNG, {}, verify=lambda *args: None)
        tree = next(x[2] for x in store.calls if x[1] == '/git/trees')
        self.assertNotIn('base_tree', tree)
        commit = next(x[2] for x in store.calls if x[1] == '/git/commits')
        self.assertEqual(commit['parents'], [])
        self.assertEqual(store.calls[-1], ('POST', '/git/refs',
                                          {'ref': 'refs/heads/' + MEDIA_BRANCH, 'sha': 'c' * 40}, False))

    def test_invalid_image_never_writes(self):
        store = Store()
        for original, preview in ((b'not PNG', PNG), (PNG, PNG + b'x' * 1_000_000)):
            with self.assertRaises(MediaError):
                publish_briefing(store, original, preview, {})
        self.assertEqual(store.calls, [])

    def test_verification_failure_prevents_returning_delivery_urls(self):
        store = Store()

        def fail(*args):
            raise MediaError('unavailable')

        with self.assertRaisesRegex(MediaError, 'unavailable'):
            publish_briefing(store, PNG, PNG, {}, verify=fail)


class VerificationTests(unittest.TestCase):
    def test_get_is_unauthenticated_and_bounded(self):
        response = Response(content_length=str(len(PNG)))
        opener = Opener([response])
        verify_public_png(URL, PNG, opener=opener)
        request, timeout = opener.calls[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertFalse(request.has_header('Authorization'))
        self.assertFalse(request.has_header('Cookie'))
        self.assertEqual(timeout, 10)
        self.assertEqual(response.read_limits, [len(PNG) + 1])

    def test_rejects_changed_bytes_without_retry(self):
        opener = Opener([Response(data=PNG[:-1] + b'X')])
        with self.assertRaisesRegex(MediaError, 'bytes do not match'):
            verify_public_png(URL, PNG, opener=opener)
        self.assertEqual(len(opener.calls), 1)

    def test_rejects_wrong_hosts_branch_refs_and_redirect_destinations(self):
        opener = Opener([])
        for url in (URL.replace('raw.githubusercontent.com', 'example.com'),
                    URL.replace('https:', 'http:'), URL + '?token=secret',
                    URL.replace('c' * 40, 'line-alert-media'),
                    URL.replace('raw.githubusercontent.com', 'raw.githubusercontent.com@evil.com')):
            with self.assertRaises(MediaError):
                verify_public_png(url, PNG, opener=opener)
        self.assertEqual(opener.calls, [])
        with self.assertRaisesRegex(MediaError, 'Unexpected'):
            verify_public_png(URL, PNG, opener=Opener([Response(url='https://example.com/x.png')]))

    def test_rejects_bad_content_type_and_oversize_declaration(self):
        for response in (Response(content_type='text/html'), Response(content_length='99999999')):
            with self.assertRaises(MediaError):
                verify_public_png(URL, PNG, opener=Opener([response]))
            self.assertEqual(response.read_limits, [])

    def test_read_never_consumes_unbounded_oversized_response(self):
        response = Response(data=PNG + b'x' * 1_000_000)
        with self.assertRaises(MediaError):
            verify_public_png(URL, PNG, opener=Opener([response]))
        self.assertEqual(response.read_limits, [len(PNG) + 1])

    def test_propagation_404_retries_at_most_three_times(self):
        errors = [urllib.error.HTTPError(URL, 404, 'Not Found', {}, None) for _ in range(3)]
        opener, sleeps = Opener(errors), []
        with self.assertRaisesRegex(MediaError, 'HTTP 404'):
            verify_public_png(URL, PNG, opener=opener, sleep=sleeps.append)
        self.assertEqual(len(opener.calls), 3)
        self.assertEqual(sleeps, [1, 2])

    def test_publication_becomes_available_on_retry(self):
        opener = Opener([urllib.error.HTTPError(URL, 404, 'Not Found', {}, None), Response()])
        sleeps = []
        verify_public_png(URL, PNG, opener=opener, sleep=sleeps.append)
        self.assertEqual(sleeps, [1])

    def test_redirect_is_not_retried(self):
        opener = Opener([urllib.error.HTTPError(URL, 302, 'Redirect', {}, None)])
        with self.assertRaisesRegex(MediaError, 'HTTP 302'):
            verify_public_png(URL, PNG, opener=opener)
        self.assertEqual(len(opener.calls), 1)


if __name__ == '__main__':
    unittest.main()
