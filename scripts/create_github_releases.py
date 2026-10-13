#!/usr/bin/env python3
"""Create and sync GitHub Releases via GitHub REST API."""
import json
import subprocess
import urllib.request
import sys

def get_token():
    auth_out = subprocess.check_output(
        ['git', 'credential', 'fill'],
        input='url=https://github.com/yimuhub/yimu-baokuanstudio.git\n',
        text=True
    )
    for line in auth_out.splitlines():
        if line.startswith('password='):
            return line.split('=', 1)[1]
    raise RuntimeError("No token found from git credential helper")

def get_existing_releases(token):
    req = urllib.request.Request(
        'https://api.github.com/repos/yimuhub/yimu-baokuanstudio/releases',
        headers={
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'YimuStudio-Release-Manager'
        }
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def create_or_update_release(token, tag, name, body, is_latest=False):
    existing = get_existing_releases(token)
    found_id = None
    for r in existing:
        if r.get('tag_name') == tag:
            found_id = r.get('id')
            break

    payload = {
        'tag_name': tag,
        'name': name,
        'body': body,
        'draft': False,
        'prerelease': False,
    }
    if is_latest:
        payload['make_latest'] = 'true'

    data = json.dumps(payload).encode('utf-8')
    if found_id:
        url = f'https://api.github.com/repos/yimuhub/yimu-baokuanstudio/releases/{found_id}'
        method = 'PATCH'
    else:
        url = 'https://api.github.com/repos/yimuhub/yimu-baokuanstudio/releases'
        method = 'POST'

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'YimuStudio-Release-Manager',
            'Content-Type': 'application/json'
        },
        method=method
    )
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode())
        print(f"[{method}] Release {tag}: {res.get('html_url')}")
        return res

if __name__ == '__main__':
    token = get_token()
    print("Fetched GitHub Token successfully.")
    releases = get_existing_releases(token)
    print(f"Found {len(releases)} existing releases.")
