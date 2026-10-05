"""Install Move as a normal macOS background app with its own folder permissions."""
import base64,hashlib,json,os,plistlib,shutil,subprocess,sys,tempfile,time
from pathlib import Path

def install(c):
    from engine import MoveError,atomic_write,encoded
    home=Path.home()
    if Path(c['codex_home']).resolve()!=home/'.codex':
        raise MoveError('Native login receiver currently requires the standard ~/.codex profile')
    if not c.get('peer_public_key'):raise MoveError('Pair the other Mac before enabling Move')
    service='gui/'+str(os.getuid())+'/com.local.codex-move.receiver'
    status=subprocess.run(['/bin/launchctl','print',service],capture_output=True)
    if status.returncode==0:raise MoveError('Receiver is already loaded; stop it deliberately before replacing its app')
    source=Path(__file__).with_name('receiver.swift')
    apps=home/'Applications';apps.mkdir(exist_ok=True)
    app=apps/'Codex Move Receiver.app'
    if app.exists():
        running=subprocess.run(['/usr/bin/pgrep','-f',str(app/'Contents/MacOS/CodexMoveReceiver')],capture_output=True)
        if running.returncode==0:raise MoveError('Quit the existing Move receiver app before replacing it')
    state=Path(c['state_dir']);state.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.move-native-',dir=apps))
    staged=stage/app.name;contents=staged/'Contents';(contents/'MacOS').mkdir(parents=True)
    try:
        payload=base64.b64decode(source.with_name('receiver-universal.b64').read_text(),validate=False)
        if hashlib.sha256(payload).hexdigest()!='cd03da0b2b07d1797ac67e5c77a1fb99d0f34d39786477067bfe71a2bcd42a72':
            raise MoveError('Native receiver payload verification failed')
        binary=contents/'MacOS/CodexMoveReceiver';binary.write_bytes(payload);binary.chmod(0o755)
        info={'CFBundleExecutable':'CodexMoveReceiver','CFBundleIdentifier':'local.codex.move.receiver','CFBundleName':'Codex Move Receiver','CFBundleDisplayName':'Codex Move Receiver','CFBundleVersion':'2','CFBundleShortVersionString':'1.1','CFBundlePackageType':'APPL','LSUIElement':True,'NSDocumentsFolderUsageDescription':'Move transfers the selected Codex chat work folder between your Macs.','NSDesktopFolderUsageDescription':'Move includes Desktop files referenced by your selected Codex chat.','NSDownloadsFolderUsageDescription':'Move includes downloaded files referenced by your selected Codex chat.','NSRemovableVolumesUsageDescription':'Move includes external-drive files referenced by your selected Codex chat.','NSNetworkVolumesUsageDescription':'Move uses your selected shared transfer folder and referenced files.'}
        (contents/'Info.plist').write_bytes(plistlib.dumps(info))
        subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(staged)],check=True,capture_output=True)
        subprocess.run(['/usr/bin/codesign','--verify','--strict',str(staged)],check=True,capture_output=True)
        if app.exists():
            backup=state/('previous-native-app-'+str(time.time_ns())+'.app');app.rename(backup)
        staged.rename(app)
    finally:shutil.rmtree(stage)
    c={k:v for k,v in c.items() if k!='_path'};c['runtime_python']=sys.executable
    config=Path(c['state_dir'])/'config.json';atomic_write(config,encoded(c))
    agent=home/'Library/LaunchAgents/com.local.codex-move.receiver.plist';agent.parent.mkdir(parents=True,exist_ok=True)
    if agent.exists():shutil.copy2(agent,state/('previous-launchagent-'+str(time.time_ns())+'.plist'))
    spec={'Label':'com.local.codex-move.receiver','ProgramArguments':['/usr/bin/open','-W','-g','-a',str(app)],'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'StandardErrorPath':str(state/'launcher-error.log')}
    atomic_write(agent,plistlib.dumps(spec))
    subprocess.run(['/bin/launchctl','bootstrap','gui/'+str(os.getuid()),str(agent)],check=True)
    return {'service':service,'app':str(app),'plist':str(agent),'folder_permission':'macOS may request access to the selected workspace folders'}
