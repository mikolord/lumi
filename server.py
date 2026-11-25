"""Multiuser gallery API and authenticated byte-range media server."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from io import BytesIO
from urllib.parse import urlsplit, parse_qs
import json
import shutil
import re
import os
from http.cookies import SimpleCookie
import mimetypes
import hmac
import hashlib
import base64
import threading
from vault import Vault, VaultError
from accounts import ACCOUNT_SECONDS, PHOTO_EXT, VIDEO_EXT
from users import Accounts
import ipaddress
import tempfile
from urllib.parse import unquote


class Handler(SimpleHTTPRequestHandler):
    thumbnail_limit = threading.BoundedSemaphore(2)
    vault = None
    accounts = None

    def end_headers(self):
        if self.command in ('GET','HEAD') and urlsplit(self.path).path in ('/','/index.html','/boot.js','/sw.js','/VERSION'):
            self.send_header('Cache-Control','no-cache, must-revalidate')
        super().end_headers()

    def handle_one_request(self):
        if self.accounts:self.accounts.request_started()
        try:return super().handle_one_request()
        finally:
            if self.accounts:self.accounts.request_finished()

    def account_token(self):
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", "")).get(self.accounts.cookie_name)
            return cookie.value if cookie else ""
        except Exception:
            return ""

    def token(self):
        try:
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            cookie = cookies.get(self.vault.cookie_name)
            return cookie.value if cookie else ''
        except Exception:
            return ''

    def session_cookie(self, token):
        secure = '; Secure' if self.app_origin().startswith('https://') else ''
        return f'{self.vault.cookie_name}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={300 if token else 0}{secure}'

    def json_response(self, payload, status=200, token=None, account_token=None, csrf_token=None):
        if self.accounts and account_token is not None:
            csrf_token=self.accounts.csrf_token(account_token) if account_token else ''
        if csrf_token is not None and isinstance(payload,dict):payload=dict(payload,csrf=csrf_token)
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        if token is not None:
            self.send_header('Set-Cookie', self.session_cookie(token))
        if account_token is not None:
            secure = '; Secure' if self.app_origin().startswith('https://') else ''
            self.send_header('Set-Cookie', f'{self.accounts.cookie_name}={account_token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={ACCOUNT_SECONDS if account_token else 0}{secure}')
        if csrf_token is not None:
            secure='; Secure' if self.app_origin().startswith('https://') else ''
            self.send_header('Set-Cookie',f'photo_csrf={csrf_token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={3600 if csrf_token else 0}{secure}')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def app_origin(self):
        return self.origin() or self.headers.get('X-Photo-App-Origin','') or 'http://'+self.headers.get('Host','localhost')

    def csrf_cookie(self):
        try:
            value=SimpleCookie(self.headers.get('Cookie','')).get('photo_csrf')
            return value.value if value else ''
        except Exception:return ''

    def csrf_allowed(self):
        supplied=self.headers.get('X-Photo-CSRF','')
        cookie=self.csrf_cookie()
        return bool(supplied and cookie and supplied.isascii() and cookie.isascii() and hmac.compare_digest(supplied,cookie) and self.accounts.csrf_valid(self.account_token(),supplied))

    def origin(self):
        return self.headers.get('Origin','')

    def origin_allowed(self):
        origin=self.origin()
        parsed=urlsplit(origin)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:return False
        allowed={self.vault.origin,*os.environ.get('PHOTO_ORIGINS','').split(',')}
        return origin in allowed or parsed.netloc.lower()==self.headers.get('Host','').lower()

    def local_setup(self):
        try:
            peer=ipaddress.ip_address(self.client_address[0])
            parsed=urlsplit(self.app_origin());host=parsed.hostname
            # First-run setup must use the directly addressed LAN endpoint, never a forwarded public request.
            if any(self.headers.get(name) for name in ('Forwarded','X-Forwarded-For','X-Forwarded-Host','X-Forwarded-Proto','Via')):return False
            lan=os.environ.get('PHOTO_LAN_ORIGIN','')
            if lan and (self.app_origin()!=lan or self.headers.get('Host','').lower()!=urlsplit(lan).netloc.lower()):return False
            if not lan and ':' not in self.headers.get('Host',''):return False
            local_host=host=='localhost' or ipaddress.ip_address(host).is_private
            return peer.is_private and local_host
        except (ValueError,TypeError):
            return False

    def bind_user(self):
        if self.accounts:
            self.user,self.vault,self.importer=self.accounts.context(self.account_token());self.accounts.touch_session(self.account_token(),self.headers.get('User-Agent',''))

    def library_response(self):
        return self.accounts.library_state(self.account_token(),self.token()) if self.accounts else self.vault.library(self.token())

    def get_updates(self):
        from updates import Updates
        with self.accounts.control.lock:
            if not hasattr(self.accounts,'updater'):self.accounts.updater=Updates(self.accounts.control.directory,self.vault.root)
            return self.accounts.updater

    def get_people(self):
        from people import People
        return People(self.vault)

    def get_editor(self):
        from editor import MediaEditor
        with self.vault.lock:
            if not hasattr(self.importer,'editor'):self.importer.editor=MediaEditor(self.vault)
            return self.importer.editor

    def upload(self):
        self.bind_user()
        with self.vault.upload_lock:self.upload_file()

    def upload_file(self):
        self.accounts.require(self.account_token())
        size=int(self.headers.get('Content-Length','0'))
        name=unquote(self.headers.get('X-File-Name','')).replace('\\','/').split('/')[-1][:255]
        suffix=Path(name).suffix.lower()
        if suffix not in PHOTO_EXT|VIDEO_EXT:raise VaultError('Этот формат фото или видео пока не поддерживается.',415)
        if not 0<size<=10*1024**3:raise VaultError('Файл пустой или больше 10 ГБ.',413)
        key=self.headers.get('X-Upload-ID','')
        if key and not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}',key):raise VaultError('Некорректный идентификатор загрузки.')
        if key:
            with self.vault.lock:old=self.vault.db.execute('SELECT * FROM upload_receipts WHERE key=?',(key,)).fetchone()
            if old:
                if old['size']!=size or old['name']!=name:raise VaultError('Идентификатор уже использован для другого файла.',409)
                self.connection.settimeout(60)
                remaining=size
                while remaining:
                    chunk=self.rfile.read(min(1024*1024,remaining))
                    if not chunk:raise VaultError('Передача прервана.')
                    remaining-=len(chunk)
                self.json_response(dict(id=old['asset_id'],repeated=True,duplicate=bool(old['duplicate'])));return
        self.connection.settimeout(60)
        incoming=self.vault.directory/'incoming'
        with self.vault.operation_lock:
            self.vault.check_quota(size)
            if shutil.disk_usage(self.vault.directory).free<size+250*1024**2:raise VaultError('На сервере недостаточно свободного места.',413)
            incoming.mkdir(exist_ok=True)
            target=tempfile.NamedTemporaryFile(dir=incoming,suffix=suffix,delete=False)
            path=Path(target.name)
            # Reserve the entire logical size before reading any bytes. All concurrent
            # uploads, imports and duplicates count this reservation against the quota.
            try:target.truncate(size)
            except Exception:
                target.close();path.unlink(missing_ok=True);raise
        try:
            remaining=size
            while remaining:
                chunk=self.rfile.read(min(1024*1024,remaining))
                if not chunk:raise VaultError('Загрузка прервана.')
                target.write(chunk);remaining-=len(chunk)
            target.flush();target.close()
            self.accounts.require(self.account_token())
            digest=self.importer.hash_file(path)
            with self.vault.operation_lock:
                index=self.importer.lookup_content(size,digest)
                duplicate=index is not None
                if duplicate:
                    if key:
                        with self.vault.lock,self.vault.db:self.vault.db.execute('INSERT INTO upload_receipts(key,name,size,asset_id,duplicate) VALUES(?,?,?,?,1)',(key,name,size,index))
                else:index=self.importer.ingest(path,name,consume=True,receipt=(key,name,size) if key else None,content_hash=digest)
        finally:
            target.close()
            with self.vault.operation_lock:path.unlink(missing_ok=True)
        self.json_response(dict(id=index,duplicate=duplicate))

    def do_POST(self):
        if not self.vault:
            self.json_response(dict(error='Server protection unavailable'),503);return
        if self.accounts:
            if self.origin() and not self.origin_allowed():
                self.json_response(dict(error='Запрос с другого сайта запрещён.'),403);return
            if not self.csrf_allowed():
                self.json_response(dict(error='Сессия формы истекла. Обнови страницу.',code='csrf'),403);return
        elif not self.origin_allowed():
            self.json_response(dict(error='Запрос с другого сайта запрещён.'),403);return
        try:
            path=urlsplit(self.path).path
            if path=='/api/assets/upload' and self.accounts:
                self.upload();return
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=131072:raise VaultError('Некорректный размер запроса.',413)
            body=json.loads(self.rfile.read(size))
            if not isinstance(body,dict):raise VaultError('Некорректный запрос.')
            if self.accounts:
                a=self.accounts
                if path in ('/api/account/register','/api/account/login'):
                    session=a.register(body,local_setup=self.local_setup()) if path.endswith('register') else a.login(body,self.client_address[0])
                    a.touch_session(session,self.headers.get('User-Agent',''));self.json_response(a.status(session),account_token=session,token='');return
                if path=='/api/tv/pair/start':
                    self.json_response(a.pair_start(body.get('device')));return
                if path=='/api/tv/pair/poll':
                    session=a.pair_poll(body)
                    self.json_response(dict(approved=bool(session)),account_token=session if session else None,token='' if session else None);return
                self.bind_user()
                if path=='/api/account/sessions/revoke':
                    self.json_response(dict(sessions=a.revoke(self.account_token(),body)));return
                if path in ('/api/tv/pair/inspect','/api/tv/pair/approve'):
                    self.json_response(a.pair_inspect(self.account_token(),body,path.endswith('/approve')));return
                if path=='/api/account/logout':
                    a.logout(self.account_token());self.vault.sign_out(self.token())
                    self.json_response(dict(ok=True),account_token='',token='');return
                if path in ('/api/vault/disable','/api/vault/passkey/remove'):
                    a.confirm_password(self.account_token(),body.get('password'))
                    session=self.vault.remove_protection(path.endswith('/remove'))
                    self.json_response(a.library_state(self.account_token(),session),token=session);return
                if path=='/api/vault/preferences':
                    self.vault.conceal_hidden(body.get('concealHidden'))
                    self.json_response(self.library_response());return
                if path=='/api/account/delete':
                    self.json_response(a.delete_user(self.account_token(),body,True),account_token='',token='');return
                if path=='/api/account/password':
                    session=a.change_password(self.account_token(),body)
                    self.json_response(a.status(session),account_token=session,token='');return
                if path=='/api/account/profile':
                    self.json_response(a.rename(self.account_token(),body.get('name')));return
                if path=='/api/admin/users/create':
                    self.json_response(a.create_user(self.account_token(),body));return
                if path=='/api/admin/users/update':
                    self.json_response(a.update_user(self.account_token(),body));return
                if path=='/api/admin/users/delete':
                    self.json_response(a.delete_user(self.account_token(),body));return
                if path=='/api/admin/updates/action':
                    a.require(self.account_token(),True)
                    self.json_response(self.get_updates().action(body.get('action'),getattr(self,'restart',lambda:None)));return
                if path=='/api/people/action':
                    self.json_response(self.get_people().action(body));return
                if path=='/api/import/immich/start':
                    self.json_response(a.immich(self.account_token()).start(body));return
                if path=='/api/import/immich/stop':
                    self.json_response(a.immich(self.account_token()).stop());return
                if path=='/api/account/folder':
                    a.require(self.account_token(),True)
                    self.json_response(self.importer.start_import(body.get('source'),body.get('path','')));return
                if path=='/api/account/finish':
                    self.importer.finish();self.json_response(a.status(self.account_token()));return
                if path=='/api/albums/action':
                    self.vault.album_action(body,self.token());self.json_response(self.library_response());return
                if path=='/api/albums/share':
                    self.json_response(a.set_grants(self.account_token(),body.get('id'),body.get('users')));return
                if path in ('/api/editor/save','/api/editor/restore'):
                    index=body.get('index')
                    if type(index) is not int:raise VaultError('Неверная фотография.')
                    editor=self.get_editor()
                    if path.endswith('/restore'):
                        editor.restore(index,self.token());self.json_response(self.library_response())
                    else:
                        token=self.account_token()
                        self.json_response(editor.start(index,body.get('recipe'),self.token(),lambda:a.require(token)))
                    return
                if path=='/api/assets/check':
                    size=body.get('size');digest=body.get('sha256')
                    if type(size) is not int or not 0<size<=10*1024**3 or not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise VaultError('Некорректная проверка файла.')
                    self.json_response(dict(duplicate=self.importer.lookup_content(size,digest) is not None));return
                if path=='/api/assets/favorite':
                    self.vault.favorite(body.get('indices'),body.get('value'),self.token());self.json_response(self.library_response());return
            token=self.token()
            if path=='/api/vault/setup':
                session=self.vault.setup(body.get('setupToken'),body.get('pin'),account_authorized=bool(self.accounts))
                data=self.accounts.library_state(self.account_token(),session) if self.accounts else self.vault.library(session)
                self.json_response(data,token=session)
            elif path=='/api/vault/unlock':
                session=self.vault.unlock(body.get('pin',''))
                data=self.accounts.library_state(self.account_token(),session) if self.accounts else self.vault.library(session)
                self.json_response(data,token=session)
            elif path=='/api/vault/lock':
                self.vault.sign_out(token);self.json_response(self.vault.status(''),token='')
            elif path=='/api/assets/action':
                self.vault.mutate(body.get('action'),body.get('indices'),token,account_authorized=bool(self.accounts));self.json_response(self.library_response())
            elif path in ('/api/vault/register/options','/api/vault/login/options'):
                self.json_response(self.vault.passkey_options('/register/' in path,token,self.app_origin()))
            elif path in ('/api/vault/register/verify','/api/vault/login/verify'):
                session=self.vault.passkey_verify('/register/' in path,body.get('challengeId'),body.get('credential'),token)
                data=self.accounts.library_state(self.account_token(),session or token) if self.accounts else self.vault.library(session or token)
                self.json_response(data,token=session)
            else:self.json_response(dict(error='Неизвестный запрос.'),404)
        except VaultError as error:self.json_response(dict(error=error.message),error.status)
        except (ValueError,TypeError,KeyError):self.json_response(dict(error='Некорректный запрос.'),400)
        except Exception:self.json_response(dict(error='Не удалось выполнить запрос.'),500)

    def api_get(self):
        path=urlsplit(self.path).path
        try:
            if self.accounts and path=='/api/assets/upload-status':
                self.bind_user();key=parse_qs(urlsplit(self.path).query).get('key',[''])[0]
                with self.vault.lock:row=self.vault.db.execute('SELECT asset_id,duplicate FROM upload_receipts WHERE key=?',(key,)).fetchone()
                self.json_response(dict(complete=bool(row),id=row[0] if row else None,duplicate=bool(row[1]) if row else False));return True
            if self.accounts and path=='/api/import/immich':
                self.json_response(self.accounts.immich(self.account_token()).status());return True
            if self.accounts and path=='/api/account/status':
                status=self.accounts.status(self.account_token())
                status['canSetup']=self.local_setup()
                status['setupUrl']=os.environ.get('PHOTO_LAN_ORIGIN','')
                csrf=self.accounts.csrf_token(self.account_token(),self.csrf_cookie())
                self.json_response(status,csrf_token=csrf);return True
            if self.accounts and path.startswith('/api/'):
                self.bind_user()
                if path=='/api/thumbnails/verify':
                    raw=parse_qs(urlsplit(self.path).query).get('index',[''])[0]
                    if not raw.isdigit():raise VaultError('Неверная фотография.')
                    with self.vault.operation_lock,self.vault.lock:
                        row=self.vault.db.execute('SELECT state FROM assets WHERE id=?',(int(raw),)).fetchone()
                        if not row or row['state']!='public':raise VaultError('Миниатюра недоступна.',404)
                        preview=self.vault.media_path(int(raw),True,self.token());stat=preview.stat()
                        fingerprint=f'thumb192v1|{self.user["id"]}|{raw}|{preview.name}|{stat.st_size}|{stat.st_mtime_ns}'
                        tag=hashlib.sha256(fingerprint.encode()).hexdigest()
                    from vault import unb64
                    key=hmac.new(unb64(self.accounts.control._setting('csrf_secret')),('lumi-thumbnail-v1|'+self.user['id']).encode(),hashlib.sha256).digest()
                    self.json_response(dict(owner=self.user['id'],tag=tag,key=base64.b64encode(key).decode()));return True
                if path=='/api/account/sessions':
                    self.json_response(dict(sessions=self.accounts.sessions(self.account_token())));return True
                if path=='/api/admin/updates':
                    self.accounts.require(self.account_token(),True)
                    self.json_response(self.get_updates().info());return True
                if path=='/api/admin/metrics':
                    self.accounts.require(self.account_token(),True)
                    from resource_monitor import snapshot
                    self.json_response(snapshot());return True
                if path=='/api/people':
                    pid=parse_qs(urlsplit(self.path).query).get('id',[''])[0]
                    self.json_response(self.get_people().detail(pid) if pid else self.get_people().status());return True
                if path=='/api/assets/info':
                    raw=parse_qs(urlsplit(self.path).query).get('index',[''])[0]
                    if not raw.isdigit():raise VaultError('Неверная фотография.')
                    self.importer.refresh_metadata(int(raw),self.token());self.json_response(self.library_response());return True
                if path=='/api/editor':
                    raw=parse_qs(urlsplit(self.path).query).get('index',[''])[0]
                    if not raw.isdigit():raise VaultError('Неверная фотография.')
                    self.json_response(self.get_editor().source(int(raw),self.token()));return True
                if path=='/api/account/folders':
                    self.accounts.require(self.account_token(),True)
                    query=parse_qs(urlsplit(self.path).query)
                    self.json_response(self.importer.folders(query.get('source',[None])[0],query.get('path',[''])[0]));return True
                if path=='/api/account/import':self.json_response(self.importer.job());return True
                if path=='/api/admin/users':self.json_response(dict(users=self.accounts.list_users(self.account_token())));return True
                if path=='/api/albums/people':
                    with self.accounts.control.lock:
                        people=[dict(row) for row in self.accounts.control.db.execute('SELECT id,name,login FROM users WHERE id!=? AND disabled=0',(self.user['id'],))]
                        grants=[dict(row) for row in self.accounts.control.db.execute('SELECT album_id,user_id FROM album_grants WHERE owner_id=?',(self.user['id'],))]
                    self.json_response(dict(users=people,grants=grants));return True
                if path=='/api/storage':
                    usage=shutil.disk_usage(self.vault.directory);used=self.vault.usage();quota=self.user['quota']
                    free=min(max(0,quota-used),usage.free) if quota else usage.free
                    self.json_response(dict(total=quota or None,used=used,free=max(0,quota-used) if quota else None,available=free,media_bytes=used,scope='account',quota=quota));return True
            if self.vault and path in ('/api/library','/api/vault/status'):
                self.json_response(self.library_response() if path=='/api/library' else self.vault.status(self.token()));return True
        except VaultError as error:
            self.json_response(dict(error=error.message),error.status);return True
        return False

    def do_GET(self):
        if not self.api_get():super().do_GET()

    def do_HEAD(self):
        if not self.api_get():super().do_HEAD()

    def serve_media(self, path):
        size = path.stat().st_size
        start, end, partial = 0, size - 1, False
        header = self.headers.get('Range')
        if header:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', header.strip())
            if not match or not any(match.groups()):
                self.send_error(400, 'Invalid range')
                return None
            first, last = match.groups()
            if not first:
                start = max(0, size - int(last))
            else:
                start, end = int(first), min(int(last), size - 1) if last else size - 1
            if start >= size or end < start:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.end_headers()
                return None
            partial = True
        source = path.open('rb'); source.seek(start)
        self._range_remaining = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(self._range_remaining))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if partial:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        return source

    def send_head(self):
        self._range_remaining = None
        if self.vault:
            path = Path(self.translate_path(self.path)).resolve()
            route = urlsplit(self.path).path
            match = re.fullmatch(r'/media/(\d+)/(original|preview|source|source-preview)', route)
            try:
                thumb=re.fullmatch(r'/media/(\d+)/thumbnail',route)
                if self.accounts and thumb:
                    self.bind_user()
                    with self.thumbnail_limit,self.vault.operation_lock,self.vault.lock:
                        row=self.vault.db.execute('SELECT state FROM assets WHERE id=?',(int(thumb[1]),)).fetchone()
                        if not row or row['state']!='public':raise VaultError('Миниатюра недоступна.',404)
                        source=self.vault.media_path(int(thumb[1]),True,self.token())
                        from PIL import Image,ImageOps
                        with Image.open(source) as image:
                            image=ImageOps.exif_transpose(image);image.thumbnail((192,192));output=BytesIO();image.convert('RGB').save(output,'JPEG',quality=78,optimize=True)
                    data=output.getvalue();self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();return BytesIO(data)
                face=re.fullmatch(r'/media/people/([a-f0-9]{32})/preview',route)
                if self.accounts and face:
                    self.bind_user();data=self.get_people().crop(face[1])
                    self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();return BytesIO(data)
                shared=re.fullmatch(r'/media/shared/([a-f0-9]{32})/([a-f0-9]{32})/(\d+)/(original|preview)',route)
                if self.accounts and shared:
                    return self.serve_media(self.accounts.shared_path(self.account_token(),shared[1],shared[2],int(shared[3]),shared[4]=='preview'))
                if self.accounts and (match or route.startswith('/assets/')):
                    self.bind_user()
                    self.accounts.require(self.account_token())
                if match:
                    return self.serve_media(self.vault.media_path(int(match[1]), match[2] in ('preview','source-preview'), self.token(),source=match[2].startswith('source')))
                if path.is_relative_to(self.vault.root):
                    relative = path.relative_to(self.vault.root).as_posix()
                    if self.accounts and relative.startswith('assets/'):
                        self.bind_user()
                        self.accounts.require(self.account_token())
                        if self.vault.legacy_index(relative) is None:
                            raise VaultError('Доступ запрещён.',403)
                    index = self.vault.legacy_index(relative)
                    if index is not None:
                        self.vault.media_path(index, False, self.token())
                        return self.serve_media(path)
                if path.name == 'metadata-data.js' or path.suffix.lower() in ('.py', '.sqlite3', '.db', '.yaml', '.env') or (path.is_dir() and route not in ('/', '')):
                    raise VaultError('Доступ запрещён.', 403)
            except VaultError as error:
                self.send_error(error.status, 'Access denied' if error.status != 404 else 'Not found')
                return None
        if urlsplit(self.path).path == '/api/storage':
            try:
                root = Path(self.directory)
                usage = shutil.disk_usage(root)
                media = list(self.vault.media.iterdir()) if self.vault else [p for p in (root / 'assets').iterdir() if p.is_file() and (re.fullmatch(r'\d+\.jpg', p.name) or p.suffix.lower() == '.mp4')]
                payload = dict(total=usage.total, used=usage.used, free=usage.free, media_bytes=sum(p.stat().st_size for p in media), scope='volume')
                data = json.dumps(payload).encode('utf-8')
                self.send_response(200)
            except OSError:
                data = b'{"error":"Storage unavailable"}'
                self.send_response(503)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            return BytesIO(data)
        path = Path(self.translate_path(self.path))
        header = self.headers.get('Range')
        if not header or path.name not in ('demo-video.mp4', 'demo-vertical.mp4') or not path.is_file():
            return super().send_head()
        size = path.stat().st_size
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', header.strip())
        if not match or not any(match.groups()):
            self.send_error(400, 'Invalid range')
            return None
        first, last = match.groups()
        if not first:
            length = int(last)
            start = max(0, size - length)
            end = size - 1
        else:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        if start >= size or end < start:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.end_headers()
            return None
        source = path.open('rb')
        source.seek(start)
        self._range_remaining = end - start + 1
        self.send_response(206)
        self.send_header('Content-Type', 'video/mp4')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(self._range_remaining))
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        return source

    def copyfile(self, source, outputfile):
        if self._range_remaining is None:
            return super().copyfile(source, outputfile)
        remaining = self._range_remaining
        while remaining:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)


if __name__ == '__main__':
    Handler.vault = Vault(Path.cwd(), Path(os.environ.get('PHOTO_DATA_DIR', '/data')), os.environ.get('PHOTO_ORIGIN', 'http://localhost:8000'))
    Handler.accounts = Accounts(Handler.vault, json.loads(os.environ.get('PHOTO_SOURCES', '{}')))
    from people import start_worker
    start_worker(Handler.accounts)
    def cleanup_trash():
        while True:
            threading.Event().wait(60)
            try:
                Handler.accounts.request_started()
                try:Handler.accounts.expire_all()
                finally:Handler.accounts.request_finished()
            except Exception:
                pass  # Retry on the next cycle; originals remain inaccessible when expired.
    threading.Thread(target=cleanup_trash, daemon=True).start()
    httpd=ThreadingHTTPServer(('0.0.0.0',8000),Handler)
    Handler.restart=staticmethod(lambda:threading.Thread(target=httpd.shutdown,daemon=True).start())
    try:httpd.serve_forever()
    finally:httpd.server_close()
