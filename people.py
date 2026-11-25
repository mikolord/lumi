"""Account-local people index. Only public, owned photos participate."""
from io import BytesIO
import json
import math
import os
import secrets
import threading
import time
import urllib.request
import urllib.error
from PIL import Image
from vault import VaultError

MODEL = 'yunet2023-sface2021-v1'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS people(id TEXT PRIMARY KEY,name TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS people_faces(id TEXT PRIMARY KEY,person_id TEXT NOT NULL,asset_id INTEGER NOT NULL,box TEXT NOT NULL,vector TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS people_faces_person ON people_faces(person_id);
CREATE INDEX IF NOT EXISTS people_faces_asset ON people_faces(asset_id);
CREATE TABLE IF NOT EXISTS people_scans(asset_id INTEGER PRIMARY KEY,model TEXT NOT NULL,error TEXT NOT NULL DEFAULT '');
'''


def normalize(vector):
    if not isinstance(vector,list) or len(vector)!=128 or any(type(x) not in (int,float) or not math.isfinite(x) for x in vector):
        raise ValueError('Invalid face vector')
    length=math.sqrt(sum(x*x for x in vector))
    if not .00001<length<1e10:raise ValueError('Invalid face vector')
    return [x/length for x in vector]


def detect(image):
    url=os.environ.get('PHOTO_FACE_URL','').rstrip('/')
    token=os.environ.get('PHOTO_FACE_TOKEN','')
    if not url or not token:raise VaultError('Сервис распознавания ещё не подключён.',503)
    request=urllib.request.Request(url+'/detect',data=image,headers={'Content-Type':'image/jpeg','Authorization':'Bearer '+token})
    # No redirects: the service URL is administrator-controlled, not user input.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect).open(request,timeout=40) as response:
        raw=response.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError('Face response too large')
        result=json.loads(raw)
    faces=result.get('faces')
    if not isinstance(faces,list) or len(faces)>100:raise ValueError('Invalid face response')
    return faces


class People:
    def __init__(self,vault):self.v=vault

    def active(self):
        return not getattr(self.v,'retired',False) and self.v._setting('people_enabled')=='1' and self.v._setting('people_visible')!='0'

    def visible_person(self,pid):
        if not isinstance(pid,str):raise VaultError('Человек не найден.',404)
        row=self.v.db.execute("SELECT p.* FROM people p JOIN people_faces f ON f.person_id=p.id JOIN assets a ON a.id=f.asset_id WHERE p.id=? AND a.state='public' LIMIT 1",(pid,)).fetchone()
        if not row:raise VaultError('Человек не найден.',404)
        return row

    def status(self):
        v=self.v
        with v.lock:
            total=v.db.execute("SELECT COUNT(*) FROM assets WHERE state='public' AND kind='photo'").fetchone()[0]
            done=v.db.execute("SELECT COUNT(*) FROM people_scans s JOIN assets a ON a.id=s.asset_id WHERE a.state='public' AND a.kind='photo' AND s.model=?",(MODEL,)).fetchone()[0]
            failed=v.db.execute("SELECT COUNT(*) FROM people_scans s JOIN assets a ON a.id=s.asset_id WHERE a.state='public' AND s.error<>''").fetchone()[0]
            groups={}
            for row in v.db.execute("SELECT p.id,p.name,p.excluded,p.favorite,p.pinned,p.hidden,p.cover_face,f.id face,f.asset_id FROM people p JOIN people_faces f ON f.person_id=p.id JOIN assets a ON a.id=f.asset_id WHERE a.state='public' ORDER BY p.pinned DESC,p.favorite DESC,p.name COLLATE NOCASE,p.id,f.asset_id DESC"):
                item=groups.setdefault(row['id'],dict(id=row['id'],name=row['name'],excluded=bool(row['excluded']),favorite=bool(row['favorite']),pinned=bool(row['pinned']),hidden=bool(row['hidden']),cover=row['face'],indices=[]))
                if row['face']==row['cover_face']:item['cover']=row['face']
                if row['asset_id'] not in item['indices']:item['indices'].append(row['asset_id'])
            for row in v.db.execute("SELECT id,name FROM people WHERE excluded=1 AND id NOT IN (SELECT person_id FROM people_faces f JOIN assets a ON a.id=f.asset_id WHERE a.state='public')"):
                # No thumbnail or private photo identifiers are exposed for excluded templates.
                groups[row['id']]=dict(id=row['id'],name=row['name'],excluded=True,cover=None,indices=[])
            visible=v._setting('people_visible')
            return dict(visible=visible=='1' if visible is not None else bool(self.active() or groups),enabled=self.active(),available=bool(os.environ.get('PHOTO_FACE_URL') and os.environ.get('PHOTO_FACE_TOKEN')),total=total,done=done,failed=failed,error=v._setting('people_error') or '',people=[p for p in groups.values() if not p['excluded'] and not p.get('hidden')],hidden=[p for p in groups.values() if p.get('hidden') and not p['excluded']],excluded=[p for p in groups.values() if p['excluded']],processing=getattr(v,'people_processing',None))

    def detail(self,pid):
        with self.v.lock:
            person=self.visible_person(pid)
            faces=[dict(id=r['id'],index=r['asset_id']) for r in self.v.db.execute("SELECT f.id,f.asset_id FROM people_faces f JOIN assets a ON a.id=f.asset_id WHERE f.person_id=? AND a.state='public' ORDER BY f.asset_id DESC",(pid,))]
            cover=person['cover_face'] if person['cover_face'] in {f['id'] for f in faces} else faces[0]['id']
            return dict(id=pid,name=person['name'],excluded=bool(person['excluded']),favorite=bool(person['favorite']),pinned=bool(person['pinned']),hidden=bool(person['hidden']),cover=cover,faces=faces,indices=list(dict.fromkeys(f['index'] for f in faces)))

    def action(self,body):
        v=self.v;action=body.get('action')
        with v.operation_lock,v.lock,v.db:
            if getattr(v,'retired',False):raise VaultError('Пользователь удалён.',401)
            if action in ('enabled','visible'):
                value=body.get('value')
                if type(value) is not bool:raise VaultError('Некорректная настройка.')
                if value and not (os.environ.get('PHOTO_FACE_URL') and os.environ.get('PHOTO_FACE_TOKEN')):raise VaultError('Сервис распознавания ещё не подключён.',503)
                v._set('people_enabled','1' if value else '0');v._set('people_error','')
                if action=='visible':v._set('people_visible','1' if value else '0')
            elif action=='retry':
                v.db.execute("DELETE FROM people_scans WHERE error<>''");v._set('people_error','')
            elif action=='exclude':
                pid=body.get('id');value=body.get('value')
                if type(value) is not bool:raise VaultError('Некорректная настройка.')
                existing=v.db.execute('SELECT id FROM people WHERE id=? AND excluded=1',(pid,)).fetchone() if isinstance(pid,str) else None
                if not existing:self.visible_person(pid)
                vectors=[json.loads(row[0]) for row in v.db.execute("SELECT f.vector FROM people_faces f JOIN assets a ON a.id=f.asset_id WHERE f.person_id=? AND a.state='public'",(pid,))]
                template=normalize([sum(vec[i] for vec in vectors) for i in range(128)]) if vectors else None
                v.db.execute('UPDATE people SET excluded=?,ignore_vector=COALESCE(?,ignore_vector) WHERE id=?',(int(value),json.dumps(template) if template else None,pid))
            elif action=='preference':
                self.visible_person(body.get('id'));field=body.get('field');value=body.get('value')
                if field not in ('favorite','pinned','hidden') or type(value) is not bool:raise VaultError('Некорректная настройка.')
                v.db.execute('UPDATE people SET '+field+'=? WHERE id=?',(int(value),body['id']))
            elif action=='profile':
                self.visible_person(body.get('id'));name=body.get('name');cover=body.get('cover')
                if not isinstance(name,str) or len(name.strip())>80:raise VaultError('Имя — до 80 символов.')
                if not isinstance(cover,str) or not v.db.execute("SELECT 1 FROM people_faces f JOIN assets a ON a.id=f.asset_id WHERE f.id=? AND f.person_id=? AND a.state='public'",(cover,body['id'])).fetchone():raise VaultError('Выбери фотографию этого человека.',404)
                v.db.execute('UPDATE people SET name=?,cover_face=? WHERE id=?',(name.strip(),cover,body['id']))
            elif action=='rename':
                self.visible_person(body.get('id'));name=body.get('name')
                if not isinstance(name,str) or len(name.strip())>80:raise VaultError('Имя — до 80 символов.')
                v.db.execute('UPDATE people SET name=? WHERE id=?',(name.strip(),body['id']))
            elif action=='merge':
                source=body.get('id');target=body.get('target');before=self.visible_person(source);after=self.visible_person(target)
                if source==target:raise VaultError('Выбери другого человека.')
                v.db.execute('UPDATE people SET name=?,favorite=?,pinned=?,cover_face=? WHERE id=?',(after['name'] or before['name'],int(after['favorite'] or before['favorite']),int(after['pinned'] or before['pinned']),after['cover_face'] or before['cover_face'],target))
                v.db.execute('UPDATE people_faces SET person_id=? WHERE person_id=?',(target,source));v.db.execute('DELETE FROM people WHERE id=?',(source,))
            elif action=='merge-many':
                target=body.get('target');sources=body.get('sources');name=body.get('name')
                if not isinstance(sources,list) or not 1<=len(sources)<=3000 or not all(isinstance(pid,str) for pid in sources) or len(set(sources))!=len(sources) or target in sources:raise VaultError('Выбери карточки для объединения.')
                if not isinstance(name,str) or len(name.strip())>80:raise VaultError('Имя — до 80 символов.')
                after=self.visible_person(target);before=[self.visible_person(pid) for pid in sources]
                favorite=any([after['favorite']]+[p['favorite'] for p in before]);pinned=any([after['pinned']]+[p['pinned'] for p in before]);cover=after['cover_face'] or next((p['cover_face'] for p in before if p['cover_face']),None)
                v.db.execute('UPDATE people SET name=?,favorite=?,pinned=?,cover_face=? WHERE id=?',(name.strip(),int(favorite),int(pinned),cover,target))
                for pid in sources:v.db.execute('UPDATE people_faces SET person_id=? WHERE person_id=?',(target,pid));v.db.execute('DELETE FROM people WHERE id=?',(pid,))
            elif action=='move':
                face=body.get('face');target=body.get('target')
                row=v.db.execute("SELECT f.id FROM people_faces f JOIN assets a ON a.id=f.asset_id WHERE f.id=? AND a.state='public'",(face,)).fetchone() if isinstance(face,str) else None
                if not row:raise VaultError('Лицо недоступно.',404)
                if target:self.visible_person(target)
                else:
                    target=secrets.token_hex(16);v.db.execute('INSERT INTO people(id) VALUES(?)',(target,))
                v.db.execute('UPDATE people_faces SET person_id=? WHERE id=?',(target,face))
            else:raise VaultError('Неизвестное действие.')
        return self.status()

    def crop(self,face):
        v=self.v
        with v.operation_lock,v.lock:
            row=v.db.execute("SELECT f.box,a.preview FROM people_faces f JOIN assets a ON a.id=f.asset_id WHERE f.id=? AND a.state='public'",(face,)).fetchone()
            if not row:raise VaultError('Лицо недоступно.',404)
            with Image.open(v.media/row['preview']) as source:
                x,y,w,h=json.loads(row['box']);width,height=source.size
                side=max(w*width,h*height)*1.6;cx=(x+w/2)*width;cy=(y+h/2)*height
                side=min(side,width,height)
                left=max(0,min(width-side,cx-side/2));top=max(0,min(height-side,cy-side/2))
                image=source.convert('RGB').crop((int(left),int(top),int(left+side),int(top+side)))
                image.thumbnail((240,240));output=BytesIO();image.save(output,'JPEG',quality=85);return output.getvalue()

    def process_one(self,inference=detect):
        v=self.v
        with v.operation_lock,v.lock:
            if not self.active():return False
            row=v.db.execute("SELECT a.id,a.preview FROM assets a LEFT JOIN people_scans s ON s.asset_id=a.id AND s.model=? WHERE a.state='public' AND a.kind='photo' AND s.asset_id IS NULL ORDER BY a.id LIMIT 1",(MODEL,)).fetchone()
            if not row:return False
            index=row['id'];v.people_processing=index
            try:
                # Use an upright preview of the original; edits do not alter identity.
                path=v.media/row['preview']
                if path.stat().st_size>8*1024**2:raise OSError('Preview too large')
                data=path.read_bytes()
            except OSError:
                with v.db:v.db.execute('INSERT OR REPLACE INTO people_scans VALUES(?,?,?)',(index,MODEL,'Не удалось прочитать фотографию.'))
                v.people_processing=None;return True
        try:
            faces=inference(data)
            if not isinstance(faces,list) or len(faces)>100:raise ValueError('Invalid face response')
            checked=[]
            for face in faces:
                box=face.get('box');vector=normalize(face.get('vector'))
                if not isinstance(box,list) or len(box)!=4 or any(type(x) not in (int,float) or not math.isfinite(x) or x<0 or x>1 for x in box) or min(box[2:])<=0 or box[0]+box[2]>1.001 or box[1]+box[3]>1.001:raise ValueError('Invalid face box')
                checked.append((box,vector))
            with v.operation_lock,v.lock,v.db:
                if not self.active():return False
                current=v.db.execute("SELECT preview FROM assets WHERE id=? AND state='public'",(index,)).fetchone()
                if not current or current['preview']!=row['preview']:return False
                # Average only currently public faces; private photos cannot influence groups.
                groups={}
                for old in v.db.execute("SELECT f.person_id,f.vector FROM people_faces f JOIN assets a ON a.id=f.asset_id WHERE a.state='public'"):
                    pid=old['person_id'];vec=json.loads(old['vector']);groups[pid]=[a+b for a,b in zip(groups.get(pid,[0.]*128),vec)]
                centers={pid:normalize(vec) for pid,vec in groups.items() if any(abs(x)>.0001 for x in vec)}
                ignored={r['id']:json.loads(r['ignore_vector']) for r in v.db.execute('SELECT id,ignore_vector FROM people WHERE excluded=1 AND ignore_vector IS NOT NULL')}
                used=set()
                for box,vector in checked:
                    if any(sum(a*b for a,b in zip(vector,template))>=.50 for template in ignored.values()):continue
                    scores=sorted(((sum(a*b for a,b in zip(vector,center)),pid) for pid,center in centers.items() if pid not in used),reverse=True)
                    # Conservative matching, with ambiguity margin. Never merge two faces in one photo.
                    pid=scores[0][1] if scores and scores[0][0]>=.50 and (len(scores)<2 or scores[0][0]-scores[1][0]>=.06) else secrets.token_hex(16)
                    if pid in ignored:continue
                    v.db.execute('INSERT OR IGNORE INTO people(id) VALUES(?)',(pid,));used.add(pid)
                    v.db.execute('INSERT INTO people_faces VALUES(?,?,?,?,?)',(secrets.token_hex(16),pid,index,json.dumps(box),json.dumps(vector)))
                v.db.execute('INSERT OR REPLACE INTO people_scans VALUES(?,?,?)',(index,MODEL,''));v._set('people_error','')
            return True
        except urllib.error.HTTPError as error:
            invalid=error.code==422;error.close()
            with v.lock,v.db:
                if self.active() and invalid:
                    v.db.execute('INSERT OR REPLACE INTO people_scans VALUES(?,?,?)',(index,MODEL,'Не удалось распознать фотографию.'))
                    return True
                if not getattr(v,'retired',False):v._set('people_error','Сервис распознавания недоступен. Повторим автоматически.')
            raise
        except Exception:
            with v.lock,v.db:
                if not getattr(v,'retired',False):v._set('people_error','Сервис распознавания недоступен. Повторим автоматически.')
            raise
        finally:v.people_processing=None


def start_worker(accounts):
    """One low-priority inference at a time; request leases protect library deletion."""
    def work():
        cooldown={}
        while True:
            time.sleep(3)
            accounts.request_started()
            try:
                with accounts.control.lock:users=[dict(r) for r in accounts.control.db.execute('SELECT * FROM users WHERE disabled=0')]
                for user in users:
                    if cooldown.get(user['id'],0)>time.time():continue
                    try:
                        v,_=accounts.library(user)
                        if not People(v).active():continue
                        # Recheck blocking/deletion immediately before work.
                        with accounts.control.lock:
                            if not accounts.control.db.execute('SELECT 1 FROM users WHERE id=? AND disabled=0',(user['id'],)).fetchone():continue
                        People(v).process_one()
                    except Exception:cooldown[user['id']]=time.time()+30
            finally:accounts.request_finished()
    if os.environ.get('PHOTO_FACE_URL') and os.environ.get('PHOTO_FACE_TOKEN'):
        threading.Thread(target=work,daemon=True,name='people-index').start()
