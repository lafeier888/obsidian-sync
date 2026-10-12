const $ = id => document.getElementById(id);
const labels = {same:'一致',modified:'修改',local:'本地新增',remote:'远程新增',error:'无法对比'};
let files=[],session=null,selected=null,side='local',filter='all',generation=0,readVersion=0,syncing=false;
function readSetting(key){try{return localStorage.getItem('vault-'+key);}catch{return null;}}
function writeSetting(key,value){try{localStorage.setItem('vault-'+key,value);}catch{}}
const savedMode=readSetting('mode');
if(['http','directory'].includes(savedMode))$('mode').value=savedMode;
const savedLocal=readSetting('local');
if(savedLocal!==null)$('local').value=savedLocal;
const remoteValues={http:readSetting('remote-http'),directory:readSetting('remote-directory')};
// Migrate the previous single remote field only into its saved source mode.
if(remoteValues[$('mode').value]===null)remoteValues[$('mode').value]=readSetting('remote');
remoteValues.http??='http://127.0.0.1:9988';
remoteValues.directory??='';
let currentMode=$('mode').value;
$('remote').value=remoteValues[currentMode];
function saveRemote(){remoteValues[currentMode]=$('remote').value;writeSetting('remote-'+currentMode,remoteValues[currentMode]);}
function saveSettings(){writeSetting('local',$('local').value);writeSetting('mode',currentMode);saveRemote();}
function updateMode(){ $('remote-label').textContent=currentMode==='http'?'远程服务地址':'对比仓库路径'; $('remote').placeholder=currentMode==='http'?'http://192.168.1.10:9988':'/Volumes/RemoteVault'; }
updateMode();
$('local').addEventListener('input',()=>writeSetting('local',$('local').value));
$('local').addEventListener('change',()=>writeSetting('local',$('local').value));
$('remote').addEventListener('input',saveRemote);
$('remote').addEventListener('change',saveRemote);
$('mode').addEventListener('change',()=>{saveRemote();currentMode=$('mode').value;$('remote').value=remoteValues[currentMode];writeSetting('mode',currentMode);updateMode();});
async function api(route,data){const response=await fetch(route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); const result=await response.json();if(!response.ok)throw new Error(result.error||'请求失败');return result;}
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'success';}
function updateActions(){const status=selected?.status;$('push').hidden=!['local','modified'].includes(status);$('pull').hidden=!['remote','modified'].includes(status);$('push').disabled=syncing;$('pull').disabled=syncing;$('del').hidden=!selected?.remote;$('del').disabled=syncing;$('diff-tab').hidden=status!=='modified';}
function updateSummary(){const counts={};files.forEach(f=>counts[f.status]=(counts[f.status]||0)+1);$('summary').textContent=Object.entries(counts).map(([key,n])=>`${labels[key]} ${n}`).join(' · ')||'空仓库';}
function clearDocument(){ selected=null;readVersion++;$('filename').textContent='文档预览';$('filepath').textContent='选择左侧文件以查看内容';$('file-status').textContent='';$('local-tab').disabled=true;$('remote-tab').disabled=true;$('content').hidden=true;$('diff-view').hidden=true;$('placeholder').hidden=false; updateActions(); }
$('scan-form').addEventListener('submit',async event=>{event.preventDefault();saveSettings();const version=++generation;readVersion++;$('scan').disabled=true;$('scan').textContent='扫描中…';message('正在递归扫描并比较文件，请稍候…');try{const settings={local:$('local').value.trim(),remote:$('remote').value.trim(),mode:$('mode').value};const result=await api('/api/scan',settings);if(version!==generation)return;files=result.files;session=result.session;clearDocument();render();const counts={};files.forEach(f=>counts[f.status]=(counts[f.status]||0)+1);$('summary').textContent=Object.entries(counts).map(([key,n])=>`${labels[key]} ${n}`).join(' · ')||'空仓库';message(result.warnings.length?`扫描完成，但部分目录读取失败：${result.warnings.join('；')}`:`扫描完成，共 ${files.length} 个文件。`,!!result.warnings.length);}catch(error){message(error.message+'（保留上次扫描结果）',true);}finally{if(version===generation){$('scan').disabled=false;$('scan').textContent='↻ 扫描并对比';}}});
function render(){const tree=$('tree');tree.replaceChildren();$('count').textContent=`${files.length} 个文件`;const query=$('search').value.toLowerCase();const visible=files.filter(f=>(filter==='all'||f.status===filter)&&f.path.toLowerCase().includes(query));if(!visible.length){const empty=document.createElement('div');empty.className='empty-tree';empty.textContent=session?'没有匹配的文件':'填写仓库路径并扫描';tree.append(empty);return;}const root={dirs:new Map(),files:[]};visible.forEach(f=>{const parts=f.path.split('/');let node=root;for(const part of parts.slice(0,-1)){if(!node.dirs.has(part))node.dirs.set(part,{dirs:new Map(),files:[]});node=node.dirs.get(part);}node.files.push(f);});function draw(node,container){for(const [name,child] of node.dirs){const folder=document.createElement('details');folder.className='folder';folder.open=true;const heading=document.createElement('summary');heading.textContent='▱ '+name;folder.append(heading);const children=document.createElement('div');children.className='children';draw(child,children);folder.append(children);container.append(folder);}for(const f of node.files){const button=document.createElement('button');button.className='file'+(selected?.path===f.path?' selected':'');button.title=f.path+' · '+labels[f.status];button.setAttribute('aria-label',button.title);const icon=document.createElement('span');icon.className='file-icon';icon.textContent='▤';const name=document.createElement('span');name.className='name';name.textContent=f.path.split('/').pop();const dot=document.createElement('i');dot.className='dot '+f.status;button.append(icon,name,dot);if(f.status!=='same'){const status=document.createElement('span');status.className='status-label';status.textContent=labels[f.status];button.append(status);}button.addEventListener('click',()=>{selected=f;side=f.local?'local':'remote';render();show();});container.append(button);}}draw(root,tree);}
$('search').addEventListener('input',render);$('filters').addEventListener('click',event=>{const button=event.target.closest('[data-filter]');if(!button)return;filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));render();});
async function show(){if(!selected)return;if(side==='diff'&&selected.status!=='modified')side='local';updateActions();const version=++readVersion;const file=selected;$('filename').textContent=file.path.split('/').pop();$('filepath').textContent=file.path;$('file-status').textContent=labels[file.status];$('local-tab').disabled=!file.local;$('remote-tab').disabled=!file.remote;$('local-tab').classList.toggle('active',side==='local');$('remote-tab').classList.toggle('active',side==='remote');$('diff-tab').classList.toggle('active',side==='diff');$('diff-view').hidden=true;$('placeholder').hidden=true;$('content').hidden=false;$('content').textContent='正在读取…';try{if(side==='diff'){const result=await api('/api/diff',{session,path:file.path});if(version!==readVersion)return;renderDiff(result);return;}const result=await api('/api/read',{session,path:file.path,side});if(version!==readVersion)return;$('content').textContent=result.content===''?'（空文件）':result.content;$('details').textContent=`${side==='local'?'本地':'远程'} · ${result.content.length.toLocaleString()} 字符 · UTF-8`;}catch(error){if(version===readVersion){$('content').textContent='读取失败：'+error.message;$('details').textContent='无法读取';}}}
$('local-tab').addEventListener('click',()=>{side='local';show();});$('remote-tab').addEventListener('click',()=>{side='remote';show();});

async function syncFile(direction){
    if(syncing||!selected)return;
    const file=selected,token=session;
    syncing=true;updateActions();$('scan').disabled=true;
    message(`正在 ${direction==='push'?'推送到远程':'拉取到本地'}：${file.path}…`);
    try{
        await api('/api/sync',{session:token,path:file.path,direction});
        file.local=true;file.remote=true;file.status='same';file.error=null;
        render();updateSummary();
        if(selected?.path===file.path)await show();
        message(`${direction==='push'?'Push':'Pull'} 完成：${file.path}`);
    }catch(error){message(`同步失败：${error.message}`,true);}
    finally{syncing=false;updateActions();$('scan').disabled=false;}
}
$('push').addEventListener('click',()=>syncFile('push'));
$('pull').addEventListener('click',()=>syncFile('pull'));

async function deleteRemote(){
    if(syncing||!selected?.remote)return;
    const file=selected,token=session;
    syncing=true;updateActions();$('scan').disabled=true;
    message(`正在删除远程文件：${file.path}…`);
    try{
        await api('/api/delete',{session:token,path:file.path});
        file.remote=false;
        if(file.local){file.status=file.error?'error':'local';}
        else{files=files.filter(item=>item!==file);}
        if(selected===file){
            if(file.local){side='local';await show();}
            else{clearDocument();}
        }
        render();updateSummary();
        message(`已删除远程文件：${file.path}`);
    }catch(error){message(`删除失败：${error.message}`,true);}
    finally{syncing=false;updateActions();$('scan').disabled=false;}
}
$('del').addEventListener('click',deleteRemote);

$('diff-tab').addEventListener('click',()=>{side='diff';show();});
function renderDiff(result){
    const container=$('diff-view');container.replaceChildren();
    const note=document.createElement('div');note.className='diff-note';
    const {added,removed,modified}=result.counts;
    note.textContent=`本地 → 远程：新增 ${added} 行 · 删除 ${removed} 行 · 修改 ${modified} 行。行尾显示 LF / CRLF / 无换行。`;
    container.append(note);
    if(!added&&!removed&&!modified){note.textContent='当前两端内容已一致，请重新扫描更新状态。';}
    const table=document.createElement('table');table.className='diff-table';
    const head=document.createElement('thead'),heading=document.createElement('tr');
    for(const text of ['行','本地内容','行','远程内容']){const cell=document.createElement('th');cell.textContent=text;heading.append(cell);}head.append(heading);table.append(head);
    const body=document.createElement('tbody');
    for(const row of result.rows){
        const tr=document.createElement('tr');tr.className='diff-'+row.kind;
        for(const source of ['local','remote']){
            const number=document.createElement('td');number.className='line-number';number.textContent=row[source+'_line']??'';
            const cell=document.createElement('td');cell.className='diff-text '+source;
            const text=row[source];
            if(text!==null){
                const code=document.createElement('span');code.textContent=text.replace(/(\r\n|\n|\r)$/,'');
                const ending=document.createElement('span');ending.className='line-ending';ending.textContent=text.endsWith('\r\n')?'CRLF':text.endsWith('\n')?'LF':text.endsWith('\r')?'CR':'无换行';
                cell.append(code,ending);
            }
            tr.append(number,cell);
        }
        body.append(tr);
    }
    table.append(body);container.append(table);$('content').hidden=true;container.hidden=false;
    $('details').textContent='逐行对比 · 本地 → 远程';
}
