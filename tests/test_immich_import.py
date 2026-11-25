"""Immich connector tests against an isolated local API fixture, never a real installation."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from vault import Vault,VaultError
from users import Accounts
from immich_import import Remote

class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.v=Vault(ROOT,Path(self.temp.name)/'data','http://localhost');self.accounts=Accounts(self.v,{})
        self.admin=self.accounts.register(dict(name='Admin',login='admin',password='administrator password'),True)
        user=self.accounts.create_user(self.admin,dict(name='Member',login='member',password='member password',quota=0));self.user_id=user['id']
        self.token=self.accounts.login(dict(login='member',password='member password'),'fixture');self.job=self.accounts.immich(self.token)
        outer=self;self.requests=[];self.cursor_mode=False;self.fail_download=False;self.release=threading.Event();self.release.set();self.started=threading.Event();self.photo=(ROOT/'assets/10.jpg').read_bytes()
        class Fixture(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def respond(self,data):
                body=data if isinstance(data,bytes) else json.dumps(data).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_GET(self):
                outer.requests.append(('GET',self.path));outer.assertEqual(self.headers['x-api-key'],'private-test-key')
                if self.path=='/api/users/me':self.respond(dict(id='remote-owner'))
                elif self.path=='/api/albums':self.respond([dict(id='album-1',ownerId='remote-owner',albumName='Remote Family'),dict(id='album-2',ownerId='someone-else',albumName='Other')])
                elif self.path=='/api/assets/asset-1/original':
                    if outer.fail_download:self.send_error(503);return
                    outer.started.set();outer.release.wait(5);self.respond(outer.photo)
                else:self.send_error(404)
            def do_POST(self):
                outer.requests.append(('POST',self.path));outer.assertEqual(self.path,'/api/search/metadata')
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                photo=dict(id='asset-1',originalFileName='portrait.jpg',ownerId='remote-owner',isFavorite=True,fileCreatedAt='2020-01-01T12:00:00Z',visibility='timeline')
                if body.get('albumIds'):items=[photo];page=None
                elif body.get('page',2)==1:items=[photo,dict(photo,id='hidden-1',visibility='locked')];page='2'
                else:items=[dict(photo,id='foreign-1',ownerId='someone-else')];page=None
                self.respond(dict(assets=dict(items=items,nextPage=None if outer.cursor_mode else page,nextCursor='cursor-2' if outer.cursor_mode and page else None)))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=self.server.serve_forever,daemon=True).start()
        port=self.server.server_port
        class FixtureRemote(Remote):
            def __init__(self,url,key):
                with patch('immich_import.socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.0.0.5',port))]):super().__init__(url,key)
                self.addresses=['127.0.0.1'];self.host='127.0.0.1';self.port=port
        self.mock=patch('immich_import.Remote',FixtureRemote);self.mock.start()
    def run_import(self):
        self.job.start(dict(url='http://immich.example',key='private-test-key',albums=True))
        for _ in range(500):
            if self.job.status().get('state') not in ('running','stopping'):return self.job.status()
            time.sleep(.01)
        self.fail('Job did not finish')
    def tearDown(self):
        self.release.set();self.job.stop()
        for _ in range(500):
            if self.job.status().get('state') not in ('running','stopping'):break
            time.sleep(.01)
        self.mock.stop();self.server.shutdown();self.server.server_close()
        for v,_ in self.accounts.libraries.values():
            if v is not self.v:v.db.close()
        self.v.db.close();self.temp.cleanup()
    def test_copy_resume_albums_favorites_and_source_reads_only(self):
        state=self.run_import();self.assertEqual(state['state'],'complete',state);self.assertEqual(state['added'],1);self.assertEqual(state['albums'],1);self.assertEqual(state['total'],3);self.assertEqual(state['processed'],3);self.assertEqual(state['skipped'],2);self.assertEqual(len(state['issues']),2);self.assertTrue(all(item['reason'] for item in state['issues']))
        v=self.accounts.libraries[self.user_id][0];self.assertEqual(len(v.albums()),1);self.assertEqual(v.albums()[0]['indices'],[0]);self.assertEqual(v.db.execute('SELECT favorite FROM assets').fetchone()[0],1)
        self.assertEqual(v.media_path(0,False,'').read_bytes(),self.photo)
        self.cursor_mode=True;again=self.run_import();self.assertEqual(again['added'],0);self.assertEqual(again['reused'],1);self.assertEqual(len(v.albums()),1)
        self.assertEqual(sum(path.endswith('/original') for _,path in self.requests),1)
        self.assertNotIn('private-test-key',json.dumps(dict(v.db.execute('SELECT * FROM settings'))))
        self.assertTrue(all(method=='GET' or path=='/api/search/metadata' for method,path in self.requests))
        self.assertTrue(all(item['state']=='purged' for item in self.accounts.library_state(self.admin,'')['items']))
    def test_failed_file_report_and_retry(self):
        self.fail_download=True;state=self.run_import();self.assertEqual(state['failed'],1);self.assertEqual(state['issues'][0]['name'],'portrait.jpg');self.assertTrue(state['issues'][0]['retryable'])
        self.fail_download=False;self.job.start(dict(url='http://immich.example',key='private-test-key',albums=True,retryIds=[state['issues'][0]['id']]))
        for _ in range(500):
            if self.job.status().get('state') not in ('running','stopping'):break
            time.sleep(.01)
        state=self.job.status();self.assertEqual(state['added'],1);self.assertEqual(state['failed'],0);self.assertEqual(state['total'],1)

    def test_quota_and_cancel_cleanup(self):
        self.accounts.update_user(self.admin,dict(id=self.user_id,quota=1));state=self.run_import();self.assertEqual(state['state'],'failed');self.assertIn('места',state['error'])
        v=self.accounts.libraries[self.user_id][0];self.assertEqual(list(v.media.iterdir()),[])
        self.accounts.update_user(self.admin,dict(id=self.user_id,quota=0));self.release.clear();self.started.clear();self.job.start(dict(url='http://immich.example',key='private-test-key'))
        self.assertTrue(self.started.wait(2));self.job.stop();self.release.set()
        for _ in range(200):
            if self.job.status()['state']=='cancelled':break
            time.sleep(.01)
        self.assertEqual(self.job.status()['state'],'cancelled');self.assertEqual(list(v.media.iterdir()),[])
    def test_destination_and_key_validation(self):
        for url in ('http://127.0.0.1','http://[::ffff:127.0.0.1]','http://169.254.169.254','http://user:secret@192.168.1.3','http://192.168.1.3/../secret','http://192.168.1.3?key=secret'):
            with self.assertRaises(VaultError):Remote(url,'private-test-key')
        with self.assertRaises(VaultError):Remote('http://192.168.1.3','invalid\nkey')

if __name__=='__main__':unittest.main()
