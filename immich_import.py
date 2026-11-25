"""Explicit per-user Immich copy job. The source receives only GET and read-only search POST."""
import hashlib
import http.client
import ipaddress
import json
from pathlib import Path
import re
import secrets
import shutil
import socket
import ssl
import tempfile
import threading
from urllib.parse import urlsplit, unquote
from vault import VaultError
from accounts import PHOTO_EXT, VIDEO_EXT


class Remote:
    def __init__(self,url,key):
        try:
            parsed=urlsplit(url.strip().rstrip('/'))
            if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError()
            if '..' in unquote(parsed.path).split('/') or '%' in parsed.path or not re.fullmatch(r'[/a-zA-Z0-9_.-]*',parsed.path):raise ValueError()
            self.host,self.port=parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80)
            self.addresses=list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(self.host,self.port,type=socket.SOCK_STREAM)))
            if not self.addresses:raise ValueError()
            for address in self.addresses:
                ip=ipaddress.ip_address(address)
                ip=getattr(ip,'ipv4_mapped',None) or ip
                if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:raise ValueError()
                if parsed.scheme=='http' and not ip.is_private:raise ValueError()
        except (ValueError,OSError):raise VaultError('Укажи HTTPS-адрес Immich или HTTP-адрес в домашней сети.')
        if not isinstance(key,str) or not 8<=len(key)<=4096 or any(ord(c)<33 or ord(c)>126 for c in key):raise VaultError('Укажи API-ключ Immich.')
        self.url=parsed.geturl();self.scheme=parsed.scheme;self.key=key
        self.prefix=parsed.path.rstrip('/')
        if not self.prefix.endswith('/api'):self.prefix+='/api'
        # Normalize /api and trailing slashes so a resumed import reuses its map.
        self.url=f'{parsed.scheme}://{parsed.netloc}{self.prefix}'

    def request(self,path,body=None):
        conn=http.client.HTTPConnection(self.host,self.port,timeout=45)
        # Pin validated DNS result; never follow redirects or forward the API key.
        conn.sock=socket.create_connection((self.addresses[0],self.port),timeout=45)
        if self.scheme=='https':conn.sock=ssl.create_default_context().wrap_socket(conn.sock,server_hostname=self.host)
        headers={'x-api-key':self.key,'Accept':'application/json'}
        data=json.dumps(body).encode() if body is not None else None
        if data is not None:headers['Content-Type']='application/json'
        try:
            conn.request('POST' if body is not None else 'GET',self.prefix+path,body=data,headers=headers)
            response=conn.getresponse()
            if response.status!=200:
                code=response.status;response.close();conn.close()
                if code in (401,403):raise VaultError('Immich отклонил ключ. Проверь права asset.read, asset.download, album.read и user.read.',403)
                raise VaultError('Immich не смог выполнить запрос. Проверь адрес и совместимость API.',502)
            return conn,response
        except Exception:
            conn.close();raise

    def json(self,path,body=None):
        conn,response=self.request(path,body)
        try:
            raw=response.read(16*1024**2+1)
            if len(raw)>16*1024**2:raise VaultError('Слишком большой ответ Immich.',502)
            return json.loads(raw)
        finally:response.close();conn.close()


class ImmichImport:
    def __init__(self,accounts,user_id,vault,importer):
        self.accounts,self.user_id,self.v,self.importer=accounts,user_id,vault,importer
        self.lock=threading.RLock();self.cancel=threading.Event()
        previous=self.status()
        if previous.get('state') in ('running','stopping'):
            self.progress(state='interrupted',error='Сервер перезапустился. Введи API-ключ ещё раз, чтобы продолжить без повторных копий.')

    def status(self):
        with self.v.lock:return json.loads(self.v._setting('immich_job') or '{}')

    def progress(self,**changes):
        with self.v.lock,self.v.db:
            if getattr(self.v,'retired',False):return {}
            state=self.status();state.update(changes);self.v._set('immich_job',json.dumps(state));return state

    def active(self):
        if self.cancel.is_set():raise InterruptedError()
        with self.accounts.control.lock:
            row=self.accounts.control.db.execute('SELECT disabled FROM users WHERE id=?',(self.user_id,)).fetchone()
        if not row or row['disabled'] or getattr(self.v,'retired',False):raise InterruptedError()

    def start(self,body):
        with self.v.operation_lock,self.lock:
            self.v.check_quota()
            if self.status().get('state') in ('running','stopping'):raise VaultError('Импорт уже выполняется.',409)
            # Validation and DNS happen in the worker so the UI gets a job immediately.
            url,key=body.get('url'),body.get('key')
            if not isinstance(url,str) or len(url)>2048 or not isinstance(key,str):raise VaultError('Укажи адрес и API-ключ Immich.')
            retry_ids=body.get('retryIds');previous=self.status();retry_source=previous.get('url');retry_owner=previous.get('owner')
            if retry_ids is not None:
                allowed={item.get('id') for item in previous.get('issues',[]) if item.get('retryable') and item.get('id')}
                if not isinstance(retry_ids,list) or not retry_ids or any(not isinstance(uid,str) or uid not in allowed for uid in retry_ids):raise VaultError('Список файлов для повтора устарел.')
            self.cancel.clear();state=self.progress(state='running',stage='Подключение',url='',added=0,reused=0,skipped=0,failed=0,total=None,processed=0,issues=[],albums=0,error='',current='')
            threading.Thread(target=self.run,args=(url,key,bool(body.get('albums',True)),retry_ids,retry_source,retry_owner),daemon=True).start()
            return state

    def stop(self):
        with self.lock:
            if self.status().get('state')=='running':self.cancel.set();return self.progress(state='stopping')
            return self.status()

    def search(self,remote,album=None):
        page=1;seen=set();cursor=None;cursors=set()
        while True:
            self.active();body=dict(size=200,page=page,withExif=True,visibility='timeline')
            if cursor:body.pop('page');body['cursor']=cursor
            if album:body['albumIds']=[album]
            result=remote.json('/search/metadata',body)['assets'];items=result.get('items',[])
            if not isinstance(items,list):raise VaultError('Неожиданный ответ поиска Immich.',502)
            for asset in items:
                uid=asset.get('id')
                if uid in seen:continue
                seen.add(uid);yield asset
            next_cursor=result.get('nextCursor')
            if next_cursor:
                if not isinstance(next_cursor,str) or len(next_cursor)>8192 or next_cursor in cursors:raise VaultError('Immich вернул повторный курсор.',502)
                cursors.add(next_cursor);cursor=next_cursor;page+=1
                if page>100000:raise VaultError('Слишком много страниц импорта.')
                continue
            next_page=result.get('nextPage')
            if not next_page:break
            if not str(next_page).isdigit() or int(next_page)<=page:raise VaultError('Immich вернул неподдерживаемую пагинацию.',502)
            page=int(next_page)
            if page>100000:raise VaultError('Слишком много страниц импорта.')

    def download(self,remote,source,asset):
        uid=asset['id'];name=Path(str(asset.get('originalFileName','')).replace('\\','/')).name[:255]
        if not re.fullmatch(r'[a-zA-Z0-9-]{1,80}',uid):raise VaultError('Некорректный ID файла Immich.',502)
        suffix=Path(name).suffix.lower()
        if suffix not in PHOTO_EXT|VIDEO_EXT:return None
        conn,response=remote.request('/assets/'+uid+'/original')
        target=None;path=None
        try:
            size=int(response.getheader('Content-Length') or 0)
            if size<0 or size>10*1024**3:raise VaultError('Файл Immich превышает 10 ГБ.',413)
            with self.v.operation_lock:
                self.active();self.v.check_quota(size)
                if shutil.disk_usage(self.v.directory).free<size+250*1024**2:raise VaultError('На сервере недостаточно места.',413)
                incoming=self.v.directory/'incoming';incoming.mkdir(exist_ok=True)
                target=tempfile.NamedTemporaryFile(dir=incoming,suffix=suffix,delete=False);path=Path(target.name)
                if size:target.truncate(size)
            received=0
            while True:
                self.active();chunk=response.read(1024**2)
                if not chunk:break
                received+=len(chunk)
                if received>10*1024**3 or (size and received>size):raise VaultError('Некорректный размер файла Immich.',413)
                with self.v.operation_lock:
                    self.v.check_quota(0 if size else len(chunk));target.write(chunk)
            if not received or (size and received!=size):raise VaultError('Файл Immich передан не полностью.',502)
            target.flush();target.close();self.active()
            index=self.importer.ingest(path,name,consume=True,external=(source,uid))
            with self.v.operation_lock,self.v.lock,self.v.db:
                self.v.check_quota();row=self.v.db.execute('SELECT metadata FROM assets WHERE id=?',(index,)).fetchone()
                metadata=json.loads(row[0]);metadata['takenAt']=asset.get('fileCreatedAt') or metadata.get('takenAt')
                self.v.db.execute('UPDATE assets SET metadata=?,favorite=? WHERE id=?',(json.dumps(metadata),int(bool(asset.get('isFavorite'))),index))
            return index
        finally:
            response.close();conn.close()
            if target:target.close()
            if path:
                with self.v.operation_lock:path.unlink(missing_ok=True)

    def run(self,url,key,with_albums,retry_ids=None,retry_source=None,retry_owner=None):
        remote=None
        try:
            remote=Remote(url,key);
            if retry_ids is not None and remote.url!=retry_source:raise VaultError('Для повтора укажи тот же адрес Immich.')
            me=remote.json('/users/me');owner=me['id']
            if retry_ids is not None and owner!=retry_owner:raise VaultError('Для повтора используй ключ того же аккаунта Immich.')
            source=hashlib.sha256((remote.url+'|'+owner).encode()).hexdigest();self.progress(url=remote.url,owner=owner,stage='Фотографии')
            added=reused=skipped=failed=albums=processed=0;issues=[]
            self.progress(stage='Подсчёт фотографий',total=None,processed=0)
            wanted=set(retry_ids) if retry_ids is not None else None
            total=sum(1 for item in self.search(remote) if wanted is None or item.get('id') in wanted);self.progress(stage='Фотографии',total=total)
            for asset in self.search(remote):
                self.active();uid=asset.get('id');
                if wanted is not None and uid not in wanted:continue
                asset_owner=asset.get('ownerId') or (asset.get('owner') or {}).get('id');name=Path(str(asset.get('originalFileName') or 'Без названия').replace('\\','/')).name[:255]
                reason=None
                if asset_owner!=owner:reason='Файл другого пользователя'
                elif asset.get('isTrashed'):reason='Файл удалён в Immich'
                elif asset.get('isArchived') or asset.get('visibility','timeline')!='timeline':reason='Скрыт или находится в архиве Immich'
                if reason:skipped+=1
                else:
                    with self.v.lock:known=self.v.db.execute('SELECT asset_id FROM external_assets WHERE source=? AND remote_id=?',(source,uid)).fetchone()
                    if known:reused+=1
                    else:
                        self.progress(current=name)
                        try:
                            if self.download(remote,source,asset) is None:skipped+=1;reason='Этот формат пока не поддерживается'
                            else:added+=1
                        except InterruptedError:raise
                        except VaultError as error:
                            failed+=1;reason=error.message
                            if error.status==413:
                                issues.append(dict(id=uid,name=name,reason=reason,retryable=True));self.progress(failed=failed,issues=issues,processed=processed,total=total);raise
                        except Exception:failed+=1;reason='Не удалось загрузить файл. Попробуй ещё раз.'
                if reason and len(issues)<200:issues.append(dict(id=uid,name=name,reason=reason,retryable=not (asset_owner!=owner or asset.get('isTrashed') or asset.get('isArchived') or asset.get('visibility','timeline')!='timeline')))
                processed+=1;self.progress(added=added,reused=reused,skipped=skipped,failed=failed,processed=processed,total=total,issues=issues)
            if with_albums:
                self.progress(stage='Альбомы',current='')
                for album in remote.json('/albums'):
                    self.active();album_owner=album.get('ownerId') or next((item.get('user',{}).get('id') for item in album.get('albumUsers',[]) if item.get('role')=='owner'),None)
                    if album_owner!=owner:continue
                    indices=[]
                    for asset in self.search(remote,album['id']):
                        with self.v.lock:row=self.v.db.execute("SELECT e.asset_id FROM external_assets e JOIN assets a ON e.asset_id=a.id WHERE e.source=? AND e.remote_id=? AND a.state='public'",(source,asset.get('id'))).fetchone()
                        if row:indices.append(row[0])
                    with self.v.operation_lock,self.v.lock,self.v.db:
                        self.active();mapped=self.v.db.execute('SELECT album_id FROM external_albums WHERE source=? AND remote_id=?',(source,album['id'])).fetchone()
                        local=mapped[0] if mapped else None
                        if not local or not self.v.db.execute('SELECT 1 FROM albums WHERE id=?',(local,)).fetchone():
                            name=str(album.get('albumName') or 'Альбом Immich')[:70];candidate=name;number=2
                            while self.v.db.execute('SELECT 1 FROM albums WHERE name=?',(candidate,)).fetchone():candidate=f'{name} ({number})';number+=1
                            local=secrets.token_hex(16);self.v.db.execute('INSERT INTO albums(id,name) VALUES(?,?)',(local,candidate));self.v.db.execute('INSERT OR REPLACE INTO external_albums VALUES(?,?,?)',(source,album['id'],local))
                        self.v.db.executemany('INSERT OR IGNORE INTO album_items VALUES(?,?)',[(local,index) for index in indices])
                    albums+=1;self.progress(albums=albums)
            self.progress(state='complete',stage='Готово',current='',total=processed)
        except InterruptedError:
            if not getattr(self.v,'retired',False):self.progress(state='cancelled',stage='Остановлено',current='')
        except VaultError as error:
            if not getattr(self.v,'retired',False):self.progress(state='failed',error=error.message,current='')
        except Exception:
            if not getattr(self.v,'retired',False):self.progress(state='failed',error='Не удалось завершить импорт. Проверь доступность Immich и повтори с тем же адресом — уже скопированные файлы не повторятся.',current='')
        finally:
            if remote:remote.key=''
            key=''
