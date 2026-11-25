"""Administrator-triggered tagged GitHub releases; staged code, persistent data, rollback."""
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import secrets
import subprocess
import sys
import tarfile
import threading
import time
import tempfile
import urllib.request
import urllib.error
from contextlib import contextmanager
from vault import VaultError

TAG=re.compile(r'^v(\d+)\.(\d+)\.(\d+)$')
MAX_ARCHIVE=96*1024**2
RUNTIME=1


@contextmanager
def activation_lock(home):
    """Serialize the immutable launcher and the currently running backend."""
    path=Path(home)/'activation.lock';path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with path.open('a+b') as handle:
        try:import fcntl
        except ImportError:fcntl=None  # Windows is used only for local, single-process tests.
        if fcntl:fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
        try:yield
        finally:
            if fcntl:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def version(tag):
    match=TAG.fullmatch('v'+str(tag).removeprefix('v'))
    if not match:raise VaultError('Неверная версия обновления.')
    return tuple(map(int,match.groups()))


def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_name(path.name+'.'+secrets.token_hex(6)+'.tmp')
    with open(temporary,'x',encoding='utf-8') as output:json.dump(data,output,ensure_ascii=False)
    os.chmod(temporary,0o600);os.replace(temporary,path)


def read_json(path):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}


def download(url,limit):
    """Token is restricted to api.github.com; signed asset redirects never receive it."""
    from urllib.parse import urlsplit
    token=os.environ.get('PHOTO_GITHUB_TOKEN','')
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            parsed=urlsplit(newurl)
            if parsed.scheme!='https' or not (parsed.hostname=='api.github.com' or (parsed.hostname or '').endswith('.githubusercontent.com')):raise VaultError('Небезопасный адрес обновления.',502)
            redirected=super().redirect_request(req,fp,code,msg,headers,newurl)
            if redirected and parsed.hostname!='api.github.com':redirected.remove_header('Authorization')
            return redirected
    if not url.startswith('https://api.github.com/'):raise VaultError('Неверный адрес выпуска.')
    headers={'User-Agent':'Mira-Photos-updater','Accept':'application/octet-stream' if '/releases/assets/' in url else 'application/vnd.github+json'}
    if token:headers['Authorization']='Bearer '+token
    request=urllib.request.Request(url,headers=headers)
    with urllib.request.build_opener(Redirect).open(request,timeout=60) as response:
        data=response.read(limit+1)
        if len(data)>limit:raise VaultError('Обновление превышает допустимый размер.',413)
        return data


class Updates:
    def __init__(self,data,root):
        self.home=Path(data)/'updates';self.root=Path(root).resolve();self.lock=threading.Lock();self.running=False
        self.home.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=self.home/'status.json'
        old=read_json(self.path)
        if old.get('phase') in ('checking','downloading','installing'):self.save(phase='idle',message='Сервер перезапустился. Можно продолжить.')

    def save(self,**changes):
        state=read_json(self.path);state.update(changes);write_json(self.path,state);return state

    def current(self):return (self.root/'VERSION').read_text().strip()

    def git(self,args,cwd=None,timeout=90):
        import shlex
        key=self.home/'github_ed25519';hosts=self.home/'github_known_hosts'
        command='ssh -p 443 -i '+shlex.quote(str(key))+' -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile='+shlex.quote(str(hosts))
        env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,'GIT_SSH_COMMAND':command}
        return subprocess.run(['git','-c','core.hooksPath='+os.devnull,*args],cwd=cwd,env=env,check=True,capture_output=True,timeout=timeout).stdout

    def source(self):
        repo=os.environ.get('PHOTO_UPDATE_REPO','mikolord/lumi')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise VaultError('Репозиторий обновлений не настроен.')
        return repo

    def info(self):
        state=read_json(self.path);activation=read_json(self.home/'active.json');tag=state.get('tag')
        return dict(current=self.current(),repo=os.environ.get('PHOTO_UPDATE_REPO','mikolord/lumi'),latest=tag.removeprefix('v') if tag else None,newer=bool(tag and version(tag)>version(self.current())),phase=state.get('phase','idle'),message=state.get('message',''),checked=state.get('checked'),downloaded=state.get('downloaded'),canInstall=os.environ.get('PHOTO_UPDATE_LAUNCHER')=='1',canRollback=bool(activation.get('previous') is not None and activation.get('active')!=activation.get('previous')),rollbackMessage=activation.get('error',''))

    def check(self):
        self.save(phase='checking',message='Проверяем выпуски…')
        repo=self.source()
        if (self.home/'github_ed25519').is_file():
            rows=self.git(['ls-remote','--tags','--refs','ssh://git@ssh.github.com:443/'+repo+'.git']).decode().splitlines()
            tags=[(name.removeprefix('refs/tags/'),commit) for row in rows if len(row.split())==2 for commit,name in [row.split()] if TAG.fullmatch(name.removeprefix('refs/tags/'))]
            if not tags:raise VaultError('Стабильных выпусков пока нет.')
            tag,commit=max(tags,key=lambda item:version(item[0]));self.save(phase='idle',tag=tag,commit=commit,transport='ssh',checked=int(time.time()),message='Доступно обновление' if version(tag)>version(self.current()) else 'Установлена последняя версия');return
        try:release=json.loads(download('https://api.github.com/repos/'+repo+'/releases/latest',1024**2))
        except urllib.error.HTTPError as error:
            code=error.code;error.close()
            if code in (401,403,404):raise VaultError('Выпусков пока нет или серверу недоступен репозиторий. Для приватного репозитория нужен доступ на чтение.',502)
            raise
        tag=release.get('tag_name','')
        if not TAG.fullmatch(tag) or release.get('draft') or release.get('prerelease'):raise VaultError('Подходящий стабильный выпуск не найден.',502)
        assets={a.get('name'):a.get('url') for a in release.get('assets',[])}
        self.save(phase='idle',tag=tag,assets=assets,transport='https',checked=int(time.time()),message='Доступно обновление' if version(tag)>version(self.current()) else 'Установлена последняя версия')

    def stage(self):
        state=read_json(self.path);tag=state.get('tag','')
        if not TAG.fullmatch(tag) or version(tag)<=version(self.current()):raise VaultError('Сначала проверь наличие новой версии.')
        self.save(phase='downloading',message='Скачиваем обновление…')
        if state.get('transport')=='ssh':
            with tempfile.TemporaryDirectory(prefix='source-',dir=self.home) as directory:
                self.git(['clone','--depth','1','--single-branch','--branch',tag,'ssh://git@ssh.github.com:443/'+self.source()+'.git',directory])
                commit=self.git(['rev-parse','refs/tags/'+tag],cwd=directory).decode().strip()
                if commit!=state.get('commit'):raise VaultError('Метка выпуска изменилась. Проверь обновления ещё раз.',409)
                names=self.git(['ls-tree','-r','--name-only','HEAD'],cwd=directory).decode().splitlines()
                names=[name for name in names if (len(PurePosixPath(name).parts)==1 and PurePosixPath(name).suffix in ('.py','.js','.css','.html','.webmanifest')) or name in ('VERSION','RUNTIME','requirements.txt','faces/metrics.py') or (name.split('/')[0] in ('assets','icons') and PurePosixPath(name).suffix.lower() in ('.jpg','.jpeg','.png','.webp','.svg','.mp4'))]
                # Write a simple file-only archive; do not execute checkout hooks or setup scripts.
                from io import BytesIO
                output=BytesIO()
                with tarfile.open(fileobj=output,mode='w:gz') as archive:
                    for name in names:
                        path=Path(directory)/name
                        if path.is_symlink():raise VaultError('Ссылки в пакете недопустимы.',502)
                        archive.add(path,arcname=name,recursive=False)
                data=output.getvalue()
                manifest=dict(version='v'+(Path(directory)/'VERSION').read_text().strip(),runtime=int((Path(directory)/'RUNTIME').read_text().strip()),requirementsSha256=hashlib.sha256((Path(directory)/'requirements.txt').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),sha256=hashlib.sha256(data).hexdigest())
        else:
            assets=state.get('assets',{});manifest_url=assets.get('mira-photos-manifest.json');archive_url=assets.get('mira-photos-'+tag+'.tar.gz')
            if not manifest_url or not archive_url:raise VaultError('В выпуске нет установочного пакета.',502)
            manifest=json.loads(download(manifest_url,16384));data=download(archive_url,MAX_ARCHIVE)
        if manifest.get('version')!=tag or manifest.get('runtime')!=RUNTIME or manifest.get('requirementsSha256')!=hashlib.sha256((self.root/'requirements.txt').read_bytes().replace(b'\r\n',b'\n')).hexdigest():raise VaultError('Для этой версии требуется обновить Docker-контейнер. Пакет не установлен.',409)
        if len(data)>MAX_ARCHIVE:raise VaultError('Обновление превышает допустимый размер.',413)
        if not isinstance(manifest.get('sha256'),str) or hashlib.sha256(data).hexdigest()!=manifest['sha256']:raise VaultError('Проверка пакета не пройдена.',502)
        from io import BytesIO
        destination=self.home/'releases'/(tag+'-'+secrets.token_hex(6));destination.mkdir(parents=True,mode=0o700)
        required={'server.py','vault.py','accounts.py','users.py','people.py','resource_monitor.py','updates.py','requirements.txt','VERSION','RUNTIME','index.html','boot.js','app.js','style.css','sw.js','manifest.webmanifest','faces/metrics.py','editor.py','immich_import.py'}
        seen=set();total=0
        with tarfile.open(fileobj=BytesIO(data),mode='r:gz') as archive:
            for member in archive:
                name=PurePosixPath(member.name)
                if member.name in seen or member.name.startswith('/') or '\\' in member.name or '..' in name.parts or not member.isfile() or len(name.parts)>3 or any(part.startswith('.') for part in name.parts):raise VaultError('Неверная структура пакета.',502)
                allowed=(len(name.parts)==1 and name.suffix in ('.py','.js','.css','.html','.txt','.webmanifest')) or member.name in ('VERSION','RUNTIME') or (name.parts[0] in ('assets','icons') and name.suffix.lower() in ('.jpg','.jpeg','.png','.webp','.svg','.mp4')) or member.name=='faces/metrics.py'
                if not allowed:raise VaultError('Недопустимый файл в пакете.',502)
                total+=member.size
                if total>200*1024**2 or len(seen)>2048:raise VaultError('Распакованный пакет слишком большой.',413)
                target=destination.joinpath(*name.parts);target.parent.mkdir(parents=True,exist_ok=True)
                source=archive.extractfile(member)
                with target.open('xb') as output:output.write(source.read())
                seen.add(member.name)
        if not required.issubset(seen) or (destination/'VERSION').read_text().strip()!=tag[1:]:raise VaultError('Пакет неполный.',502)
        check="from pathlib import Path; [compile(p.read_text(encoding='utf-8'),str(p),'exec') for p in Path('.').rglob('*.py')]; import server,people,users,editor,resource_monitor,updates"
        subprocess.run([sys.executable,'-B','-c',check],cwd=destination,check=True,capture_output=True,timeout=20)
        self.save(phase='ready',downloaded=tag,slot=destination.name,message='Обновление скачано и проверено')

    def install(self,restart,rollback=False):
        if os.environ.get('PHOTO_UPDATE_LAUNCHER')!='1':raise VaultError('Для установки требуется запуск через обновлённый контейнер.',409)
        with activation_lock(self.home):
            state=read_json(self.path);active=read_json(self.home/'active.json');old=active.get('active','factory')
            slot=active.get('previous') if rollback else state.get('slot')
            if not isinstance(slot,str) or (not rollback and (state.get('phase')!='ready' or state.get('downloaded')!=state.get('tag'))):raise VaultError('Нет подготовленного обновления.',409)
            if slot!='factory' and (not re.fullmatch(r'v\d+\.\d+\.\d+-[a-f0-9]{12}',slot) or not (self.home/'releases'/slot/'server.py').is_file()):raise VaultError('Пакет недоступен.',409)
            write_json(self.home/'active.json',dict(active=slot,previous=old,pending=True,error=''))
            self.save(phase='installing',message='Перезапускаем приложение…')
        threading.Timer(1,restart).start()

    def action(self,action,restart):
        if action not in ('check','download','install','rollback'):raise VaultError('Неизвестное действие.')
        with self.lock:
            if self.running:raise VaultError('Обновление уже выполняется.',409)
            if action in ('install','rollback'):
                self.install(restart,action=='rollback');self.running=True;return self.info()
            self.running=True
        def work():
            try:self.check() if action=='check' else self.stage()
            except Exception as error:self.save(phase='error',message=error.message if isinstance(error,VaultError) else 'Не удалось получить обновление. Попробуй ещё раз.')
            finally:
                with self.lock:self.running=False
        threading.Thread(target=work,daemon=True).start();return self.info()
