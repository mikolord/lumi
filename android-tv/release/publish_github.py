"""Publish a public TV release and its direct GitHub update manifest.
Requires Git Credential Manager authentication; no token is stored in the APK.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import urllib.error

REPO = 'mikolord/lumi'
ROOT = Path(__file__).resolve().parents[1]

def git(*args, cwd=ROOT):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True).stdout.decode().strip()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--prerelease', action='store_true', help='Publish a beta APK without changing the stable update feed')
    args = parser.parse_args()
    info = json.loads((ROOT / 'release/tv/version.json').read_text())
    apk = ROOT / 'release/tv/rc-foto.apk'
    data = apk.read_bytes()
    if hashlib.sha256(data).hexdigest() != info['sha256']: raise ValueError('APK checksum mismatch')
    version = info['versionName']
    tag = 'android-v' + version
    name = 'lumi-android-' + version + '.apk'
    public_info = dict(info, url='https://github.com/' + REPO + '/releases/download/' + tag + '/' + name)
    manifest = (json.dumps(public_info, ensure_ascii=False, indent=2) + '\n').encode()
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
        payload = dict(tag_name=tag, target_commitish=args.source_commit, name='lumi Android ' + version,
            body=info.get('notes', ''), draft=False, prerelease=args.prerelease, make_latest='false')
        release = api(base + '/releases', json.dumps(payload, ensure_ascii=False).encode())
    assets = {asset['name']: asset for asset in release['assets']}
    upload = release['upload_url'].split('{', 1)[0]
    for asset_name, contents, content_type in [(name, data, 'application/vnd.android.package-archive'),
            ('tv-version.json', manifest, 'application/json')]:
        if asset_name in assets:
            if assets[asset_name].get('digest') != 'sha256:' + hashlib.sha256(contents).hexdigest():
                raise ValueError('Published asset differs; increment the version instead of replacing it')
            continue
        api(upload + '?name=' + asset_name, contents, content_type)
    if args.prerelease:
        print('Published beta (stable feed unchanged):', release['html_url'])
        return
    remote = 'https://github.com/' + REPO + '.git'
    with tempfile.TemporaryDirectory(prefix='lumi-tv-feed-') as temporary:
        destination = Path(temporary).resolve()
        git('init', '-b', 'tv-updates', str(destination))
        git('config', 'user.name', git('config', 'user.name'), cwd=destination)
        git('config', 'user.email', git('config', 'user.email'), cwd=destination)
        if git('ls-remote', '--heads', remote, 'refs/heads/tv-updates'):
            git('fetch', '--depth=1', remote, 'refs/heads/tv-updates', cwd=destination)
            git('checkout', '-B', 'tv-updates', 'FETCH_HEAD', cwd=destination)
        (destination / 'tv').mkdir(exist_ok=True)
        (destination / 'tv/version.json').write_bytes(manifest)
        git('add', '--', 'tv/version.json', cwd=destination)
        if git('status', '--porcelain', cwd=destination):
            git('commit', '-m', 'Publish TV ' + version + ' direct update manifest', cwd=destination)
        git('push', remote, 'HEAD:refs/heads/tv-updates', cwd=destination)
    print('Published:', release['html_url'])

if __name__ == '__main__': main()
