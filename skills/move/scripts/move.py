#!/usr/bin/env python3
"""On-demand Codex transfers, with a small per-user receiving service."""
import argparse,fcntl,json,os,plistlib,shutil,subprocess,sys,time,uuid
from pathlib import Path
from engine import *
from signing import ensure_key,device_name,sign,verify,signed_write

def state_home():return Path(os.environ.get('CODEX_HOME') or str(Path.home()/'.codex'))/'move'
def config_path():return state_home()/'config.json'
def load_config(path=None):
    p=Path(path or config_path());c=json.loads(p.read_text());c['_path']=str(p)
    for k in ('device','peer'):device_name(c[k])
    if c['device']==c['peer']:raise MoveError('Source and destination devices must differ')
    return c

def save_status(c,category,ident,status):
    p=Path(c['state_dir'])/category/(ident+'.json');atomic_write(p,encoded(status));return p

def ensure_dropbox(c):
    if not c.get('start_dropbox',True):return
    if subprocess.run(['/usr/bin/pgrep','-x','Dropbox'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        subprocess.run(['/usr/bin/open','-g','-a','Dropbox'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)

def open_native(thread_id):
    valid_id(thread_id)
    r=subprocess.run(['/usr/bin/open','-b','com.openai.codex','codex://threads/'+thread_id],capture_output=True)
    if r.returncode:raise MoveError('The destination app did not accept the open request')
    return True

def queue(c,thread_id,workspace,title=''):
    if not c.get('peer_public_key'):raise MoveError('This receiver has not been paired with the other Mac')
    thread_id=valid_id(thread_id);home=Path(c['codex_home']);roll=locate_rollout(home,thread_id)
    workspace=Path(workspace).resolve()
    # A new move after completion captures subsequent source work as a fresh continuation.
    p=Path(c['state_dir'])/'outgoing'/(thread_id+'.json')
    if p.exists():
        old=json.loads(p.read_text())
        if old['status'] in ('queued','waiting_for_source','sent'):return old
        save_status(c,'outgoing-history',old['request_id'],old)
    request={'request_id':str(uuid.uuid4()),'thread_id':thread_id,'workspace':str(workspace),'title':title,'target_device':c['peer'],'status':'queued','queued_at':time.time()}
    save_status(c,'outgoing',thread_id,request)
    ensure_dropbox(c)
    return request

def process_outgoing(c):
    folder=Path(c['state_dir'])/'outgoing'
    for p in sorted(folder.glob('*.json')):
        r=json.loads(p.read_text())
        if r['status'] in ('queued','waiting_for_source'):
            try:
                path,m=pack(c['codex_home'],r['thread_id'],r['workspace'],c['bus'],c['device'],c['peer'],r.get('title',''),verify_native=True,codex=c.get('codex','codex'))
                key=Path(c['state_dir'])/'signing-key'
                atomic_write(str(path)+'.sig',sign(path.read_bytes(),key))
                r.update(status='sent',job_id=m['job_id'],manifest_hash=file_digest(path),sent_at=time.time(),new_blob_bytes=m['new_blob_bytes'])
            except MoveError as e:
                if any(term in str(e) for term in ('active','changed while','changed during','Source changed','Directory changed','partial record')):r.update(status='waiting_for_source',last_wait_reason=str(e))
                else:r.update(status='error',error=str(e))
            except Exception as e:r.update(status='error',error=str(e))
            atomic_write(p,encoded(r))
        if r['status']=='sent':
            receipt=Path(c['bus'])/'receipts'/(r['job_id']+'.json');signature=Path(str(receipt)+'.sig')
            if not receipt.is_file() or not signature.is_file():continue
            try:
                data=receipt.read_bytes();verify(data,signature.read_bytes(),c['peer'],c['peer_public_key']);answer=json.loads(data)
                if answer.get('job_id')!=r['job_id'] or answer.get('manifest_hash')!=r['manifest_hash'] or answer.get('source_thread_id')!=r['thread_id']:raise MoveError('Destination receipt does not match this transfer')
                if answer.get('status')=='error' and not answer.get('verified'):
                    r.update(status='error',error=answer.get('error','Destination verification failed'),failed_at=time.time());atomic_write(p,encoded(r));continue
                if not answer.get('verified'):raise MoveError('Destination receipt does not confirm verification')
                r.update(status='complete',completed_at=time.time(),destination=answer)
                atomic_write(p,encoded(r))
            except (MoveError,ValueError,OSError) as e:
                # Files may be visible in Dropbox before their matching signature.
                r['last_receipt_error']=str(e);atomic_write(p,encoded(r))

def process_incoming(c,opener=open_native):
    for path in sorted((Path(c['bus'])/'jobs').glob('*.json')):
        authenticated=False
        try:
            if path.stat().st_size>32*1024*1024:raise MoveError('Manifest is unexpectedly large')
            raw=path.read_bytes();m=json.loads(raw)
            if m.get('target_device')!=c['device']:continue
            ident=valid_id(m['job_id'])
            if path.name!=ident+'.json' or m.get('source_device')!=c['peer']:raise MoveError('Unexpected sender or job name')
            previous=Path(c['state_dir'])/'incoming'/(ident+'.json')
            if previous.exists():
                old=json.loads(previous.read_text())
                if old.get('status')=='error' and old.get('manifest_hash')==digest(raw):continue
                if old.get('status')=='complete':
                    if old.get('manifest_hash')!=digest(raw):raise MoveError('Completed job manifest was changed')
                    continue
            sig=Path(str(path)+'.sig')
            if not sig.is_file():continue
            verify(raw,sig.read_bytes(),c['peer'],c['peer_public_key']);authenticated=True
            ensure_dropbox(c)
            save_status(c,'incoming',ident,{'status':'receiving','job_id':ident,'manifest_hash':digest(raw),'started_at':time.time()})
            dest,m=unpack(path,c['bus'],c['received_root'],c['device'])
            receipt=import_native(dest,m,c['bus'],c['codex_home'],c.get('codex','codex'))
            if c.get('open_app',True) and not receipt.get('open_requested'):
                receipt['open_requested']=bool(opener(receipt['thread_id']))
                atomic_write(dest/'native-receipt.json',encoded(receipt))
            receipt.update(manifest_hash=digest(raw),receiving_device=c['device'],completed_at=time.time(),source_preserved=True)
            out=Path(c['bus'])/'receipts'/(ident+'.json')
            signed_write(out,encoded(receipt),Path(c['state_dir'])/'signing-key')
            save_status(c,'incoming',ident,{'status':'complete',**receipt})
        except Exception as e:
            try:ident=valid_id(path.stem)
            except MoveError:continue
            permanent=any(term in str(e) for term in ('Native continuation history verification failed','Existing transport session differs','History no longer resolves'))
            if permanent and authenticated:
                failure={'job_id':ident,'manifest_hash':digest(raw),'source_thread_id':m['thread_id'],'status':'error','verified':False,'error':str(e)}
                signed_write(Path(c['bus'])/'receipts'/(ident+'.json'),encoded(failure),Path(c['state_dir'])/'signing-key')
            save_status(c,'incoming',ident,{'status':'error' if permanent else 'pending_or_error','job_id':ident,'manifest_hash':digest(path.read_bytes()),'error':str(e),'checked_at':time.time()})

def run_once(c,opener=open_native):
    process_outgoing(c);process_incoming(c,opener=opener)

def watch(c):
    state=Path(c['state_dir']);state.mkdir(parents=True,exist_ok=True)
    with open(state/'receiver.lock','a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise MoveError('The move receiver is already running')
        ensure_dropbox(c)
        while True:
            try:
                run_once(c)
                atomic_write(state/'health.json',encoded({'pid':os.getpid(),'device':c['device'],'last_cycle':time.time()}))
            except Exception as e:
                atomic_write(state/'health.json',encoded({'pid':os.getpid(),'device':c['device'],'last_cycle':time.time(),'error':str(e)}))
            time.sleep(2)

def setup(device,peer,bus,peer_key=None,home=None,state=None,received=None):
    device_name(device);device_name(peer)
    if device==peer:raise MoveError('Source and destination devices must differ')
    home=Path(home or os.environ.get('CODEX_HOME') or Path.home()/'.codex').resolve()
    state=Path(state or home/'move').resolve()
    if (state/'config.json').exists():
        raise MoveError('Move is already configured; preserve the existing pairing and update its configuration deliberately')
    key,public=ensure_key(state)
    c={'version':2,'device':device,'peer':peer,'codex_home':str(home),'state_dir':str(state),'bus':str(Path(bus).expanduser().resolve()),'received_root':str(Path(received or Path.home()/'Documents/Codex/Moved').resolve()),'codex':str(Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex')) if Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex').is_file() else (shutil.which('codex') or 'codex'),'open_app':True,'start_dropbox':True}
    if peer_key:c['peer_public_key']=Path(peer_key).read_text().strip()
    atomic_write(state/'config.json',encoded(c))
    registry=Path(c['bus'])/'devices'/(device+'.json')
    atomic_write(registry,encoded({'device':device,'public_key':public,'version':2}))
    return {'config':str(state/'config.json'),'public_key':public,'paired':bool(peer_key)}

def receiver_status(c):
    state=Path(c['state_dir']);health=state/'health.json'
    result=json.loads(health.read_text()) if health.exists() else {}
    result['running']=False
    try:
        with open(state/'receiver.lock','a+') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:result['running']=True
    except OSError:pass
    result['heartbeat_age_seconds']=max(0,time.time()-result['last_cycle']) if result.get('last_cycle') else None
    result['status']='running' if result['running'] else 'receiver_not_running'
    return result

def install_service(c):
    from native_service import install
    return install(c)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config')
    sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('setup');s.add_argument('--device',required=True);s.add_argument('--peer',required=True);s.add_argument('--bus',required=True);s.add_argument('--peer-key')
    q=sub.add_parser('queue');q.add_argument('--thread',required=True);q.add_argument('--workspace',required=True);q.add_argument('--title',default='')
    s=sub.add_parser('status');s.add_argument('--thread')
    sub.add_parser('once');sub.add_parser('watch');sub.add_parser('install-service')
    args=p.parse_args()
    if args.command=='setup':result=setup(args.device,args.peer,args.bus,args.peer_key)
    else:
        c=load_config(args.config)
        if args.command=='queue':result=queue(c,args.thread,args.workspace,args.title)
        elif args.command=='status':
            if args.thread:
                path=Path(c['state_dir'])/'outgoing'/(valid_id(args.thread)+'.json');result=json.loads(path.read_text()) if path.exists() else {'status':'not_queued'}
            else:
                result=receiver_status(c)
        elif args.command=='once':run_once(c);result={'cycle_complete':True}
        elif args.command=='watch':watch(c);return
        else:result=install_service(c)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except Exception as e:print(json.dumps({'status':'error','error':str(e)}),file=sys.stderr);sys.exit(1)
