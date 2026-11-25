"""Non-destructive, account-local media adjustments. Originals remain immutable."""
import json
import math
import secrets
import shutil
import subprocess
import threading
import time
import tempfile
from pathlib import Path
from PIL import Image, ImageOps, ImageEnhance, ImageDraw
from vault import VaultError
from accounts import make_preview

FILTERS={'original','vivid','warm','cool','mono','silver','sepia'}

def validate(value,video=False,duration=0):
    if not isinstance(value,dict):raise VaultError('Неверные настройки редактора.')
    r={}
    for key,low,high,default in [('brightness',-1,1,0),('contrast',-1,1,0),('saturation',-1,1,0),('warmth',-1,1,0),('straighten',-45,45,0),('start',0,max(0,duration),0),('end',0,max(0,duration),duration)]:
        n=value.get(key,default)
        if type(n) not in (int,float) or not math.isfinite(n) or not low<=n<=high:raise VaultError('Неверное значение '+key)
        r[key]=float(n)
    r['rotation']=value.get('rotation',0)
    if type(r['rotation']) is not int or r['rotation'] not in (0,90,180,270):raise VaultError('Неверный поворот.')
    for key in ('flip','mute'):
        r[key]=value.get(key,False)
        if type(r[key]) is not bool:raise VaultError('Неверный переключатель.')
    r['filter']=value.get('filter','original')
    if not isinstance(r['filter'],str) or r['filter'] not in FILTERS:raise VaultError('Неизвестный фильтр.')
    crop=value.get('crop',[0,0,1,1])
    if not isinstance(crop,list) or len(crop)!=4 or any(type(n) not in (int,float) or not math.isfinite(n) for n in crop):raise VaultError('Неверная область обрезки.')
    x,y,w,h=crop
    if min(x,y)<0 or min(w,h)<.05 or x+w>1.00001 or y+h>1.00001:raise VaultError('Область обрезки вне фотографии.')
    r['crop']=crop
    if video and (r['end']-r['start']<.1):raise VaultError('Оставь не меньше 0,1 секунды видео.')
    strokes=value.get('strokes',[])
    if not isinstance(strokes,list) or len(strokes)>100:raise VaultError('Слишком много линий.')
    total=0;r['strokes']=[]
    for stroke in strokes:
        if not isinstance(stroke,dict) or stroke.get('color') not in ('#ffffff','#ffcc00','#ff453a','#000000'):raise VaultError('Неверный цвет линии.')
        points=stroke.get('points');total+=len(points) if isinstance(points,list) else 10000
        if total>4000 or not isinstance(points,list) or len(points)<2:raise VaultError('Неверная линия.')
        for point in points:
            if not isinstance(point,list) or len(point)!=2 or any(type(n) not in (int,float) or not math.isfinite(n) or not 0<=n<=1 for n in point):raise VaultError('Неверная точка.')
        r['strokes'].append(dict(color=stroke['color'],points=points))
    if video and strokes:raise VaultError('Разметка доступна для фотографий.')
    return r

def recover(v):
    """Called once when a library is opened by a new server process."""
    with v.operation_lock:
        with v.lock,v.db:
            old=v._setting('editor_job')
            if old:
                state=json.loads(old)
                if state.get('state')=='processing':
                    state.update(state='failed',error='Сохранение прервано перезапуском сервера. Повтори его.');v._set('editor_job',json.dumps(state))
            referenced={r[0] for r in v.db.execute('SELECT original FROM assets UNION SELECT preview FROM assets UNION SELECT original FROM asset_edits UNION SELECT preview FROM asset_edits')}
        for file in (v.directory/'incoming').glob('edit-reserve-*'):file.unlink(missing_ok=True)
        stage=v.directory/'editing'
        if stage.is_dir() and not stage.is_symlink() and stage.resolve().is_relative_to(v.directory.resolve()):
            for folder in stage.iterdir():
                if folder.is_dir() and not folder.is_symlink():
                    for file in folder.iterdir():
                        if file.is_file() or file.is_symlink():file.unlink(missing_ok=True)
                    try:folder.rmdir()
                    except OSError:pass
        for file in v.media.glob('edit-*'):
            if file.name not in referenced:file.unlink(missing_ok=True)

class MediaEditor:
    def __init__(self,vault):
        self.v=vault;self.lock=threading.RLock();self.job={}
        old=vault._setting('editor_job')
        if old:
            self.job=json.loads(old)
            if self.job.get('state')=='processing':self.progress(state='failed',error='Сохранение прервано перезапуском сервера. Повтори его.')

    def progress(self,**fields):
        with self.lock:
            self.job.update(fields)
            if not getattr(self.v,'retired',False):
                with self.v.lock,self.v.db:self.v._set('editor_job',json.dumps(self.job))
            return dict(self.job)

    def status(self):
        with self.lock:return dict(self.job)

    def source(self,index,token):
        with self.v.lock:
            owner_row=self.v.db.execute('SELECT state FROM assets WHERE id=?',(index,)).fetchone()
            if owner_row and owner_row['state']=='shared':raise VaultError('Общий альбом доступен только для просмотра.',403)
        self.v.media_path(index,False,token,source=True)
        with self.v.lock:
            row=self.v.db.execute('SELECT * FROM assets WHERE id=?',(index,)).fetchone()
            if row['state']=='shared':raise VaultError('Общий альбом доступен только для просмотра.',403)
            edit=self.v.db.execute('SELECT * FROM asset_edits WHERE asset_id=?',(index,)).fetchone()
            result=dict(metadata=json.loads(row['metadata']),kind=row['kind'],recipe=json.loads(edit['recipe']) if edit else None)
        result['job']=self.status();return result

    def start(self,index,recipe,token,check):
        with self.v.operation_lock:
            self.v.check_quota()
            source=self.source(index,token);r=validate(recipe,source['kind']=='video',source['metadata'].get('duration',0))
            with self.lock:
                if self.job.get('state')=='processing':raise VaultError('Дождись завершения сохранения.',409)
                self.progress(state='processing',index=index,error='',startedAt=time.time())
                threading.Thread(target=self.render,args=(index,r,check),daemon=True).start()
                return self.status()

    def restore(self,index,token):
        if self.status().get('state')=='processing':raise VaultError('Дождись завершения сохранения.',409)
        self.source(index,token)
        with self.v.operation_lock,self.v.lock,self.v.db:
            self.v.check_quota()
            row=self.v.db.execute('SELECT * FROM asset_edits WHERE asset_id=?',(index,)).fetchone()
            self.v.db.execute('DELETE FROM asset_edits WHERE asset_id=?',(index,))
            if row:
                for key in ('original','preview'):(self.v.media/row[key]).unlink(missing_ok=True)

    def render(self,index,r,check):
        v=self.v;created=[];reservation=None;stage=None
        try:
            with v.operation_lock:
                check();v.check_quota()
                with v.lock:row=dict(v.db.execute('SELECT * FROM assets WHERE id=?',(index,)).fetchone())
                if row['state'] not in ('public','hidden','trash'):raise VaultError('Файл недоступен.',404)
                source=v.media/row['original'];meta=json.loads(row['metadata']);video=row['kind']=='video';uid=secrets.token_hex(16)
                available=min(shutil.disk_usage(v.directory).free-250*1024**2,(v.quota_bytes-v.usage()) if v.quota_bytes else 10*1024**3)
                if available<65536:raise VaultError('Недостаточно места для сохранения изменений.',413)
                budget=int(available if video else min(available,max(source.stat().st_size*8,32*1024**2)))
                incoming=v.directory/'incoming';incoming.mkdir(exist_ok=True)
                reserve=tempfile.NamedTemporaryFile(dir=incoming,prefix='edit-reserve-',delete=False);reservation=Path(reserve.name)
                try:reserve.truncate(budget)
                finally:reserve.close()
                stage=v.directory/'editing'/uid;stage.mkdir(parents=True)
                suffix='.mp4' if video else '.jpg';target=stage/('edit-'+uid+suffix);preview=stage/('edit-'+uid+'-preview.jpg')
                published=v.media/target.name;published_preview=v.media/preview.name;created=[target,preview,published,published_preview]
            # Rendering uses private staging plus a quota reservation. Library reads
            # remain available while FFmpeg processes a long movie.
            if video:self.render_video(source,target,r,budget,check)
            else:self.render_photo(source,target,r)
            metadata,kind=make_preview(target,preview,target.name)
            metadata['name']=str(meta.get('name','photo')).rsplit('.',1)[0]+suffix;metadata['takenAt']=meta.get('takenAt')
            with v.operation_lock:
                check();v.check_quota()
                with v.lock:now=v.db.execute('SELECT state FROM assets WHERE id=?',(index,)).fetchone()
                if not now or now[0] not in ('public','hidden','trash'):raise VaultError('Файл больше недоступен.',404)
                if target.stat().st_size+preview.stat().st_size>budget:raise VaultError('Недостаточно места для результата.',413)
                reservation.unlink(missing_ok=True);reservation=None
                target.replace(published);preview.replace(published_preview);v.check_quota()
                with v.lock,v.db:
                    old=v.db.execute('SELECT * FROM asset_edits WHERE asset_id=?',(index,)).fetchone()
                    v.db.execute('INSERT OR REPLACE INTO asset_edits VALUES(?,?,?,?,?,?)',(index,json.dumps(r),published.name,published_preview.name,json.dumps(metadata),time.time_ns()))
                created=[]
                if old:
                    for key in ('original','preview'):
                        try:(v.media/old[key]).unlink(missing_ok=True)
                        except OSError:pass
                self.progress(state='complete',error='')
        except Exception as error:
            self.progress(state='failed',error=error.message if isinstance(error,VaultError) else 'Не удалось сохранить изменения. Оригинал сохранён.')
        finally:
            for path in created:path.unlink(missing_ok=True)
            if reservation:reservation.unlink(missing_ok=True)
            if stage:
                try:stage.rmdir()
                except OSError:pass

    @staticmethod
    def render_photo(source,target,r):
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:pass
        with Image.open(source) as opened:
            if opened.width*opened.height>60000000:raise VaultError('Фото слишком большое для редактора: максимум 60 Мп.')
            image=ImageOps.exif_transpose(opened).convert('RGB')
        if r['flip']:image=ImageOps.mirror(image)
        if r['rotation']:image=image.rotate(-r['rotation'],expand=True)
        if r['straighten']:image=image.rotate(-r['straighten'],resample=Image.Resampling.BICUBIC)
        x,y,w,h=r['crop'];iw,ih=image.size;image=image.crop((round(x*iw),round(y*ih),round((x+w)*iw),round((y+h)*ih)))
        image=ImageEnhance.Brightness(image).enhance(1+r['brightness']*.8)
        image=ImageEnhance.Contrast(image).enhance(1+r['contrast']*.8)
        image=ImageEnhance.Color(image).enhance(1+r['saturation'])
        f=r['filter']
        if f=='vivid':image=ImageEnhance.Color(ImageEnhance.Contrast(image).enhance(1.12)).enhance(1.3)
        if f in ('mono','silver'):image=ImageOps.grayscale(image).convert('RGB');image=ImageEnhance.Contrast(image).enhance(1.22 if f=='silver' else 1)
        if f=='sepia':image=ImageOps.colorize(ImageOps.grayscale(image),'#25170c','#f4d7ad')
        warmth=r['warmth']+(.25 if f=='warm' else -.25 if f=='cool' else 0)
        if warmth:
            red,green,blue=image.split();red=red.point(lambda x:max(0,min(255,round(x+warmth*22))));blue=blue.point(lambda x:max(0,min(255,round(x-warmth*22))));image=Image.merge('RGB',(red,green,blue))
        draw=ImageDraw.Draw(image)
        for stroke in r['strokes']:draw.line([(round(x*image.width),round(y*image.height)) for x,y in stroke['points']],fill=stroke['color'],width=max(2,round(min(image.size)*.008)),joint='curve')
        image.save(target,'JPEG',quality=95)

    @staticmethod
    def render_video(source,target,r,available,check=lambda:None):
        filters=[]
        if r['flip']:filters.append('hflip')
        if r['rotation']==90:filters.append('transpose=1')
        elif r['rotation']==180:filters+=['hflip','vflip']
        elif r['rotation']==270:filters.append('transpose=2')
        if r['straighten']:filters.append(f"rotate={r['straighten']}*PI/180:fillcolor=black")
        x,y,w,h=r['crop'];filters.append(f'crop=iw*{w}:ih*{h}:iw*{x}:ih*{y}')
        f=r['filter'];brightness=r['brightness']*.3;contrast=1+r['contrast']*.8;saturation=1+r['saturation'];warmth=r['warmth']+(.25 if f=='warm' else -.25 if f=='cool' else 0)
        if f=='vivid':contrast*=1.12;saturation*=1.3
        if f in ('mono','silver'):saturation=0;contrast*=1.22 if f=='silver' else 1
        filters.append(f'eq=brightness={brightness}:contrast={contrast}:saturation={saturation}')
        if warmth:filters.append(f'colorbalance=rs={warmth*.12}:bs={-warmth*.12}')
        if f=='sepia':filters.append('colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131')
        filters+=['scale=trunc(iw/2)*2:trunc(ih/2)*2','setsar=1']
        command=['ffmpeg','-protocol_whitelist','file,pipe','-nostdin','-v','error','-threads','2','-filter_threads','1','-ss',str(r['start']),'-i',str(source),'-t',str(r['end']-r['start']),'-map','0:v:0','-vf',','.join(filters),'-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p']
        command+=['-an'] if r['mute'] else ['-map','0:a:0?','-c:a','aac','-b:a','160k']
        command+=['-map_metadata','-1','-metadata:s:v:0','rotate=0','-movflags','+faststart','-fs',str(max(1,int(available)-512*1024)),'-y',str(target)]
        process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        started=time.monotonic()
        try:
            while process.poll() is None:
                check()
                if time.monotonic()-started>1800:raise VaultError('Сохранение заняло слишком много времени. Попробуй более короткое видео.')
                time.sleep(.5)
            if process.returncode:raise VaultError('Не удалось обработать видео. Оригинал сохранён.')
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
        probe=json.loads(subprocess.run(['ffprobe','-v','error','-show_format','-of','json',str(target)],capture_output=True,check=True,timeout=30).stdout)
        if abs(float(probe['format']['duration'])-(r['end']-r['start']))>.5:raise VaultError('Сохранение остановлено: недостаточно места для всего видео.',413)
