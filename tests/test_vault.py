import functools
import hashlib
import http.cookiejar
import importlib.util
import json
from pathlib import Path
import secrets
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vault import Vault, VaultError, RETENTION, b64, unb64
from server import Handler
import cbor2
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.vault = Vault(ROOT, Path(self.temp.name) / 'private', 'http://localhost')
        self.setup_token = (self.vault.directory / 'setup-token').read_text()
        self.token = self.vault.setup(self.setup_token, '48271639')

    def tearDown(self):
        self.vault.db.close()
        self.temp.cleanup()

    def test_system_album_covers(self):
        v=self.vault
        public=[item['id'] for item in v.library('')['items'] if item['state']=='public']
        self.assertEqual(v.library('')['collectionCovers']['Недавние'],max(public))
        v._set('cover:Недавние','1')
        self.assertEqual(v.library('')['collectionCovers']['Недавние'],max(public))
        with self.assertRaises(VaultError):
            v.album_action(dict(action='system-cover',name='Недавние',index=1),'')
        with self.assertRaises(VaultError):
            v.album_action(dict(action='system-cover',name='Избранное',index=1),'')
        v.favorite([1],True,'')
        v.album_action(dict(action='system-cover',name='Избранное',index=1),'')
        self.assertEqual(v.library('')['collectionCovers']['Избранное'],1)
        v.mutate('hide',[1],self.token)
        self.assertNotIn('Избранное',v.library('')['collectionCovers'])
        newest=max(i for i in public if i!=1)
        v.mutate('trash',[newest],self.token)
        self.assertEqual(v.library('')['collectionCovers']['Недавние'],max(i for i in public if i not in (1,newest)))
        with self.assertRaises(VaultError):
            v.album_action(dict(action='system-cover',name='Недавние',index=1),'')
        with self.assertRaises(VaultError):
            v.album_action(dict(action='system-cover',name='Скрытые',index=0),'')

    def test_password_setup_rate_limit_and_sessions(self):
        self.assertTrue(self.vault.authenticated(self.token))
        self.assertFalse(self.vault.authenticated('forged'))
        with self.assertRaises(VaultError):
            self.vault.setup(self.setup_token, '99999999')
        self.assertFalse((self.vault.directory / 'setup-token').exists())
        self.assertNotEqual(self.vault._setting('pin_hash'), '48271639')
        for _ in range(5):
            with self.assertRaises(VaultError):
                self.vault.unlock('wrong')
        with self.assertRaises(VaultError) as error:
            self.vault.unlock('48271639')
        self.assertEqual(error.exception.status, 429)
        self.vault.sign_out(self.token)
        self.assertFalse(self.vault.authenticated(self.token))

    def test_authorization_duplicates_restore_and_expiry(self):
        with self.assertRaises(VaultError):
            self.vault.mutate('hide', [0], '')
        self.vault.mutate('duplicate', [0], self.token)
        duplicate_id = self.vault.library(self.token)['items'][-1]['id']
        self.vault.mutate('hide', [0], self.token)
        with self.assertRaises(VaultError):
            self.vault.media_path(0, True, '')
        self.assertTrue(self.vault.media_path(duplicate_id, False, '').exists(), 'duplicates have independent files and protection')
        private = self.vault.library('')['items'][0]
        self.assertEqual(private['state'], 'locked')
        self.assertNotIn('metadata', private)
        self.vault.mutate('trash', [0], self.token)
        first_date = self.vault.library(self.token)['items'][0]['deletedAt']
        self.vault.mutate('trash', [0], self.token)
        self.assertEqual(self.vault.library(self.token)['items'][0]['deletedAt'], first_date)
        self.vault.mutate('restore', [0], self.token)
        self.assertEqual(self.vault.library(self.token)['items'][0]['state'], 'hidden')
        self.vault.mutate('trash', [0], self.token)
        path = self.vault.media_path(0, False, self.token)
        deletion = self.vault.db.execute('SELECT deleted_at FROM assets WHERE id=0').fetchone()[0]
        self.vault.expire(deletion + RETENTION - 1)
        self.assertTrue(path.exists())
        self.vault.expire(deletion + RETENTION)
        self.assertFalse(path.exists(), 'expired original is physically removed from the data directory')
        with self.assertRaises(VaultError):
            self.vault.media_path(0, False, self.token)
        self.assertTrue((ROOT / 'assets/10.jpg').exists(), 'source design fixtures are not modified')

    def registration(self):
        options = self.vault.passkey_options(True, self.token)
        challenge = options['publicKey']['challenge']
        self.assertEqual(options['publicKey']['authenticatorSelection']['userVerification'], 'required')
        private = ec.generate_private_key(ec.SECP256R1())
        numbers = private.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, 'big'), -3: numbers.y.to_bytes(32, 'big')})
        credential_id = secrets.token_bytes(32)
        client = json.dumps(dict(type='webauthn.create', challenge=challenge, origin='http://localhost')).encode()
        authenticator = hashlib.sha256(b'localhost').digest() + bytes([0x45]) + struct.pack('>I', 0) + bytes(16) + struct.pack('>H', len(credential_id)) + credential_id + cose
        credential = dict(id=b64(credential_id), rawId=b64(credential_id), type='public-key', response=dict(clientDataJSON=b64(client), attestationObject=b64(cbor2.dumps(dict(fmt='none', attStmt={}, authData=authenticator)))), clientExtensionResults={})
        self.vault.passkey_verify(True, options['challengeId'], credential, self.token)
        return private, credential_id

    def assertion(self, private, credential_id, options, origin='http://localhost', verified=True, count=1):
        client = json.dumps(dict(type='webauthn.get', challenge=options['publicKey']['challenge'], origin=origin)).encode()
        authenticator = hashlib.sha256(b'localhost').digest() + bytes([0x05 if verified else 0x01]) + struct.pack('>I', count)
        signature = private.sign(authenticator + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return dict(id=b64(credential_id), rawId=b64(credential_id), type='public-key', response=dict(clientDataJSON=b64(client), authenticatorData=b64(authenticator), signature=b64(signature)), clientExtensionResults={})

    def test_real_passkey_signatures_origin_uv_and_replay(self):
        private, credential_id = self.registration()
        options = self.vault.passkey_options(False, '')
        credential = self.assertion(private, credential_id, options)
        session = self.vault.passkey_verify(False, options['challengeId'], credential, '')
        self.assertTrue(self.vault.authenticated(session))
        with self.assertRaises(VaultError):
            self.vault.passkey_verify(False, options['challengeId'], credential, '')
        for origin, uv in [('https://evil.example', True), ('http://localhost', False)]:
            options = self.vault.passkey_options(False, '')
            with self.assertRaises(VaultError):
                self.vault.passkey_verify(False, options['challengeId'], self.assertion(private, credential_id, options, origin, uv, 2), '')
        options = self.vault.passkey_options(False, '')
        invalid = self.assertion(private, credential_id, options, count=2)
        invalid['response']['signature'] = b64(bytes(64))
        with self.assertRaises(VaultError):
            self.vault.passkey_verify(False, options['challengeId'], invalid, '')

    def test_http_direct_urls_head_ranges_and_csrf(self):
        class TestHandler(Handler):
            vault = self.vault
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(TestHandler, directory=str(ROOT)))
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            self.vault.mutate('hide', [0], self.token)
            for route in ('/media/0/original', '/media/0/preview', '/assets/10.jpg', '/assets/%31%30.jpg'):
                for method in ('GET', 'HEAD'):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(urllib.request.Request(base + route, method=method, headers={'Range': 'bytes=0-15'}))
                    self.assertIn(error.exception.code, (401, 403))
            request = urllib.request.Request(base + '/media/0/original', headers={'Cookie': f'photo_vault={self.token}', 'Range': 'bytes=0-15'})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertEqual(response.read(), (ROOT / 'assets/10.jpg').read_bytes()[:16])
            payload = json.dumps(dict(action='unhide', indices=[0])).encode()
            request = urllib.request.Request(base + '/api/assets/action', data=payload, headers={'Cookie': f'photo_vault={self.token}', 'Origin': 'https://evil.example'})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 403)
        finally:
            server.shutdown(); server.server_close(); worker.join()


if __name__ == '__main__':
    unittest.main()
