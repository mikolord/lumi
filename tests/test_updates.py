import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from updates import Updates,read_json
from vault import VaultError
from faces.metrics import raw,Monitor


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name);root=self.home/'factory';root.mkdir();(root/'VERSION').write_text('0.66.0');(root/'requirements.txt').write_bytes((ROOT/'requirements.txt').read_bytes());self.updater=Updates(self.home/'data',root)

    def tearDown(self):self.temp.cleanup()

    def fixture(self,archive=None,sha=None):
        files=[p for p in ROOT.iterdir() if p.is_file() and (p.suffix in ('.py','.js','.css') or p.name in ('VERSION','RUNTIME','requirements.txt','index.html','manifest.webmanifest'))]+[ROOT/'faces/metrics.py']
        if archive is None:
            output=io.BytesIO()
            with tarfile.open(fileobj=output,mode='w:gz') as tar:
                for path in files:tar.add(path,arcname=path.relative_to(ROOT).as_posix())
            archive=output.getvalue()
        version=(ROOT/'VERSION').read_text().strip()
        manifest=dict(version='v'+version,runtime=1,requirementsSha256=hashlib.sha256((ROOT/'requirements.txt').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),sha256=sha or hashlib.sha256(archive).hexdigest())
        assets={'mira-photos-manifest.json':'https://api.github.com/repos/fixture/releases/assets/1','mira-photos-v'+version+'.tar.gz':'https://api.github.com/repos/fixture/releases/assets/2'}
        release=dict(tag_name='v'+version,assets=[dict(name=k,url=v) for k,v in assets.items()])
        return lambda url,limit: json.dumps(release).encode() if url.endswith('/latest') else json.dumps(manifest).encode() if url.endswith('/1') else archive

    def test_check_download_validate_install_and_manual_rollback(self):
        u=self.updater
        with patch('updates.download',side_effect=self.fixture()):u.check();u.stage()
        self.assertEqual(u.info()['phase'],'ready');self.assertTrue(u.info()['newer'])
        state=read_json(u.path);self.assertTrue((u.home/'releases'/state['slot']/'index.html').is_file())
        with self.assertRaises(VaultError):u.install(lambda:None)
        with patch.dict('os.environ',{'PHOTO_UPDATE_LAUNCHER':'1'}),patch('updates.threading.Timer') as timer:
            u.install(lambda:None);timer.assert_called_once()
            active=read_json(u.home/'active.json');self.assertEqual(active['previous'],'factory');self.assertTrue(active['pending'])
            self.assertTrue(u.info()['canRollback']);u.install(lambda:None,rollback=True)
            self.assertEqual(read_json(u.home/'active.json')['active'],'factory')

    def test_corruption_path_traversal_symlinks_and_incompatible_runtime(self):
        u=self.updater
        with patch('updates.download',side_effect=self.fixture(sha='a'*64)):
            u.check()
            with self.assertRaises(VaultError):u.stage()
        for name,kind in (('../outside.py',tarfile.REGTYPE),('link.py',tarfile.SYMTYPE)):
            output=io.BytesIO()
            with tarfile.open(fileobj=output,mode='w:gz') as tar:
                member=tarfile.TarInfo(name);member.type=kind;member.linkname='/etc/passwd';member.size=0;tar.addfile(member,io.BytesIO())
            with patch('updates.download',side_effect=self.fixture(output.getvalue())):
                u.check()
                with self.assertRaises(VaultError):u.stage()
        self.assertFalse((self.home/'data/updates/releases/outside.py').exists())
        (u.root/'requirements.txt').write_text('incompatible')
        with patch('updates.download',side_effect=self.fixture()):
            u.check()
            with self.assertRaises(VaultError):u.stage()


class MetricsTests(unittest.TestCase):
    def test_container_memory_excludes_cache_and_supports_v1_v2(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for path,value in {'cpuacct/cpuacct.usage':'1000000000','memory/memory.usage_in_bytes':'4096','memory/memory.stat':'total_inactive_file 1024\n','memory/memory.limit_in_bytes':'8192'}.items():
                target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(value)
            self.assertEqual(raw(root),dict(cpuNs=1000000000,memory=3072,limit=8192,scope='container'))
            for path,value in {'cpu.stat':'usage_usec 2000000\n','memory.current':'8192','memory.stat':'inactive_file 2048\n','memory.max':'max'}.items():(root/path).write_text(value)
            self.assertEqual(raw(root),dict(cpuNs=2000000000,memory=6144,limit=None,scope='container'))
        monitor=Monitor()
        with patch('faces.metrics.raw',return_value=dict(cpuNs=100,memory=4096,limit=None,scope='container')):
            self.assertIsNone(monitor.sample()['cpu']);self.assertEqual(monitor.sample()['memory'],4096)


if __name__=='__main__':unittest.main()
