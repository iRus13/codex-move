from pathlib import Path
import json,hashlib,sys
src=Path(sys.argv[1] if len(sys.argv)>1 else 'skills/move')
files={str(p.relative_to(src)):p.read_text() for p in sorted(src.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
payload=json.dumps(files,ensure_ascii=False)
hashes={k:hashlib.sha256(v.encode()).hexdigest() for k,v in files.items()}
body='''import hashlib, json, os, sys, tempfile, shutil, uuid
from pathlib import Path
from datetime import datetime, timezone
FILES = __FILES__
HASHES = __HASHES__

def check(root):
    for rel, digest in HASHES.items():
        p = root / rel
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Verification failed: ' + str(p))

def main():
    if sys.argv[1:] not in ([], ['--verify-only']):
        raise RuntimeError('Usage: Install Move.command [--verify-only]')
    root = Path(os.environ.get('CODEX_HOME') or str(Path.home() / '.codex')).expanduser()
    if not root.is_absolute():
        raise RuntimeError('CODEX_HOME must be an absolute path')
    target = root / 'skills' / 'move'
    if target.is_symlink():
        raise RuntimeError('Existing move skill is a symbolic link; leaving it unchanged')
    if '--verify-only' in sys.argv:
        check(target)
        print('Verified move skill files at ' + str(target))
        return
    try:
        check(target)
        print('Move is already installed and verified at ' + str(target))
        return
    except RuntimeError:
        pass
    if target.exists() and not target.is_dir():
        raise RuntimeError('The move destination exists but is not a folder')
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.move-install-', dir=target.parent))
    backup = None
    try:
        for rel, content in FILES.items():
            path = stage / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        check(stage)
        if target.exists():
            backups = root / 'skill-backups'
            backups.mkdir(parents=True, exist_ok=True)
            backup = backups / ('move-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
            target.rename(backup)
        try:
            stage.rename(target)
            check(target)
        except BaseException:
            if target.exists():
                target.rename(stage)
            if backup is not None:
                backup.rename(target)
            raise
    finally:
        if stage.exists(): shutil.rmtree(stage)
    print('Installed and verified move at ' + str(target))
    if backup is not None: print('Previous skill preserved at ' + str(backup))
    print('Use $move in Codex. If it is not listed, open a new chat or restart Codex after finishing active work.')
    print('This installs the skill only. It does not transfer chats or confirm that the other Mac is connected.')

try:
    main()
except Exception as e:
    print('Move installation stopped: ' + str(e), file=sys.stderr)
    sys.exit(1)
'''.replace('__FILES__',repr(files)).replace('__HASHES__',repr(hashes))
header='''#!/bin/sh
set -eu
move_python=""
move_config="${CODEX_HOME:-$HOME/.codex}/move/config.json"
if [ -f "$move_config" ]; then
  move_python=$(/usr/bin/plutil -extract runtime_python raw -o - "$move_config" 2>/dev/null || true)
fi
if [ ! -x "$move_python" ]; then
  move_python="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [ ! -x "$move_python" ]; then
  move_python=$(command -v python3 || true)
fi
if [ ! -x "$move_python" ] || ! "$move_python" -c 'import sys; assert sys.version_info >= (3,9)' >/dev/null 2>&1; then
  echo "Python 3.9 or newer is required. Install Move from within Codex using its bundled Python. No changes were made." >&2
  exit 1
fi
"$move_python" - "$@" <<'MOVE_INSTALL_PYTHON'
'''
out=Path('Install Move.command');out.write_text(header+body+'\nMOVE_INSTALL_PYTHON\n');out.chmod(0o755)
Path('skill-hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
print(str(out.resolve()))
