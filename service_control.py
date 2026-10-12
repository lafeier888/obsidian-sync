#!/usr/bin/env python3
"""Manage the local service on Windows, Linux and macOS."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import shlex
import shutil
import subprocess
import sys
import time

WINDOWS = os.name == 'nt'
if WINDOWS:
    import msvcrt
else:
    import fcntl

PROJECT = Path(__file__).resolve().parent
STATE = Path(os.environ.get('OBSYNC_STATE_DIR', str(PROJECT / '.run'))).expanduser().resolve()
LOG = STATE / 'server.log'
RECORD = STATE / 'server.json'


def process_info(pid):
    if WINDOWS:
        command = (f"[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); $p = Get-CimInstance Win32_Process -Filter 'ProcessId = {int(pid)}'; "
                   "if ($p) { @{born=$p.CreationDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ'); "
                   "command=$p.CommandLine} | ConvertTo-Json -Compress }")
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                capture_output=True, encoding='utf-8', errors='replace',
                                creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            data = json.loads(result.stdout.lstrip('\ufeff'))
            return data['born'] + ' ' + (data['command'] or '')
        except (ValueError, KeyError, TypeError):
            return ''
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart=', '-o', 'stat=', '-o', 'args='], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ''


def load_record():
    try:
        return json.loads(RECORD.read_text())
    except (OSError, ValueError):
        return {}


def running(record):
    pid = record.get('pid')
    if not isinstance(pid, int) or pid <= 1:
        return False
    info = process_info(pid)
    # Check process creation time and absolute script path before sending signals.
    return bool(info and info.startswith(record.get('born', '!')) and str(PROJECT / 'server.py') in info and (WINDOWS or not info.split()[5].startswith('Z')))


def recover_record(arguments):
    """Recover only a listener running this exact checkout and configuration."""
    if WINDOWS or not shutil.which('lsof'):
        return {}
    args = options(arguments)
    found = subprocess.run(['lsof', '-nP', '-t', f'-iTCP:{args.port}', '-sTCP:LISTEN'], capture_output=True, text=True)
    for value in set(found.stdout.split()):
        if not value.isdigit():
            continue
        pid = int(value)
        command = subprocess.run(['ps', '-p', str(pid), '-o', 'args='], capture_output=True, text=True).stdout.strip()
        tokens = shlex.split(command)
        script = str(PROJECT / 'server.py')
        if script not in tokens:
            continue
        actual_arguments = tokens[tokens.index(script)+1:]
        try:
            actual = options(actual_arguments)
        except SystemExit:
            continue
        if actual.host != args.host or actual.port != args.port:
            continue
        info = process_info(pid)
        record = {'pid':pid, 'born':info[:24], 'arguments':actual_arguments,
                  'url':f"http://{'127.0.0.1' if actual.host == '0.0.0.0' else actual.host}:{actual.port}"}
        if running(record):
            RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2))
            print(f'已恢复本项目服务的进程记录（PID {pid}）。')
            return record
    return {}


def options(arguments):
    parser = argparse.ArgumentParser(prog='./ob-sync.sh start')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8899)
    parser.add_argument('--vault', default='./notes')
    parser.add_argument('--remote-only', action='store_true')
    args = parser.parse_args(arguments)
    if not 1 <= args.port <= 65535:
        parser.error('port 必须在 1–65535 之间')
    return args


def start(arguments, record):
    if running(record):
        print(f"服务已运行，PID {record['pid']}，地址 {record['url']}；修改参数请使用 restart。")
        return
    args = options(arguments)
    # Fail explicitly when another service owns the selected address.
    for attempt in range(30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE if WINDOWS else socket.SO_REUSEADDR, 1)
            try:
                probe.bind((args.host, args.port))
                break
            except OSError as error:
                if attempt == 29:
                    diagnostic = f'netstat -ano | findstr :{args.port}' if WINDOWS else f'lsof -nP -iTCP:{args.port} -sTCP:LISTEN'
                    raise RuntimeError(f'无法监听 {args.host}:{args.port}：{error}。请使用 {diagnostic} 检查占用，或指定 --port。') from error
        time.sleep(.1)
    with LOG.open('ab') as output:
        process = subprocess.Popen([sys.executable, '-u', str(PROJECT / 'server.py'), *arguments], cwd=PROJECT, stdin=subprocess.DEVNULL, stdout=output, stderr=output, **({'creationflags':subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {'start_new_session':True}))
    host = '127.0.0.1' if args.host == '0.0.0.0' else args.host
    record = {'pid':process.pid, 'born':process_info(process.pid)[:24], 'arguments':arguments, 'url':f'http://{host}:{args.port}'}
    RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    for _ in range(50):
        if process.poll() is not None:
            raise RuntimeError('启动失败，日志：\n' + LOG.read_text(errors='replace')[-4000:])
        try:
            with socket.create_connection((host,args.port), timeout=.2):
                print(f"启动成功：{record['url']}（PID {process.pid}）\n日志：{LOG}")
                return
        except OSError:
            time.sleep(.1)
    if running(record):
        os.kill(process.pid, signal.SIGTERM)
    raise RuntimeError(f'等待启动超时，请查看日志：{LOG}')


def stop(record):
    if not running(record):
        print('服务未运行。')
        return
    pid = record['pid']
    os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        if not running(record):
            print(f'服务已停止（PID {pid}）。')
            return
        time.sleep(.1)
    if running(record):
        os.kill(pid, signal.SIGTERM if WINDOWS else signal.SIGKILL)
        for _ in range(20):
            if not running(record):
                print(f'服务已停止（PID {pid}）。')
                return
            time.sleep(.1)
    raise RuntimeError('停止失败，请检查进程状态。')


def main():
    parser = argparse.ArgumentParser(prog='./ob-sync.sh', description='后台启动、停止、重启及查看服务状态')
    parser.add_argument('action', choices=['start','stop','restart','status'])
    parser.add_argument('arguments', nargs=argparse.REMAINDER, help='start/restart 可传递 server.py 的启动参数')
    args = parser.parse_args()
    if args.action in ('stop','status') and args.arguments:
        parser.error('stop/status 不接收启动参数')
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE/'control.lock').open('a+b') as guard:
        if WINDOWS:
            guard.seek(0, 2)
            if guard.tell() == 0:
                guard.write(b'0'); guard.flush()
            for attempt in range(300):
                guard.seek(0)
                try:
                    msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if attempt == 299:
                        raise RuntimeError('另一个管理命令正在运行，请稍后重试。')
                    time.sleep(.1)
        else:
            fcntl.flock(guard, fcntl.LOCK_EX)
        record = load_record()
        if not running(record):
            recovery_arguments = record.get('arguments', [])
            if args.action in ('start', 'restart') and args.arguments:
                recovery_arguments = args.arguments
            record = recover_record(recovery_arguments) or record
        if args.action == 'status':
            print(f"服务运行中：{record['url']}（PID {record['pid']}）\n日志：{LOG}" if running(record) else '服务未运行（当前脚本没有正在运行的服务）。')
        elif args.action == 'stop':
            stop(record)
        elif args.action == 'restart':
            arguments = args.arguments or record.get('arguments', [])
            options(arguments)  # Validate before stopping a running service.
            stop(record)
            start(arguments, record)
        else:
            start(args.arguments, record)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
