import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path('skills/move/scripts').resolve()))
from signing import *
class SigningTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='move-sign-',dir=None);self.base=Path(self.temp.name);self.key,self.pub=ensure_key(self.base/'sender')
 def tearDown(self):self.temp.cleanup()
 def test_pair_verifies(self):self.assertTrue(verify(b'job',sign(b'job',self.key),'mac-mini',self.pub))
 def test_changed_job_rejected(self):
  with self.assertRaises(MoveError):verify(b'changed',sign(b'job',self.key),'mac-mini',self.pub)
 def test_other_device_key_rejected(self):
  _,other=ensure_key(self.base/'other')
  with self.assertRaises(MoveError):verify(b'job',sign(b'job',self.key),'mac-mini',other)
 def test_key_is_private_and_reused(self):
  self.assertEqual(self.key.stat().st_mode&0o777,0o600);self.assertEqual(ensure_key(self.base/'sender')[1],self.pub)
if __name__=='__main__':unittest.main(verbosity=2)
