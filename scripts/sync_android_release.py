"""Attach an already published, checksum-verified Android APK to a server release.

No rebuild, signing key, or stable Android feed change is involved.
"""
import argparse
import hashlib
import json
import re
import subprocess
import urllib.request
from urllib.parse import quote

BASE = 'https://api.github.com/repos/mikolord/lumi'
START = '<!-- lumi-android-download -->'
END = '<!-- /lumi-android-download -->'


def download(url):
    if not url.startswith('https://github.com/mikolord/lumi/releases/download/'):
        raise ValueError('Android download must come from the public Lumi repository')
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def synchronize(api, server_tag, android_tag=None, fetch=download):
    if not re.fullmatch(r'v\d+\.\d+\.\d+', server_tag):
        raise ValueError('Expected a server release tag vX.Y.Z')
    server = api(BASE + '/releases/tags/' + server_tag)
    if server['draft'] or server['prerelease']:
        raise ValueError('Expected a published stable server release')
    if android_tag:
        android = api(BASE + '/releases/tags/' + quote(android_tag, safe=''))
    else:
        # Include prereleases explicitly; keep their beta status in the download block.
        candidates = []
        for page in range(1, 11):
            batch = api(BASE + f'/releases?per_page=100&page={page}')
            candidates.extend(x for x in batch if not x['draft'] and
                              x['tag_name'].startswith(('android-v', 'tv-v')))
            if len(batch) < 100:
                break
        if not candidates:
            raise ValueError('Publish an Android release before synchronizing downloads')
        android = max(candidates, key=lambda x: x['published_at'])
    if android['draft'] or not android['tag_name'].startswith(('android-v', 'tv-v')):
        raise ValueError('Expected a published Android or TV release')
    apk = [a for a in android['assets'] if a['name'].endswith('.apk')]
    manifests = [a for a in android['assets'] if a['name'] == 'tv-version.json']
    if len(apk) != 1 or len(manifests) != 1:
        raise ValueError('Android release must have one APK and its version manifest')
    info = json.loads(fetch(manifests[0]['browser_download_url']))
    data = fetch(apk[0]['browser_download_url'])
    if hashlib.sha256(data).hexdigest() != info['sha256']:
        raise ValueError('Published Android APK checksum mismatch')
    companion = (json.dumps(info, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    contents = [(apk[0]['name'], data, 'application/vnd.android.package-archive'),
                ('android-version.json', companion, 'application/json')]
    existing = {a['name']: a for a in server['assets']}
    # Validate every existing asset before uploading anything; never replace releases.
    for name, payload, _ in contents:
        if name in existing:
            expected = 'sha256:' + hashlib.sha256(payload).hexdigest()
            if existing[name].get('digest') != expected:
                raise ValueError('Asset differs; publish a new server release: ' + name)
    upload = server['upload_url'].split('{', 1)[0]
    for name, payload, mime in contents:
        if name not in existing:
            api(upload + '?name=' + quote(name), payload, mime)
    label = 'Android для телефонов, планшетов и ТВ' if android['tag_name'].startswith('android-v') else 'Android TV'
    status = ' — **бета**, устанавливается вручную' if android['prerelease'] else ''
    block = (START + '\n\n' + label + status + ': [' + info['versionName'] + '](' +
             apk[0]['browser_download_url'] + ').\n\n'
             'Для работы приложения нужен свой сервер Lumi в Docker. '
             'Стабильный канал обновлений ТВ не изменяется.\n\n' + END)
    body = server.get('body') or ''
    if START in body and END in body:
        body = body[:body.index(START)] + block + body[body.index(END) + len(END):]
    else:
        body = body.rstrip() + '\n\n' + block
    if body != (server.get('body') or ''):
        api(BASE + '/releases/' + str(server['id']), json.dumps({'body': body}, ensure_ascii=False).encode(), method='PATCH')
    return server['html_url']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-tag', required=True)
    parser.add_argument('--android-tag')
    args = parser.parse_args()
    result = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
                            text=True, capture_output=True, check=True)
    credentials = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    token = credentials.get('password')
    if not token:
        raise RuntimeError('GitHub authentication required')

    def api(url, body=None, content_type='application/json', method=None):
        if not url.startswith((BASE + '/', 'https://uploads.github.com/repos/mikolord/lumi/')):
            raise ValueError('Unexpected authenticated GitHub destination')
        request = urllib.request.Request(url, data=body, method=method, headers={
            'Authorization': 'Bearer ' + token, 'User-Agent': 'Lumi-release-sync',
            'Accept': 'application/vnd.github+json', 'Content-Type': content_type})
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)

    print('Android download synchronized:', synchronize(api, args.server_tag, args.android_tag))


if __name__ == '__main__':
    main()
