import hashlib
import io
import json
import shutil
import subprocess
import time
import unittest
from PIL import Image
import test_multiuser as base
ROOT=base.ROOT
from editor import validate

class EditorTests(unittest.TestCase):
    setUp=base.MultiuserTests.setUp
    tearDown=base.MultiuserTests.tearDown
    client=base.MultiuserTests.client
    call=base.MultiuserTests.call
    denied=base.MultiuserTests.denied

    def wait_edit(self,index):
        for _ in range(600):
            data=self.call(self.alice,'/api/editor?index='+str(index))
            if data['job']['state']!='processing':
                self.assertEqual(data['job']['state'],'complete',data['job']);return data
            time.sleep(.1)
        self.fail('Editor did not finish')

    def test_photo_render_original_restore_private_and_shared(self):
        image=Image.new('RGB',(120,80),(80,130,160));data=io.BytesIO();image.save(data,'PNG');body=data.getvalue()
        self.call(self.alice,'/api/assets/upload',body,headers={'X-File-Name':'source.png'})
        source=self.call(self.alice,'/api/editor?index=0');self.assertIsNone(source['recipe'])
        self.denied(self.bob,'/api/editor?index=0',404)
        self.denied(self.alice,'/api/editor/save',400,dict(index=0,recipe={'crop':[-1,0,1,1]}))
        self.call(self.alice,'/api/editor/save',dict(index=0,recipe={'rotation':90,'crop':[0,0,.5,1],'filter':'mono','brightness':.2,'strokes':[{'color':'#ff453a','points':[[.1,.1],[.9,.9]]}]}))
        self.wait_edit(0)
        self.assertEqual(self.call(self.alice,'/media/0/source'),body)
        edited=self.call(self.alice,'/media/0/original');self.assertNotEqual(edited,body)
        with Image.open(io.BytesIO(edited)) as out:
            self.assertEqual(out.size,(40,120));pixel=out.getpixel((30,5));self.assertLessEqual(max(pixel)-min(pixel),3,'Saved monochrome must really remove color')
        item=self.call(self.alice,'/api/library')['items'][0];self.assertEqual(item['metadata']['width'],40);self.assertIn('revision',item)
        self.call(self.alice,'/api/assets/action',dict(action='duplicate',indices=[0]));self.assertEqual(self.call(self.alice,'/media/1/original'),edited)
        album=self.call(self.alice,'/api/albums/action',dict(action='create',name='Edited'))['albums'][0]['id']
        self.call(self.alice,'/api/albums/action',dict(action='add',id=album,indices=[0]))
        bob=self.call(self.bob,'/api/account/status')['id'];self.call(self.alice,'/api/albums/share',dict(id=album,users=[bob]))
        shared=next(i for i in self.call(self.bob,'/api/library')['items'] if i['state']=='shared')
        self.assertEqual(shared['metadata']['width'],40);self.assertEqual(self.call(self.bob,shared['original']),edited)
        self.denied(self.bob,'/api/editor?index='+str(shared['id']),403)
        self.call(self.alice,'/api/editor/restore',dict(index=0));self.assertEqual(self.call(self.alice,'/media/0/original'),body)
        self.call(self.alice,'/api/editor/save',dict(index=0,recipe={'filter':'sepia'}));self.wait_edit(0)
        uid=self.call(self.alice,'/api/account/status')['id'];v,_=self.accounts.libraries[uid]
        with v.lock:edit=dict(v.db.execute('SELECT * FROM asset_edits WHERE asset_id=0').fetchone())
        paths=[v.media/edit[k] for k in ('original','preview')];before_failure=self.call(self.alice,'/media/0/original')
        self.call(self.admin,'/api/admin/users/update',dict(id=uid,quota=v.usage()+10))
        self.call(self.alice,'/api/editor/save',dict(index=0,recipe={'brightness':.5}))
        for _ in range(100):
            job=self.call(self.alice,'/api/editor?index=0')['job']
            if job['state']!='processing':break
            time.sleep(.1)
        self.assertEqual(job['state'],'failed');self.assertEqual(self.call(self.alice,'/media/0/original'),before_failure)
        self.call(self.admin,'/api/admin/users/update',dict(id=uid,quota=1000000))
        self.call(self.alice,'/api/vault/setup',dict(pin='12345678'));self.call(self.alice,'/api/assets/action',dict(action='hide',indices=[0]));self.call(self.alice,'/api/vault/lock',{})
        self.denied(self.alice,'/media/0/source',401);self.denied(self.alice,'/media/0/source-preview',401);self.denied(self.alice,'/api/editor?index=0',401)
        self.call(self.alice,'/api/vault/unlock',dict(pin='12345678'));self.call(self.alice,'/api/assets/action',dict(action='trash',indices=[0]));self.call(self.alice,'/api/assets/action',dict(action='purge',indices=[0]))
        self.assertTrue(all(not p.exists() for p in paths));self.assertEqual(v.db.execute('SELECT COUNT(*) FROM asset_edits').fetchone()[0],0)

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg checked inside NAS image')
    def test_video_trim_mute_and_original(self):
        uid=self.call(self.alice,'/api/account/status')['id'];self.call(self.admin,'/api/admin/users/update',dict(id=uid,quota=100*1024**2))
        tagged=self.home/'dated.mp4';subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(ROOT/'assets/demo-vertical.mp4'),'-c','copy','-metadata','creation_time=2025-03-23T11:20:00Z','-y',str(tagged)],check=True)
        body=tagged.read_bytes();self.call(self.alice,'/api/assets/upload',body,headers={'X-File-Name':'video.mp4'})
        self.call(self.alice,'/api/editor/save',dict(index=0,recipe={'start':.5,'end':1.5,'mute':True,'filter':'mono','rotation':90}))
        self.wait_edit(0);self.assertEqual(self.call(self.alice,'/media/0/source'),body)
        item=self.call(self.alice,'/api/library')['items'][0];self.assertTrue(item['metadata']['takenAt'].startswith('2025-03-23'));self.assertAlmostEqual(item['metadata']['duration'],1,delta=.3)
        uid=self.call(self.alice,'/api/account/status')['id'];v,_=self.accounts.libraries[uid]
        with v.lock,v.db:
            old=json.loads(v.db.execute('SELECT metadata FROM assets WHERE id=0').fetchone()[0]);old.pop('takenAt',None);old.pop('dateChecked',None);v.db.execute('UPDATE assets SET metadata=? WHERE id=0',(json.dumps(old),))
            rendered=json.loads(v.db.execute('SELECT metadata FROM asset_edits WHERE asset_id=0').fetchone()[0]);rendered['takenAt']=None;v.db.execute('UPDATE asset_edits SET metadata=? WHERE asset_id=0',(json.dumps(rendered),))
        repaired=self.call(self.alice,'/api/assets/info?index=0')['items'][0]['metadata'];self.assertTrue(repaired['takenAt'].startswith('2025-03-23'));self.assertAlmostEqual(repaired['duration'],1,delta=.3)
        self.denied(self.bob,'/api/assets/info?index=0',404)
        path=v.media_path(0,False,'');probe=json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,check=True).stdout)
        self.assertAlmostEqual(float(probe['format']['duration']),1,delta=.3)
        self.assertFalse(any(s['codec_type']=='audio' for s in probe['streams']))
        self.call(self.alice,'/api/editor/restore',dict(index=0));self.assertEqual(hashlib.sha256(self.call(self.alice,'/media/0/original')).digest(),hashlib.sha256(body).digest())

class MetadataRulesTests(unittest.TestCase):
    def test_video_date_tags(self):
        from accounts import video_date
        self.assertTrue(video_date({'format':{'tags':{'creation_time':'2025-03-23T11:20:00Z'}}}).startswith('2025-03-23T11:20:00'))
        self.assertTrue(video_date({'streams':[{'codec_type':'video','tags':{'creation_time':'2024-01-02T03:04:00Z'}}]}).startswith('2024-01-02'))
        self.assertTrue(video_date({'format':{'tags':{'creation_time':'2026-01-01T00:00:00Z','com.apple.quicktime.creationdate':'2025-03-23T11:20:00+0300'}}}).endswith('+03:00'))
        self.assertIsNone(video_date({'format':{'tags':{'creation_time':'nonsense'}}}))

    def test_rendered_duration_keeps_capture_date(self):
        from vault import Vault
        metadata=Vault.display_metadata({'takenAt':'2025-03-23','addedAt':'2026-11-22','duration':15,'dateChecked':True},{'takenAt':None,'addedAt':'2026-11-23','duration':.6,'width':100})
        self.assertEqual(metadata['takenAt'],'2025-03-23');self.assertEqual(metadata['duration'],.6);self.assertEqual(metadata['addedAt'],'2026-11-22')

if __name__=='__main__':unittest.main()
