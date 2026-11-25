"""Immutable Docker bootstrap; updated code lives in /data/updates, outside photos."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.request
from updates import activation_lock

factory=Path(__file__).resolve().parent
home=Path(os.environ.get('PHOTO_DATA_DIR','/data'))/'updates'
state_path=home/'active.json'
stopping=False;child=None


def read():
    try:return json.loads(state_path.read_text())
    except (OSError,ValueError):return {}


def save(state):
    home.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=home/'active.next';path.write_text(json.dumps(state));os.chmod(path,0o600);os.replace(path,state_path)


def stop(*_):
    global stopping
    stopping=True
    if child and child.poll() is None:child.terminate()


def root(slot):
    if slot=='factory':return factory
    if not isinstance(slot,str) or not re.fullmatch(r'v\d+\.\d+\.\d+-[a-f0-9]{12}',slot):return factory
    path=home/'releases'/slot
    return path if path.resolve().is_relative_to((home/'releases').resolve()) and (path/'server.py').is_file() else factory


signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
while not stopping:
    state=read();slot=state.get('active','factory');directory=root(slot)
    child=subprocess.Popen([sys.executable,'-B','server.py'],cwd=directory,env={**os.environ,'PHOTO_UPDATE_LAUNCHER':'1'})
    healthy=False
    for _ in range(100):
        if stopping or child.poll() is not None:break
        try:
            with urllib.request.urlopen('http://127.0.0.1:8000/api/account/status',timeout=1) as response:
                if response.status==200:healthy=True;break
        except OSError:pass
        time.sleep(.2)
    if stopping:break
    if not healthy and state.get('pending'):
        child.terminate();child.wait(timeout=10)
        with activation_lock(home):
            current=read()
            if current.get('active')==slot:save(dict(active=current.get('previous') or 'factory',previous=None,failed=slot,pending=False,error='Новая версия не запустилась. Восстановлена предыдущая.'))
        continue
    if healthy and state.get('pending'):
        with activation_lock(home):
            current=read()
            if current.get('active')==slot:
                current['pending']=False;current['error']='';save(current)
    result=child.wait()
    if not stopping:time.sleep(.3)
if child and child.poll() is None:
    try:child.wait(timeout=10)
    except subprocess.TimeoutExpired:child.kill();child.wait()
