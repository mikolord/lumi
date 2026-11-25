"""Build a code-only GitHub release: no libraries, credentials or NAS configuration."""
import hashlib
import json
from pathlib import Path
import re
import tarfile

root=Path(__file__).resolve().parents[1];tag='v'+(root/'VERSION').read_text().strip()
assert re.fullmatch(r'v\d+\.\d+\.\d+',tag)
output=root.parent/'photo-releases'/tag;output.mkdir(parents=True,exist_ok=True)
archive=output/('mira-photos-'+tag+'.tar.gz')
files=[p for p in root.iterdir() if p.is_file() and (p.suffix in ('.py','.js','.css') or p.name in ('VERSION','RUNTIME','requirements.txt','index.html','manifest.webmanifest'))]
files += [p for folder in ('assets','icons') for p in (root/folder).rglob('*') if p.is_file() and p.suffix.lower() in ('.jpg','.jpeg','.png','.webp','.svg','.mp4')]
files.append(root/'faces/metrics.py')
with tarfile.open(archive,'w:gz') as tar:
    for path in sorted(files):tar.add(path,arcname=path.relative_to(root).as_posix(),recursive=False)
manifest=dict(version=tag,runtime=int((root/'RUNTIME').read_text().strip()),requirementsSha256=hashlib.sha256((root/'requirements.txt').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
(output/'mira-photos-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print(output)
