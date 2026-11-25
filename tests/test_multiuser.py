"""Real HTTP tests with separate cookie jars and physical, isolated media."""
import concurrent.futures
import functools
import http.cookiejar
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from vault import Vault,VaultError
from users import Accounts
from server import Handler


class MultiuserTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.control=Vault(ROOT,self.home/'data','http://localhost')
        self.accounts=Accounts(self.control,{'photo':ROOT/'assets'})
        class TestHandler(Handler):
            def log_message(self,*args):pass
        TestHandler.vault=self.control;TestHandler.accounts=self.accounts
        self.server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(TestHandler,directory=str(ROOT)))
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.admin=self.client();self.alice=self.client();self.bob=self.client()
        self.call(self.admin,'/api/account/register',dict(name='Admin',login='admin',password='administrator password'))
        self.call(self.admin,'/api/account/finish',{})
        self.call(self.admin,'/api/admin/users/create',dict(name='Alice',login='alice',password='alice password',quota=1000000))
        self.call(self.admin,'/api/admin/users/create',dict(name='Bob',login='bob',password='bob password',quota=1000000))
        self.call(self.alice,'/api/account/login',dict(login='alice',password='alice password'))
        self.call(self.bob,'/api/account/login',dict(login='bob',password='bob password'))

    def client(self):
        client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));client.photo_csrf='';return client
    def call(self,client,path,body=None,method=None,origin=None,headers=None):
        if body is not None and not client.photo_csrf:self.call(client,'/api/account/status')
        raw=body if isinstance(body,bytes) else json.dumps(body).encode() if body is not None else None
        request=urllib.request.Request(self.url+path,data=raw,method=method,headers={'Origin':origin or self.url,'Content-Type':'application/json','X-Photo-App-Origin':self.url,'X-Photo-CSRF':client.photo_csrf,**(headers or {})})
        with client.open(request) as response:
            data=response.read()
            result=json.loads(data) if 'application/json' in response.headers.get('Content-Type','') and data else data
            if isinstance(result,dict) and 'csrf' in result:client.photo_csrf=result['csrf']
            return result
    def denied(self,client,path,code,body=None,method=None,**kwargs):
        try:self.call(client,path,body,method,**kwargs)
        except urllib.error.HTTPError as error:self.assertEqual(error.code,code,path);error.close()
        else:self.fail('Unexpected access: '+path)
    def upload(self,client):return self.call(client,'/api/assets/upload',(ROOT/'assets/10.jpg').read_bytes()+__import__('secrets').token_bytes(16),headers={'X-File-Name':'photo.jpg'})['id']

    def tearDown(self):
        self.server.shutdown();self.server.server_close()
        for v,_ in self.accounts.libraries.values():
            if v is not self.control:v.db.close()
        self.control.db.close();self.temp.cleanup()

    def test_device_sessions_and_qr_pairing(self):
        tv=self.client(); pair=self.call(tv,'/api/tv/pair/start',dict(device='Гостиная Android TV'))
        self.assertFalse(self.call(tv,'/api/tv/pair/poll',dict(id=pair['id'],secret=pair['poll']))['approved'])
        self.denied(tv,'/api/tv/pair/inspect',401,dict(id=pair['id'],secret=pair['approve']))
        self.denied(self.alice,'/api/tv/pair/inspect',404,dict(id=pair['id'],secret=pair['poll']))
        info=self.call(self.alice,'/api/tv/pair/inspect',dict(id=pair['id'],secret=pair['approve']))
        self.assertEqual(info['code'],pair['code']);self.assertNotIn('poll',info)
        self.denied(self.alice,'/api/tv/pair/approve',400,dict(id=pair['id'],secret=pair['approve'],code='xxxxxx'))
        self.call(self.alice,'/api/tv/pair/approve',dict(id=pair['id'],secret=pair['approve'],code=pair['code']))
        self.assertTrue(self.call(tv,'/api/tv/pair/poll',dict(id=pair['id'],secret=pair['poll']))['approved'])
        self.assertEqual(self.call(tv,'/api/account/status')['id'],self.call(self.alice,'/api/account/status')['id'])
        self.denied(self.client(),'/api/tv/pair/poll',404,dict(id=pair['id'],secret=pair['poll']))
        sessions=self.call(self.alice,'/api/account/sessions')['sessions'];self.assertEqual(len(sessions),2)
        other=next(s for s in sessions if not s['current']);self.assertEqual(other['device'],'Гостиная Android TV')
        self.call(self.bob,'/api/account/sessions/revoke',dict(id=other['id']))
        self.assertTrue(self.call(tv,'/api/account/status')['authenticated'])
        self.call(self.alice,'/api/account/sessions/revoke',dict(others=True))
        self.assertFalse(self.call(tv,'/api/account/status')['authenticated']);self.assertTrue(self.call(self.alice,'/api/account/status')['authenticated'])
        approval_device=self.client();self.call(approval_device,'/api/account/login',dict(login='alice',password='alice password'))
        pair=self.call(tv,'/api/tv/pair/start',dict(device='TV'))
        self.call(approval_device,'/api/tv/pair/approve',dict(id=pair['id'],secret=pair['approve'],code=pair['code']))
        self.call(self.alice,'/api/account/sessions/revoke',dict(others=True))
        self.denied(tv,'/api/tv/pair/poll',403,dict(id=pair['id'],secret=pair['poll']))
        pair=self.call(tv,'/api/tv/pair/start',dict(device='TV'))
        with self.control.lock,self.control.db:self.control.db.execute('UPDATE tv_pairing SET expires=? WHERE id=?',(time.time()-1,pair['id']))
        self.denied(self.alice,'/api/tv/pair/inspect',404,dict(id=pair['id'],secret=pair['approve']))

    def test_encrypted_thumbnail_scope_and_revocation(self):
        a=self.upload(self.alice);self.upload(self.bob)
        original=Vault.media_path
        def checked_path(vault,*args,**kwargs):
            self.assertTrue(vault.operation_lock._is_owned(),'Thumbnail must acquire operation lock before the vault lock')
            return original(vault,*args,**kwargs)
        with patch.object(Vault,'media_path',checked_path):
            alice=self.call(self.alice,'/api/thumbnails/verify?index=0');bob=self.call(self.bob,'/api/thumbnails/verify?index=0')
            self.assertNotEqual(alice['owner'],bob['owner']);self.assertNotEqual(alice['key'],bob['key']);self.assertNotEqual(alice['tag'],bob['tag'])
            thumbnail=self.call(self.alice,'/media/0/thumbnail');self.assertEqual(thumbnail[:2],b'\xff\xd8')
        from PIL import Image
        self.assertLessEqual(max(Image.open(io.BytesIO(thumbnail)).size),192)
        self.denied(self.client(),'/api/thumbnails/verify?index=0',401);self.denied(self.client(),'/media/0/thumbnail',401)
        self.call(self.alice,'/api/assets/action',dict(action='hide',indices=[a]))
        self.denied(self.alice,'/api/thumbnails/verify?index=0',404);self.denied(self.alice,'/media/0/thumbnail',404)
        self.assertTrue(self.call(self.bob,'/api/thumbnails/verify?index=0'))

    def test_first_setup_roles_namespaces_and_upload(self):
        anonymous=self.client()
        self.denied(anonymous,'/api/account/register',409,dict(name='Hacker',login='hacker',password='password 1234'))
        self.denied(self.alice,'/api/admin/users',403)
        self.denied(self.alice,'/api/account/folders',403)
        self.denied(self.alice,'/api/admin/users/create',403,dict(name='x',login='new',password='new password',quota=0))
        self.denied(anonymous,'/api/library',401)
        a=self.upload(self.alice)
        self.assertEqual(a,0)
        self.assertEqual(len(self.call(self.alice,'/api/library')['items']),1)
        self.assertEqual(self.call(self.bob,'/api/library')['items'],[])
        for method in ('GET','HEAD'):
            self.denied(self.bob,'/media/0/original',404,method=method)
            self.denied(anonymous,'/media/0/original',401,method=method)
            self.denied(self.bob,'/%61ssets/10.jpg',403,method=method)
        b=self.upload(self.bob);self.assertEqual(b,0)
        # Equal numeric IDs resolve to different physical files and independent states.
        alice_id=self.call(self.alice,'/api/account/status')['id'];bob_id=self.call(self.bob,'/api/account/status')['id']
        self.assertNotEqual(self.accounts.libraries[alice_id][0].media_path(0,False,''),self.accounts.libraries[bob_id][0].media_path(0,False,''))
        self.call(self.alice,'/api/assets/action',dict(action='hide',indices=[0]))
        self.denied(self.alice,'/media/0/original',401)
        self.assertTrue(self.call(self.bob,'/media/0/original'))
        self.call(self.alice,'/api/vault/setup',dict(pin='48271639'))
        self.assertTrue(self.call(self.alice,'/media/0/original'))
        self.assertFalse(self.call(self.bob,'/api/vault/status')['configured'])
        self.call(self.bob,'/api/vault/setup',dict(pin='98765432'))
        self.denied(self.bob,'/api/vault/unlock',401,dict(pin='48271639'))
        self.denied(self.alice,'/api/account/profile',403,dict(name='hacked'),origin='https://evil.example')

    def test_quotas_duplication_trash_and_concurrent_uploads(self):
        self.upload(self.alice)
        status=self.call(self.alice,'/api/account/status');used=status['used']
        self.call(self.admin,'/api/admin/users/update',dict(id=status['id'],quota=used))
        self.denied(self.alice,'/api/assets/upload',413,(ROOT/'assets/10.jpg').read_bytes(),headers={'X-File-Name':'another.jpg'})
        self.denied(self.alice,'/api/assets/action',413,dict(action='duplicate',indices=[0]))
        self.call(self.alice,'/api/assets/action',dict(action='trash',indices=[0]))
        self.assertEqual(self.call(self.alice,'/api/account/status')['used'],used)
        self.call(self.alice,'/api/vault/setup',dict(pin='48271639'))
        self.call(self.alice,'/api/assets/action',dict(action='purge',indices=[0]))
        self.assertEqual(self.call(self.alice,'/api/account/status')['used'],0)
        self.call(self.admin,'/api/admin/users/update',dict(id=status['id'],quota=used))
        def attempt(_):
            try:self.upload(self.alice);return True
            except urllib.error.HTTPError as error:self.assertEqual(error.code,413);error.close();return False
        with concurrent.futures.ThreadPoolExecutor(2) as pool:outcomes=list(pool.map(attempt,range(2)))
        self.assertEqual(sum(outcomes),1)
        self.assertLessEqual(self.call(self.alice,'/api/account/status')['used'],used)

    def test_personal_albums_explicit_sharing_and_revocation(self):
        self.upload(self.alice)
        state=self.call(self.alice,'/api/albums/action',dict(action='create',name='Семья'));album=state['albums'][0]
        self.call(self.alice,'/api/albums/action',dict(action='add',id=album['id'],indices=[0]))
        self.assertEqual(self.call(self.bob,'/api/library')['albums'],[])
        bob_id=self.call(self.bob,'/api/account/status')['id']
        self.call(self.alice,'/api/albums/share',dict(id=album['id'],users=[bob_id]))
        received=self.call(self.bob,'/api/library');item=received['items'][0]
        self.assertEqual(item['state'],'shared');self.assertTrue(received['albums'][0]['shared'])
        self.assertTrue(self.call(self.bob,item['original']))
        self.denied(self.bob,'/api/assets/action',404,dict(action='trash',indices=[item['id']]))
        self.call(self.alice,'/api/assets/action',dict(action='hide',indices=[0]))
        self.denied(self.bob,item['original'],404)
        self.assertEqual(self.call(self.bob,'/api/library')['items'][0]['state'],'purged')
        self.call(self.alice,'/api/vault/setup',dict(pin='48271639'))
        self.call(self.alice,'/api/assets/action',dict(action='unhide',indices=[0]))
        received_again=self.call(self.bob,'/api/library');self.assertEqual(received_again['items'][0]['id'],item['id'])
        self.call(self.alice,'/api/albums/share',dict(id=album['id'],users=[]))
        self.denied(self.bob,item['original'],404)
        self.denied(self.admin,item['original'],404)

    def test_csrf_through_proxy_and_between_account_sessions(self):
        # KeenDNS removes Origin. A signed token and cookie still authorize this own-site request.
        state=self.call(self.alice,'/api/account/profile',dict(name='Alice through proxy'),headers={'Origin':''})
        self.assertEqual(state['name'],'Alice through proxy')
        self.denied(self.alice,'/api/account/profile',403,dict(name='No token'),headers={'Origin':'','X-Photo-CSRF':''})
        alice_csrf=self.alice.photo_csrf
        self.call(self.alice,'/api/account/login',dict(login='bob',password='bob password'))
        # A stale tab cannot submit its old Alice actions with the now-current Bob cookie.
        bob_csrf=self.alice.photo_csrf;self.alice.photo_csrf=alice_csrf
        self.denied(self.alice,'/api/account/profile',403,dict(name='Wrong account'),headers={'Origin':''})
        self.alice.photo_csrf=bob_csrf
        self.assertEqual(self.call(self.alice,'/api/account/status')['name'],'Bob')
        self.denied(self.alice,'/api/account/profile',403,dict(name='Evil'),origin='https://evil.example')

    def test_disable_password_reset_and_persistent_accounts(self):
        alice_id=self.call(self.alice,'/api/account/status')['id']
        self.call(self.admin,'/api/admin/users/update',dict(id=alice_id,disabled=True))
        self.denied(self.alice,'/api/library',401)
        self.denied(self.client(),'/api/account/login',401,dict(login='alice',password='alice password'))
        self.call(self.admin,'/api/admin/users/update',dict(id=alice_id,disabled=False,password='new alice password'))
        self.denied(self.client(),'/api/account/login',401,dict(login='alice',password='alice password'))
        fresh=self.client();self.assertTrue(self.call(fresh,'/api/account/login',dict(login='alice',password='new alice password'))['authenticated'])
        # Recreate the account service over the same persistent SQLite.
        restarted=Accounts(self.control,{})
        self.assertTrue(restarted.configured)
        token=restarted.login(dict(login='alice',password='new alice password'),address='restart')
        self.assertEqual(restarted.status(token)['id'],alice_id)
        for v,_ in restarted.libraries.values():
            if v is not self.control:v.db.close()

    def test_reselected_content_is_skipped_and_private_assets_stay_private(self):
        import hashlib
        body=(ROOT/'assets/10.jpg').read_bytes();digest=hashlib.sha256(body).hexdigest()
        first=self.call(self.alice,'/api/assets/upload',body,headers={'X-File-Name':'original.jpg'})
        again=self.call(self.alice,'/api/assets/upload',body,headers={'X-File-Name':'renamed.jpg','X-Upload-ID':'second-selection-123456'})
        self.assertTrue(again.get('duplicate'),'Reselecting identical bytes must skip a second asset')
        self.assertEqual(first['id'],again['id'])
        self.assertTrue(self.call(self.alice,'/api/assets/upload-status?key=second-selection-123456')['duplicate'])
        def send_same(n):return self.call(self.alice,'/api/assets/upload',body,headers={'X-File-Name':f'copy-{n}.jpg','X-Upload-ID':f'parallel-duplicate-{n:08d}'})
        with concurrent.futures.ThreadPoolExecutor(2) as pool:copies=list(pool.map(send_same,range(2)))
        self.assertTrue(all(row['duplicate'] and row['id']==first['id'] for row in copies))
        self.assertEqual(len(self.call(self.alice,'/api/library')['items']),1)
        self.assertTrue(self.call(self.alice,'/api/assets/check',dict(size=len(body),sha256=digest))['duplicate'])
        self.assertFalse(self.call(self.bob,'/api/assets/check',dict(size=len(body),sha256=digest))['duplicate'])
        self.call(self.alice,'/api/vault/setup',dict(pin='12345678'))
        self.call(self.alice,'/api/assets/action',dict(action='hide',indices=[0]))
        self.call(self.alice,'/api/vault/lock',{})
        check=self.call(self.alice,'/api/assets/check',dict(size=len(body),sha256=digest))
        self.assertEqual(check,{'duplicate':True})
        self.assertEqual(self.call(self.alice,'/api/library')['items'][0]['state'],'locked')
        self.denied(self.alice,'/media/0/original',401)
        # Legacy assets get indexed lazily, by actual bytes, not just file name/size.
        uid=self.call(self.alice,'/api/account/status')['id'];v,imp=self.accounts.libraries[uid]
        with v.lock,v.db:v.db.execute('DELETE FROM asset_hashes')
        self.assertTrue(self.call(self.alice,'/api/assets/check',dict(size=len(body),sha256=digest))['duplicate'])
        self.denied(self.alice,'/api/assets/check',400,dict(size=len(body),sha256='forged'))
        self.call(self.alice,'/api/assets/upload',body+b'1',headers={'X-File-Name':'same-name.jpg'})
        different=self.call(self.alice,'/api/assets/upload',body+b'2',headers={'X-File-Name':'same-name.jpg'})
        self.assertFalse(different['duplicate'],'Same size/name with different bytes must be kept')
        self.assertEqual(len(self.call(self.alice,'/api/library')['items']),3)

    def test_upload_receipts_survive_retry_and_isolate_accounts(self):
        key='unique-file-id-123456789'
        body=(ROOT/'assets/10.jpg').read_bytes();headers={'X-File-Name':'photo.jpg','X-Upload-ID':key}
        self.assertFalse(self.call(self.alice,'/api/assets/upload-status?key='+key)['complete'])
        first=self.call(self.alice,'/api/assets/upload',body,headers=headers)
        again=self.call(self.alice,'/api/assets/upload',body,headers=headers)
        self.assertEqual(first['id'],again['id']);self.assertTrue(again['repeated'])
        self.assertTrue(self.call(self.alice,'/api/assets/upload-status?key='+key)['complete'])
        self.assertFalse(self.call(self.bob,'/api/assets/upload-status?key='+key)['complete'])
        self.assertEqual(len(self.call(self.alice,'/api/library')['items']),1)
        self.denied(self.alice,'/api/assets/upload',409,b'changed body',headers=headers)
        headers['X-Upload-ID']='concurrent-file-123456789'
        def upload(_):return self.call(self.alice,'/api/assets/upload',body,headers=headers)['id']
        with concurrent.futures.ThreadPoolExecutor(2) as pool:ids=list(pool.map(upload,range(2)))
        self.assertEqual(ids[0],ids[1]);self.assertEqual(len(self.call(self.alice,'/api/library')['items']),1)

    def test_album_cover_persistence_visibility_and_sharing(self):
        self.upload(self.alice);self.upload(self.alice);self.upload(self.alice)
        album=self.call(self.alice,'/api/albums/action',dict(action='create',name='Cover test'))['albums'][0];uid=album['id']
        self.call(self.alice,'/api/albums/action',dict(action='add',id=uid,indices=[0,1]))
        self.denied(self.alice,'/api/albums/action',404,dict(action='cover',id=uid,index=2))
        self.denied(self.bob,'/api/albums/action',404,dict(action='cover',id=uid,index=0))
        state=self.call(self.alice,'/api/albums/action',dict(action='cover',id=uid,index=1));self.assertEqual(state['albums'][0]['cover'],1)
        self.assertEqual(self.call(self.alice,'/api/library')['albums'][0]['cover'],1)
        bob_id=self.call(self.bob,'/api/account/status')['id']
        self.call(self.alice,'/api/albums/share',dict(id=uid,users=[bob_id]))
        shared=self.call(self.bob,'/api/library');cover=shared['albums'][0]['cover']
        self.assertEqual(shared['items'][cover]['original'].split('/')[-2],'1')
        self.call(self.alice,'/api/assets/action',dict(action='hide',indices=[1]))
        self.assertEqual(self.call(self.alice,'/api/library')['albums'][0]['cover'],0)
        shared=self.call(self.bob,'/api/library');self.assertEqual(shared['items'][shared['albums'][0]['cover']]['original'].split('/')[-2],'0')
        self.denied(self.alice,'/api/albums/action',404,dict(action='cover',id=uid,index=1))
        self.call(self.alice,'/api/albums/action',dict(action='remove',id=uid,indices=[0]))
        self.assertIsNone(self.call(self.alice,'/api/library')['albums'][0]['cover'])

    def test_delete_user_revokes_sessions_shares_and_erases_library(self):
        alice_id=self.call(self.alice,'/api/account/status')['id']
        admin_id=self.call(self.admin,'/api/account/status')['id']
        self.upload(self.alice);self.upload(self.bob)
        v,importer=self.accounts.libraries[alice_id]
        media=list(v.media.iterdir());self.assertTrue(media)
        album=self.call(self.alice,'/api/albums/action',dict(action='create',name='Shared before delete'))['albums'][0]
        self.call(self.alice,'/api/albums/action',dict(action='add',id=album['id'],indices=[0]))
        bob_id=self.call(self.bob,'/api/account/status')['id']
        self.call(self.alice,'/api/albums/share',dict(id=album['id'],users=[bob_id]))
        shared=next(i for i in self.call(self.bob,'/api/library')['items'] if i['state']=='shared')['original']
        self.denied(self.bob,'/api/admin/users/delete',403,dict(id=alice_id,confirmLogin='alice'))
        self.denied(self.admin,'/api/admin/users/delete',401,dict(id=admin_id,confirmLogin='admin',files='delete'))
        self.denied(self.admin,'/api/admin/users/delete',400,dict(id=alice_id,confirmLogin='wrong'))
        self.call(self.admin,'/api/admin/users/delete',dict(id=alice_id,confirmLogin='alice',files='delete'))
        self.denied(self.alice,'/api/library',401)
        self.denied(self.client(),'/api/account/login',401,dict(login='alice',password='alice password'))
        self.denied(self.bob,shared,404)
        self.assertFalse(any(path.exists() for path in media))
        with self.accounts.request_lock:pass
        self.assertFalse(v.directory.exists())
        self.assertNotIn(alice_id,[u['id'] for u in self.call(self.admin,'/api/admin/users')['users']])
        self.assertTrue(self.call(self.bob,'/media/0/original'))
        with self.assertRaises(VaultError):v.check_quota()
        # An in-flight upload bound to the retired library cannot save after deletion.
        source=self.home/'pending.jpg';source.write_bytes((ROOT/'assets/10.jpg').read_bytes())
        with self.assertRaises(VaultError):__import__('accounts').LibraryImporter.ingest(importer,source,'pending.jpg')
        self.accounts.expire_all()
        replacement=self.call(self.admin,'/api/admin/users/create',dict(name='New Alice',login='alice',password='new alice password',quota=0))
        self.assertNotEqual(replacement['id'],alice_id)

    def test_personal_storage_counts_only_own_files_and_quota(self):
        self.upload(self.admin);self.upload(self.alice);self.upload(self.bob)
        admin=self.call(self.admin,'/api/storage');alice=self.call(self.alice,'/api/storage')
        self.assertEqual(admin['scope'],'account');self.assertIsNone(admin['total']);self.assertIsNone(admin['free'])
        self.assertGreater(admin['used'],0);self.assertGreater(admin['available'],0)
        self.assertEqual(alice['total'],1000000);self.assertEqual(alice['free'],1000000-alice['used'])
        before=alice['used'];self.upload(self.bob)
        self.assertEqual(self.call(self.alice,'/api/storage')['used'],before)
        self.call(self.alice,'/api/assets/action',dict(action='trash',indices=[0]))
        self.assertEqual(self.call(self.alice,'/api/storage')['used'],before)
        self.denied(self.client(),'/api/storage',401)

    def test_delete_keep_files_and_wait_for_inflight_request(self):
        self.upload(self.alice);uid=self.call(self.alice,'/api/account/status')['id'];v,importer=self.accounts.libraries[uid]
        source=v.media_path(0,False,'');original=source.read_bytes()
        self.denied(self.admin,'/api/admin/users/delete',400,dict(id=uid,confirmLogin='alice'))
        self.call(self.admin,'/api/admin/users/delete',dict(id=uid,confirmLogin='alice',files='keep'))
        self.denied(self.alice,'/api/library',401)
        with self.accounts.request_lock:pass
        self.assertEqual(source.read_bytes(),original);self.assertTrue(v.directory.exists())
        replacement=self.call(self.admin,'/api/admin/users/create',dict(name='New Alice',login='alice',password='new alice password',quota=0))
        self.assertNotEqual(replacement['id'],uid)
        self.call(self.alice,'/api/account/login',dict(login='alice',password='new alice password'))
        self.assertEqual(self.call(self.alice,'/api/library')['items'],[])
        # Hold a request lease: credentials go away immediately; open DB/file
        # readers finish before physical removal and connection closure.
        self.upload(self.bob);bob=self.call(self.bob,'/api/account/status')['id'];bv,bi=self.accounts.libraries[bob]
        self.accounts.request_started()
        try:
            self.call(self.admin,'/api/admin/users/delete',dict(id=bob,confirmLogin='bob',files='delete'))
            self.assertTrue(bv.directory.exists());self.assertEqual(bv.db.execute('SELECT count(*) FROM assets').fetchone()[0],1)
            self.denied(self.bob,'/api/library',401)
            with self.assertRaises(VaultError):bi.ingest(source,'late.jpg')
        finally:self.accounts.request_finished()
        # The HTTP response can arrive before its handler releases the last lease.
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            with self.accounts.request_lock:
                if self.accounts.active_requests==0:break
            threading.Event().wait(.01)
        self.assertFalse(bv.directory.exists());self.assertTrue(source.exists())

    def test_owner_deletion_transfers_admin_and_preserves_other_users(self):
        self.upload(self.admin);self.upload(self.bob)
        uid=self.call(self.admin,'/api/account/status')['id'];alice=self.call(self.alice,'/api/account/status')['id']
        body=dict(confirmLogin='admin',password='administrator password',files='delete')
        self.denied(self.admin,'/api/account/delete',409,body)
        self.denied(self.admin,'/api/account/delete',401,{**body,'password':'wrong','successor':alice})
        self.call(self.admin,'/api/account/delete',{**body,'successor':alice})
        self.denied(self.admin,'/api/library',401)
        status=self.call(self.alice,'/api/account/status');self.assertEqual(status['role'],'admin');self.assertTrue(status['ready'])
        self.assertTrue(self.call(self.bob,'/media/0/original'))
        with self.accounts.request_lock:pass
        self.assertTrue((self.control.directory/'vault.sqlite3').exists());self.assertFalse(self.control.media.exists())
        self.assertEqual(self.call(self.alice,'/api/library')['items'],[])
        self.assertEqual(len(self.call(self.alice,'/api/admin/users')['users']),2)
        self.assertTrue(self.accounts.configured)
        restarted=Vault(ROOT,self.control.directory,'http://localhost')
        try:
            new_accounts=Accounts(restarted,{'photo':ROOT/'assets'})
            self.assertTrue(new_accounts.configured)
            self.assertEqual(restarted.db.execute('SELECT count(*) FROM assets').fetchone()[0],0)
            self.assertFalse(any(restarted.media.iterdir()),'Restart must not resurrect demo or deleted owner media')
        finally:restarted.db.close()


    def test_disable_protection_requires_password_and_keeps_account_isolation(self):
        self.upload(self.alice);self.upload(self.bob)
        self.call(self.alice,'/api/vault/setup',dict(pin='48271639'))
        self.call(self.alice,'/api/assets/action',dict(action='hide',indices=[0]))
        self.call(self.bob,'/api/vault/setup',dict(pin='87654321'))
        self.call(self.bob,'/api/assets/action',dict(action='hide',indices=[0]))
        self.call(self.bob,'/api/vault/lock',{})
        self.denied(self.client(),'/api/vault/disable',401,dict(password='alice password'))
        self.denied(self.alice,'/api/vault/disable',401,dict(password='wrong'))
        result=self.call(self.alice,'/api/vault/disable',dict(password='alice password'))
        self.assertFalse(result['vault']['protectionEnabled']);self.assertFalse(result['vault']['configured']);self.assertTrue(result['vault']['authenticated'])
        self.assertEqual(result['items'][0]['state'],'hidden')
        self.call(self.alice,'/api/vault/lock',{})
        for method in ('GET','HEAD'):self.call(self.alice,'/media/0/original',method=method,headers={'Range':'bytes=0-10'})
        self.denied(self.client(),'/media/0/original',401)
        self.denied(self.bob,'/media/0/original',401)
        self.denied(self.alice,'/api/vault/unlock',409,dict(pin='48271639'))
        result=self.call(self.alice,'/api/vault/setup',dict(pin='11223344'));self.assertTrue(result['vault']['protectionEnabled'])
        self.call(self.alice,'/api/vault/lock',{});self.denied(self.alice,'/media/0/original',401)
        self.denied(self.alice,'/api/vault/unlock',401,dict(pin='48271639'))
        self.call(self.alice,'/api/vault/unlock',dict(pin='11223344'))

    def test_remove_passkey_preserves_pin_and_conceal_is_per_account(self):
        self.call(self.alice,'/api/vault/setup',dict(pin='48271639'));uid=self.call(self.alice,'/api/account/status')['id'];v,_=self.accounts.libraries[uid]
        with v.lock,v.db:
            v.db.execute('INSERT INTO credentials VALUES(?,?,?)',('old-key','test-key',0));old=v.session();pin=v._setting('pin_hash')
        self.denied(self.alice,'/api/vault/passkey/remove',401,dict(password='wrong'))
        result=self.call(self.alice,'/api/vault/passkey/remove',dict(password='alice password'))
        self.assertFalse(result['vault']['passkey']);self.assertTrue(result['vault']['configured']);self.assertTrue(result['vault']['protectionEnabled'])
        self.assertEqual(v._setting('pin_hash'),pin);self.assertFalse(v.authenticated(old))
        self.denied(self.alice,'/api/vault/preferences',400,dict(concealHidden='yes'))
        result=self.call(self.alice,'/api/vault/preferences',dict(concealHidden=True));self.assertTrue(result['vault']['concealHidden'])
        self.assertFalse(self.call(self.bob,'/api/vault/status')['concealHidden'])
        self.call(self.alice,'/api/account/logout',{});self.call(self.alice,'/api/account/login',dict(login='alice',password='alice password'))
        self.assertTrue(self.call(self.alice,'/api/vault/status')['concealHidden'])
        result=self.call(self.alice,'/api/vault/preferences',dict(concealHidden=False));self.assertFalse(result['vault']['concealHidden'])

if __name__=='__main__':unittest.main()
