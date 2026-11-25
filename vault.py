"""Per-user album vault: server authorization, WebAuthn and durable 90-day trash."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

RETENTION = 90 * 86400
SESSION_SECONDS = 300


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def unb64(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


class VaultError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


class Vault:
    def __init__(self, root, directory, origin, seed=True):
        self.root, self.directory, self.origin = Path(root).resolve(), Path(directory).resolve(), origin.rstrip('/')
        if self.root == self.directory or self.root in self.directory.parents:
            raise RuntimeError('Vault data must be outside the public document root')
        self.directory.mkdir(parents=True, exist_ok=True)
        try:os.chmod(self.directory,0o700)
        except OSError:pass
        self.media = self.directory / 'media'
        self.media.mkdir(exist_ok=True)
        incoming=self.directory/'incoming'
        if incoming.is_dir():
            for path in incoming.iterdir():
                if path.is_file():path.unlink(missing_ok=True)
        self.rp_id = urlsplit(self.origin).hostname
        self.cookie_name = '__Host-photo_vault' if self.origin.startswith('https://') else 'photo_vault'
        self.lock = threading.RLock()
        self.operation_lock = threading.RLock()
        self.upload_lock = threading.RLock()
        self.quota_bytes = 0
        self.db = sqlite3.connect(self.directory / 'vault.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS assets(id INTEGER PRIMARY KEY, media_key TEXT NOT NULL, kind TEXT NOT NULL,
            original TEXT NOT NULL, preview TEXT NOT NULL, legacy_original TEXT, legacy_preview TEXT,
            metadata TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'public', previous_state TEXT NOT NULL DEFAULT 'public', deleted_at REAL);
          CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, expires REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS credentials(id TEXT PRIMARY KEY, public_key TEXT NOT NULL, sign_count INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS challenges(id TEXT PRIMARY KEY, kind TEXT NOT NULL, value TEXT NOT NULL, owner TEXT, expires REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY CHECK(id=1), failures INTEGER NOT NULL, blocked_until REAL NOT NULL);
          INSERT OR IGNORE INTO attempts VALUES(1,0,0);
        ''')
        from people import SCHEMA
        self.db.executescript(SCHEMA)
        columns={row[1] for row in self.db.execute('PRAGMA table_info(people)')}
        if 'excluded' not in columns:self.db.execute('ALTER TABLE people ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0')
        if 'ignore_vector' not in columns:self.db.execute('ALTER TABLE people ADD COLUMN ignore_vector TEXT')
        for column in ('favorite','pinned','hidden'):
            if column not in columns:self.db.execute('ALTER TABLE people ADD COLUMN '+column+' INTEGER NOT NULL DEFAULT 0')
        if 'cover_face' not in columns:self.db.execute('ALTER TABLE people ADD COLUMN cover_face TEXT')
        self.db.commit()
        with self.lock, self.db:
            if not self._setting('setup_hash') and not self.configured and not self._setting('account_hash') and seed:
                token = secrets.token_urlsafe(32)
                (self.directory / 'setup-token').write_text(token, encoding='utf-8')
                try:
                    os.chmod(self.directory / 'setup-token', 0o600)
                except OSError:
                    pass
                self._set('setup_hash', hashlib.sha256(token.encode()).hexdigest())
            if not self._setting('user_id'):
                self._set('user_id', b64(secrets.token_bytes(32)))
            if seed:
                self._seed()
        with self.lock,self.db:
            self.db.executescript('CREATE TABLE IF NOT EXISTS albums(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE); CREATE TABLE IF NOT EXISTS album_items(album_id TEXT NOT NULL,asset_id INTEGER NOT NULL,PRIMARY KEY(album_id,asset_id)); CREATE TABLE IF NOT EXISTS shared_items(ref TEXT PRIMARY KEY,asset_id INTEGER NOT NULL);')
            if 'cover_id' not in [row[1] for row in self.db.execute('PRAGMA table_info(albums)')]:
                self.db.execute('ALTER TABLE albums ADD COLUMN cover_id INTEGER')
            if 'favorite' not in [row[1] for row in self.db.execute('PRAGMA table_info(assets)')]:
                self.db.execute('ALTER TABLE assets ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0')
            if 'origin' not in [row[1] for row in self.db.execute('PRAGMA table_info(challenges)')]:
                self.db.execute('ALTER TABLE challenges ADD COLUMN origin TEXT')
        with self.lock,self.db:self.db.execute('CREATE TABLE IF NOT EXISTS asset_edits(asset_id INTEGER PRIMARY KEY,recipe TEXT NOT NULL,original TEXT NOT NULL,preview TEXT NOT NULL,metadata TEXT NOT NULL,revision INTEGER NOT NULL)')
        self.expire()

    def usage(self):
        with self.operation_lock:
            return sum(path.stat().st_size for directory in (self.media,self.directory/'incoming') if directory.is_dir() for path in directory.iterdir() if path.is_file())

    def check_quota(self,additional=0):
        if getattr(self,'retired',False):raise VaultError('Пользователь удалён.',401)
        if self.quota_bytes and self.usage()+additional>self.quota_bytes:
            raise VaultError('Недостаточно места: достигнут лимит аккаунта.',413)

    def albums(self):
        with self.lock:
            result=[]
            for row in self.db.execute('SELECT * FROM albums ORDER BY rowid'):
                indices=[r[0] for r in self.db.execute("SELECT i.asset_id FROM album_items i JOIN assets a ON a.id=i.asset_id WHERE i.album_id=? AND a.state='public' ORDER BY a.id",(row['id'],))]
                result.append(dict(id=row['id'],name=row['name'],indices=indices,cover=row['cover_id'] if row['cover_id'] in indices else next(iter(indices),None)))
            return result

    def album_action(self,body,token):
        action=body.get('action');album_id=body.get('id')
        with self.lock,self.db:
            if action=='system-cover':
                name=body.get('name');index=body.get('index')
                if name != 'Избранное':raise VaultError('Альбом недоступен.',404)
                row=self.db.execute("SELECT favorite FROM assets WHERE id=? AND state='public'",(index,)).fetchone() if type(index) is int else None
                if not row or (name=='Избранное' and not row[0]):raise VaultError('Выбери фотографию из этого альбома.',404)
                self._set('cover:'+name,str(index))
            elif action=='create':
                name=body.get('name')
                if not isinstance(name,str) or not 1<=len(name.strip())<=80 or name.strip() in ('Недавние','Избранное','Видео','Скрытые','Недавно удалённые'):raise VaultError('Укажи другое название альбома — до 80 символов.')
                if self.db.execute('SELECT 1 FROM albums WHERE name=?',(name.strip(),)).fetchone():raise VaultError('Альбом с таким именем уже есть.',409)
                album_id=secrets.token_hex(16);self.db.execute('INSERT INTO albums(id,name) VALUES(?,?)',(album_id,name.strip()))
            elif action in ('add','remove','delete','cover'):
                if not self.db.execute('SELECT 1 FROM albums WHERE id=?',(album_id,)).fetchone():raise VaultError('Альбом не найден.',404)
                if action=='cover':
                    index=body.get('index')
                    if type(index) is not int or not self.db.execute("SELECT 1 FROM album_items i JOIN assets a ON a.id=i.asset_id WHERE i.album_id=? AND a.id=? AND a.state='public'",(album_id,index)).fetchone():raise VaultError('Выбери доступную фотографию из этого альбома.',404)
                    self.db.execute('UPDATE albums SET cover_id=? WHERE id=?',(index,album_id))
                elif action=='delete':
                    self.db.execute('DELETE FROM albums WHERE id=?',(album_id,));self.db.execute('DELETE FROM album_items WHERE album_id=?',(album_id,))
                else:
                    indices=body.get('indices')
                    if not isinstance(indices,list) or len(indices)>5000 or any(type(i) is not int for i in indices):raise VaultError('Неверный список файлов.')
                    for index in indices:
                        row=self.db.execute('SELECT state FROM assets WHERE id=?',(index,)).fetchone()
                        if not row or row[0] in ('purged','shared'):raise VaultError('Файл недоступен.',404)
                        if row[0]!='public':self.require(token)
                    for index in indices:
                        if action=='add':self.db.execute('INSERT OR IGNORE INTO album_items VALUES(?,?)',(album_id,index))
                        else:
                            self.db.execute('DELETE FROM album_items WHERE album_id=? AND asset_id=?',(album_id,index))
                            self.db.execute('UPDATE albums SET cover_id=NULL WHERE id=? AND cover_id=?',(album_id,index))
            else:raise VaultError('Неизвестное действие.')
        return dict(id=album_id)

    def favorite(self,indices,value,token):
        if not isinstance(indices,list) or len(indices)>5000 or any(type(i) is not int for i in indices):raise VaultError('Неверный список файлов.')
        with self.lock,self.db:
            for index in indices:
                row=self.db.execute('SELECT state FROM assets WHERE id=?',(index,)).fetchone()
                if not row or row[0] in ('purged','shared'):raise VaultError('Файл недоступен.',404)
                if row[0]!='public':self.require(token)
            self.db.executemany('UPDATE assets SET favorite=? WHERE id=?',[(int(bool(value)),i) for i in indices])

    def _setting(self, key):
        with self.lock:
            row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            return row[0] if row else None

    def _set(self, key, value):
        with self.lock:
            self.db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))

    @property
    def configured(self):
        return bool(self._setting('pin_hash'))

    def _seed(self):
        if self._setting('real_library')=='1' or self.db.execute('SELECT 1 FROM assets LIMIT 1').fetchone():
            return
        source = (self.root / 'app.js').read_text(encoding='utf-8')
        declaration = re.search(r'(?:const baseIds|const ids)=\[([^\]]+)\]', source)
        keys = [int(value) if value.isdigit() else value.strip("'") for value in re.findall(r"\d+|'video'|'vertical'", declaration[1])]
        metadata_source = (self.root / 'metadata-data.js').read_text(encoding='utf-8')
        catalogue = json.loads(metadata_source.split('=', 1)[1].strip().rstrip(';'))
        for index, key in enumerate(keys):
            video = key in ('video', 'vertical')
            original = 'assets/demo-vertical.mp4' if key == 'vertical' else 'assets/demo-video.mp4' if key == 'video' else f'assets/{key}.jpg'
            preview = 'assets/video-vertical.jpg' if key == 'vertical' else 'assets/video-poster.jpg' if key == 'video' else original
            original_name = f'{index}-original' + Path(original).suffix
            preview_name = f'{index}-preview.jpg' if video else original_name
            shutil.copyfile(self.root / original, self.media / original_name)
            if video:
                shutil.copyfile(self.root / preview, self.media / preview_name)
            self.db.execute('INSERT INTO assets(id,media_key,kind,original,preview,legacy_original,legacy_preview,metadata) VALUES(?,?,?,?,?,?,?,?)',
                            (index, json.dumps(key), 'video' if video else 'photo', original_name, preview_name, original, preview, json.dumps(catalogue.get(original, {}))))

    def authenticated(self, token):
        if self._setting('protection_disabled')=='1':return True
        if not token:
            return False
        with self.lock:
            row = self.db.execute('SELECT expires FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            return bool(row and row[0] > time.time())

    def require(self, token):
        if not self.authenticated(token):
            raise VaultError('Требуется код-пароль или ключ доступа.', 401)

    def session(self):
        token = secrets.token_urlsafe(32)
        self.db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
        self.db.execute('INSERT INTO sessions VALUES(?,?)', (hashlib.sha256(token.encode()).hexdigest(), time.time() + SESSION_SECONDS))
        return token

    def status(self, token):
        with self.lock:
            return dict(ownerRegistered=bool(self._setting('account_hash')), configured=self.configured, authenticated=self.authenticated(token), passkey=bool(self.db.execute('SELECT 1 FROM credentials LIMIT 1').fetchone()),protectionEnabled=self._setting('protection_disabled')!='1',concealHidden=self._setting('conceal_hidden')=='1')

    def setup(self, token, pin, account_authorized=False):
        with self.lock, self.db:
            if self.configured:
                raise VaultError('Код-пароль уже настроен.', 409)
            expected = self._setting('setup_hash') or ''
            if not account_authorized and (not isinstance(token, str) or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected)):
                raise VaultError('Нужна одноразовая ссылка настройки.', 403)
            if not isinstance(pin, str) or not re.fullmatch(r'\d{6,12}', pin, flags=re.ASCII):
                raise VaultError('Код-пароль должен содержать от 6 до 12 цифр.')
            salt = secrets.token_bytes(24)
            self._set('protection_disabled','0')
            self._set('pin_salt', b64(salt))
            self._set('pin_hash', b64(hashlib.pbkdf2_hmac('sha256', pin.encode(), salt, 600000)))
            self.db.execute("DELETE FROM settings WHERE key='setup_hash'")
            (self.directory / 'setup-token').unlink(missing_ok=True)
            return self.session()

    def unlock(self, pin):
        with self.lock, self.db:
            if not self.configured:
                raise VaultError('Сначала настрой код-пароль по одноразовой ссылке.', 409)
            failures, blocked = self.db.execute('SELECT failures,blocked_until FROM attempts WHERE id=1').fetchone()
            now = time.time()
            if blocked > now:
                raise VaultError(f'Попробуй через {int(blocked - now) + 1} сек.', 429)
            candidate = hashlib.pbkdf2_hmac('sha256', str(pin)[:100].encode(), unb64(self._setting('pin_salt')), 600000)
            if not hmac.compare_digest(candidate, unb64(self._setting('pin_hash'))):
                failures += 1
                cooldown = min(900, 30 * 2 ** min(5, (failures - 5) // 5)) if failures >= 5 else 0
                self.db.execute('UPDATE attempts SET failures=?,blocked_until=? WHERE id=1', (failures, now + cooldown))
                # Keep failed attempts even though the caller receives an error.
                self.db.commit()
                raise VaultError('Неверный код-пароль.', 401)
            self.db.execute('UPDATE attempts SET failures=0,blocked_until=0 WHERE id=1')
            return self.session()

    def remove_protection(self,passkey_only=False):
        with self.operation_lock,self.lock,self.db:
            self.db.execute('PRAGMA secure_delete=ON')
            for table in ('credentials','challenges','sessions'):self.db.execute('DELETE FROM '+table)
            if passkey_only:return self.session() if self.configured else ''
            self.db.execute("DELETE FROM settings WHERE key IN ('pin_hash','pin_salt','setup_hash')")
            self.db.execute('UPDATE attempts SET failures=0,blocked_until=0 WHERE id=1')
            self._set('protection_disabled','1')
            return ''

    def conceal_hidden(self,value):
        if type(value) is not bool:raise VaultError('Некорректная настройка.')
        with self.lock,self.db:self._set('conceal_hidden','1' if value else '0')

    def sign_out(self, token):
        with self.lock, self.db:
            self.db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256((token or '').encode()).hexdigest(),))

    def asset_metadata(self,row):
        metadata=json.loads(row['metadata'])
        if row['kind']=='video' and not metadata.get('addedAt'):
            source=self.media/row['original']
            if source.is_file():metadata['addedAt']=datetime.fromtimestamp(source.stat().st_mtime,timezone.utc).isoformat()
        return metadata

    @staticmethod
    def display_metadata(source,rendered):
        result={**source,**rendered}
        for field in ('takenAt','addedAt','dateChecked'):
            if field in source:result[field]=source[field]
            else:result.pop(field,None)
        return result

    def library(self, token):
        self.expire()
        authorized = self.authenticated(token)
        with self.lock:
            result = []
            for row in self.db.execute('SELECT * FROM assets ORDER BY id'):
                item = dict(id=row['id'], key=json.loads(row['media_key']), kind=row['kind'], state=row['state'] if authorized or row['state'] in ('public','purged') else 'locked')
                if row['state'] != 'purged' and (authorized or row['state'] == 'public'):
                    item.update(favorite=bool(row['favorite']), metadata=self.asset_metadata(row), deletedAt=row['deleted_at'] * 1000 if row['deleted_at'] is not None else None)
                    edit=self.db.execute('SELECT * FROM asset_edits WHERE asset_id=?',(row['id'],)).fetchone()
                    if edit:item.update(metadata=self.display_metadata(item['metadata'],json.loads(edit['metadata'])),edit=json.loads(edit['recipe']),revision=edit['revision'])
                result.append(item)
            latest=self.db.execute("SELECT id FROM assets WHERE state='public' ORDER BY id DESC LIMIT 1").fetchone()
            covers={'Недавние':latest['id']} if latest else {}
            for name in ('Избранное',):
                value=self._setting('cover:'+name)
                row=self.db.execute("SELECT id,favorite FROM assets WHERE id=? AND state='public'",(value,)).fetchone() if value is not None else None
                if row and (name!='Избранное' or row['favorite']):covers[name]=row['id']
            return dict(items=result, vault=self.status(token), collectionCovers=covers)

    def media_path(self, index, preview, token, source=False):
        self.expire()
        with self.lock:
            row = self.db.execute('SELECT * FROM assets WHERE id=?', (index,)).fetchone()
            if not row or row['state'] == 'purged':
                raise VaultError('Файл удалён.', 404)
            if row['state'] != 'public':
                self.require(token)
            edited=None if source else self.db.execute('SELECT * FROM asset_edits WHERE asset_id=?',(index,)).fetchone()
            path = self.media / (edited or row)['preview' if preview else 'original']
            if not path.is_file():
                raise VaultError('Файл не найден.', 404)
            return path

    def legacy_index(self, relative):
        with self.lock:
            row = self.db.execute('SELECT id FROM assets WHERE legacy_original=? OR legacy_preview=? LIMIT 1', (relative, relative)).fetchone()
            return row['id'] if row else None

    def mutate(self, action, indices, token, account_authorized=False):
        with self.operation_lock:
            return self._mutate(action,indices,token,account_authorized)

    def _mutate(self, action, indices, token, account_authorized=False):
        if not account_authorized:self.require(token)
        if not isinstance(indices, list) or not indices or len(indices) > 5000 or any(type(i) is not int for i in indices):
            raise VaultError('Неверный список файлов.')
        if action not in ('hide', 'unhide', 'trash', 'restore', 'purge', 'duplicate'):
            raise VaultError('Неизвестное действие.')
        with self.lock, self.db:
            rows = []
            for index in dict.fromkeys(indices):
                row = self.db.execute('SELECT * FROM assets WHERE id=?', (index,)).fetchone()
                if not row or row['state'] in ('purged','shared'):
                    raise VaultError('Файл недоступен.', 404)
                if row['state']!='public':self.require(token)
                if action in ('restore', 'purge') and row['state'] != 'trash':
                    raise VaultError('Файл не находится в удалённых.', 409)
                rows.append(row)
            if action=='duplicate':
                self.check_quota(sum(sum((self.media/name).stat().st_size for name in set((row['original'],row['preview']))) for row in rows))
            for row in rows:
                index = row['id']
                if action == 'trash' and row['state'] != 'trash':
                    self.db.execute("UPDATE assets SET previous_state=state,state='trash',deleted_at=? WHERE id=?", (time.time(), index))
                elif action == 'restore':
                    self.db.execute('UPDATE assets SET state=previous_state,deleted_at=NULL WHERE id=?', (index,))
                elif action == 'hide' and row['state'] != 'trash':
                    self.db.execute("UPDATE assets SET state='hidden' WHERE id=?", (index,))
                elif action == 'unhide' and row['state'] != 'trash':
                    self.db.execute("UPDATE assets SET state='public' WHERE id=?", (index,))
                elif action == 'purge':
                    self._purge(row)
                elif action == 'duplicate':
                    new_index = self.db.execute('SELECT COALESCE(MAX(id),-1)+1 FROM assets').fetchone()[0]
                    displayed=self.media_path(index,False,token)
                    original = f'{new_index}-original' + displayed.suffix
                    preview = f'{new_index}-preview.jpg' if row['kind'] == 'video' else original
                    shutil.copyfile(displayed, self.media / original)
                    if preview != original:
                        shutil.copyfile(self.media_path(index,True,token), self.media / preview)
                    self.db.execute('INSERT INTO assets(id,media_key,kind,original,preview,metadata,state) VALUES(?,?,?,?,?,?,?)',
                                    (new_index, row['media_key'], row['kind'], original, preview, json.dumps({**json.loads(row['metadata']),**json.loads((self.db.execute('SELECT metadata FROM asset_edits WHERE asset_id=?',(index,)).fetchone() or ['{}'])[0])}), 'hidden' if row['state'] == 'hidden' else 'public'))
        return self.library(token)

    def _purge(self, row):
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.execute('DELETE FROM people_faces WHERE asset_id=?',(row['id'],))
        self.db.execute('DELETE FROM people_scans WHERE asset_id=?',(row['id'],))
        self.db.execute('DELETE FROM people WHERE excluded=0 AND id NOT IN (SELECT person_id FROM people_faces)')
        edit=self.db.execute('SELECT * FROM asset_edits WHERE asset_id=?',(row['id'],)).fetchone()
        if edit:
            for key in ('original','preview'):(self.media/edit[key]).unlink(missing_ok=True)
            self.db.execute('DELETE FROM asset_edits WHERE asset_id=?',(row['id'],))
        for name in set((row['original'], row['preview'])):
            (self.media / name).unlink(missing_ok=True)
        self.db.execute("UPDATE assets SET state='purged',metadata='{}',previous_state='public',deleted_at=NULL WHERE id=?", (row['id'],))

    def expire(self, now=None):
        with self.operation_lock, self.lock, self.db:
            for row in self.db.execute("SELECT * FROM assets WHERE state='trash' AND deleted_at<=?", ((time.time() if now is None else now) - RETENTION,)).fetchall():
                self._purge(row)

    def passkey_options(self, registration, token, origin=None):
        origin=origin or self.origin
        rp_id=urlsplit(origin).hostname
        from webauthn import generate_registration_options, generate_authentication_options
        from webauthn.helpers import options_to_json
        from webauthn.helpers.structs import AuthenticatorSelectionCriteria, AuthenticatorAttachment, ResidentKeyRequirement, UserVerificationRequirement, PublicKeyCredentialDescriptor
        with self.lock, self.db:
            if registration:
                self.require(token)
                options = generate_registration_options(rp_id=rp_id, rp_name='Фото', user_id=unb64(self._setting('user_id')), user_name=getattr(self,'account_login','owner'), user_display_name=getattr(self,'account_name','Мой аккаунт'),
                    authenticator_selection=AuthenticatorSelectionCriteria(authenticator_attachment=AuthenticatorAttachment.PLATFORM, resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED),
                    exclude_credentials=[PublicKeyCredentialDescriptor(id=unb64(row['id'])) for row in self.db.execute('SELECT id FROM credentials')])
            else:
                credentials = self.db.execute('SELECT id FROM credentials').fetchall()
                if not credentials:
                    raise VaultError('Ключ доступа ещё не подключён.', 409)
                options = generate_authentication_options(rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED, allow_credentials=[PublicKeyCredentialDescriptor(id=unb64(row['id'])) for row in credentials])
            challenge_id = secrets.token_urlsafe(24)
            self.db.execute('DELETE FROM challenges WHERE expires<?', (time.time(),))
            self.db.execute('INSERT INTO challenges(id,kind,value,owner,expires,origin) VALUES(?,?,?,?,?,?)', (challenge_id, 'register' if registration else 'login', b64(options.challenge), hashlib.sha256(token.encode()).hexdigest() if registration else None, time.time() + 120,origin))
            return dict(challengeId=challenge_id, publicKey=json.loads(options_to_json(options)))

    def passkey_verify(self, registration, challenge_id, credential, token):
        from webauthn import verify_registration_response, verify_authentication_response
        with self.lock, self.db:
            row = self.db.execute('SELECT * FROM challenges WHERE id=?', (challenge_id,)).fetchone()
            if not row:
                raise VaultError('Проверка истекла. Повтори вход.', 401)
            self.db.execute('DELETE FROM challenges WHERE id=?', (challenge_id,))
            self.db.commit()  # Challenges are one-use even when verification fails.
            if row['expires'] < time.time() or row['kind'] != ('register' if registration else 'login'):
                raise VaultError('Проверка истекла. Повтори вход.', 401)
            if registration:
                self.require(token)
                if not hmac.compare_digest(row['owner'], hashlib.sha256(token.encode()).hexdigest()):
                    raise VaultError('Сеанс изменился.', 401)
            try:
                if registration:
                    verified = verify_registration_response(credential=credential, expected_challenge=unb64(row['value']), expected_origin=row['origin'] or self.origin, expected_rp_id=urlsplit(row['origin'] or self.origin).hostname, require_user_verification=True)
                    self.db.execute('INSERT INTO credentials VALUES(?,?,?)', (b64(verified.credential_id), b64(verified.credential_public_key), verified.sign_count))
                    return None
                if not isinstance(credential, dict):
                    raise ValueError()
                saved = self.db.execute('SELECT * FROM credentials WHERE id=?', (credential.get('id'),)).fetchone()
                if not saved:
                    raise ValueError()
                verified = verify_authentication_response(credential=credential, expected_challenge=unb64(row['value']), expected_origin=row['origin'] or self.origin, expected_rp_id=urlsplit(row['origin'] or self.origin).hostname,
                    credential_public_key=unb64(saved['public_key']), credential_current_sign_count=saved['sign_count'], require_user_verification=True)
                self.db.execute('UPDATE credentials SET sign_count=? WHERE id=?', (verified.new_sign_count, saved['id']))
                return self.session()
            except Exception as error:
                raise VaultError('Не удалось подтвердить ключ доступа.', 401) from error
