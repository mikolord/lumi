"""Attach a checked code-only server package to a public GitHub release."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
REPO = 'mikolord/lumi'

def main():
    tag = 'v' + (ROOT / 'VERSION').read_text().strip()
    package = ROOT.parent / 'photo-releases' / tag
    manifest = package / 'mira-photos-manifest.json'
    archive = package / ('mira-photos-' + tag + '.tar.gz')
    info = json.loads(manifest.read_text())
    if info['sha256'] != hashlib.sha256(archive.read_bytes()).hexdigest(): raise ValueError('Package checksum mismatch')
    result = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
        text=True, capture_output=True, check=True)
    credentials = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    token = credentials.get('password')
    if not token: raise RuntimeError('GitHub authentication required')
    def api(url, body=None, content_type='application/json'):
        request = urllib.request.Request(url, data=body, headers={'Authorization': 'Bearer ' + token,
            'User-Agent': 'Lumi-publisher', 'Accept': 'application/vnd.github+json', 'Content-Type': content_type})
        with urllib.request.urlopen(request, timeout=120) as response: return json.load(response)
    base = 'https://api.github.com/repos/' + REPO
    try: release = api(base + '/releases/tags/' + tag)
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        if code != 404: raise
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
        payload = dict(tag_name=tag, target_commitish=commit, name='lumi server ' + tag[1:], draft=False,
            prerelease=False, make_latest='true', body='Сервер личной фототеки. Docker обязателен. Установка: https://github.com/mikolord/lumi#установка-сервера')
        release = api(base + '/releases', json.dumps(payload, ensure_ascii=False).encode())
    assets = {asset['name']: asset for asset in release['assets']}
    upload = release['upload_url'].split('{', 1)[0]
    for path, content_type in [(archive, 'application/gzip'), (manifest, 'application/json')]:
        data = path.read_bytes()
        if path.name in assets:
            if assets[path.name].get('digest') != 'sha256:' + hashlib.sha256(data).hexdigest():
                raise ValueError('Published asset differs; increment VERSION')
            continue
        api(upload + '?name=' + path.name, data, content_type)
    print('Published:', release['html_url'])

if __name__ == '__main__': main()
