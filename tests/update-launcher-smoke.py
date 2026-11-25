"""Isolated Docker only: real installation, restart, preserved account and boot rollback."""
import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

assert os.environ.get('PHOTO_SMOKE_ISOLATED')=='1'
with tempfile.TemporaryDirectory(prefix='updater-smoke-') as folder:
    data=Path(folder)/'data';data.mkdir();updates=data/'updates';updates.mkdir()
    env={**os.environ,'PHOTO_DATA_DIR':str(data),'PHOTO_ORIGIN':'http://127.0.0.1:8000','PHOTO_LAN_ORIGIN':'','PHOTO_SOURCES':'{}'}
    client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));csrf=''
    def call(path,body=None):
        global csrf
        if body is not None and not csrf:call('/api/account/status')
        req=urllib.request.Request('http://127.0.0.1:8000'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','X-Photo-CSRF':csrf,'X-Photo-App-Origin':'http://127.0.0.1:8000'})
        with client.open(req,timeout=5) as response:result=json.load(response);csrf=result.get('csrf',csrf);return result
    def wait_for(test):
        last=None
        for _ in range(160):
            try:
                last=test()
                if last:return last
            except (OSError,ValueError):pass
            time.sleep(.1)
        raise AssertionError('Timeout: '+str(last)+'; activation='+((updates/'active.json').read_text() if (updates/'active.json').exists() else 'none'))
    server=subprocess.Popen(['python','launcher.py'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        wait_for(lambda:call('/api/account/status'))
        call('/api/account/register',dict(name='Update smoke',login='smoke',password='isolated password 123'));call('/api/account/finish',{})
        assert call('/api/admin/updates')['canInstall']
        good='v0.68.0-'+'a'*12;destination=updates/'releases'/good
        shutil.copytree('/site',destination,ignore=shutil.ignore_patterns('tests','__pycache__'))
        (destination/'VERSION').write_text('0.68.0')
        (updates/'status.json').write_text(json.dumps(dict(phase='ready',tag='v0.68.0',downloaded='v0.68.0',slot=good)))
        call('/api/admin/updates/action',dict(action='install'))
        wait_for(lambda:call('/api/admin/updates')['current']=='0.68.0')
        assert call('/api/account/status')['login']=='smoke'
        assert call('/api/admin/updates')['canRollback']
        bad='v0.69.0-'+'b'*12;broken=updates/'releases'/bad;broken.mkdir();(broken/'server.py').write_text('raise RuntimeError("expected broken fixture")')
        (updates/'status.json').write_text(json.dumps(dict(phase='ready',tag='v0.69.0',downloaded='v0.69.0',slot=bad)))
        call('/api/admin/updates/action',dict(action='install'))
        wait_for(lambda:(json.loads((updates/'active.json').read_text()).get('error')))
        wait_for(lambda:call('/api/admin/updates')['current']=='0.68.0')
        assert call('/api/account/status')['login']=='smoke'
        assert call('/api/admin/updates')['rollbackMessage']
        assert not call('/api/admin/updates')['canRollback'],'Failed version must not become a manual rollback target'
        print('Real update launcher: install staged code, restart, preserve account and automatically restore previous working version after broken startup passed')
    finally:server.terminate();server.wait(timeout=15)
