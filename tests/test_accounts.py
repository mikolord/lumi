import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from vault import Vault,VaultError,b64
from users import Accounts
from accounts import LibraryImporter

class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.v=Vault(ROOT,self.home/'data','http://localhost')
        self.source=self.home/'photos';self.source.mkdir()
        self.a=Accounts(self.v,{'photo':self.source})
    def tearDown(self):
        for v,_ in self.a.libraries.values():
            if v is not self.v:v.db.close()
        self.v.db.close();self.temp.cleanup()
    def register(self):return self.a.register(dict(name='Owner',login='owner',password='a strong password'),local_setup=True)
    def test_first_setup_and_rate_limit(self):
        with self.assertRaises(VaultError):self.a.register(dict(name='x',login='hacker',password='a long password'))
        token=self.register();self.assertTrue(self.a.authenticated(token));self.assertFalse((self.v.directory/'setup-token').exists())
        with self.assertRaises(VaultError):self.register()
        for _ in range(5):
            with self.assertRaises(VaultError):self.a.login(dict(login='owner',password='bad'))
        with self.assertRaises(VaultError) as failure:self.a.login(dict(login='owner',password='a strong password'))
        self.assertEqual(failure.exception.status,429)
        self.a.logout(token);self.assertFalse(self.a.authenticated(token))
    def test_import_resume_and_source_integrity(self):
        token=self.register();user,v,importer=self.a.context(token)
        folder=self.source/'family';folder.mkdir();source=folder/'photo.jpg';source.write_bytes((ROOT/'assets/10.jpg').read_bytes());before=source.read_bytes()
        (folder/'bad.jpg').write_bytes(b'bad image')
        (folder/'Immich').mkdir();(folder/'Immich'/'private.jpg').write_bytes(before)
        for relative in ('../data','/etc','family/../../data'):
            with self.assertRaises(VaultError):importer.resolve('photo',relative)
        importer.start_import('photo','family');deadline=time.time()+20
        while importer.job()['state']=='running' and time.time()<deadline:time.sleep(.05)
        self.assertEqual(importer.job()['state'],'complete');self.assertEqual(importer.job()['added'],1);self.assertEqual(importer.job()['skipped'],1)
        importer.finish();item=next(item for item in v.library('')['items'] if item['state']=='public')
        self.assertEqual(item['metadata']['width'],480)
        pin=v.setup(None,'48271639',account_authorized=True);v.mutate('hide',[item['id']],pin)
        importer.start_import('photo','family')
        while importer.job()['state']=='running':time.sleep(.05)
        self.assertEqual(v.db.execute('SELECT COUNT(*) FROM imports').fetchone()[0],1)
        v.mutate('trash',[item['id']],pin);v.mutate('purge',[item['id']],pin)
        self.assertEqual(source.read_bytes(),before)
    def test_v43_owner_migration_preserves_password_and_library(self):
        salt=bytes(range(24));password='existing owner password'
        with self.v.lock,self.v.db:
            self.v._set('account_login','existing');self.v._set('account_name','Existing owner')
            self.v._set('account_salt',b64(salt));self.v._set('account_hash',b64(hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000)))
            self.v._set('real_library','1');self.v._set('onboarding_done','1')
        migrated=Accounts(self.v,{})
        token=migrated.login(dict(login='existing',password=password))
        self.assertEqual(migrated.status(token)['role'],'admin')
        self.assertTrue(migrated.status(token)['ready'])
        self.assertIs(migrated.context(token)[1],self.v)
        self.assertEqual(len(migrated.library_state(token,'')['items']),56)
        self.assertEqual(migrated.status(token)['name'],'Existing owner')
if __name__=='__main__':unittest.main()
