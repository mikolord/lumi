"""Server users and isolated libraries. No process-global current user."""
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
import re
import shutil

from vault import Vault, VaultError, b64, unb64
from accounts import LibraryImporter, ACCOUNT_SECONDS


class Accounts:
    def __init__(self, control, sources):
        self.control, self.sources = control, sources
        self.cookie_name = 'photo_account'
        self.libraries = {}
        self.remote_imports = {}
        self.library_lock = threading.RLock()
        self.request_lock = threading.RLock()
        self.active_requests = 0
        self.deletion_lock = threading.RLock()
        with control.lock,control.db:
            if not control._setting('csrf_secret'):control._set('csrf_secret',b64(secrets.token_bytes(32)))
            control.db.executescript('''
              CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,login TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,salt TEXT NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL,
                quota INTEGER NOT NULL DEFAULT 0,disabled INTEGER NOT NULL DEFAULT 0,legacy INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS account_sessions(hash TEXT PRIMARY KEY,expires REAL NOT NULL,user_id TEXT);
              CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY,failures INTEGER NOT NULL,blocked REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS deleted_libraries(id TEXT PRIMARY KEY,remove_files INTEGER NOT NULL,legacy INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS album_grants(owner_id TEXT NOT NULL,album_id TEXT NOT NULL,user_id TEXT NOT NULL,
                PRIMARY KEY(owner_id,album_id,user_id));
            ''')
            if 'user_id' not in [row[1] for row in control.db.execute('PRAGMA table_info(account_sessions)')]:
                control.db.execute('ALTER TABLE account_sessions ADD COLUMN user_id TEXT')
            columns={row[1] for row in control.db.execute('PRAGMA table_info(account_sessions)')}
            for column,kind in [('device','TEXT'),('created','REAL'),('seen','REAL')]:
                if column not in columns:control.db.execute('ALTER TABLE account_sessions ADD COLUMN '+column+' '+kind)
            control.db.execute('CREATE TABLE IF NOT EXISTS tv_pairing(id TEXT PRIMARY KEY,approve_hash TEXT NOT NULL,poll_hash TEXT NOT NULL,code TEXT NOT NULL,device TEXT NOT NULL,expires REAL NOT NULL,user_id TEXT,approved_by TEXT)')
            if not self.configured and control._setting('account_hash'):
                uid=secrets.token_hex(16)
                control.db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?)',
                    (uid,control._setting('account_login'),control._setting('account_name'),control._setting('account_salt'),control._setting('account_hash'),'admin',0,0,1))
                control.db.execute('UPDATE account_sessions SET user_id=?',(uid,))
            control.db.execute("DELETE FROM settings WHERE key='setup_hash'")
            (control.directory/'setup-token').unlink(missing_ok=True)
        self.cleanup_deleted()

    def csrf_valid(self,account_token,value):
        try:
            if not isinstance(value,str) or len(value)>256:return False
            nonce,expires,signature=value.split('.')
            if int(expires)<time.time():return False
            binding=hashlib.sha256((account_token or '').encode()).hexdigest()
            expected=b64(hmac.new(unb64(self.control._setting('csrf_secret')),(nonce+'.'+expires+'|'+binding).encode(),hashlib.sha256).digest())
            return hmac.compare_digest(expected,signature)
        except (ValueError,TypeError):return False

    def csrf_token(self,account_token,existing=''):
        if self.csrf_valid(account_token,existing):return existing
        nonce=secrets.token_urlsafe(24);expires=str(int(time.time()+3600))
        binding=hashlib.sha256((account_token or '').encode()).hexdigest()
        signature=b64(hmac.new(unb64(self.control._setting('csrf_secret')),(nonce+'.'+expires+'|'+binding).encode(),hashlib.sha256).digest())
        return nonce+'.'+expires+'.'+signature

    @property
    def configured(self):
        with self.control.lock:
            return bool(self.control.db.execute('SELECT 1 FROM users LIMIT 1').fetchone())

    def user(self,token):
        with self.control.lock:
            row=self.control.db.execute('''SELECT u.* FROM users u JOIN account_sessions s ON s.user_id=u.id
              WHERE s.hash=? AND s.expires>? AND u.disabled=0''',
              (hashlib.sha256((token or '').encode()).hexdigest(),time.time())).fetchone()
            return dict(row) if row else None

    def authenticated(self,token):
        return self.user(token) is not None

    def require(self,token,admin=False):
        user=self.user(token)
        if not user:raise VaultError('Войди в аккаунт.',401)
        if admin and user['role']!='admin':raise VaultError('Доступно только администратору.',403)
        return user

    def library(self,user):
        with self.library_lock:
            with self.control.lock:
                if not self.control.db.execute('SELECT 1 FROM users WHERE id=?',(user['id'],)).fetchone():
                    raise VaultError('Пользователь удалён.',404)
            if user['id'] not in self.libraries:
                v=self.control if user['legacy'] else Vault(self.control.root,self.control.directory/'users'/user['id'],self.control.origin,seed=False)
                v.cookie_name='photo_vault'
                v.quota_bytes=user['quota']
                v.account_login=user['login'];v.account_name=user['name']
                with v.lock,v.db:
                    v._set('account_hash','registered')
                    if not v._setting('real_library'):
                        for row in v.db.execute('SELECT * FROM assets').fetchall():v._purge(row)
                        v._set('real_library','1')
                importer=LibraryImporter(v,self.sources if user['role']=='admin' else {})
                self.libraries[user['id']]=(v,importer)
            return self.libraries[user['id']]

    def context(self,token,admin=False):
        user=self.require(token,admin)
        v,importer=self.library(user)
        return user,v,importer

    def status(self,token):
        with self.control.lock:
            result=dict(configured=self.configured,authenticated=False)
        user=self.user(token)
        if user:
            v,importer=self.library(user)
            result.update(authenticated=True,id=user['id'],name=user['name'],login=user['login'],role=user['role'],
                          quota=user['quota'],used=v.usage(),folder=v._setting('source_folder'),
                          ready=user['role']!='admin' or v._setting('onboarding_done')=='1',job=importer.job())
        return result

    def session(self,user_id,device=''):
        token=secrets.token_urlsafe(32)
        self.control.db.execute('DELETE FROM account_sessions WHERE expires<?',(time.time(),))
        self.control.db.execute('INSERT INTO account_sessions(hash,expires,user_id,device,created,seen) VALUES(?,?,?,?,?,?)',
          (hashlib.sha256(token.encode()).hexdigest(),time.time()+ACCOUNT_SECONDS,user_id,device[:120],time.time(),time.time()))
        return token

    @staticmethod
    def device_name(agent):
        agent=(agent or '')[:300]
        if 'Android' in agent and ('TV' in agent or 'BRAVIA' in agent):return 'Android TV'
        if 'iPhone' in agent:return 'iPhone'
        if 'iPad' in agent:return 'iPad'
        if 'Android' in agent:return 'Android'
        if 'Windows' in agent:return 'Windows'
        if 'Macintosh' in agent:return 'Mac'
        return 'Неизвестное устройство'

    def touch_session(self,token,agent):
        digest=hashlib.sha256((token or '').encode()).hexdigest()
        with self.control.lock,self.control.db:
            self.control.db.execute("UPDATE account_sessions SET seen=?,device=CASE WHEN device IS NULL OR device='' THEN ? ELSE device END WHERE hash=? AND (device IS NULL OR device='' OR seen IS NULL OR seen<?)",(time.time(),self.device_name(agent),digest,time.time()-300))

    def sessions(self,token):
        user=self.require(token);current=hashlib.sha256(token.encode()).hexdigest()
        with self.control.lock:
            rows=self.control.db.execute('SELECT hash,device,created,seen,expires FROM account_sessions WHERE user_id=? AND expires>? ORDER BY COALESCE(seen,0) DESC',(user['id'],time.time())).fetchall()
            return [dict(id=r['hash'],device=r['device'] or 'Устройство без названия',created=r['created'],seen=r['seen'],expires=r['expires'],current=hmac.compare_digest(r['hash'],current)) for r in rows]

    def revoke(self,token,body):
        user=self.require(token);current=hashlib.sha256(token.encode()).hexdigest();target=body.get('id')
        with self.control.lock,self.control.db:
            if body.get('others') is True:self.control.db.execute('DELETE FROM account_sessions WHERE user_id=? AND hash<>?',(user['id'],current))
            elif isinstance(target,str) and re.fullmatch('[a-f0-9]{64}',target) and target!=current:self.control.db.execute('DELETE FROM account_sessions WHERE user_id=? AND hash=?',(user['id'],target))
            else:raise VaultError('Нельзя завершить текущий сеанс этим действием.')
        return self.sessions(token)

    def pair_start(self,device):
        device=device.strip() if isinstance(device,str) else ''
        if not device or len(device)>80:raise VaultError('Укажи название устройства до 80 символов.')
        identifier=secrets.token_urlsafe(18);approve=secrets.token_urlsafe(32);poll=secrets.token_urlsafe(32);code=str(secrets.randbelow(1000000)).zfill(6);now=time.time()
        with self.control.lock,self.control.db:
            self.control.db.execute('DELETE FROM tv_pairing WHERE expires<?',(now,))
            if self.control.db.execute('SELECT COUNT(*) FROM tv_pairing').fetchone()[0]>=1000:raise VaultError('Слишком много запросов на вход.',429)
            self.control.db.execute('INSERT INTO tv_pairing VALUES(?,?,?,?,?,?,NULL,NULL)',(identifier,hashlib.sha256(approve.encode()).hexdigest(),hashlib.sha256(poll.encode()).hexdigest(),code,device,now+180))
        return dict(id=identifier,approve=approve,poll=poll,code=code,expires=int(now+180))

    def pair_lookup(self,identifier,secret,field):
        if not isinstance(identifier,str) or not isinstance(secret,str) or not re.fullmatch('[A-Za-z0-9_-]{20,80}',identifier) or not re.fullmatch('[A-Za-z0-9_-]{30,80}',secret):raise VaultError('Код входа недействителен.',404)
        row=self.control.db.execute('SELECT * FROM tv_pairing WHERE id=? AND expires>?',(identifier,time.time())).fetchone()
        if not row or not hmac.compare_digest(row[field],hashlib.sha256(secret.encode()).hexdigest()):raise VaultError('Код входа истёк или уже использован.',404)
        return row

    def pair_inspect(self,token,body,approve=False):
        user=self.require(token)
        with self.control.lock,self.control.db:
            row=self.pair_lookup(body.get('id'),body.get('secret'),'approve_hash')
            if row['user_id']:raise VaultError('Этот код уже подтверждён.',409)
            if approve:
                if body.get('code')!=row['code']:raise VaultError('Код на экране не совпадает.',400)
                self.control.db.execute('UPDATE tv_pairing SET user_id=?,approved_by=? WHERE id=?',(user['id'],hashlib.sha256(token.encode()).hexdigest(),row['id']))
            return dict(device=row['device'],code=row['code'],expires=int(row['expires']))

    def pair_poll(self,body):
        with self.control.lock,self.control.db:
            row=self.pair_lookup(body.get('id'),body.get('secret'),'poll_hash')
            if not row['user_id']:return None
            user=self.control.db.execute('SELECT u.id FROM users u JOIN account_sessions s ON s.user_id=u.id WHERE u.id=? AND u.disabled=0 AND s.hash=? AND s.expires>?',(row['user_id'],row['approved_by'],time.time())).fetchone()
            if not user:raise VaultError('Аккаунт недоступен.',403)
            self.control.db.execute('DELETE FROM tv_pairing WHERE id=?',(row['id'],))
            return self.session(user['id'],row['device'])

    @staticmethod
    def validate(body):
        name,login,password=body.get('name'),body.get('login'),body.get('password')
        if not isinstance(name,str) or not 1<=len(name.strip())<=80:raise VaultError('Укажи имя — до 80 символов.')
        if not isinstance(login,str) or not re.fullmatch(r'[a-zA-Z0-9_.@+-]{3,80}',login):raise VaultError('Логин: 3–80 латинских букв, цифр или символов _.@+-')
        if not isinstance(password,str) or not 10<=len(password)<=256:raise VaultError('Пароль: от 10 до 256 символов.')
        salt=secrets.token_bytes(24)
        return name.strip(),login.lower(),b64(salt),b64(hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000))

    def register(self,body,local_setup=False):
        # Like Rack Live: only first-run setup from the installation's LAN.
        # A configured PHOTO_SETUP_PASSWORD can additionally bootstrap a remote installation.
        with self.control.lock,self.control.db:
            if self.configured:raise VaultError('Администратор уже создан. Войди в аккаунт.',409)
            if not local_setup:raise VaultError('Первую регистрацию открой из домашней сети по локальному адресу сервера.',403)
            name,login,salt,pw=self.validate(body);uid=secrets.token_hex(16)
            self.control.db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?)',(uid,login,name,salt,pw,'admin',0,0,1))
            self.control._set('account_hash','registered')
            self.control.db.execute("DELETE FROM settings WHERE key='setup_hash'")
            (self.control.directory/'setup-token').unlink(missing_ok=True)
            return self.session(uid)

    def login(self,body,address='local'):
        key='ip:'+address
        with self.control.lock,self.control.db:
            row=self.control.db.execute('SELECT failures,blocked FROM login_attempts WHERE key=?',(key,)).fetchone()
            failures,blocked=(row[0],row[1]) if row else (0,0)
            if blocked>time.time():raise VaultError(f'Попробуй через {int(blocked-time.time())+1} сек.',429)
            user=self.control.db.execute('SELECT * FROM users WHERE login=?',(str(body.get('login','')).lower(),)).fetchone()
            password=body.get('password','');password=password if isinstance(password,str) else ''
            candidate=hashlib.pbkdf2_hmac('sha256',password[:256].encode(),unb64(user['salt']) if user else bytes(24),600000)
            if not user or not hmac.compare_digest(candidate,unb64(user['password_hash'])) or user['disabled']:
                failures+=1;delay=min(900,30*2**min(5,(failures-5)//5)) if failures>=5 else 0
                self.control.db.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)',(key,failures,time.time()+delay))
                self.control.db.commit();raise VaultError('Неверный логин или пароль.',401)
            self.control.db.execute('DELETE FROM login_attempts WHERE key=?',(key,))
            return self.session(user['id'])

    def logout(self,token):
        with self.control.lock,self.control.db:
            self.control.db.execute('DELETE FROM account_sessions WHERE hash=?',(hashlib.sha256((token or '').encode()).hexdigest(),))

    def rename(self,token,name):
        user=self.require(token)
        if not isinstance(name,str) or not 1<=len(name.strip())<=80:raise VaultError('Укажи имя — до 80 символов.')
        with self.control.lock,self.control.db:self.control.db.execute('UPDATE users SET name=? WHERE id=?',(name.strip(),user['id']))
        return self.status(token)

    def confirm_password(self,token,password):
        user=self.require(token)
        if not isinstance(password,str) or not hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',password[:256].encode(),unb64(user['salt']),600000),unb64(user['password_hash'])):
            raise VaultError('Текущий пароль неверный.',401)
        return user

    def change_password(self,token,body):
        user=self.require(token)
        old=body.get('oldPassword','')
        if not isinstance(old,str) or not hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',old[:256].encode(),unb64(user['salt']),600000),unb64(user['password_hash'])):raise VaultError('Текущий пароль неверный.',401)
        _,_,salt,pw=self.validate(dict(name=user['name'],login=user['login'],password=body.get('password')))
        with self.control.lock,self.control.db:
            self.control.db.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?',(salt,pw,user['id']))
            self.control.db.execute('DELETE FROM account_sessions WHERE user_id=?',(user['id'],))
            session=self.session(user['id'])
        v,_=self.library(user)
        with v.lock,v.db:v.db.execute('DELETE FROM sessions')
        return session

    def list_users(self,token):
        self.require(token,True)
        with self.control.lock:users=[dict(row) for row in self.control.db.execute('SELECT * FROM users ORDER BY role,login')]
        return [dict(id=u['id'],name=u['name'],login=u['login'],role=u['role'],quota=u['quota'],disabled=bool(u['disabled']),used=self.library(u)[0].usage()) for u in users]

    def create_user(self,token,body):
        self.require(token,True)
        name,login,salt,pw=self.validate(body)
        quota=body.get('quota')
        if type(quota) is not int or quota<0 or quota>10**16:raise VaultError('Укажи лимит места. 0 — без ограничения.')
        uid=secrets.token_hex(16)
        try:
            with self.control.lock,self.control.db:
                self.control.db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?)',(uid,login,name,salt,pw,'user',quota,0,0))
        except sqlite3.IntegrityError as error:raise VaultError('Этот логин уже занят.',409) from error
        return dict(id=uid)

    def update_user(self,token,body):
        with self.deletion_lock:return self._update_user(token,body)

    def _update_user(self,token,body):
        actor=self.require(token,True);uid=body.get('id')
        with self.control.lock:
            row=self.control.db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        if not row:raise VaultError('Пользователь не найден.',404)
        user=dict(row);v,_=self.library(user)
        with v.operation_lock:
            quota=body.get('quota',user['quota'])
            if type(quota) is not int or quota<0 or quota>10**16:raise VaultError('Некорректный лимит.')
            if quota and quota<v.usage():raise VaultError('Лимит меньше уже занятого места.',409)
            disabled=bool(body.get('disabled',user['disabled']))
            if user['role']=='admin' and disabled:raise VaultError('Нельзя заблокировать администратора.')
            password=body.get('password')
            with self.control.lock,self.control.db:
                self.control.db.execute('UPDATE users SET quota=?,disabled=? WHERE id=?',(quota,int(disabled),uid))
                if password:
                    _,_,salt,pw=self.validate(dict(name=user['name'],login=user['login'],password=password))
                    self.control.db.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?',(salt,pw,uid))
                if disabled or password:
                    self.control.db.execute('DELETE FROM account_sessions WHERE user_id=?',(uid,))
            v.quota_bytes=quota
        return dict(ok=True)

    def request_started(self):
        with self.request_lock:self.active_requests+=1

    def request_finished(self):
        with self.request_lock:
            self.active_requests-=1
            if self.active_requests==0:self.cleanup_deleted()

    def cleanup_deleted(self):
        # Called only while no HTTP request or expiry sweep holds a library.
        # Tombstones survive restart, including an interrupted filesystem cleanup.
        with self.library_lock:
            with self.control.lock:rows=self.control.db.execute('SELECT * FROM deleted_libraries').fetchall()
            for row in rows:
                uid=row['id'];cached=self.libraries.get(uid)
                if cached:
                    v,_=cached
                    with v.operation_lock,v.lock:
                        if v is not self.control:v.db.close()
                    del self.libraries[uid]
                self.remote_imports.pop(uid,None)
                if row['remove_files']:
                    root=self.control.directory.resolve()
                    targets=[root/name for name in ('media','incoming','editing')] if row['legacy'] else [root/'users'/uid]
                    for target in targets:
                        # Never follow symlinks, a user-provided path, or delete /data.
                        if target.is_symlink():target.unlink();continue
                        resolved=target.resolve()
                        if not resolved.is_relative_to(root) or resolved==root:raise RuntimeError('Invalid library cleanup path')
                        if target.exists():shutil.rmtree(target)
                with self.control.lock,self.control.db:self.control.db.execute('DELETE FROM deleted_libraries WHERE id=?',(uid,))

    def delete_user(self,token,body,self_delete=False):
        with self.deletion_lock:return self._delete_user(token,body,self_delete)

    def _delete_user(self,token,body,self_delete=False):
        actor=self.require(token,not self_delete);uid=actor['id'] if self_delete else body.get('id')
        with self.control.lock:row=self.control.db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        if not row:raise VaultError('Пользователь не найден.',404)
        user=dict(row);own=uid==actor['id']
        if body.get('confirmLogin')!=user['login']:raise VaultError('Введи логин пользователя для подтверждения.')
        if body.get('files') not in ('keep','delete'):raise VaultError('Выбери, сохранить файлы или удалить их.')
        if own:
            password=body.get('password','')
            if not isinstance(password,str) or not hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',password[:256].encode(),unb64(user['salt']),600000),unb64(user['password_hash'])):
                raise VaultError('Текущий пароль неверный.',401)
        successor=None
        if user['role']=='admin':
            with self.control.lock:
                other=self.control.db.execute("SELECT id FROM users WHERE role='admin' AND disabled=0 AND id!=?",(uid,)).fetchone()
                if not other:
                    successor=self.control.db.execute('SELECT * FROM users WHERE id=? AND id!=? AND disabled=0',(body.get('successor'),uid)).fetchone()
                    if not successor:raise VaultError('Выбери нового администратора перед удалением своего аккаунта.',409)
        v,importer=self.library(user)
        with v.operation_lock,v.lock:
            for key in ('editor_job','immich_job','import_job'):
                job=json.loads(v._setting(key) or '{}')
                if job.get('state') in ('running','processing','stopping'):raise VaultError('Дождись завершения обработки файлов или останови импорт.',409)
            if importer.job().get('state') in ('running','processing'):raise VaultError('Дождись завершения импорта.',409)
            if successor:
                next_v,next_importer=self.library(dict(successor))
                next_importer.sources=self.sources
                with next_v.lock,next_v.db:next_v._set('onboarding_done','1')
            with self.control.lock,self.control.db:
                # Recheck ownership inside the registry transaction before revoking access.
                if successor:
                    changed=self.control.db.execute("UPDATE users SET role='admin' WHERE id=? AND disabled=0",(successor['id'],)).rowcount
                    if changed!=1:raise VaultError('Новый администратор недоступен. Выбери другого пользователя.',409)
                self.control.db.execute('PRAGMA secure_delete=ON')
                self.control.db.execute('DELETE FROM account_sessions WHERE user_id=?',(uid,))
                self.control.db.execute('DELETE FROM album_grants WHERE owner_id=? OR user_id=?',(uid,uid))
                self.control.db.execute('INSERT INTO deleted_libraries VALUES(?,?,?)',(uid,int(body['files']=='delete'),user['legacy']))
                self.control.db.execute('DELETE FROM users WHERE id=?',(uid,))
            v.retired=True
            v.db.execute('PRAGMA secure_delete=ON')
            with v.db:
                for table in ('sessions','credentials','challenges'):v.db.execute('DELETE FROM '+table)
            # A legacy owner's DB is the server registry, never remove that file.
            if user['legacy'] and body['files']=='delete':
                with v.db:
                    for table in ('assets','albums','album_items','shared_items','imports','upload_receipts','external_assets','external_albums','asset_hashes','asset_edits','people','people_faces','people_scans'):v.db.execute('DELETE FROM '+table)
                    v.db.execute("DELETE FROM settings WHERE key NOT IN ('csrf_secret','account_hash','real_library')")
            return dict(ok=True,files=body['files'],signedOut=own)

    def immich(self,token):
        user,v,importer=self.context(token)
        from immich_import import ImmichImport
        with self.library_lock:
            if user['id'] not in self.remote_imports:
                self.remote_imports[user['id']]=ImmichImport(self,user['id'],v,importer)
            return self.remote_imports[user['id']]

    def set_grants(self,token,album_id,user_ids):
        owner,v,_=self.context(token)
        if not isinstance(user_ids,list) or len(user_ids)>500:raise VaultError('Некорректный список пользователей.')
        with v.lock:
            if not v.db.execute('SELECT 1 FROM albums WHERE id=?',(album_id,)).fetchone():raise VaultError('Альбом не найден.',404)
        with self.control.lock,self.control.db:
            for uid in user_ids:
                if uid==owner['id'] or not self.control.db.execute('SELECT 1 FROM users WHERE id=? AND disabled=0',(uid,)).fetchone():raise VaultError('Пользователь не найден.')
            self.control.db.execute('DELETE FROM album_grants WHERE owner_id=? AND album_id=?',(owner['id'],album_id))
            self.control.db.executemany('INSERT INTO album_grants VALUES(?,?,?)',[(owner['id'],album_id,uid) for uid in set(user_ids)])
        return dict(ok=True)

    def shared(self,token):
        recipient=self.require(token)
        with self.control.lock:
            grants=[dict(row) for row in self.control.db.execute('SELECT u.*,g.album_id FROM album_grants g JOIN users u ON u.id=g.owner_id WHERE g.user_id=? AND u.disabled=0',(recipient['id'],))]
        result=[]
        for grant in grants:
            v,_=self.library(grant)
            with v.lock:
                album=v.db.execute('SELECT * FROM albums WHERE id=?',(grant['album_id'],)).fetchone()
                if not album:continue
                items=[dict(row) for row in v.db.execute("SELECT a.* FROM assets a JOIN album_items i ON a.id=i.asset_id WHERE i.album_id=? AND a.state='public' ORDER BY a.id",(album['id'],))]
            for item in items:
                with v.lock:edit=v.db.execute('SELECT metadata,revision FROM asset_edits WHERE asset_id=?',(item['id'],)).fetchone()
                source=v.asset_metadata(item)
                item['metadata']=json.dumps(v.display_metadata(source,json.loads(edit['metadata'])) if edit else source)
                if edit:item['revision']=edit['revision']
            visible=[item['id'] for item in items]
            result.append(dict(owner=grant['id'],ownerName=grant['name'],id=album['id'],name=album['name'],items=items,cover=album['cover_id'] if album['cover_id'] in visible else next(iter(visible),None)))
        return result

    def shared_path(self,token,owner,album,index,preview):
        grant=next((g for g in self.shared(token) if g['owner']==owner and g['id']==album),None)
        if not grant or not any(i['id']==index for i in grant['items']):raise VaultError('Нет доступа к файлу.',404)
        with self.control.lock:user=dict(self.control.db.execute('SELECT * FROM users WHERE id=?',(owner,)).fetchone())
        v,_=self.library(user)
        return v.media_path(index,preview,'')

    def library_state(self,token,vault_token):
        user,v,_=self.context(token)
        shared_albums=[];active=[]
        for shared in self.shared(token):
            indices=[];cover=None
            for row in shared.pop('items'):
                route=f"/media/shared/{shared['owner']}/{shared['id']}/{row['id']}"
                with v.lock,v.db:
                    old=v.db.execute('SELECT asset_id FROM shared_items WHERE ref=?',(route,)).fetchone()
                    if old:index=old[0]
                    else:
                        index=v.db.execute('SELECT COALESCE(MAX(id),-1)+1 FROM assets').fetchone()[0]
                        v.db.execute("INSERT INTO assets(id,media_key,kind,original,preview,metadata,state) VALUES(?,?,?,'','','{}','shared')",(index,json.dumps(route),row['kind']))
                        v.db.execute('INSERT INTO shared_items VALUES(?,?)',(route,index))
                    v.db.execute("UPDATE assets SET state='shared' WHERE id=?",(index,))
                indices.append(index)
                if row['id']==shared.get('cover'):cover=index
                active.append(dict(id=index,key=route,kind=row['kind'],state='shared',metadata=json.loads(row['metadata']),revision=row.get('revision',0),preview=route+'/preview',original=route+'/original'))
            shared_albums.append(dict(id='shared:'+shared['owner']+':'+shared['id'],name=shared['name'],indices=indices,cover=cover,shared=True,ownerName=shared['ownerName']))
        with v.lock,v.db:
            known=[r[0] for r in v.db.execute('SELECT asset_id FROM shared_items')]
            keep={row['id'] for row in active}
            for index in known:
                if index not in keep:v.db.execute("UPDATE assets SET state='purged' WHERE id=?",(index,))
        data=v.library(vault_token)
        for item in active:data['items'][item['id']]=item
        data['albums']=v.albums()+shared_albums
        data['accountId']=user['id']
        return data

    def expire_all(self):
        with self.control.lock:users=[dict(row) for row in self.control.db.execute('SELECT * FROM users')]
        for user in users:
            try:self.library(user)[0].expire()
            except VaultError as error:
                if error.status!=404:raise
