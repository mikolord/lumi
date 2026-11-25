"""Allowlisted, read-only NAS folder import into a private user library."""
import json
import hashlib
from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import threading

from vault import VaultError

ACCOUNT_SECONDS = 30 * 86400
PHOTO_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.tif', '.tiff', '.bmp', '.gif'}
VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi'}


class LibraryImporter:
    def __init__(self, vault, sources):
        self.vault = vault
        self.sources = {name: Path(path).resolve() for name,path in sources.items()}
        with vault.lock,vault.db:
            vault.db.execute('CREATE TABLE IF NOT EXISTS imports(source TEXT PRIMARY KEY, asset_id INTEGER NOT NULL)')
            vault.db.execute('CREATE TABLE IF NOT EXISTS upload_receipts(key TEXT PRIMARY KEY,name TEXT NOT NULL,size INTEGER NOT NULL,asset_id INTEGER NOT NULL)')
            vault.db.execute('CREATE TABLE IF NOT EXISTS external_assets(source TEXT,remote_id TEXT,asset_id INTEGER,PRIMARY KEY(source,remote_id))')
            vault.db.execute('CREATE TABLE IF NOT EXISTS external_albums(source TEXT,remote_id TEXT,album_id TEXT,PRIMARY KEY(source,remote_id))')
            vault.db.execute('CREATE TABLE IF NOT EXISTS asset_hashes(asset_id INTEGER PRIMARY KEY,size INTEGER NOT NULL,digest TEXT NOT NULL)')
            vault.db.execute('CREATE INDEX IF NOT EXISTS asset_hashes_digest ON asset_hashes(size,digest)')
            if 'duplicate' not in {r[1] for r in vault.db.execute('PRAGMA table_info(upload_receipts)')}:
                vault.db.execute('ALTER TABLE upload_receipts ADD COLUMN duplicate INTEGER NOT NULL DEFAULT 0')
            previous = self.job()
            if previous.get('state') == 'running':
                previous.update(state='interrupted',error='Подключение прервано перезапуском сервера. Его можно продолжить.')
                vault._set('import_job',json.dumps(previous))

        from editor import recover
        recover(vault)

    def resolve(self, source, relative=''):
        if source not in self.sources or not isinstance(relative,str):
            raise VaultError('Папка недоступна.',404)
        root = self.sources[source]
        target = root / relative
        # Never follow symlinks, including an ancestor, into another share or private application data.
        if Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise VaultError('Папка недоступна.',403)
        cursor = root
        for part in Path(relative).parts:
            if part.startswith(('.', '@')) or 'immich' in part.lower():
                raise VaultError('Папка недоступна.',403)
            cursor /= part
            if cursor.is_symlink():
                raise VaultError('Ссылки на другие папки не поддерживаются.',403)
        target = target.resolve()
        if not target.is_relative_to(root) or not target.is_dir():
            raise VaultError('Папка недоступна.',404)
        return target

    def folders(self, source=None, relative=''):
        if not source:
            return dict(roots=[dict(id=name, name=name) for name,path in self.sources.items() if path.is_dir()])
        target = self.resolve(source, relative)
        try:
            children = [entry.name for entry in target.iterdir() if not entry.is_symlink() and entry.is_dir() and not entry.name.startswith(('.', '@')) and 'immich' not in entry.name.lower()]
        except OSError as error:
            raise VaultError('Нет доступа к папке.',403) from error
        return dict(source=source, path=relative, folders=sorted(children,key=str.casefold))

    def job(self):
        return json.loads(self.vault._setting('import_job') or '{}')

    def progress(self, **values):
        with self.vault.lock, self.vault.db:
            job = self.job(); job.update(values)
            self.vault._set('import_job', json.dumps(job, ensure_ascii=False))

    def start_import(self, source, relative):
        target = self.resolve(source,relative)
        with self.vault.operation_lock,self.vault.lock, self.vault.db:
            self.vault.check_quota()
            if self.job().get('state') == 'running':
                raise VaultError('Подключение папки уже выполняется.',409)
            existing = self.vault._setting('source_folder')
            label = source + ('/'+relative if relative else '')
            if existing and existing != label:
                raise VaultError('Уже подключена другая папка.',409)
            self.vault._set('source_folder',label)
            self.vault._set('import_job',json.dumps(dict(state='running',done=0,added=0,skipped=0,total=None)))
        threading.Thread(target=self.import_folder,args=(target,),daemon=True).start()
        return self.job()

    def import_folder(self, target):
        v = self.vault
        done = added = skipped = 0
        try:
            files = []
            for directory, dirs, names in os.walk(target,followlinks=False):
                base = Path(directory)
                dirs[:] = sorted(d for d in dirs if not d.startswith(('.', '@')) and 'immich' not in d.lower() and not (base/d).is_symlink())
                files.extend(base/name for name in sorted(names) if not name.startswith('.') and Path(name).suffix.lower() in PHOTO_EXT | VIDEO_EXT and not (base/name).is_symlink())
            self.progress(total=len(files))
            # Demo rows stay in SQLite for stable IDs but disappear from this owner's library.
            with v.lock,v.db:
                if not v._setting('real_library'):
                    v.db.execute("UPDATE assets SET state='purged',metadata='{}',deleted_at=NULL")
                    v._set('real_library','1')
            for source in files:
                key = str(source)
                with v.lock:
                    exists = v.db.execute('SELECT 1 FROM imports WHERE source=?',(key,)).fetchone()
                if exists:
                    done += 1; self.progress(done=done); continue
                try:
                    if source.is_symlink() or not source.resolve().is_relative_to(target):
                        raise ValueError('Outside source folder')
                    index=self.ingest(source,source.name)
                    with v.lock,v.db:v.db.execute('INSERT INTO imports VALUES(?,?)',(key,index))
                    added += 1
                except VaultError as error:
                    self.progress(state='failed',error=error.message,added=added,skipped=skipped,done=done)
                    return
                except Exception:
                    skipped += 1
                done += 1
                self.progress(done=done,added=added,skipped=skipped)
            self.progress(state='complete')
        except Exception:
            self.progress(state='failed',error='Не удалось прочитать папку. Проверь доступ и повтори подключение.')

    def refresh_metadata(self,index,token):
        v=self.vault
        with v.operation_lock:
            with v.lock:
                row=v.db.execute('SELECT * FROM assets WHERE id=?',(index,)).fetchone()
                if row and row['state']=='shared':raise VaultError('Общий альбом доступен только для просмотра.',403)
            path=v.media_path(index,False,token,source=True)
            metadata=json.loads(row['metadata'])
            if row['kind']=='video' and not metadata.get('dateChecked'):
                if not iso_date(metadata.get('takenAt')):
                    try:metadata['takenAt']=video_date(probe_video(path))
                    except (OSError,ValueError,subprocess.SubprocessError):metadata['takenAt']=None
                metadata['dateChecked']=True
                metadata.setdefault('addedAt',datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat())
                with v.lock,v.db:v.db.execute('UPDATE assets SET metadata=? WHERE id=?',(json.dumps(metadata),index))

    @staticmethod
    def hash_file(path):
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        return digest.hexdigest()

    def lookup_content(self,size,digest):
        v=self.vault
        with v.operation_lock:
            if getattr(v,'retired',False):raise VaultError('Аккаунт удалён.',401)
            with v.lock:
                rows=list(v.db.execute("SELECT a.id,a.original,h.size,h.digest FROM assets a LEFT JOIN asset_hashes h ON a.id=h.asset_id WHERE a.state IN ('public','hidden','trash') AND ((h.asset_id IS NULL AND (json_extract(a.metadata,'$.bytes') IS NULL OR json_extract(a.metadata,'$.bytes')=?)) OR (h.size=? AND h.digest=?)) ORDER BY a.id",(size,size,digest)))
            for row in rows:
                path=v.media/row['original']
                if not path.is_file():continue
                actual_size=path.stat().st_size
                if actual_size!=size:continue
                found=row['digest']
                if found is None:
                    found=self.hash_file(path)
                    with v.lock,v.db:v.db.execute('INSERT OR REPLACE INTO asset_hashes VALUES(?,?,?)',(row['id'],size,found))
                if found==digest:return row['id']
        return None

    def ingest(self,source,name,consume=False,receipt=None,external=None,content_hash=None):
        v=self.vault
        with v.operation_lock:
            v.check_quota(0 if consume else source.stat().st_size)
            uid=secrets.token_hex(16)
            original=v.media/(uid+source.suffix.lower())
            preview=v.media/(uid+'-preview.jpg')
            try:
                if consume:source.replace(original)
                else:shutil.copyfile(source,original)
                metadata,kind=make_preview(original,preview,name)
                v.check_quota()
                with v.lock,v.db:
                    index=v.db.execute('SELECT COALESCE(MAX(id),-1)+1 FROM assets').fetchone()[0]
                    v.db.execute('INSERT INTO assets(id,media_key,kind,original,preview,metadata) VALUES(?,?,?,?,?,?)',(index,json.dumps('file-'+uid),kind,original.name,preview.name,json.dumps(metadata)))
                    if receipt:v.db.execute('INSERT INTO upload_receipts(key,name,size,asset_id) VALUES(?,?,?,?)',(*receipt,index))
                    if content_hash:v.db.execute('INSERT INTO asset_hashes VALUES(?,?,?)',(index,metadata['bytes'],content_hash))
                    if external:v.db.execute('INSERT INTO external_assets VALUES(?,?,?)',(*external,index))
                return index
            except Exception:
                original.unlink(missing_ok=True);preview.unlink(missing_ok=True)
                raise

    def finish(self):
        with self.vault.lock,self.vault.db:
            if self.job().get('state') not in (None,'complete'):
                raise VaultError('Дождись завершения подключения папки.',409)
            self.vault._set('onboarding_done','1')


def iso_date(value):
    if not isinstance(value,str):return None
    try:
        date=datetime.fromisoformat(value.strip().replace('Z','+00:00'))
        return date.isoformat() if 1900<=date.year<=2100 else None
    except (ValueError,OverflowError):return None

def video_date(info):
    tags=[info.get('format',{}).get('tags',{})]+[stream.get('tags',{}) for stream in info.get('streams',[]) if stream.get('codec_type')=='video']
    for key in ('com.apple.quicktime.creationdate','creation_time','date'):
        for bucket in tags:
            value=iso_date(bucket.get(key))
            if value:return value
    return None

def probe_video(path):
    result=subprocess.run(['ffprobe','-protocol_whitelist','file,pipe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,check=True,timeout=60)
    return json.loads(result.stdout)

def make_preview(original, preview, name):
    from PIL import Image, ImageOps
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass
    video = original.suffix.lower() in VIDEO_EXT
    metadata = dict(name=name, bytes=original.stat().st_size,format=original.suffix[1:].upper(),addedAt=datetime.fromtimestamp(original.stat().st_mtime,timezone.utc).isoformat())
    if video:
        info = probe_video(original)
        stream = next(s for s in info['streams'] if s['codec_type']=='video')
        metadata.update(takenAt=video_date(info),dateChecked=True,width=stream['width'],height=stream['height'],duration=float(info.get('format',{}).get('duration',0)))
        subprocess.run(['ffmpeg','-protocol_whitelist','file,pipe','-nostdin','-v','error','-i',str(original),'-frames:v','1','-vf','scale=1600:1600:force_original_aspect_ratio=decrease','-y',str(preview)],capture_output=True,check=True,timeout=120)
    else:
        with Image.open(original) as image:
            exif = image.getexif()
            raw_date = exif.get(36867) or exif.get(306)
            metadata.update(camera=' '.join(str(exif.get(tag) or '') for tag in (271,272)).strip() or None, takenAt=(str(raw_date)[:10].replace(':','-')+'T'+str(raw_date)[11:19]) if raw_date else None)
            image = ImageOps.exif_transpose(image)
            metadata.update(width=image.width,height=image.height)
            image.thumbnail((1600,1600))
            image.convert('RGB').save(preview,'JPEG',quality=88)
    return metadata,'video' if video else 'photo'
