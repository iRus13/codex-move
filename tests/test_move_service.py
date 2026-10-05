import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path('skills/move/scripts').resolve()));sys.path.insert(0,str(Path('tests').resolve()))
from move import *
from test_move_engine import make_session
from unittest.mock import patch
class ServiceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='move-service-',dir=None);self.base=Path(self.temp.name).resolve();self.bus=self.base/'bus'
  self.a=self.config('mini','book');self.b=self.config('book','mini')
  self.a['peer_public_key']=(Path(self.b['state_dir'])/'signing-key.pub').read_text();self.b['peer_public_key']=(Path(self.a['state_dir'])/'signing-key.pub').read_text()
  self.workspace=self.base/'source work';self.workspace.mkdir();(self.workspace/'data.txt').write_text('work to move')
  self.sid,self.roll=make_session(Path(self.a['codex_home']),self.workspace)
  with CodexRPC(codex_home=self.a['codex_home']) as rpc:rpc.call('thread/resume',{'threadId':self.sid,'excludeTurns':True})
  self.opened=[]
 def tearDown(self):self.temp.cleanup()
 def config(self,device,peer):
  home=self.base/(device+'-home');home.mkdir();state=home/'move';setup(device,peer,self.bus,home=home,state=state,received=self.base/(device+'-received'))
  c=json.loads((state/'config.json').read_text());c.update(start_dropbox=False,open_app=True);return c
 def opener(self,thread):self.opened.append(thread);return True
 def test_signed_transfer_receipt_and_idempotence(self):
  first=queue(self.a,self.sid,self.workspace,'Test');second=queue(self.a,self.sid,self.workspace,'Test');self.assertEqual(first['request_id'],second['request_id'])
  run_once(self.a,opener=self.opener);run_once(self.b,opener=self.opener);run_once(self.a,opener=self.opener)
  status=json.loads((Path(self.a['state_dir'])/'outgoing'/(self.sid+'.json')).read_text());self.assertEqual(status['status'],'complete');self.assertTrue(status['destination']['verified']);self.assertTrue(status['destination']['open_requested']);self.assertEqual(len(self.opened),1)
  run_once(self.b,opener=self.opener);self.assertEqual(len(self.opened),1)
  self.assertEqual((Path(status['destination']['workspace'])/'data.txt').read_text(),'work to move')
 def test_waits_for_final_source_record(self):
  rows=self.roll.read_bytes().splitlines();active_id=str(uuid.uuid4())
  start={'timestamp':'2026-10-05T00:01:00Z','ordinal':len(rows),'type':'event_msg','payload':{'type':'task_started','turn_id':active_id,'started_at':1791158460,'collaboration_mode_kind':'default'}}
  final=encoded({'timestamp':'2026-10-05T00:01:01Z','ordinal':len(rows)+1,'type':'event_msg','payload':{'type':'task_complete','turn_id':active_id,'last_agent_message':'Done','started_at':1791158460,'completed_at':1791158461,'duration_ms':1000}}).rstrip(b'\n')
  with self.roll.open('ab') as f:f.write(encoded(start))
  queue(self.a,self.sid,self.workspace);process_outgoing(self.a)
  status_path=Path(self.a['state_dir'])/'outgoing'/(self.sid+'.json')
  self.assertEqual(json.loads(status_path.read_text())['status'],'waiting_for_source')
  self.assertFalse(list((self.bus/'jobs').glob('*.json')))
  with self.roll.open('ab') as f:f.write(final+b'\n')
  with CodexRPC(codex_home=self.a['codex_home']) as rpc:rpc.call('thread/resume',{'threadId':self.sid,'excludeTurns':True})
  process_outgoing(self.a);process_incoming(self.b,opener=self.opener);process_outgoing(self.a)
  self.assertEqual(json.loads(status_path.read_text())['status'],'complete',str(list((Path(self.b['state_dir'])/'incoming').glob('*')))+str([p.read_text() for p in (Path(self.b['state_dir'])/'incoming').glob('*')]))
 def test_later_move_keeps_completed_request_and_captures_new_work(self):
  first=queue(self.a,self.sid,self.workspace)
  process_outgoing(self.a);process_incoming(self.b,opener=self.opener);process_outgoing(self.a)
  (self.workspace/'data.txt').write_text('new work after moving')
  second=queue(self.a,self.sid,self.workspace)
  self.assertNotEqual(first['request_id'],second['request_id'])
  saved=Path(self.a['state_dir'])/'outgoing-history'/(first['request_id']+'.json')
  self.assertEqual(json.loads(saved.read_text())['status'],'complete')
  process_outgoing(self.a);process_incoming(self.b,opener=self.opener);process_outgoing(self.a)
  status=json.loads((Path(self.a['state_dir'])/'outgoing'/(self.sid+'.json')).read_text())
  self.assertEqual((Path(status['destination']['workspace'])/'data.txt').read_text(),'new work after moving')
 def test_setup_preserves_existing_pairing(self):
  p=Path(self.a['state_dir'])/'config.json';before=p.read_bytes()
  with self.assertRaisesRegex(MoveError,'already configured'):
   setup('mini','book',self.bus,home=self.a['codex_home'])
  self.assertEqual(p.read_bytes(),before)
 def test_stale_heartbeat_is_not_running_receiver(self):
  atomic_write(Path(self.a['state_dir'])/'health.json',encoded({'pid':os.getpid(),'last_cycle':time.time()}))
  self.assertFalse(receiver_status(self.a)['running'])
 def test_real_background_receivers_complete_transfer(self):
  workers=[]
  try:
   for config in (self.a,self.b):
    config['open_app']=False
    config_path=Path(config['state_dir'])/'config.json';atomic_write(config_path,encoded(config))
    workers.append(subprocess.Popen([sys.executable,str(Path('skills/move/scripts/move.py').resolve()),'--config',str(config_path),'watch'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
   limit=time.monotonic()+45
   while time.monotonic()<limit and not all(receiver_status(c)['running'] for c in (self.a,self.b)):time.sleep(0.05)
   self.assertTrue(all(receiver_status(c)['running'] for c in (self.a,self.b)))
   queue(self.a,self.sid,self.workspace)
   status_path=Path(self.a['state_dir'])/'outgoing'/(self.sid+'.json')
   while time.monotonic()<limit:
    result=json.loads(status_path.read_text())
    if result['status']=='complete':break
    self.assertTrue(all(w.poll() is None for w in workers));time.sleep(0.1)
   self.assertEqual(result['status'],'complete',str(result)+str([p.read_text() for p in (Path(self.b['state_dir'])/'incoming').glob('*.json')]))
   self.assertTrue(result['destination']['verified'])
  finally:
   for worker in workers:
    worker.terminate()
    try:worker.wait(timeout=3)
    except subprocess.TimeoutExpired:worker.kill();worker.wait()
  self.assertFalse(receiver_status(self.a)['running'])
 def test_configured_codex_works_without_cli_on_path(self):
  native='/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
  self.assertTrue(Path(native).is_file())
  self.a['codex']=native;self.b['codex']=native
  with patch.dict(os.environ,{'PATH':'/usr/bin:/bin'}):
   queue(self.a,self.sid,self.workspace)
   process_outgoing(self.a);process_incoming(self.b,opener=self.opener);process_outgoing(self.a)
  result=json.loads((Path(self.a['state_dir'])/'outgoing'/(self.sid+'.json')).read_text())
  self.assertEqual(result['status'],'complete',str(result))
 def test_verification_failure_is_signed_and_retriable_as_new_request(self):
  first=queue(self.a,self.sid,self.workspace);process_outgoing(self.a)
  with patch('move.import_native',side_effect=MoveError('Native continuation history verification failed')) as importer:
   process_incoming(self.b,opener=self.opener);process_incoming(self.b,opener=self.opener)
   self.assertEqual(importer.call_count,1)
  process_outgoing(self.a)
  result=json.loads((Path(self.a['state_dir'])/'outgoing'/(self.sid+'.json')).read_text())
  self.assertEqual(result['status'],'error');self.assertIn('verification failed',result['error'])
  second=queue(self.a,self.sid,self.workspace);self.assertNotEqual(first['request_id'],second['request_id'])
  process_outgoing(self.a);process_incoming(self.b,opener=self.opener);process_outgoing(self.a)
  result=json.loads((Path(self.a['state_dir'])/'outgoing'/(self.sid+'.json')).read_text())
  self.assertEqual(result['status'],'complete')
 def test_unsigned_job_does_not_import(self):
  path,m=pack(self.a['codex_home'],self.sid,self.workspace,self.bus,'mini','book',verify_native=True)
  process_incoming(self.b,opener=self.opener);self.assertEqual(self.opened,[]);self.assertFalse(Path(self.b['received_root']).exists())
 def test_tampered_signed_job_does_not_import(self):
  queue(self.a,self.sid,self.workspace);process_outgoing(self.a)
  job=next((self.bus/'jobs').glob('*.json'));m=json.loads(job.read_text());m['title']='tampered';job.write_bytes(encoded(m))
  process_incoming(self.b,opener=self.opener);self.assertEqual(self.opened,[]);self.assertFalse(Path(self.b['received_root']).exists())
if __name__=='__main__':unittest.main(verbosity=2)
