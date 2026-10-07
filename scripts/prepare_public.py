"""Create a code-only publication snapshot under this project's tmp directory.

No Git command, external transmission, recursive deletion or Vault operation.
The explicit allowlist is independent of the working checkout's Git ignore state.
"""
from __future__ import annotations
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def selected():
    files=[]
    for folder,suffixes in [('app',{'.py'}),('tests',{'.py','.cjs'}),('web',{'.html','.css','.js'}),('browser-extension',{'.json','.html','.css','.js','.md'}),('.github',{'.yml','.yaml'}),('scripts',{'.py'})]:
        for path in (ROOT/folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix in suffixes:files.append((path,path.relative_to(ROOT)))
    for name in ('config.example.json','pytest.ini','requirements.txt','requirements.lock.txt','requirements-gpu.txt','start.ps1','启动.cmd','安装转写.ps1','web/assets/desk-wallpaper.png','docs/第一层到主题材料区提示词.md'):
        files.append((ROOT/name,Path(name)))
    for path in (ROOT/'docs/public').glob('*'):
        if path.is_file():
            target=Path(path.name) if path.name in ('README.md','LICENSE','CHANGELOG.md','CONTRIBUTING.md','AGENTS.md') else Path('docs')/path.name
            files.append((path,target))
    return files

def private_checks():
    cfg_path=ROOT/'config.json'
    cfg=json.loads(cfg_path.read_text('utf-8')) if cfg_path.exists() else {}
    secrets=[str(ROOT),str(Path.home())]
    secrets.extend(cfg[k] for k in ('obsidian_vault','ai_api_key','firecrawl_api_key','x_client_id') if cfg.get(k))
    credentials=ROOT/'data/credentials'
    if list(credentials.glob('*.dpapi')):
        from app import sessions
        for platform in sessions.PAGES:
            if sessions.path(platform).exists():
                state=sessions.load(platform)
                secrets.extend(c['value'] for c in state.get('cookies',[]) if len(c.get('value',''))>=16)
                secrets.extend(c['value'] for o in state.get('origins',[]) for c in o.get('localStorage',[]) if len(c.get('value',''))>=16)
    identifiers=set();originals=[]
    database=ROOT/'data/library.sqlite3'
    if database.is_file():
        with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as conn:
            for canonical,body in conn.execute('SELECT canonical,body FROM materials'):
                parsed=urlparse(canonical)
                match=re.search(r'/(?:status|link|video)/([A-Za-z0-9_-]+)',parsed.path)
                if match:identifiers.add(match[1])
                if parsed.hostname=='www.youtube.com':
                    from urllib.parse import parse_qs
                    identifiers.update(parse_qs(parsed.query).get('v',[]))
                if len(body)>=80:originals.append(body)
    return secrets,identifiers,originals

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='tmp/public-release/shoucang')
    args=parser.parse_args()
    destination=(ROOT/args.output).resolve()
    allowed=(ROOT/'tmp').resolve()
    if destination==allowed or not destination.is_relative_to(allowed):raise SystemExit('输出仅允许项目 tmp 内的独立子目录')
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):raise SystemExit('输出目录非空；请使用新的独立目录，不覆盖现有文件')
    secrets,identifiers,originals=private_checks()
    mapping={value:(str(9000000000000000000+i) if value.isdigit() else 'BV1TST'+str(i).zfill(6) if value.startswith('BV') else 'TST'+str(i).zfill(8)) for i,value in enumerate(sorted(identifiers))}
    prepared=[];rewritten=0
    for source,target in selected():
        if source.is_symlink():raise SystemExit('拒绝链接源文件：'+str(target))
        data=source.read_bytes()
        if source.suffix!='.png':
            value=data.decode('utf-8')
            if target.parts[0]=='tests':
                for private,replacement in mapping.items():
                    if private in value:value=value.replace(private,replacement);rewritten+=1
            for secret in secrets:
                if secret in value or secret.replace('\\','\\\\') in value or secret.replace('\\','/') in value:
                    raise SystemExit('发现个人路径或凭据；未生成发布目录：'+str(target))
            if any(body in value for body in originals):raise SystemExit('发现现有收藏原文；未生成发布目录：'+str(target))
            if re.search(r'\b(?:ghp_|github_pat_|sk-live-|sk-proj-)[A-Za-z0-9_-]{20,}',value):raise SystemExit('疑似真实凭据；未生成发布目录：'+str(target))
            if target.parts[0]!='tests' and any(identifier in value for identifier in identifiers):
                raise SystemExit('代码或文档中含现有来源标识；未生成发布目录：'+str(target))
            data=value.encode('utf-8')
        prepared.append((target,data))
    destination.mkdir(parents=True,exist_ok=True)
    for target,data in prepared:
        path=destination/target;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    ignore='''data/
tmp/
.venv/
.pytest_cache/
__pycache__/
*.pyc
*.log
config.json
config.tmp
.env
.env.*
*.sqlite3
*.sqlite3-*
*.dpapi
docs/design/
CODEX_HISTORY.md
'''
    (destination/'.gitignore').write_text(ignore,'utf-8')
    print(json.dumps({'output':str(destination),'files':len(prepared)+1,'synthetic_test_identifiers':rewritten,'private_files_included':0},ensure_ascii=False))

if __name__=='__main__':main()
