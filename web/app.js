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
$('exclude-dirs').value=readSetting('exclude-dirs')??'';
$('exclude-dirs').addEventListener('input',()=>{writeSetting('exclude-dirs',$('exclude-dirs').value);if(session&&!syncing){session=null;files=[];clearDocument();render();updateSummary();message('过滤配置已保存，请重新扫描。');}});
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
function updateActions(){$('exclude-dirs').disabled=syncing;const status=selected?.status;$('push').hidden=!['local','modified'].includes(status);$('pull').hidden=!['remote','modified'].includes(status);$('push').disabled=syncing;$('pull').disabled=syncing;$('del').hidden=!selected?.remote;$('del').disabled=syncing;$('diff-tab').hidden=status!=='modified';$('merge-tab').hidden=status!=='modified';}
function updateSummary(){const counts={};files.forEach(f=>counts[f.status]=(counts[f.status]||0)+1);$('summary').textContent=Object.entries(counts).map(([key,n])=>`${labels[key]} ${n}`).join(' · ')||'空仓库';}
function clearDocument(){ selected=null;readVersion++;$('file-times').textContent='';$('filename').textContent='文档预览';$('filepath').textContent='选择左侧文件以查看内容';$('file-status').textContent='';$('local-tab').disabled=true;$('remote-tab').disabled=true;$('content').hidden=true;$('diff-view').hidden=true;$('merge-view').hidden=true;$('placeholder').hidden=false; updateActions(); }
$('scan-form').addEventListener('submit',async event=>{event.preventDefault();if(syncing)return;saveSettings();const version=++generation;readVersion++;$('scan').disabled=true;$('scan').textContent='扫描中…';message('正在递归扫描并比较文件，请稍候…');try{const settings={local:$('local').value.trim(),remote:$('remote').value.trim(),mode:$('mode').value,exclude_dirs:$('exclude-dirs').value.split(/[\n,，、]/).map(s=>s.trim()).filter(Boolean)};const result=await api('/api/scan',settings);if(version!==generation)return;files=result.files;session=result.session;clearDocument();render();const counts={};files.forEach(f=>counts[f.status]=(counts[f.status]||0)+1);$('summary').textContent=Object.entries(counts).map(([key,n])=>`${labels[key]} ${n}`).join(' · ')||'空仓库';message(result.warnings.length?`扫描完成，但部分目录读取失败：${result.warnings.join('；')}`:`扫描完成，共 ${files.length} 个文件。`,!!result.warnings.length);}catch(error){message(error.message+'（保留上次扫描结果）',true);}finally{if(version===generation){$('scan').disabled=false;$('scan').textContent='↻ 扫描并对比';}}});
function render(){const tree=$('tree');tree.replaceChildren();$('count').textContent=`${files.length} 个文件`;const query=$('search').value.toLowerCase();const visible=files.filter(f=>(filter==='all'||f.status===filter)&&f.path.toLowerCase().includes(query));if(!visible.length){const empty=document.createElement('div');empty.className='empty-tree';empty.textContent=session?'没有匹配的文件':'填写仓库路径并扫描';tree.append(empty);return;}const root={dirs:new Map(),files:[]};visible.forEach(f=>{const parts=f.path.split('/');let node=root;for(const part of parts.slice(0,-1)){if(!node.dirs.has(part))node.dirs.set(part,{dirs:new Map(),files:[]});node=node.dirs.get(part);}node.files.push(f);});function draw(node,container,prefix=''){for(const [name,child] of node.dirs){const folder=document.createElement('details');folder.className='folder';folder.open=true;const heading=document.createElement('summary');heading.textContent='▱ '+name;const path=prefix?prefix+'/'+name:name;const actions=document.createElement('span');actions.className='folder-actions';for(const action of ['push','pull','del']){const control=document.createElement('button');control.type='button';control.textContent=action==='del'?'Del':action==='push'?'Push':'Pull';control.title=`${path}：递归 ${action}，不受搜索或状态筛选影响`;control.setAttribute('aria-label',`${path} ${action}`);control.disabled=syncing||!batchTargets(path,action).length;control.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();batchDirectory(path,action);});actions.append(control);}heading.append(actions);folder.append(heading);const children=document.createElement('div');children.className='children';draw(child,children,path);folder.append(children);container.append(folder);}for(const f of node.files){const button=document.createElement('button');button.className='file'+(selected?.path===f.path?' selected':'');button.title=f.path+' · '+labels[f.status];button.setAttribute('aria-label',button.title);const icon=document.createElement('span');icon.className='file-icon';icon.textContent='▤';const name=document.createElement('span');name.className='name';name.textContent=f.path.split('/').pop();const dot=document.createElement('i');dot.className='dot '+f.status;button.append(icon,name,dot);if(f.status!=='same'){const status=document.createElement('span');status.className='status-label';status.textContent=labels[f.status];button.append(status);}button.addEventListener('click',()=>{selected=f;side=f.local?'local':'remote';render();show();});container.append(button);}}draw(root,tree);}
$('search').addEventListener('input',render);$('filters').addEventListener('click',event=>{const button=event.target.closest('[data-filter]');if(!button)return;filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));render();});
async function show(){if(!selected)return;if(['diff','merge'].includes(side)&&selected.status!=='modified')side='local';updateActions();const version=++readVersion;const file=selected;showFileTimes(file);$('filename').textContent=file.path.split('/').pop();$('filepath').textContent=file.path;$('file-status').textContent=labels[file.status];$('local-tab').disabled=!file.local;$('remote-tab').disabled=!file.remote;$('local-tab').classList.toggle('active',side==='local');$('remote-tab').classList.toggle('active',side==='remote');$('diff-tab').classList.toggle('active',side==='diff');$('merge-tab').classList.toggle('active',side==='merge');$('diff-view').hidden=true;$('merge-view').hidden=true;$('placeholder').hidden=true;$('content').hidden=false;$('content').textContent='正在读取…';try{if(side==='merge'){await openMerge(file,version);return;}if(side==='diff'){const result=await api('/api/diff',{session,path:file.path});if(version!==readVersion)return;renderDiff(result);return;}const result=await api('/api/read',{session,path:file.path,side});if(version!==readVersion)return;file[side+'_mtime']=result.mtime??file[side+'_mtime'];showFileTimes(file);$('content').textContent=result.content===''?'（空文件）':result.content;$('details').textContent=`${side==='local'?'本地':'远程'} · ${result.content.length.toLocaleString()} 字符 · UTF-8`;}catch(error){if(version===readVersion){$('content').textContent='读取失败：'+error.message;$('details').textContent='无法读取';}}}
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

function batchTargets(directory,action){
    return files.filter(file=>file.path.startsWith(directory+'/')&&
        (action==='del'?file.remote:action==='push'?['local','modified'].includes(file.status):['remote','modified'].includes(file.status)));
}
async function batchDirectory(directory,action){
    if(syncing||!session)return;
    const targets=batchTargets(directory,action),token=session;
    if(!targets.length)return;
    syncing=true;updateActions();$('scan').disabled=true;$('exclude-dirs').disabled=true;render();
    let succeeded=0;const failures=[];
    try{
        for(const [index,file] of targets.entries()){
            message(`${directory} ${action}：${index+1}/${targets.length} · ${file.path}`);
            try{
                await api(action==='del'?'/api/delete':'/api/sync',{session:token,path:file.path,direction:action});
                if(action==='del'){
                    file.remote=false;
                    if(file.local)file.status=file.error?'error':'local';
                    else files=files.filter(item=>item!==file);
                }else{file.local=true;file.remote=true;file.status='same';file.error=null;}
                succeeded++;
            }catch(error){failures.push(`${file.path}：${error.message}`);}
        }
        if(selected){
            if(!files.includes(selected))clearDocument();
            else{if(!selected.remote)side='local';await show();}
        }
        updateSummary();
        message(`${directory} ${action} 完成：成功 ${succeeded}，失败 ${failures.length}。${failures.join('；')}`,!!failures.length);
    }finally{syncing=false;updateActions();$('scan').disabled=false;$('exclude-dirs').disabled=false;render();}
}

const mergeDrafts=new Map();
let mergeKey=null,activeChange=-1;
function mergeDraftKey(file){return session+'|'+file.path;}
function composeMerge(draft){return draft.blocks.map(block=>block.result).join('');}
function initializeMerge(original,previous){
    let blocks=original.blocks.map(block=>({...block,result:block.auto_result??block.local,choice:block.kind==='equal'?'same':block.auto_result!=null?'auto':null}));
    // If the sources changed, retain the complete edited draft as one editable block.
    if(previous){
        if(previous.hashes.local===original.hashes.local&&previous.hashes.remote===original.hashes.remote)blocks=previous.blocks;
        else blocks=[{kind:'replace',local:original.local,remote:original.remote,local_start:1,remote_start:1,result:composeMerge(previous),choice:'manual'}];
    }
    return {...original,blocks};
}
async function openMerge(file,version,force=false){
    const key=mergeDraftKey(file);let draft=mergeDrafts.get(key);
    if(!draft||force){
        const original=await api('/api/merge',{session,path:file.path,action:'load'});
        if(version!==readVersion)return;
        draft=initializeMerge(original,draft);mergeDrafts.set(key,draft);
    }
    if(version!==readVersion)return;
    file.local_mtime=draft.local_mtime;file.remote_mtime=draft.remote_mtime??file.remote_mtime;showFileTimes(file);$('merge-local-time').textContent='修改时间：'+formatMtime(file.local_mtime);$('merge-remote-time').textContent='修改时间：'+formatMtime(file.remote_mtime);mergeKey=key;activeChange=-1;$('merge-path').textContent=file.path;
    $('content').hidden=true;$('merge-view').hidden=false;$('details').textContent='三栏合并';
    $('merge-notice').textContent='已自动保留单侧内容和处理换行差异；不同的实质内容需选择。无历史基础时不自动推断删除，未处理块暂保留本地。';
    renderMerge(draft);
}
function mergeLineCount(text){return text?(text.match(/\r\n|\r|\n/g)||[]).length+(text.endsWith('\n')||text.endsWith('\r')?0:1):0;}
function mergeNumbers(text,start){return Array.from({length:mergeLineCount(text)},(_,i)=>start+i).join('\n');}
function updateMergeProgress(){
    const draft=mergeDrafts.get(mergeKey);if(!draft)return;
    const changes=draft.blocks.filter(b=>b.kind!=='equal');
    $('merge-progress').textContent=`${changes.length} 处差异 · ${changes.filter(b=>b.choice!==null).length} 已处理`;
    $('previous-change').disabled=syncing||!changes.length;$('next-change').disabled=syncing||!changes.length;
    let start=1;
    for(const [index,block] of draft.blocks.entries()){
        const row=$('merge-blocks').children[index];
        row.querySelector('.result-lines').textContent=mergeNumbers(block.result,start);
        start+=mergeLineCount(block.result);
        const editor=row.querySelector('textarea');
        editor.style.height=Math.max(1,mergeLineCount(block.local),mergeLineCount(block.remote),mergeLineCount(block.result))*22+'px';
    }
}
function acceptMergeBlock(index,choice){
    if(syncing)return;const draft=mergeDrafts.get(mergeKey),block=draft.blocks[index];
    block.result=choice==='local'?block.local:choice==='remote'?block.remote:choice==='both'?block.local+(block.local&&block.remote&&!/[\r\n]$/.test(block.local)?'\n':'')+block.remote:'';
    block.choice=choice;renderMerge(draft);
}
function renderMerge(draft){
    const container=$('merge-blocks'),scroll=container.scrollTop;container.replaceChildren();
    draft.blocks.forEach((block,index)=>{
        const row=document.createElement('div');row.className='merge-block merge-'+block.kind+(block.choice?' resolved':'');row.dataset.index=index;
        for(const side of ['local','result','remote']){
            const pane=document.createElement('div');pane.className='merge-pane '+side;
            const gutter=document.createElement('pre');gutter.className='merge-lines'+(side==='result'?' result-lines':'');
            if(side!=='result')gutter.textContent=mergeNumbers(block[side],block[side+'_start']);
            pane.append(gutter);
            if(side==='result'){
                const editor=document.createElement('textarea');const terminal=block.result.match(/(\r\n|\n|\r)$/)?.[0]??'';editor.value=terminal?block.result.slice(0,-terminal.length):block.result;editor.spellcheck=false;editor.wrap='off';editor.rows=1;
                editor.setAttribute('aria-label',`合并结果块 ${index+1}`);editor.disabled=syncing;
                editor.addEventListener('input',()=>{block.result=editor.value+terminal;block.choice='manual';row.classList.add('resolved');updateMergeProgress();});pane.append(editor);
            }else{
                const code=document.createElement('pre');code.className='merge-source';code.textContent=block[side].replace(/(\r\n|\n|\r)$/,'');pane.append(code);
            }
            if(block.kind!=='equal'){
                const controls=document.createElement('div');controls.className='block-controls';
                if(block.auto_reason){const reason=document.createElement('span');reason.className='auto-reason';reason.textContent=block.auto_reason;reason.title=block.auto_reason;if(side==='result')controls.append(reason);}
                const choices=side==='local'?[['local','→','采用本地']]:side==='remote'?[['remote','←','采用远程']]:[['both','保留两边','依次保留本地和远程'],['skip','×','清空此差异块，两端内容均不纳入结果']];
                for(const [choice,text,title] of choices){const button=document.createElement('button');button.textContent=text;button.title=title;button.setAttribute('aria-label',`块 ${index+1} ${title}`);button.disabled=syncing;button.classList.toggle('chosen',block.choice===choice);button.addEventListener('click',()=>acceptMergeBlock(index,choice));controls.append(button);}
                pane.append(controls);
            }
            row.append(pane);
        }
        container.append(row);
    });
    updateMergeProgress();container.scrollTop=scroll;
}
function navigateMerge(direction){
    const changes=[...$('merge-blocks').children].filter(row=>!row.classList.contains('merge-equal'));
    if(!changes.length)return;activeChange=activeChange<0?(direction>0?0:changes.length-1):(activeChange+direction+changes.length)%changes.length;
    changes.forEach((row,i)=>row.classList.toggle('current-change',i===activeChange));
    changes[activeChange].scrollIntoView({block:'center',behavior:'smooth'});
}
$('previous-change').addEventListener('click',()=>navigateMerge(-1));$('next-change').addEventListener('click',()=>navigateMerge(1));
$('merge-tab').addEventListener('click',()=>{side='merge';show();});
$('close-merge').addEventListener('click',()=>{if(!syncing){side='local';show();}});
for(const source of ['local','remote'])$('use-'+source).addEventListener('click',()=>{
    const draft=mergeDrafts.get(mergeKey);if(!draft||syncing)return;
    draft.blocks.forEach(block=>{block.result=block[source];block.choice=block.kind==='equal'?'same':source;});renderMerge(draft);
});
$('reload-merge').addEventListener('click',async()=>{if(!selected||syncing)return;const version=++readVersion;try{await openMerge(selected,version,true);}catch(error){$('merge-notice').textContent=error.message;}});
async function saveMerge(target){
    if(syncing||!selected)return;
    const file=selected,key=mergeDraftKey(file),draft=mergeDrafts.get(key),token=session;
    if(!draft)return;
    draft.content=composeMerge(draft);syncing=true;updateActions();$('scan').disabled=true;
    document.querySelectorAll('#merge-view button, #merge-view textarea').forEach(element=>element.disabled=true);
    $('merge-notice').textContent='正在保存合并结果…';
    try{
        const result=await api('/api/merge',{session:token,path:file.path,action:'save',target,content:draft.content,hashes:draft.hashes});
        file.status=result.status;
        if(result.ok){
            mergeDrafts.delete(key);
            message('合并结果已保存到'+(target==='both'?'两端':target==='local'?'本地':'远程'));
            if(selected===file){side='local';await show();}
        }else{
            $('merge-notice').textContent=`保存未全部完成，已保存：${result.saved.join('、')||'无'}。${result.error}。请重新载入原文后重试，草稿已保留。`;
            message($('merge-notice').textContent,true);
        }
        render();updateSummary();
    }catch(error){$('merge-notice').textContent=error.message;message(error.message,true);}
    finally{syncing=false;updateActions();$('scan').disabled=false;document.querySelectorAll('#merge-view button, #merge-view textarea').forEach(element=>element.disabled=false);}
}
document.querySelectorAll('[data-save-merge]').forEach(button=>button.addEventListener('click',()=>saveMerge(button.dataset.saveMerge)));

function formatMtime(value){if(value==null)return '远程未提供';const date=new Date(typeof value==='number'?(value>1e12?value:value*1000):value);return Number.isNaN(date.getTime())?'时间格式无效':date.toLocaleString('zh-CN',{hour12:false});}
function showFileTimes(file){$('file-times').textContent=`本地：${file.local?formatMtime(file.local_mtime):'不存在'} · 远程：${file.remote?formatMtime(file.remote_mtime):'不存在'}`;}
$('smart-merge').addEventListener('click',()=>{const draft=mergeDrafts.get(mergeKey);if(!draft||syncing)return;let applied=0;for(const block of draft.blocks){if(block.choice===null&&block.auto_result!=null){block.result=block.auto_result;block.choice='auto';applied++;}}renderMerge(draft);$('merge-notice').textContent=`已自动处理 ${applied} 个待选块；其他可自动合并的块已在打开时处理。不同实质内容需人工选择，已有编辑保留。`;});
