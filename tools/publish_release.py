"""Validate all three unsigned packages; --publish releases them on GitHub.

Uses GITHUB_TOKEN or the existing Git credential helper, in memory only.
No signing service, certificate or signing key is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kgstv import __version__

REPO = 'DH5DAX/open-kgstv'
TARGETS = ('windows-x64', 'linux-x64', 'linux-arm64')


def credentials():
    if os.environ.get('GITHUB_TOKEN'):
        return os.environ['GITHUB_TOKEN']
    result = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
                            text=True, capture_output=True, check=True, timeout=30,
                            env=dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never'))
    fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if not fields.get('password'):
        raise RuntimeError('No GitHub credential available')
    return fields['password']


def request(token, path, *, method='GET', payload=None, content_type='application/json'):
    url = path if path.startswith('https://') else 'https://api.github.com'+path
    if urllib.parse.urlparse(url).hostname not in ('api.github.com', 'uploads.github.com'):
        raise ValueError('Unexpected GitHub API destination')
    data = json.dumps(payload).encode() if isinstance(payload, dict) else payload
    req = urllib.request.Request(url, method=method, data=data, headers={
        'Authorization': 'Bearer '+token, 'Accept': 'application/vnd.github+json',
        'User-Agent': 'OpenKGSTV-release', 'Content-Type': content_type,
        'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


def verify():
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT, text=True):
        raise RuntimeError('Commit tracked source changes before preparing a release')
    assets = []
    for target in TARGETS:
        extension = '.zip' if target == 'windows-x64' else '.tar.gz'
        archive = ROOT/'dist'/target/f'OpenKGSTV-{__version__}-{target}{extension}'
        executable = 'OpenKGSTV.exe' if target == 'windows-x64' else 'OpenKGSTV'
        if extension == '.zip':
            with zipfile.ZipFile(archive) as package:
                info = json.loads(package.read('build-info.json'))
                binary = package.read(executable)
        else:
            with tarfile.open(archive) as package:
                info = json.load(package.extractfile('build-info.json'))
                binary = package.extractfile(executable).read()
                if not package.getmember(executable).mode & 0o111:
                    raise RuntimeError('Linux executable permission missing')
        if (info['version'], info['target'], info['commit']) != (__version__, target, commit):
            raise RuntimeError('Stale package version, target or source commit: '+str(archive))
        if info['binary']['signed'] or info['binary']['arch'] != target.split('-')[1]:
            raise RuntimeError('Unexpected signature or architecture')
        if not info['validation']['ok'] or not info['validation']['frozen']:
            raise RuntimeError('Frozen package validation missing')
        if hashlib.sha256(binary).hexdigest() != info['sha256']:
            raise RuntimeError('Archived binary hash mismatch')
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != archive.with_name(archive.name+'.sha256').read_text('ascii').split()[0]:
            raise RuntimeError('Archive checksum mismatch')
        assets.append((archive, digest))
    checksum = ROOT/'dist'/'SHA256SUMS.txt'
    checksum.write_text(''.join(f'{h}  {p.name}\n' for p, h in assets), encoding='ascii')
    return commit, assets+[(checksum, hashlib.sha256(checksum.read_bytes()).hexdigest())]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    commit, assets = verify()
    print(json.dumps({'commit': commit, 'assets': [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': h} for p, h in assets]}, indent=2))
    if not args.publish:
        return
    token, prefix = credentials(), '/repos/'+REPO
    if request(token, prefix+'/commits/main')['sha'] != commit:
        raise RuntimeError('Push this exact source commit to main before publishing')
    tag = 'v'+__version__
    release = next((r for r in request(token, prefix+'/releases?per_page=100') if r['tag_name'] == tag), None)
    if release and not release['draft']:
        raise RuntimeError('Published release exists; refusing to replace assets')
    body = (ROOT/'packaging/RELEASE-NOTES.md').read_text('utf-8')
    if not release:
        release = request(token, prefix+'/releases', method='POST', payload={
            'tag_name': tag, 'target_commitish': commit, 'name': 'Open KG-STV '+__version__+' — unsigned preview',
            'body': body, 'draft': True, 'prerelease': True})
    elif release['target_commitish'] != commit:
        raise RuntimeError('Existing draft belongs to a different source commit')
    existing = {a['name']: a for a in release['assets']}
    for path, digest in assets:
        if path.name in existing:
            if existing[path.name].get('digest') != 'sha256:'+digest:
                raise RuntimeError('Draft asset differs; refusing to overwrite '+path.name)
            continue
        url = release['upload_url'].split('{')[0]+'?name='+urllib.parse.quote(path.name)
        uploaded = request(token, url, method='POST', payload=path.read_bytes(), content_type='application/octet-stream')
        if uploaded['size'] != path.stat().st_size or uploaded.get('digest') != 'sha256:'+digest:
            raise RuntimeError('GitHub asset verification failed: '+path.name)
        print('Uploaded and checksum verified: '+path.name)
    published = request(token, prefix+'/releases/'+str(release['id']), method='PATCH',
                        payload={'draft': False, 'prerelease': True, 'body': body})
    print('Published: '+published['html_url'])


if __name__ == '__main__':
    main()
