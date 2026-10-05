"""Sign transfer requests with a local key; trust only the pinned peer public key."""
import os,re,subprocess,tempfile
from pathlib import Path
from engine import MoveError,atomic_write

NAMESPACE='codex-move-v1'

def device_name(value):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}',value):raise MoveError('Device name must contain lowercase letters, numbers and hyphens')
    return value

def ensure_key(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);os.chmod(folder,0o700)
    key=folder/'signing-key'
    if not key.exists():
        subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N','','-C','codex-move','-f',str(key)],check=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL)
    if key.is_symlink():raise MoveError('Signing key must not be a symbolic link')
    os.chmod(key,0o600)
    return key,(folder/'signing-key.pub').read_text().strip()

def sign(data,key):
    r=subprocess.run(['/usr/bin/ssh-keygen','-Y','sign','-f',str(key),'-n',NAMESPACE],input=data,capture_output=True)
    if r.returncode:raise MoveError('Could not sign the transfer request')
    return r.stdout

def verify(data,signature,peer,public_key):
    device_name(peer)
    fields=public_key.split()
    if len(fields)<2 or fields[0]!='ssh-ed25519' or not re.fullmatch(r'[A-Za-z0-9+/=]+',fields[1]):raise MoveError('Invalid pinned peer public key')
    with tempfile.TemporaryDirectory(prefix='codex-move-verify-') as d:
        allowed=Path(d)/'allowed';sig=Path(d)/'signature'
        allowed.write_text(peer+' '+fields[0]+' '+fields[1]+'\n');sig.write_bytes(signature)
        r=subprocess.run(['/usr/bin/ssh-keygen','-Y','verify','-f',str(allowed),'-I',peer,'-n',NAMESPACE,'-s',str(sig)],input=data,capture_output=True)
        if r.returncode:raise MoveError('Transfer signature does not match the pinned peer')
    return True

def signed_write(path,data,key):
    signature=sign(data,key)
    atomic_write(path,data)
    atomic_write(str(path)+'.sig',signature)
