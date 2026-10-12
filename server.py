#!/usr/bin/env python3
"""Local vault browser and compatible remote notes API. Python standard library only."""
import argparse
import hashlib
import difflib
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

WEB = Path(__file__).parent / 'web'
LIMIT = 10 * 1024 * 1024
sessions = {}
lock = threading.Lock()

def diff_lines(local, remote):
    left, right = local.splitlines(keepends=True), remote.splitlines(keepends=True)
    rows = []
    counts = {'added':0, 'removed':0, 'modified':0}
    for tag, a, b, c, d in difflib.SequenceMatcher(None, left, right).get_opcodes():
        count = max(b-a, d-c)
        for offset in range(count):
            li = a+offset if a+offset < b else None
            ri = c+offset if c+offset < d else None
            kind = 'same' if tag == 'equal' else 'added' if li is None else 'removed' if ri is None else 'modified'
            if kind != 'same': counts[kind] += 1
            rows.append({'kind':kind, 'local_line':li+1 if li is not None else None,
                         'remote_line':ri+1 if ri is not None else None,
                         'local':left[li] if li is not None else None,
                         'remote':right[ri] if ri is not None else None})
    return {'rows':rows, 'counts':counts}

def root_path(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('请输入仓库目录')
    root = Path(value).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError('仓库路径必须是目录')
    return root

def file_path(root, value):
    if not isinstance(value, str) or not value:
        raise ValueError('path 必须是非空字符串')
    value = value.replace('\\', '/')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or not p.parts:
        raise ValueError('无效的相对路径')
    for part in p.parts:
        stem = part.split('.')[0].upper()
        if any(ord(c) < 32 or c in '<>:"|?*' for c in part) or part.endswith((' ', '.')) or stem in {'CON','PRN','AUX','NUL', *(f'COM{i}' for i in range(1,10)), *(f'LPT{i}' for i in range(1,10))}:
            raise ValueError('无效的路径字符或文件名')
    result = root
    for part in p.parts:
        result = result / part
        if result.is_symlink():
            raise ValueError('不支持符号链接')
    if not result.resolve().is_relative_to(root):
        raise ValueError('路径超出仓库')
    return result, p.as_posix()

def listing(root, ignore_hidden=False):
    files, warnings = [], []
    def error(e):
        warnings.append(str(e))
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=error):
        dirs[:] = sorted(d for d in dirs if not (Path(directory)/d).is_symlink() and not (ignore_hidden and d.startswith('.')))
        for name in sorted(names):
            if ignore_hidden and name.startswith('.'):
                continue
            path = Path(directory)/name
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            try:
                content = path.read_bytes().decode('utf-8')
                files.append({'path': relative, 'hash': hashlib.sha256(content.encode('utf-8')).hexdigest()})
            except (OSError, UnicodeError) as e:
                files.append({'path': relative, 'hash': None, 'error': '无法读取 UTF-8 文本：'+str(e)})
    return files, warnings

def remote_call(url, route, payload):
    if not isinstance(url, str) or not url.startswith(('http://','https://')):
        raise ValueError('远程地址必须以 http:// 或 https:// 开头')
    req = urllib.request.Request(url.rstrip('/')+route, data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        if route == '/notes/list' and e.code == 404:
            raise ValueError('远程服务缺少 POST /notes/list，无法发现远程新增文件。请部署配套 server.py 或增加列表接口。') from e
        raise ValueError(f'远程请求失败：HTTP {e.code}') from e
    except (OSError, ValueError) as e:
        raise ValueError('远程请求失败：'+str(e)) from e

class Handler(BaseHTTPRequestHandler):
    def reply(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        name = {'/':'index.html','/app.js':'app.js','/style.css':'style.css'}.get(self.path)
        if not self.server.dashboard or not name:
            self.reply(404, {'error':'接口不存在'})
            return
        body = (WEB/name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(name)[0]+'; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            if self.headers.get('Transfer-Encoding'):
                self.reply(400, {'error':'不支持 Transfer-Encoding'}); return
            if self.headers.get_content_type() != 'application/json':
                self.reply(415, {'error':'请使用 application/json'}); return
            length = int(self.headers.get('Content-Length','-1'))
            if length < 0:
                self.reply(400, {'error':'需要 Content-Length'}); return
            if length > LIMIT:
                self.reply(413, {'error':'请求体超过大小限制'}); return
            self.connection.settimeout(30)
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('请求体必须为 JSON 对象')
            if self.path in ('/notes/write', '/notes/delete', '/notes/read', '/notes/list'):
                root = self.server.vault
                if self.path == '/notes/list':
                    files, warnings = listing(root)
                    self.reply(200, {'ok':True,'files':files,'warnings':warnings}); return
                path, relative = file_path(root, data.get('path'))
                if self.path == '/notes/write':
                    if not isinstance(data.get('content'),str):
                        raise ValueError('content 必须是字符串')
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(data['content'].encode('utf-8'))
                    result = {}
                elif self.path == '/notes/delete':
                    if not path.is_file():
                        if path.exists(): raise ValueError('删除目标必须为普通文件')
                        raise FileNotFoundError('文件不存在')
                    path.unlink()
                    result = {}
                else:
                    if not path.is_file():
                        if path.exists(): raise ValueError('读取目标必须为普通文件')
                        raise FileNotFoundError('文件不存在')
                    result = {'content':path.read_bytes().decode('utf-8')}
                self.reply(200, {'ok':True,'path':relative,'filename':path.name,**result}); return
            if not self.server.dashboard:
                self.reply(404, {'error':'接口不存在'}); return
            if self.path == '/api/scan':
                local = root_path(data.get('local'))
                mode = data.get('mode','http')
                local_files, warnings = listing(local, ignore_hidden=True)
                if mode == 'directory':
                    remote = root_path(data.get('remote'))
                    remote_files, other_warnings = listing(remote)
                    warnings += other_warnings
                elif mode == 'http':
                    remote = data.get('remote')
                    result = remote_call(remote, '/notes/list', {})
                    remote_files = result.get('files')
                    if not isinstance(remote_files,list): raise ValueError('远程列表格式应为 {files: [{path, hash}]}')
                    warnings += result.get('warnings',[])
                else: raise ValueError('无效的对比模式')
                left = {f['path']:f for f in local_files}
                right = {}
                for f in remote_files:
                    _, relative = file_path(local,f['path'])
                    if relative in right: raise ValueError('远程列表包含重复路径')
                    right[relative] = f
                rows = []
                for p in sorted(left.keys() | right.keys()):
                    a,b = left.get(p),right.get(p)
                    error = (a or {}).get('error') or (b or {}).get('error')
                    if error: status = 'error'
                    elif a is None: status = 'remote'
                    elif b is None: status = 'local'
                    else:
                        remote_hash = b.get('hash')
                        if not remote_hash and mode == 'http':
                            text = remote_call(remote,'/notes/read',{'path':p})['content']
                            remote_hash = hashlib.sha256(text.encode()).hexdigest()
                        status = 'same' if a['hash'] == remote_hash else 'modified'
                    rows.append({'path':p,'status':status,'local':a is not None,'remote':b is not None,'error':error})
                import secrets
                token = secrets.token_urlsafe(24)
                with lock:
                    if len(sessions) >= 30: sessions.pop(next(iter(sessions)))
                    sessions[token] = (local,remote,mode,set(left),set(right))
                self.reply(200, {'session':token,'files':rows,'warnings':warnings}); return
            if self.path in ('/api/read', '/api/sync', '/api/delete', '/api/diff'):
                with lock: session = sessions.get(data.get('session'))
                if not session: raise ValueError('扫描已过期，请重新扫描')
                local,remote,mode,left,right = session
                if self.path == '/api/diff':
                    path = data.get('path')
                    if path not in left or path not in right:
                        raise ValueError('Diff 需要本地和远程均存在此文件')
                    local_file, relative = file_path(local, path)
                    local_content = local_file.read_bytes().decode('utf-8')
                    if mode == 'http':
                        result = remote_call(remote, '/notes/read', {'path':relative})
                        remote_content = result.get('content')
                        if not isinstance(remote_content, str):
                            raise ValueError('远程未返回有效内容')
                    else:
                        remote_file, _ = file_path(remote, relative)
                        remote_content = remote_file.read_bytes().decode('utf-8')
                    self.reply(200, diff_lines(local_content, remote_content))
                    return
                if self.path == '/api/delete':
                    path = data.get('path')
                    if path not in right:
                        raise FileNotFoundError('远程文件不存在，请重新扫描')
                    _, relative = file_path(local, path)
                    if mode == 'http':
                        result = remote_call(remote, '/notes/delete', {'path':relative})
                        if result.get('ok') is not True:
                            raise ValueError(result.get('error') or '远程未确认删除成功')
                    else:
                        remote_file, _ = file_path(remote, relative)
                        if not remote_file.is_file():
                            if remote_file.exists(): raise ValueError('删除目标必须为普通文件')
                            raise FileNotFoundError('远程文件不存在')
                        remote_file.unlink()
                    with lock:
                        right.discard(relative)
                    self.reply(200, {'ok':True, 'path':relative})
                    return
                if self.path == '/api/sync':
                    direction = data.get('direction')
                    if direction not in ('push', 'pull'):
                        raise ValueError('direction 必须为 push 或 pull')
                    path = data.get('path')
                    if path not in (left if direction == 'push' else right):
                        raise FileNotFoundError('来源文件不存在，请重新扫描')
                    local_file, relative = file_path(local, path)
                    if mode == 'directory':
                        remote_file, _ = file_path(remote, path)
                        source = local_file if direction == 'push' else remote_file
                        target = remote_file if direction == 'push' else local_file
                        content = source.read_bytes().decode('utf-8')
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(content.encode('utf-8'))
                    elif direction == 'push':
                        content = local_file.read_bytes().decode('utf-8')
                        result = remote_call(remote, '/notes/write', {'path':relative, 'content':content})
                        if result.get('ok') is not True:
                            raise ValueError(result.get('error') or '远程未确认写入成功')
                    else:
                        result = remote_call(remote, '/notes/read', {'path':relative})
                        content = result.get('content')
                        if result.get('ok') is not True or not isinstance(content, str):
                            raise ValueError(result.get('error') or '远程未返回有效内容')
                        local_file.parent.mkdir(parents=True, exist_ok=True)
                        local_file.write_bytes(content.encode('utf-8'))
                    with lock:
                        left.add(relative)
                        right.add(relative)
                    self.reply(200, {'ok':True, 'path':relative, 'status':'same'})
                    return
                side = data.get('side')
                if side not in ('local','remote'): raise ValueError('无效的来源')
                path = data.get('path')
                if path not in (left if side=='local' else right): raise FileNotFoundError('文件不存在')
                if side == 'remote' and mode == 'http':
                    content = remote_call(remote,'/notes/read',{'path':path})['content']
                else:
                    file, _ = file_path(local if side=='local' else remote,path)
                    content = file.read_bytes().decode('utf-8')
                self.reply(200, {'content':content}); return
            self.reply(404, {'error':'接口不存在'})
        except FileNotFoundError:
            self.reply(404, {'error':'文件或仓库不存在'})
        except TimeoutError:
            self.reply(408, {'error':'读取请求超时'})
        except (ValueError, UnicodeError, KeyError, TypeError) as e:
            self.reply(400, {'error':str(e)})
        except OSError as e:
            self.reply(500, {'error':str(e)})

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8899)
    parser.add_argument('--vault',default='./notes')
    parser.add_argument('--remote-only',action='store_true')
    args = parser.parse_args()
    vault = Path(args.vault).expanduser().resolve()
    vault.mkdir(parents=True,exist_ok=True)
    server = ThreadingHTTPServer((args.host,args.port),Handler)
    server.vault,server.dashboard = vault,not args.remote_only
    print(f'服务已启动：http://{args.host}:{args.port}',flush=True)
    server.serve_forever()
