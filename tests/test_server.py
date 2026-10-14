import json
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
from pathlib import Path
from http.server import ThreadingHTTPServer
import server

class VaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.local = Path(self.temp.name).resolve()/'local'
        self.remote = Path(self.temp.name).resolve()/'remote'
        self.local.mkdir(); self.remote.mkdir()
        for root, entries in [(self.local,{'目录/相同.md':'内容\r\n','修改.md':'本地','本地.md':'新增','空.md':''}), (self.remote,{'目录/相同.md':'内容\r\n','修改.md':'远程','远程.md':'新增','空.md':''})]:
            for p, text in entries.items():
                file=root/p;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(text.encode())
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.http.vault=self.remote;self.http.dashboard=True
        threading.Thread(target=self.http.serve_forever,daemon=True).start()
        self.url=f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.temp.cleanup()

    def post(self,route,data):
        request=urllib.request.Request(self.url+route,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request) as response:return json.load(response)

    def test_directory_and_http_comparison(self):
        for mode, remote in [('directory',str(self.remote)),('http',self.url)]:
            scan=self.post('/api/scan',{'local':str(self.local),'remote':remote,'mode':mode})
            statuses={f['path']:f['status'] for f in scan['files']}
            self.assertEqual(statuses,{'目录/相同.md':'same','修改.md':'modified','本地.md':'local','远程.md':'remote','空.md':'same'})
            content=self.post('/api/read',{'session':scan['session'],'path':'目录/相同.md','side':'local'})
            self.assertEqual(content['content'],'内容\r\n')
            content=self.post('/api/read',{'session':scan['session'],'path':'远程.md','side':'remote'})
            self.assertEqual(content['content'],'新增')

    def test_nontext_and_symlink(self):
        (self.local/'binary').write_bytes(b'\xff')
        (self.local/'link.md').symlink_to(self.remote/'远程.md')
        scan=self.post('/api/scan',{'local':str(self.local),'remote':str(self.remote),'mode':'directory'})
        rows={f['path']:f for f in scan['files']}
        self.assertEqual(rows['binary']['status'],'error')
        self.assertNotIn('link.md',rows)

    def test_compatible_api_and_path_safety(self):
        self.post('/notes/write',{'path':'新目录\\新文件.md','content':'正文\n'})
        self.assertEqual(self.post('/notes/read',{'path':'新目录/新文件.md'})['content'],'正文\n')
        for path in ['../outside.md','/etc/passwd','C:\\x.md','NUL.md']:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post('/notes/read',{'path':path})
            self.assertEqual(error.exception.code,400)
        (self.remote/'link').symlink_to(self.local/'本地.md')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post('/notes/write',{'path':'link','content':'bad'})
        self.assertEqual(error.exception.code,400)

    def test_hidden_local_files_and_directories_are_skipped(self):
        (self.local/'.hidden.md').write_text('hidden')
        (self.local/'.obsidian').mkdir()
        (self.local/'.obsidian'/'config.json').write_text('{}')
        (self.local/'目录'/'.nested.md').write_text('hidden')
        scan=self.post('/api/scan',{'local':str(self.local),'remote':str(self.remote),'mode':'directory'})
        self.assertFalse(any(any(p.startswith('.') for p in f['path'].split('/')) for f in scan['files']))

    def test_remote_deletion_in_both_modes(self):
        for mode, remote in [('directory',str(self.remote)),('http',self.url)]:
            (self.remote/'修改.md').write_text('远程')
            (self.remote/'远程.md').write_text('新增')
            scan=self.post('/api/scan',{'local':str(self.local),'remote':remote,'mode':mode})
            before=(self.local/'修改.md').read_bytes()
            for path in ['修改.md','远程.md']:
                result=self.post('/api/delete',{'session':scan['session'],'path':path})
                self.assertTrue(result['ok'])
                self.assertFalse((self.remote/path).exists())
                with self.assertRaises(urllib.error.HTTPError):
                    self.post('/api/read',{'session':scan['session'],'path':path,'side':'remote'})
            self.assertEqual((self.local/'修改.md').read_bytes(),before)
            again=self.post('/api/scan',{'local':str(self.local),'remote':remote,'mode':mode})
            rows={f['path']:f['status'] for f in again['files']}
            self.assertEqual(rows['修改.md'],'local')
            self.assertNotIn('远程.md',rows)
            with self.assertRaises(urllib.error.HTTPError):
                self.post('/api/delete',{'session':scan['session'],'path':'../escape.md'})

    def test_diff_in_both_modes_is_read_only(self):
        for mode, remote in [('directory',str(self.remote)),('http',self.url)]:
            scan=self.post('/api/scan',{'local':str(self.local),'remote':remote,'mode':mode})
            before=[(root/'修改.md').read_bytes() for root in [self.local,self.remote]]
            result=self.post('/api/diff',{'session':scan['session'],'path':'修改.md'})
            self.assertEqual(result['counts'],{'added':0,'removed':0,'modified':1})
            self.assertEqual(result['rows'][0]['local'],'本地')
            self.assertEqual(result['rows'][0]['remote'],'远程')
            self.assertEqual(before,[(root/'修改.md').read_bytes() for root in [self.local,self.remote]])
            with self.assertRaises(urllib.error.HTTPError):
                self.post('/api/diff',{'session':scan['session'],'path':'本地.md'})

    def test_diff_add_remove_and_line_endings(self):
        self.assertEqual(server.diff_lines('', 'new\n')['counts']['added'],1)
        self.assertEqual(server.diff_lines('old\n', '')['counts']['removed'],1)
        for left,right in [('中文\r\n','中文\n'),('中文','中文\n')]:
            result=server.diff_lines(left,right)
            self.assertEqual(result['counts']['modified'],1)
            self.assertEqual(result['rows'][0]['local'],left)
        self.assertEqual(server.diff_lines('', '')['rows'],[])

    def test_smart_merge_blank_line_and_final_newline(self):
        local='superpowers\nspce-kit\nopenspec\nkiro\n\n数据治理专项-商店\n- 流通/质量/存储/计算/埋点'
        remote='superpowers\nspce-kit\nopenspec\nkiro\n1\n数据治理专项-商店\n- 流通/质量/存储/计算/埋点\n'
        blocks=server.merge_blocks(local,remote)
        self.assertNotIn('replace',[b['kind'] for b in blocks if '埋点' in b['local']])
        self.assertEqual(''.join(b['auto_result'] if b['auto_result'] is not None else b['local'] for b in blocks),remote.rstrip('\n'))
        self.assertTrue(any(b['kind']=='format' for b in blocks))
        self.assertTrue(any(b['auto_reason']=='本地为空，保留远程内容' for b in blocks))
        self.assertEqual(''.join(b['local'] for b in blocks),local)
        self.assertEqual(''.join(b['remote'] for b in blocks),remote)
        self.assertIsNone(server.merge_blocks('left\n','right\n')[0]['auto_result'])

    def test_modification_times(self):
        result=self.post('/notes/read',{'path':'修改.md'})
        self.assertEqual(result['mtime'],(self.remote/'修改.md').stat().st_mtime)
        for mode,remote in [('directory',str(self.remote)),('http',self.url)]:
            scan=self.post('/api/scan',{'local':str(self.local),'remote':remote,'mode':mode})
            row=next(f for f in scan['files'] if f['path']=='修改.md')
            self.assertEqual(row['local_mtime'],(self.local/'修改.md').stat().st_mtime)
            result=self.post('/api/merge',{'session':scan['session'],'path':'修改.md','action':'load'})
            self.assertEqual(result['remote_mtime'],(self.remote/'修改.md').stat().st_mtime)

    def test_directory_exclusions_in_both_modes(self):
        for root in (self.local,self.remote):
            for relative in ['附件/a.md','子目录/附件/b.md','归档/旧笔记/c.md','归档/新笔记/d.md']:
                path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('text')
        for mode,remote in [('directory',str(self.remote)),('http',self.url)]:
            result=self.post('/api/scan',{'local':str(self.local),'remote':remote,'mode':mode,'exclude_dirs':['附件','归档/旧笔记']})
            paths={file['path'] for file in result['files']}
            self.assertNotIn('附件/a.md',paths)
            self.assertNotIn('子目录/附件/b.md',paths)
            self.assertNotIn('归档/旧笔记/c.md',paths)
            self.assertIn('归档/新笔记/d.md',paths)
            with self.assertRaises(urllib.error.HTTPError):
                self.post('/api/delete',{'session':result['session'],'path':'附件/a.md'})

    def test_merge_targets_and_conflict(self):
        for mode,remote in [('directory',str(self.remote)),('http',self.url)]:
            for target in ['local','remote','both']:
                (self.local/'修改.md').write_text('本地')
                (self.remote/'修改.md').write_text('远程')
                scan=self.post('/api/scan',{'local':str(self.local),'remote':remote,'mode':mode})
                request={'session':scan['session'],'path':'修改.md','action':'load'}
                original=self.post('/api/merge',request)
                self.assertEqual(''.join(block['local'] for block in original['blocks']),original['local'])
                self.assertEqual(''.join(block['remote'] for block in original['blocks']),original['remote'])
                result=self.post('/api/merge',{**request,'action':'save','hashes':original['hashes'],'target':target,'content':'合并\r\n'})
                self.assertTrue(result['ok'])
                self.assertEqual(result['status'],'same' if target=='both' else 'modified')
                for side,root in [('local',self.local),('remote',self.remote)]:
                    expected='合并\r\n' if target in (side,'both') else ('本地' if side=='local' else '远程')
                    self.assertEqual((root/'修改.md').read_bytes(),expected.encode())
                original=self.post('/api/merge',request)
                (self.remote/'修改.md').write_text('更新')
                before=(self.local/'修改.md').read_bytes()
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.post('/api/merge',{**request,'action':'save','hashes':original['hashes'],'target':'both','content':'旧草稿'})
                self.assertEqual(error.exception.code,409)
                self.assertEqual((self.local/'修改.md').read_bytes(),before)
                self.assertEqual((self.remote/'修改.md').read_text(),'更新')

    def test_delete_failure_preserves_session_and_files(self):
        scan=self.post('/api/scan',{'local':str(self.local),'remote':self.url,'mode':'http'})
        with patch('server.remote_call', return_value={'ok':False,'error':'拒绝删除'}) as call:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post('/api/delete',{'session':scan['session'],'path':'修改.md'})
            self.assertEqual(error.exception.code,400)
            call.assert_called_once_with(self.url,'/notes/delete',{'path':'修改.md'})
        self.assertTrue((self.remote/'修改.md').exists())
        self.assertIn('修改.md',server.sessions[scan['session']][4])

    def test_delete_rejects_directory_and_symlink(self):
        (self.remote/'folder').mkdir()
        (self.remote/'link').symlink_to(self.local/'本地.md')
        for path in ['folder','link','../escape.md']:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post('/notes/delete',{'path':path})
            self.assertEqual(error.exception.code,400)
        self.assertTrue((self.local/'本地.md').exists())

    def test_push_pull_in_both_modes(self):
        for mode, remote in [('directory',str(self.remote)),('http',self.url)]:
            (self.remote/'本地.md').unlink(missing_ok=True)
            (self.local/'远程.md').unlink(missing_ok=True)
            (self.local/'修改.md').write_bytes(b'local\r\n')
            (self.remote/'修改.md').write_bytes(b'remote\n')
            scan=self.post('/api/scan',{'local':str(self.local),'remote':remote,'mode':mode})
            for path,direction in [('本地.md','push'),('远程.md','pull'),('修改.md','push')]:
                result=self.post('/api/sync',{'session':scan['session'],'path':path,'direction':direction})
                self.assertTrue(result['ok'])
                self.assertEqual((self.local/path).read_bytes(),(self.remote/path).read_bytes())
            (self.remote/'修改.md').write_bytes('新的远程内容\r\n'.encode())
            self.post('/api/sync',{'session':scan['session'],'path':'修改.md','direction':'pull'})
            self.assertEqual((self.local/'修改.md').read_bytes(),'新的远程内容\r\n'.encode())
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post('/api/sync',{'session':scan['session'],'path':'../escape.md','direction':'pull'})
            self.assertEqual(error.exception.code,404)

if __name__=='__main__':unittest.main()
