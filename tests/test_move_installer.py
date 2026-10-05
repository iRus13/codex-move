import unittest, tempfile, subprocess, os, json, hashlib, time
from pathlib import Path
INSTALLER=Path('Install Move.command').resolve()
HASHES=json.loads(Path('skill-hashes.json').read_text())
class InstallerTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='move-test-',dir=None)
  self.home=Path(self.temp.name).resolve()/'MacBook home ü with spaces'
  self.home.mkdir(); self.root=self.home/'.codex'; self.target=self.root/'skills/move'
  self.env={**os.environ,'HOME':str(self.home),'CODEX_HOME':str(self.root)}
 def tearDown(self): self.temp.cleanup()
 def run_install(self,*args,expected=0):
  r=subprocess.run(['/bin/sh',str(INSTALLER),*args],env=self.env,text=True,capture_output=True,timeout=10)
  self.assertEqual(r.returncode,expected,r.stdout+r.stderr);return r
 def verify(self):
  for rel,h in HASHES.items(): self.assertEqual(hashlib.sha256((self.target/rel).read_bytes()).hexdigest(),h)
 def test_fresh_install_paths_and_hashes(self):
  self.run_install(); self.verify(); self.run_install('--verify-only')
 def test_repeat_install_is_unchanged(self):
  self.run_install(); before={str(p):p.stat().st_mtime_ns for p in self.target.rglob('*')}
  self.assertIn('already installed',self.run_install().stdout)
  self.assertEqual(before,{str(p):p.stat().st_mtime_ns for p in self.target.rglob('*')})
  self.assertFalse((self.root/'skill-backups').exists())
 def test_upgrade_preserves_previous_and_extra_files(self):
  self.target.mkdir(parents=True); (self.target/'SKILL.md').write_text('previous content'); (self.target/'personal-note').write_text('keep me')
  self.run_install(); self.verify(); backups=list((self.root/'skill-backups').iterdir());self.assertEqual(len(backups),1)
  self.assertEqual((backups[0]/'personal-note').read_text(),'keep me');self.assertEqual((backups[0]/'SKILL.md').read_text(),'previous content')
 def test_damaged_install_is_detected_and_preserved(self):
  self.run_install(); (self.target/'SKILL.md').write_text('changed')
  self.run_install('--verify-only',expected=1);self.run_install();self.verify()
  self.assertEqual((next((self.root/'skill-backups').iterdir())/'SKILL.md').read_text(),'changed')
 def test_symlink_destination_is_rejected(self):
  outside=self.home/'separate';outside.mkdir();(outside/'keep').write_text('unchanged')
  self.target.parent.mkdir(parents=True);self.target.symlink_to(outside,target_is_directory=True)
  self.run_install(expected=1);self.assertEqual((outside/'keep').read_text(),'unchanged');self.assertEqual(len(list(outside.iterdir())),1)
 def test_verify_does_not_install(self):
  self.run_install('--verify-only',expected=1);self.assertFalse(self.root.exists())
 def test_bad_argument_does_not_write(self):
  self.run_install('--wrong',expected=1);self.assertFalse(self.root.exists())
 def test_relative_codex_home_rejected(self):
  self.env['CODEX_HOME']='relative';self.run_install(expected=1);self.assertFalse(self.root.exists())
 def test_default_home_location(self):
  del self.env['CODEX_HOME'];self.run_install();self.verify()
if __name__=='__main__':unittest.main(verbosity=2)
