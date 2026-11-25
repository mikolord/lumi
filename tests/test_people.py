"""Real account/CSRF/media contracts; deterministic inference for correction edge cases."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from people import People,MODEL,normalize
from vault import Vault,VaultError
import test_multiuser as fixtures


def vector(n):return [1. if i==n else 0. for i in range(128)]
def face(n=0):return dict(box=[.2,.2,.3,.3],vector=vector(n))


class PeopleTests(unittest.TestCase):
    setUp=fixtures.MultiuserTests.setUp
    tearDown=fixtures.MultiuserTests.tearDown
    client=fixtures.MultiuserTests.client
    call=fixtures.MultiuserTests.call
    denied=fixtures.MultiuserTests.denied
    upload=fixtures.MultiuserTests.upload

    def own(self,client):
        uid=self.call(client,'/api/account/status')['id'];return self.accounts.libraries[uid][0]

    def test_merge_more_than_one_hundred_people(self):
        v=self.own(self.alice);p=People(v);asset=self.upload(self.alice)
        with v.lock,v.db:
            for n in range(121):
                pid=f'{n:032x}';fid=f'{n+1000:032x}'
                v.db.execute('INSERT INTO people(id) VALUES(?)',(pid,))
                v.db.execute('INSERT INTO people_faces(id,person_id,asset_id,box,vector) VALUES(?,?,?,?,?)',(fid,pid,asset,json.dumps([.1,.1,.3,.3]),json.dumps(vector(0))))
        ids=[f'{n:032x}' for n in range(121)]
        self.call(self.alice,'/api/people/action',dict(action='merge-many',target=ids[0],sources=ids[1:],name='Один человек'))
        self.assertEqual(len(p.detail(ids[0])['faces']),121);self.assertEqual(len(p.status()['people']),1)

    @patch.dict('os.environ',{'PHOTO_FACE_URL':'http://fixture:8001','PHOTO_FACE_TOKEN':'a'*48})
    def test_bulk_merge_atomic_and_account_isolation(self):
        v=self.own(self.alice);p=People(v);p.action(dict(action='enabled',value=True));self.upload(self.alice);p.process_one(lambda _:[face(0),face(1),face(2)])
        people=p.status()['people'];self.assertEqual(len(people),3);target=people[0]['id'];sources=[item['id'] for item in people[1:]]
        self.denied(self.bob,'/api/people/action',404,dict(action='merge-many',target=target,sources=sources,name='Alice'))
        self.denied(self.alice,'/api/people/action',404,dict(action='merge-many',target=target,sources=[sources[0],'missing'],name='Alice'))
        self.assertEqual(len(p.status()['people']),3)
        state=self.call(self.alice,'/api/people/action',dict(action='merge-many',target=target,sources=sources,name='Каролина'))
        self.assertEqual(len(state['people']),1);self.assertEqual(state['people'][0]['name'],'Каролина');self.assertEqual(len(p.detail(target)['faces']),3)

    @patch.dict('os.environ',{'PHOTO_FACE_URL':'http://fixture:8001','PHOTO_FACE_TOKEN':'a'*48})
    def test_incremental_grouping_persistence_and_corrections(self):
        v=self.own(self.alice);p=People(v)
        self.assertFalse(p.status()['enabled']);self.assertFalse(p.process_one(lambda _:self.fail('disabled')))
        self.call(self.alice,'/api/people/action',dict(action='enabled',value=True))
        a=self.upload(self.alice);b=self.upload(self.alice)
        self.assertTrue(p.process_one(lambda _:[face()]));self.assertTrue(p.process_one(lambda _:[face()]))
        self.assertFalse(p.process_one(lambda _:self.fail('must not repeat')))
        state=self.call(self.alice,'/api/people');self.assertEqual(state['done'],2);self.assertEqual(len(state['people']),1)
        person=state['people'][0];pid=person['id'];self.assertEqual(person['indices'],[b,a]);self.assertNotIn('vector',json.dumps(state))
        self.denied(self.alice,'/api/people/action',403,dict(action='rename',id=pid,name='bad'),headers={'X-Photo-CSRF':'invalid'})
        self.call(self.alice,'/api/people/action',dict(action='rename',id=pid,name='Каролина'))
        other=Vault(v.root,v.directory,v.origin,seed=False)
        try:self.assertEqual(People(other).status()['people'][0]['name'],'Каролина')
        finally:other.db.close()
        detail=self.call(self.alice,'/api/people?id='+pid);first=detail['faces'][0]['id']
        result=self.call(self.alice,'/api/people/action',dict(action='move',face=first))
        self.assertEqual(len(result['people']),2);new=next(x['id'] for x in result['people'] if x['id']!=pid)
        self.call(self.alice,'/api/people/action',dict(action='merge',id=new,target=pid))
        self.assertEqual(len(p.status()['people']),1);self.assertEqual(p.status()['people'][0]['name'],'Каролина')
        self.call(self.alice,'/api/people/action',dict(action='enabled',value=False));self.upload(self.alice)
        self.assertFalse(p.process_one(lambda _:self.fail('paused')))
        self.assertEqual(p.status()['done'],2)

    @patch.dict('os.environ',{'PHOTO_FACE_URL':'http://fixture:8001','PHOTO_FACE_TOKEN':'a'*48})
    def test_authentication_private_media_sharing_and_purge(self):
        v=self.own(self.alice);p=People(v);a=self.upload(self.alice)
        p.action(dict(action='enabled',value=True));p.process_one(lambda _:[face()]);person=p.status()['people'][0];pid=person['id'];fid=person['cover']
        path='/media/people/'+fid+'/preview'
        self.assertTrue(self.call(self.alice,path).startswith(b'\xff\xd8'))
        for client,code in ((self.bob,404),(self.client(),401)):
            for method in ('GET','HEAD'):
                self.denied(client,path,code,method=method,headers={'Range':'bytes=0-99'})
            self.denied(client,'/api/people?id='+pid,code)
        self.denied(self.bob,'/api/people/action',404,dict(action='rename',id=pid,name='stolen'))
        # Shared photos do not create identities in the recipient's own people index.
        self.assertEqual(self.call(self.bob,'/api/people')['people'],[])
        token=v.setup(None,'48271639',account_authorized=True)
        v.mutate('hide',[a],token)
        self.assertEqual(p.status()['people'],[]);self.denied(self.alice,path,404);self.denied(self.alice,'/api/people?id='+pid,404)
        v.mutate('unhide',[a],token);self.assertEqual(p.status()['people'][0]['id'],pid)
        v.mutate('trash',[a],token);self.denied(self.alice,path,404)
        v.mutate('purge',[a],token)
        self.assertEqual(v.db.execute('SELECT COUNT(*) FROM people_faces').fetchone()[0],0)
        self.assertEqual(v.db.execute('SELECT COUNT(*) FROM people_scans').fetchone()[0],0)

    @patch.dict('os.environ',{'PHOTO_FACE_URL':'http://fixture:8001','PHOTO_FACE_TOKEN':'a'*48})
    def test_inflight_hide_pause_invalid_response_and_no_faces(self):
        v=self.own(self.alice);p=People(v);a=self.upload(self.alice);p.action(dict(action='enabled',value=True))
        token=v.setup(None,'48271639',account_authorized=True)
        def hide(_):v.mutate('hide',[a],token);return [face()]
        self.assertFalse(p.process_one(hide));self.assertEqual(p.status()['people'],[])
        v.mutate('unhide',[a],token)
        def pause(_):p.action(dict(action='enabled',value=False));return [face()]
        self.assertFalse(p.process_one(pause));self.assertEqual(p.status()['done'],0)
        p.action(dict(action='enabled',value=True))
        with self.assertRaises(ValueError):p.process_one(lambda _:[dict(box=[0,0,1,1],vector=[float('nan')]*128)])
        self.assertEqual(p.status()['done'],0);self.assertTrue(p.status()['error'])
        p.process_one(lambda _:[]);self.assertEqual(p.status()['done'],1);self.assertFalse(p.status()['error'])
        self.upload(self.alice);p.process_one(lambda _:[face(0),face(0)])
        self.assertEqual(len(p.status()['people']),2,'Two faces in the same image cannot become one person')
        self.upload(self.alice)
        def invalid(_):raise urllib.error.HTTPError('http://fixture',422,'invalid',{},None)
        self.assertTrue(p.process_one(invalid));self.assertEqual(p.status()['failed'],1)
        p.action(dict(action='retry'));self.assertEqual(p.status()['failed'],0)
        self.assertEqual(p.status()['done'],2)

    @patch.dict('os.environ',{'PHOTO_FACE_URL':'http://fixture:8001','PHOTO_FACE_TOKEN':'a'*48})
    def test_deleted_user_cannot_receive_inflight_result(self):
        v=self.own(self.alice);p=People(v);self.upload(self.alice);p.action(dict(action='enabled',value=True))
        self.accounts.request_started()
        try:
            def deleted(_):
                self.call(self.admin,'/api/admin/users/delete',dict(id=self.call(self.alice,'/api/account/status')['id'],confirmLogin='alice',files='keep'))
                return [face()]
            self.assertFalse(p.process_one(deleted))
            self.assertEqual(v.db.execute('SELECT COUNT(*) FROM people_faces').fetchone()[0],0)
        finally:self.accounts.request_finished()

    @patch.dict('os.environ',{'PHOTO_FACE_URL':'http://fixture:8001','PHOTO_FACE_TOKEN':'a'*48})
    def test_visibility_and_ignored_people_remain_ignored(self):
        v=self.own(self.alice);p=People(v)
        self.assertFalse(p.status()['visible'])
        self.call(self.alice,'/api/people/action',dict(action='visible',value=True))
        first=self.upload(self.alice);p.process_one(lambda _:[face()]);person=p.status()['people'][0]
        self.call(self.alice,'/api/people/action',dict(action='exclude',id=person['id'],value=True))
        state=p.status();self.assertEqual(state['people'],[]);self.assertEqual(len(state['excluded']),1)
        self.upload(self.alice);p.process_one(lambda _:[face()]);self.assertEqual(p.status()['people'],[],'Ignored face must not return as a new person')
        token=v.setup(None,'48271639',account_authorized=True);v.mutate('trash',[first],token);v.mutate('purge',[first],token)
        excluded=p.status()['excluded'][0];self.assertIsNone(excluded['cover']);self.assertEqual(excluded['indices'],[])
        self.upload(self.alice);p.process_one(lambda _:[face()]);self.assertEqual(p.status()['people'],[],'Explicit ignore survives deletion of its original photo')
        self.call(self.alice,'/api/people/action',dict(action='exclude',id=person['id'],value=False))
        self.upload(self.alice);p.process_one(lambda _:[face()]);self.assertEqual(len(p.status()['people']),1)
        self.call(self.alice,'/api/people/action',dict(action='visible',value=False));self.assertFalse(p.status()['visible']);self.assertFalse(p.status()['enabled'])
        self.assertFalse(self.call(self.bob,'/api/people')['visible'])

    def test_admin_only_metrics_and_update_controls(self):
        for path in ('/api/admin/metrics','/api/admin/updates'):
            self.denied(self.alice,path,403);self.denied(self.client(),path,401)
        self.denied(self.alice,'/api/admin/updates/action',403,dict(action='check'))
        with patch('resource_monitor.snapshot',return_value=dict(cpu=2.5,memory=1024,components=[],cores=4,partial=False)):
            self.assertEqual(self.call(self.admin,'/api/admin/metrics')['cpu'],2.5)
        info=self.call(self.admin,'/api/admin/updates');self.assertEqual(info['current'],(Path(__file__).resolve().parents[1]/'VERSION').read_text().strip())
        self.assertFalse(info['canInstall']);self.assertNotIn('token',json.dumps(info).lower())

    @patch.dict('os.environ',{'PHOTO_FACE_URL':'http://fixture:8001','PHOTO_FACE_TOKEN':'a'*48})
    def test_person_menu_preferences_cover_and_merge_preserve_photos(self):
        v=self.own(self.alice);p=People(v);p.action(dict(action='enabled',value=True))
        a=self.upload(self.alice);p.process_one(lambda _:[face(0),face(1)])
        first=next(person for person in p.status()['people'] if json.loads(v.db.execute('SELECT vector FROM people_faces WHERE person_id=?',(person['id'],)).fetchone()[0])[0]==1)
        second=next(person for person in p.status()['people'] if person['id']!=first['id'])
        cover=first['cover'];other_cover=second['cover'];b=self.upload(self.alice);p.process_one(lambda _:[face(0)])
        self.call(self.alice,'/api/people/action',dict(action='profile',id=first['id'],name='Ранэл',cover=cover))
        self.assertEqual(next(x for x in p.status()['people'] if x['id']==first['id'])['cover'],cover)
        self.denied(self.alice,'/api/people/action',404,dict(action='profile',id=first['id'],name='Bad',cover=other_cover))
        self.assertEqual(p.detail(first['id'])['name'],'Ранэл')
        for field in ('favorite','pinned'):
            self.call(self.alice,'/api/people/action',dict(action='preference',id=first['id'],field=field,value=True))
            self.denied(self.bob,'/api/people/action',404,dict(action='preference',id=first['id'],field=field,value=True))
        self.call(self.alice,'/api/people/action',dict(action='preference',id=second['id'],field='hidden',value=True))
        self.assertEqual([x['id'] for x in p.status()['hidden']],[second['id']]);self.assertEqual(len(p.status()['people']),1)
        self.call(self.alice,'/api/people/action',dict(action='preference',id=second['id'],field='hidden',value=False))
        originals={row['id']:(v.media/row['original']).read_bytes() for row in v.db.execute('SELECT * FROM assets')}
        self.call(self.alice,'/api/people/action',dict(action='merge',id=first['id'],target=second['id']))
        merged=p.status()['people'][0];self.assertEqual(merged['name'],'Ранэл');self.assertTrue(merged['favorite']);self.assertTrue(merged['pinned']);self.assertEqual(set(merged['indices']),{a,b})
        self.assertEqual({row['id']:(v.media/row['original']).read_bytes() for row in v.db.execute('SELECT * FROM assets')},originals,'Merging person cards never changes photo files')
        reopened=Vault(v.root,v.directory,v.origin,seed=False)
        try:self.assertTrue(People(reopened).detail(merged['id'])['favorite']);self.assertEqual(People(reopened).detail(merged['id'])['cover'],cover)
        finally:reopened.db.close()
        token=v.setup(None,'48271639',account_authorized=True);v.mutate('hide',[a],token)
        self.assertNotEqual(p.detail(merged['id'])['cover'],cover,'Private cover falls back to a public face')
        self.denied(self.alice,'/media/people/'+cover+'/preview',404)


if __name__=='__main__':unittest.main()
