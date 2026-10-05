#!/usr/bin/env python3
"""Pin an independently verified peer public key; never read a private key."""
import argparse,json
from pathlib import Path
from engine import MoveError,atomic_write,encoded
from move import load_config

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file',required=True,help='Public key received through a trusted channel')
    args=parser.parse_args()
    key=Path(args.key_file).expanduser().read_text().strip()
    fields=key.split()
    import base64,struct
    if len(fields)<2 or fields[0]!='ssh-ed25519':raise MoveError('Expected an ssh-ed25519 public key')
    raw=base64.b64decode(fields[1],validate=True)
    expected=struct.pack('>I',11)+b'ssh-ed25519'+struct.pack('>I',32)
    if len(raw)!=len(expected)+32 or not raw.startswith(expected):raise MoveError('Invalid Ed25519 public key')
    config=load_config();path=Path(config.pop('_path'))
    if config.get('peer_public_key') and config['peer_public_key'].split()[:2]!=fields[:2]:
        raise MoveError('A different peer key is already pinned. Preserve the configuration and investigate before changing it.')
    own=Path(config['state_dir'])/'signing-key.pub'
    if own.read_text().split()[:2]==fields[:2]:raise MoveError('This is your own key; use the OTHER Mac public key')
    config['peer_public_key']=' '.join(fields[:2]);atomic_write(path,encoded(config))
    print(json.dumps({'paired':True,'device':config['device'],'peer':config['peer']}))
if __name__=='__main__':
    try:main()
    except Exception as exc:raise SystemExit(str(exc))
