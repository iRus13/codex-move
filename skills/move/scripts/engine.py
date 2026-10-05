"""Content-addressed, verified workspace and native-session transfer.

No cloud API, credential copying, or direct database writes. A bundle is immutable;
receiving workspaces are new directories, so a failed transfer cannot replace work.
"""
import hashlib, json, os, posixpath, re, shutil, sqlite3, stat, tempfile, time, unicodedata, uuid
from urllib.parse import unquote, urlparse
from pathlib import Path, PurePosixPath
from rpc import CodexRPC

FORMAT=2
class MoveError(RuntimeError):pass

def digest(data):return hashlib.sha256(data).hexdigest()
def encoded(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def atomic_write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.move-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
def file_digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def valid_id(value):
    try:return str(uuid.UUID(value))
    except (ValueError,TypeError,AttributeError):raise MoveError('Invalid thread/job ID')
def safe_path(value):
    if not isinstance(value,str) or not value or '\\' in value or '\x00' in value:raise MoveError('Unsafe bundle path')
    p=PurePosixPath(value)
    if p.is_absolute() or any(x in ('.','..','') for x in value.split('/')):raise MoveError('Unsafe bundle path: '+value)
    if p.parts[0] not in ('workspace','assets'):raise MoveError('Unexpected bundle root')
    return p

def locate_rollout(home,thread_id):
    thread_id=valid_id(thread_id);home=Path(home)
    for db in sorted(home.glob('state_*.sqlite'),reverse=True):
        try:
            with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as c:
                row=c.execute('select rollout_path from threads where id=?',(thread_id,)).fetchone()
            if row and Path(row[0]).is_file():return Path(row[0])
        except sqlite3.Error:continue
    matches=[]
    for folder in ('sessions','archived_sessions'):
        matches.extend((home/folder).rglob(f'rollout-*-{thread_id}.jsonl'))
    if len(matches)!=1:raise MoveError(f'Expected one session for {thread_id}; found {len(matches)}')
    return matches[0]

def read_stable(path):
    before=path.stat(); data=path.read_bytes();after=path.stat()
    if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):
        raise MoveError('File changed while snapshotting: '+str(path))
    return data

def inspect_rollout(data):
    if not data.endswith(b'\n'):raise MoveError('Session ends in a partial record')
    try:rows=[json.loads(l) for l in data.splitlines() if l.strip()]
    except (ValueError,UnicodeError) as e:raise MoveError('Unreadable native session') from e
    if not rows or rows[0].get('type')!='session_meta':raise MoveError('Missing native session metadata')
    meta=rows[0]['payload'];valid_id(meta['id']);active=set()
    for r in rows:
        p=r.get('payload',{})
        if r.get('type')!='event_msg':continue
        if p.get('type')=='task_started':active.add(p.get('turn_id'))
        elif p.get('type') in ('task_complete','turn_aborted','task_aborted'):active.discard(p.get('turn_id'))
    return meta,active

def all_turns(rpc,thread_id):
    turns=[];cursor=None
    while True:
        args={'threadId':thread_id,'limit':50,'sortDirection':'asc','itemsView':'full'}
        if cursor:args['cursor']=cursor
        result=rpc.call('thread/turns/list',args)
        turns.extend(result['data']);cursor=result.get('nextCursor')
        if not cursor:break
    return turns

def relocate_string(value,mappings):
    for old,new in sorted(mappings.items(),key=lambda p:len(p[0]),reverse=True):
        value=re.sub(re.escape(old)+r"(?=$|[/\s\)\]\"'<>:,])",lambda _:new,value)
    return value

def transform(value,path_map,id_map=None):
    if isinstance(value,list):return [transform(x,path_map,id_map) for x in value]
    if isinstance(value,dict):
        result={k:transform(v,path_map,id_map) for k,v in value.items()}
        if id_map:
            for k in ('thread_id','threadId','session_id','sessionId','forked_from_id','forkedFromId'):
                if isinstance(result.get(k),str) and result[k] in id_map:result[k]=id_map[result[k]]
        return result
    if isinstance(value,str):return relocate_string(value,path_map)
    return value

def relocate_rollout_row(row,path_map,id_map):
    result=transform(row,path_map)
    payload=result.get('payload',{})
    if result.get('type')=='session_meta':
        for key in ('id','session_id','sessionId','forked_from_id','forkedFromId'):
            if payload.get(key) in id_map:payload[key]=id_map[payload[key]]
        base=payload.get('history_base',{})
        if base.get('thread_id') in id_map:base['thread_id']=id_map[base['thread_id']]
    elif result.get('type')=='event_msg':
        for key in ('thread_id','threadId','session_id','sessionId'):
            if payload.get(key) in id_map:payload[key]=id_map[payload[key]]
    return result

def history_signature(turns,path_map=None):
    view=[{'id':t['id'],'items':t.get('items',[]),'status':t.get('status')} for t in turns]
    return digest(encoded(transform(view,path_map or {})))

def referenced_files(data):
    found=set()
    def walk(x):
        if isinstance(x,list):
            for v in x:walk(v)
        elif isinstance(x,dict):
            if x.get('type') in ('localImage','local_image','localAudio','local_audio') and isinstance(x.get('path'),str):found.add(x['path'])
            for k in ('image_url','url'):
                if isinstance(x.get(k),str) and x[k].startswith('file://'):found.add(unquote(urlparse(x[k]).path))
            for v in x.values():walk(v)
    for line in data.splitlines():
        row=json.loads(line);walk(row)
        payload=row.get('payload',{})
        if row.get('type')=='response_item' and payload.get('type')=='message':
            for content in payload.get('content',[]):
                if content.get('type') not in ('input_text','output_text'):continue
                for match in re.finditer(r'!?\[[^\]\n]*\]\((?:<)?(/[^\n]*?)(?:>)?\)',content.get('text','')):
                    ref=match.group(1)
                    if not Path(ref).is_file():
                        ref=re.sub(r':\d+$','',ref)
                    if Path(ref).is_file():found.add(ref)
    return sorted(found)


class Store:
    def __init__(self,root):self.root=Path(root);self.added_bytes=0;self.added_blobs=0
    def blob_path(self,h):
        if not isinstance(h,str) or len(h)!=64 or any(c not in '0123456789abcdef' for c in h):raise MoveError('Invalid blob hash')
        return self.root/'blobs'/h[:2]/h
    def put_bytes(self,data):
        h=digest(data);p=self.blob_path(h)
        if p.exists():
            if file_digest(p)!=h:raise MoveError('Existing blob is damaged: '+h)
        else:
            atomic_write(p,data);self.added_bytes+=len(data);self.added_blobs+=1
        return h
    def put_file(self,path):
        staging=self.root/'.staging';staging.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix='blob-',dir=staging)
        h=hashlib.sha256();size=0
        try:
            flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)
            srcfd=os.open(path,flags)
            with os.fdopen(srcfd,'rb') as src,os.fdopen(fd,'wb') as out:
                before=os.fstat(src.fileno())
                if not stat.S_ISREG(before.st_mode):raise MoveError('Not a regular file: '+str(path))
                for b in iter(lambda:src.read(1024*1024),b''):h.update(b);out.write(b);size+=len(b)
                after=os.fstat(src.fileno());out.flush();os.fsync(out.fileno())
            if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise MoveError('Source changed: '+str(path))
            key=h.hexdigest();target=self.blob_path(key)
            if target.exists():
                if file_digest(target)!=key:raise MoveError('Existing blob is damaged: '+key)
            else:
                target.parent.mkdir(parents=True,exist_ok=True);os.replace(tmp,target)
                self.added_bytes+=size;self.added_blobs+=1
            return key,size,before
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    def verify(self,h,size):
        p=self.blob_path(h)
        if not p.is_file() or p.stat().st_size!=size or file_digest(p)!=h:raise MoveError('Blob missing or damaged: '+h)
        return p

def pack(home,thread_id,workspace,bus,source_device,target_device,title='',verify_native=True,codex='codex'):
    home=Path(home).resolve();workspace=Path(workspace).resolve();store=Store(bus)
    if workspace in (Path('/'),Path.home(),home):raise MoveError('Workspace is too broad')
    if Path(bus).resolve().is_relative_to(workspace):raise MoveError('Transfer storage is inside the workspace')
    if not workspace.is_dir():raise MoveError('Workspace is missing')
    if (workspace/'.git').is_file():raise MoveError('Linked Git worktree needs native Git handoff; its .git pointer cannot be copied alone')
    root_roll=locate_rollout(home,thread_id);root_data=read_stable(root_roll);root_meta,active=inspect_rollout(root_data)
    if active:raise MoveError('Source turn is still active; wait for it to finish')
    native_signature=None;expected_turns=None
    if verify_native:
        with CodexRPC(codex=codex,codex_home=home) as rpc:
            turns=all_turns(rpc,thread_id)
            if any(t.get('status')=='inProgress' for t in turns):raise MoveError('Source turn is active')
            native_signature=history_signature(turns);expected_turns=len(turns)
    histories=[];seen=set();referenced=set()
    def capture_history(sid):
        if sid in seen:return
        seen.add(sid)
        data=root_data if sid==thread_id else read_stable(locate_rollout(home,sid))
        meta,_=inspect_rollout(data)
        referenced.update(referenced_files(data))
        if meta.get('forked_from_id'):capture_history(meta['forked_from_id'])
        if meta.get('history_base',{}).get('thread_id'):capture_history(meta['history_base']['thread_id'])
        filename=locate_rollout(home,sid).name
        if '/' in filename or not filename.endswith('-'+sid+'.jsonl'):raise MoveError('Unexpected native session filename')
        histories.append({'id':sid,'filename':filename,'hash':store.put_bytes(data),'size':len(data),'parent':meta.get('forked_from_id'),'base':meta.get('history_base',{}).get('thread_id')})
    capture_history(thread_id)
    entries=[];names=set();asset_map={};checks=[];queue=[(workspace,'workspace')]
    for ref in sorted(referenced):
        p=Path(ref).expanduser().resolve()
        if not p.is_file():raise MoveError('Referenced attachment is missing: '+str(p))
        if p.is_relative_to(workspace):continue
        if p.is_relative_to(home) and not any(p.is_relative_to(home/d) for d in ('visualizations','skills')):
            raise MoveError('Attachment inside Codex state requires explicit review: '+str(p))
        asset_map[str(p)]='assets/'+digest(str(p).encode())[:16]+'/'+p.name
        queue.append((p,asset_map[str(p)]))
    def record(entry):
        key=unicodedata.normalize('NFC',entry['path']).casefold()
        if key in names:raise MoveError('Case/Unicode filename collision: '+entry['path'])
        names.add(key);entries.append(entry)
    def walk(path,rel,root_real,root_rel):
        st=path.lstat();mode=stat.S_IMODE(st.st_mode)&0o777
        checks.append((path,(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)))
        basic={'path':rel,'mode':mode,'mtime_ns':st.st_mtime_ns}
        if stat.S_ISLNK(st.st_mode):
            try:target=path.resolve(strict=True)
            except (OSError,RuntimeError) as e:raise MoveError('Broken or cyclic symlink: '+str(path)) from e
            if target.is_relative_to(root_real):mapped=str(PurePosixPath(root_rel)/target.relative_to(root_real).as_posix())
            elif target.is_relative_to(workspace):mapped=str(PurePosixPath('workspace')/target.relative_to(workspace).as_posix())
            else:
                if target in (Path('/'),Path.home(),home) or target.is_relative_to(home):raise MoveError('Symlink points into Codex state or a broad folder: '+str(path))
                key=str(target)
                if key not in asset_map:
                    asset_map[key]='assets/'+digest(key.encode())[:16]+'/'+target.name
                    queue.append((target,asset_map[key]))
                mapped=asset_map[key]
            link=posixpath.relpath(mapped,posixpath.dirname(rel))
            record({**basic,'kind':'link','target':link})
        elif stat.S_ISDIR(st.st_mode):
            record({**basic,'kind':'dir'})
            before=sorted(os.listdir(path))
            for name in before:walk(path/name,rel+'/'+name,root_real,root_rel)
            if before!=sorted(os.listdir(path)):raise MoveError('Directory changed: '+str(path))
        elif stat.S_ISREG(st.st_mode):
            h,size,copied=store.put_file(path)
            record({**basic,'kind':'file','hash':h,'size':size,'mtime_ns':copied.st_mtime_ns})
        else:raise MoveError('Non-transferable filesystem entry: '+str(path))
    while queue:
        path,rel=queue.pop(0)
        if rel.startswith('assets/'):
            for parent in reversed(PurePosixPath(rel).parents):
                s=str(parent)
                if s!='.' and unicodedata.normalize('NFC',s).casefold() not in names:record({'path':s,'kind':'dir','mode':0o700,'mtime_ns':time.time_ns()})
        walk(path,rel,path,rel)
    for path,before in checks:
        st=path.lstat()
        if before!=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns):raise MoveError('Source changed during snapshot: '+str(path))
    # The source log must still be exactly the snapshot after the files are read.
    if read_stable(root_roll)!=root_data:raise MoveError('Chat changed while preparing the transfer')
    if verify_native:
        normalized={str(workspace):'<move-workspace>'}
        normalized.update({old:'<move-'+rel+'>' for old,rel in asset_map.items()})
        native_signature=history_signature(turns,normalized)
    manifest={'format':FORMAT,'job_id':str(uuid.uuid4()),'thread_id':thread_id,'source_device':source_device,'target_device':target_device,'source_workspace':str(workspace),'title':title,'created_at':time.time(),'histories':histories,'entries':entries,'external_assets':asset_map,'history_signature':native_signature,'turn_count':expected_turns,'new_blob_bytes':store.added_bytes,'new_blobs':store.added_blobs}
    data=encoded(manifest);path=Path(bus)/'jobs'/(manifest['job_id']+'.json')
    atomic_write(path,data)
    return path,manifest

def validate_manifest(m):
    if m.get('format')!=FORMAT:raise MoveError('Unsupported transfer format')
    valid_id(m['job_id']);valid_id(m['thread_id'])
    entries=m.get('entries');histories=m.get('histories')
    if not isinstance(entries,list) or not isinstance(histories,list):raise MoveError('Missing manifest inventory')
    seen={};folded=set()
    for e in entries:
        p=safe_path(e['path']);key=unicodedata.normalize('NFC',str(p)).casefold()
        if key in folded:raise MoveError('Duplicate or case-colliding path')
        folded.add(key);seen[str(p)]=e['kind']
        if e['kind'] not in ('file','dir','link'):raise MoveError('Unknown filesystem entry')
        if e['kind']=='link':
            target=e['target']
            if not isinstance(target,str) or target.startswith('/') or '\\' in target:raise MoveError('Unsafe link')
            safe_path(posixpath.normpath(posixpath.join(str(p.parent),target)))
    if seen.get('workspace')!='dir':raise MoveError('Missing workspace root')
    for name in seen:
        for p in PurePosixPath(name).parents:
            if str(p)!='.' and seen.get(str(p))!='dir':raise MoveError('Non-directory path ancestor')
    ids=set()
    for h in histories:
        sid=valid_id(h['id'])
        if sid in ids:raise MoveError('Duplicate history')
        ids.add(sid)
        if Path(h['filename']).name!=h['filename'] or not h['filename'].startswith('rollout-') or not h['filename'].endswith('-'+sid+'.jsonl'):raise MoveError('Unsafe history filename')
    if m['thread_id'] not in ids:raise MoveError('Missing root history')
    for h in histories:
        if h.get('parent') and h['parent'] not in ids:raise MoveError('Missing ancestor history')
        if h.get('base') and h['base'] not in ids:raise MoveError('Missing base history')

def unpack(manifest_path,bus,destination_root,target_device):
    raw=Path(manifest_path).read_bytes();m=json.loads(raw);validate_manifest(m)
    if m['target_device']!=target_device:raise MoveError('This bundle is for another device')
    store=Store(bus)
    for h in m['histories']:store.verify(h['hash'],h['size'])
    for e in m['entries']:
        if e['kind']=='file':store.verify(e['hash'],e['size'])
    root=Path(destination_root);root.mkdir(parents=True,exist_ok=True);dest=root/m['job_id']
    if dest.exists():
        saved=dest/'move-manifest.json'
        if saved.is_file() and saved.read_bytes()==raw:return dest,m
        raise MoveError('Existing destination differs; it was preserved')
    stage=Path(tempfile.mkdtemp(prefix='.move-receiving-',dir=root))
    try:
        for e in sorted(m['entries'],key=lambda x:(len(PurePosixPath(x['path']).parts),x['path'])):
            p=stage/e['path']
            if e['kind']=='dir':p.mkdir()
            elif e['kind']=='file':shutil.copyfile(store.blob_path(e['hash']),p)
            else:p.symlink_to(e['target'])
        for e in reversed(m['entries']):
            p=stage/e['path']
            if e['kind']!='link':os.chmod(p,e['mode']&0o777);os.utime(p,ns=(e['mtime_ns'],e['mtime_ns']))
        verify_tree(stage,m)
        atomic_write(stage/'move-manifest.json',raw)
        stage.rename(dest)
    finally:
        if stage.exists():shutil.rmtree(stage)
    return dest,m

def verify_tree(root,m):
    root=Path(root)
    for e in m['entries']:
        p=root/e['path']
        if e['kind']=='file':
            if p.is_symlink() or not p.is_file() or p.stat().st_size!=e['size'] or file_digest(p)!=e['hash']:raise MoveError('Received file verification failed: '+e['path'])
        elif e['kind']=='dir':
            if p.is_symlink() or not p.is_dir():raise MoveError('Received directory is missing: '+e['path'])
        elif not p.is_symlink() or os.readlink(p)!=e['target']:raise MoveError('Received link differs: '+e['path'])
    return True

def import_native(dest,m,bus,home,codex='codex'):
    """Import complete ancestry and create a native continuation; never edit a DB."""
    dest=Path(dest);home=Path(home);receipt=dest/'native-receipt.json'
    if receipt.exists():return json.loads(receipt.read_text())
    store=Store(bus);new_imports=[];paths={}
    id_map={h['id']:str(uuid.uuid5(uuid.UUID(m['job_id']),h['id'])) for h in m['histories']}
    transport_root=id_map[m['thread_id']]
    path_map={m['source_workspace']:str((dest/'workspace').resolve())}
    path_map.update({old:str((dest/rel).resolve()) for old,rel in m['external_assets'].items()})
    normalized={m['source_workspace']:'<move-workspace>',str((dest/'workspace').resolve()):'<move-workspace>'}
    for old,rel in m['external_assets'].items():
        normalized[old]='<move-'+rel+'>';normalized[str((dest/rel).resolve())]='<move-'+rel+'>'
    offset_maps={}
    for h in m['histories']:
        original=store.verify(h['hash'],h['size']).read_bytes()
        meta,_=inspect_rollout(original)
        if meta['id']!=h['id'] or meta.get('forked_from_id')!=h.get('parent'):raise MoveError('History identity does not match the manifest')
        atomic_write(dest/'source-history'/h['filename'],original)
        raw_lines=original.splitlines(keepends=True)
        rows=[relocate_rollout_row(json.loads(line),path_map,id_map) for line in raw_lines]
        rows[0]['payload']['id']=id_map[h['id']]
        original_base=meta.get('history_base')
        if original_base:
            ancestor=original_base['thread_id'];offset=original_base['end_byte_offset']
            if ancestor not in offset_maps or offset not in offset_maps[ancestor]:raise MoveError('Native history cutoff is not a recognized record boundary')
            rows[0]['payload']['history_base']['end_byte_offset']=offset_maps[ancestor][offset]
        chunks=[encoded(row) for row in rows]
        offsets={0:0};oldpos=newpos=0
        for before,after in zip(raw_lines,chunks):
            oldpos+=len(before);newpos+=len(after);offsets[oldpos]=newpos
        offset_maps[h['id']]=offsets
        incoming=b''.join(chunks)
        sid=id_map[h['id']]
        try:existing=locate_rollout(home,sid)
        except MoveError:existing=None
        if existing:
            if not existing.read_bytes().startswith(incoming):raise MoveError('Existing transport session differs; preserved: '+sid)
            paths[sid]=existing
        else:
            filename=h['filename'].replace(h['id'],sid)
            p=home/'sessions'/'move-imports'/filename
            atomic_write(p,incoming);new_imports.append(sid);paths[sid]=p
    atomic_write(dest/'native-path-map.json',encoded({'sessions':id_map,'paths':path_map}))
    marker=dest/'native-import-started.json'
    created=dest/'native-created.json'
    with CodexRPC(codex=codex,codex_home=home) as rpc:
        source_sig=m.get('history_signature')
        if not source_sig:raise MoveError('Missing source native-history verification')
        # Hydrate ancestors in dependency order before loading a forked source.
        # Each transport ID is unique to this job; original sessions stay untouched.
        for h in m['histories']:
            sid=id_map[h['id']]
            if sid in new_imports:
                rpc.call('thread/resume',{'threadId':sid,'cwd':str((dest/'workspace').resolve()),'excludeTurns':True})
        if created.exists():
            ident=json.loads(created.read_text())['thread_id']
            thread=rpc.call('thread/read',{'threadId':ident,'includeTurns':False})['thread']
        elif marker.exists():
            candidates=[];cursor=None
            while True:
                args={'cwd':str((dest/'workspace').resolve()),'limit':100,'sortDirection':'desc'}
                if cursor:args['cursor']=cursor
                page=rpc.call('thread/list',args)
                candidates.extend(t for t in page['data'] if t.get('forkedFromId')==transport_root)
                cursor=page.get('nextCursor')
                if not cursor:break
            if len(candidates)!=1:raise MoveError('A prior native import has an uncertain outcome; reconcile before retrying')
            thread=candidates[0]
            atomic_write(created,encoded({'thread_id':thread['id']}))
        else:
            atomic_write(marker,encoded({'thread_id':m['thread_id'],'time':time.time()}))
            result=rpc.call('thread/fork',{'threadId':transport_root,'path':str(paths[transport_root]),'cwd':str((dest/'workspace').resolve()),'runtimeWorkspaceRoots':[str((dest/'workspace').resolve())],'excludeTurns':True,'deferGoalContinuation':True},timeout=60)
            thread=result['thread'];atomic_write(created,encoded({'thread_id':thread['id']}))
        if thread.get('cwd')!=str((dest/'workspace').resolve()) or thread.get('forkedFromId')!=transport_root:
            raise MoveError('Recovered native thread has different source or workspace')
        actual=all_turns(rpc,thread['id'])
        if history_signature(actual,normalized)!=source_sig:
            raise MoveError('Native continuation history verification failed')
        if m.get('title'):rpc.call('thread/name/set',{'threadId':thread['id'],'name':m['title']})
        for sid in new_imports:rpc.call('thread/archive',{'threadId':sid})
        # Verify again after archiving imported ancestors: history must remain loadable.
        if history_signature(all_turns(rpc,thread['id']),normalized)!=source_sig:raise MoveError('History no longer resolves after archiving ancestors')
        out={'job_id':m['job_id'],'source_thread_id':m['thread_id'],'thread_id':thread['id'],'workspace':str((dest/'workspace').resolve()),'history_signature':source_sig,'turn_count':len(actual),'verified':True,'open_requested':False}
        atomic_write(receipt,encoded(out))
        return out
