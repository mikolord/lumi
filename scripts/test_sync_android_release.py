import hashlib
import json
import unittest
from sync_android_release import BASE, START, synchronize


class ReleaseSyncTest(unittest.TestCase):
    def setUp(self):
        self.apk = b'signed-apk-fixture'
        self.info = {'versionName': '0.8.0-beta1', 'sha256': hashlib.sha256(self.apk).hexdigest()}
        self.android = dict(id=2, tag_name='android-v0.8.0-beta1', draft=False, prerelease=True,
                            published_at='2026-11-25', assets=[
            dict(name='lumi-android-0.8.0-beta1.apk', browser_download_url='apk'),
            dict(name='tv-version.json', browser_download_url='manifest')])
        self.server = dict(id=1, draft=False, prerelease=False, body='Original server notes', assets=[],
                           upload_url='https://uploads.github.com/repos/mikolord/lumi/releases/1/assets{?name}',
                           html_url='server')
        self.writes = []

    def fetch(self, url):
        return self.apk if url == 'apk' else json.dumps(self.info).encode()

    def api(self, url, body=None, content_type=None, method=None):
        if body is None:
            if '/releases?' in url:
                return [self.android]
            return self.server if url.endswith('v0.76.1') else self.android
        self.writes.append((url, body, method))
        if method == 'PATCH':
            self.server['body'] = json.loads(body)['body']
        else:
            self.server['assets'].append(dict(name=url.split('?name=')[1],
                digest='sha256:' + hashlib.sha256(body).hexdigest()))
        return {}

    def test_preserves_server_notes_and_labels_beta_then_is_idempotent(self):
        synchronize(self.api, 'v0.76.1', fetch=self.fetch)
        self.assertEqual(len(self.writes), 3)
        self.assertIn('Original server notes', self.server['body'])
        self.assertIn('**бета**', self.server['body'])
        self.assertEqual(self.server['body'].count(START), 1)
        synchronize(self.api, 'v0.76.1', fetch=self.fetch)
        self.assertEqual(len(self.writes), 3)

    def test_checksum_failure_never_mutates_release(self):
        self.info['sha256'] = 'bad'
        with self.assertRaises(ValueError):
            synchronize(self.api, 'v0.76.1', fetch=self.fetch)
        self.assertEqual(self.writes, [])

    def test_conflicting_asset_never_overwrites_or_uploads(self):
        self.server['assets'] = [dict(name='android-version.json', digest='sha256:old')]
        with self.assertRaises(ValueError):
            synchronize(self.api, 'v0.76.1', fetch=self.fetch)
        self.assertEqual(self.writes, [])


if __name__ == '__main__':
    unittest.main()
