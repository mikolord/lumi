"""Run only in an isolated Docker container with /fixture.jpg (OpenCV sample)."""
import http.cookiejar
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from PIL import Image,ImageEnhance

assert os.environ.get('PHOTO_SMOKE_ISOLATED')=='1','Never run against a real library'
assert os.environ.get('PHOTO_FACE_URL') and os.environ.get('PHOTO_FACE_TOKEN')
with tempfile.TemporaryDirectory(prefix='people-smoke-') as directory:
    env={**os.environ,'PHOTO_DATA_DIR':directory,'PHOTO_ORIGIN':'http://127.0.0.1:8000','PHOTO_LAN_ORIGIN':'','PHOTO_SOURCES':'{}'}
    client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    csrf=''
    def call(path,body=None,raw=None):
        global csrf
        headers={'X-Photo-App-Origin':'http://127.0.0.1:8000'}
        if body is not None or raw is not None:
            if not csrf:call('/api/account/status')
            headers['X-Photo-CSRF']=csrf
            headers['Content-Type']='application/json' if raw is None else 'application/octet-stream'
        if raw is not None:headers['X-File-Name']='test-photo.jpg'
        request=urllib.request.Request('http://127.0.0.1:8000'+path,data=raw if raw is not None else json.dumps(body).encode() if body is not None else None,headers=headers)
        with client.open(request,timeout=20) as response:
            data=json.load(response)
            csrf=data.get('csrf',csrf);return data
    def start():
        process=subprocess.Popen(['python','server.py'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:call('/api/account/status');return process
            except (OSError,urllib.error.URLError):time.sleep(.1)
        process.terminate();raise AssertionError('Server not ready')
    def indexed(count):
        for _ in range(60):
            state=call('/api/people')
            if state['done']>=count:return state
            time.sleep(.25)
        raise AssertionError('Background recognition did not finish: '+str(state))
    server=start()
    try:
        call('/api/account/register',dict(name='Smoke',login='smoke',password='isolated password 123'))
        call('/api/account/finish',{})
        original=Path('/fixture.jpg').read_bytes();first=call('/api/assets/upload',raw=original)['id']
        call('/api/people/action',dict(action='enabled',value=True));state=indexed(1)
        assert len(state['people'])==1,state
        pid=state['people'][0]['id'];call('/api/people/action',dict(action='rename',id=pid,name='Test person'))
        server.terminate();server.wait(timeout=10);server=start()
        assert call('/api/people')['enabled']
        assert call('/api/people')['people'][0]['name']=='Test person'
        image=Image.open(io.BytesIO(original));output=io.BytesIO();ImageEnhance.Brightness(image).enhance(.94).save(output,'JPEG',quality=94)
        second=call('/api/assets/upload',raw=output.getvalue())['id'];state=indexed(2)
        assert len(state['people'])==1 and state['people'][0]['indices']==[second,first],state
        detail=call('/api/people?id='+pid);assert len(detail['faces'])==2
        face=detail['faces'][0]['id']
        with client.open('http://127.0.0.1:8000/media/people/'+face+'/preview') as response:assert response.read(2)==b'\xff\xd8'
        call('/api/assets/action',dict(action='hide',indices=[second]))
        assert call('/api/people')['people'][0]['indices']==[first]
        try:client.open('http://127.0.0.1:8000/media/people/'+face+'/preview');raise AssertionError('Hidden face exposed')
        except urllib.error.HTTPError as error:assert error.code==404;error.close()
        print('Real end-to-end: upload, background detection, grouping, rename, backend restart, automatic new-photo indexing and private crop protection passed')
    finally:server.terminate();server.wait(timeout=10)
