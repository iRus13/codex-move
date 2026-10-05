import hashlib,json,os,sys,tempfile,unittest,uuid
from pathlib import Path
sys.path.insert(0,str(Path('skills/move/scripts').resolve()))
from engine import *

def make_session(home,workspace,token='MOVE-TEST-8267',image_path=None):
    sid=str(uuid.uuid4());tid=str(uuid.uuid4());now='2026-10-05T00:00:00Z';records=[]
    def add(t,p):records.append({'timestamp':now,'ordinal':len(records),'type':t,'payload':p})
    add('session_meta',{'id':sid,'session_id':sid,'timestamp':now,'cwd':str(workspace),'originator':'codex_cli_rs','cli_version':'0.155.1','source':'cli','model_provider':'openai','history_mode':'paginated','base_instructions':{'text':'You are a helpful assistant.'}})
    add('event_msg',{'type':'task_started','turn_id':tid,'started_at':1791158400,'collaboration_mode_kind':'default'})
    for role,txt,kind in [('user','Remember '+token+'.','UserMessage'),('assistant','Ready: '+token+'.','AgentMessage')]:
        mid=str(uuid.uuid4())
        add('response_item',{'type':'message','id':mid,'role':role,'content':[{'type':'input_text' if role=='user' else 'output_text','text':txt}]})
        item={'type':kind,'id':mid,'content':[{'type':'text','text':txt,'text_elements':[]} if role=='user' else {'type':'Text','text':txt}]}
        if role=='user':
            item['client_id']=str(uuid.uuid4())
            if image_path:item['content'].append({'type':'local_image','path':str(image_path)})
        else:item['phase']='final_answer'
        add('event_msg',{'type':'item_completed','thread_id':sid,'turn_id':tid,'item':item,'started_at_ms':1791158400000,'completed_at_ms':1791158400000})
    add('event_msg',{'type':'task_complete','turn_id':tid,'last_agent_message':'Ready: '+token+'.','started_at':1791158400,'completed_at':1791158401,'duration_ms':1000})
    folder=home/'sessions/2026/10/05';folder.mkdir(parents=True,exist_ok=True)
    roll=folder/f'rollout-2026-10-05T00-00-00-{sid}.jsonl';roll.write_bytes(b''.join(encoded(r) for r in records))
    return sid,roll

class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='move-engine-',dir=None);self.base=Path(self.temp.name).resolve()
        self.home=self.base/'source-codex';self.home.mkdir();self.workspace=self.base/'source ü workspace';self.workspace.mkdir()
        (self.workspace/'nested').mkdir();(self.workspace/'empty directory').mkdir();(self.workspace/'nested/notes ü.txt').write_text('First line\nSecond line\n');(self.workspace/'.hidden').write_bytes(bytes(range(256)))
        (self.workspace/'script').write_text('#!/bin/sh\nexit 0\n');(self.workspace/'script').chmod(0o755)
        (self.workspace/'relative-link').symlink_to('nested/notes ü.txt');(self.workspace/'absolute-link').symlink_to(self.workspace/'nested/notes ü.txt')
        self.sid,self.roll=make_session(self.home,self.workspace);self.bus=self.base/'bus';self.dest=self.base/'destination'
    def tearDown(self):self.temp.cleanup()
    def send(self,native=False):return pack(self.home,self.sid,self.workspace,self.bus,'mini','book','Move test',verify_native=native)
    def test_roundtrip_every_file_and_link(self):
        job,m=self.send();dest,_=unpack(job,self.bus,self.dest,'book');w=dest/'workspace'
        self.assertEqual((w/'nested/notes ü.txt').read_bytes(),(self.workspace/'nested/notes ü.txt').read_bytes())
        self.assertEqual((w/'.hidden').read_bytes(),bytes(range(256)));self.assertTrue((w/'empty directory').is_dir())
        self.assertEqual((w/'script').stat().st_mode&0o777,0o755)
        self.assertEqual((w/'relative-link').read_text(),(w/'absolute-link').read_text())
        self.assertFalse(os.readlink(w/'absolute-link').startswith('/'))
    def test_unchanged_data_deduplicates(self):
        self.send();job,m=self.send();self.assertEqual(m['new_blobs'],0);self.assertEqual(m['new_blob_bytes'],0)
    def test_only_changed_file_adds_blob(self):
        self.send();(self.workspace/'.hidden').write_bytes(b'new content');_,m=self.send();self.assertEqual(m['new_blobs'],1)
    def test_active_chat_rejected(self):
        rows=self.roll.read_bytes().splitlines();self.roll.write_bytes(b'\n'.join(rows[:-1])+b'\n')
        with self.assertRaisesRegex(MoveError,'active'):self.send()
    def test_corruption_is_rejected_before_destination_creation(self):
        job,m=self.send();h=next(x['hash'] for x in m['entries'] if x['kind']=='file');Store(self.bus).blob_path(h).write_bytes(b'corrupt')
        with self.assertRaisesRegex(MoveError,'damaged'):unpack(job,self.bus,self.dest,'book')
        self.assertFalse(self.dest.exists())
    def test_wrong_device_is_rejected(self):
        job,_=self.send()
        with self.assertRaisesRegex(MoveError,'another device'):unpack(job,self.bus,self.dest,'mini')
    def test_traversal_is_rejected(self):
        job,m=self.send();m['entries'][1]['path']='workspace/../../outside';job.write_bytes(encoded(m))
        with self.assertRaisesRegex(MoveError,'Unsafe'):unpack(job,self.bus,self.dest,'book')
    def test_symlink_escape_is_rejected(self):
        job,m=self.send();next(e for e in m['entries'] if e['kind']=='link')['target']='../../outside';job.write_bytes(encoded(m))
        with self.assertRaises(MoveError):unpack(job,self.bus,self.dest,'book')
    def test_external_link_asset_follows(self):
        outside=self.base/'asset.bin';outside.write_bytes(b'external image bytes');(self.workspace/'asset').symlink_to(outside)
        job,m=self.send();dest,_=unpack(job,self.bus,self.dest,'book');outside.unlink()
        self.assertEqual((dest/'workspace/asset').read_bytes(),b'external image bytes');self.assertEqual(len(m['external_assets']),1)
    def test_repeated_receive_preserves_user_changes(self):
        job,m=self.send();dest,_=unpack(job,self.bus,self.dest,'book');(dest/'workspace/.hidden').write_text('new work')
        again,_=unpack(job,self.bus,self.dest,'book');self.assertEqual(dest,again);self.assertEqual((again/'workspace/.hidden').read_text(),'new work')
    def test_recovery_after_receipt_write_interruption(self):
        with CodexRPC(codex_home=self.home) as rpc:rpc.call('thread/resume',{'threadId':self.sid,'excludeTurns':True})
        job,m=self.send(True);dest,_=unpack(job,self.bus,self.dest,'book');book=self.base/'recover-book';book.mkdir()
        first=import_native(dest,m,self.bus,book)
        (dest/'native-receipt.json').unlink()
        second=import_native(dest,m,self.bus,book)
        self.assertEqual(first['thread_id'],second['thread_id'])
        self.assertTrue(second['verified'])

    def test_native_image_attachment_survives_moving_source(self):
        image=self.base/'attached image.png';image.write_bytes(b'unit-test image bytes')
        self.sid,self.roll=make_session(self.home,self.workspace,'IMAGE-MARKER',image)
        with CodexRPC(codex_home=self.home) as rpc:
            rpc.call('thread/resume',{'threadId':self.sid,'excludeTurns':True})
            before=all_turns(rpc,self.sid)
            self.assertIn(str(image),json.dumps(before))
        job,m=self.send(True);image.unlink()
        dest,_=unpack(job,self.bus,self.dest,'book');book=self.base/'image-book-codex';book.mkdir()
        receipt=import_native(dest,m,self.bus,book)
        with CodexRPC(codex_home=book) as rpc:
            after=all_turns(rpc,receipt['thread_id'])
        content=after[0]['items'][0]['content']
        local=[x for x in content if x.get('type')=='localImage']
        self.assertEqual(len(local),1)
        self.assertTrue(Path(local[0]['path']).is_file())
        self.assertEqual(Path(local[0]['path']).read_bytes(),b'unit-test image bytes')
        self.assertNotEqual(local[0]['path'],str(image))
        self.assertTrue((dest/'source-history').is_dir())

    def test_paginated_history_over_fifty_turns(self):
        rows=[json.loads(line) for line in self.roll.read_bytes().splitlines()]
        combined=[rows[0]]
        for i in range(75):
            turn_id=str(uuid.uuid4())
            for original in rows[1:]:
                row=json.loads(json.dumps(original));payload=row['payload']
                payload['turn_id']=turn_id
                if payload.get('item'):
                    payload['item']['id']=str(uuid.uuid4())
                row['ordinal']=len(combined);combined.append(row)
        self.roll.write_bytes(b''.join(encoded(row) for row in combined))
        with CodexRPC(codex_home=self.home) as rpc:
            rpc.call('thread/resume',{'threadId':self.sid,'excludeTurns':True})
            self.assertEqual(len(all_turns(rpc,self.sid)),75)
        job,m=self.send(True);dest,_=unpack(job,self.bus,self.dest,'book')
        book=self.base/'paginated-book';book.mkdir()
        receipt=import_native(dest,m,self.bus,book)
        self.assertEqual(receipt['turn_count'],75);self.assertTrue(receipt['verified'])

    def test_historical_tool_thread_argument_is_not_rewritten(self):
        rows=[json.loads(line) for line in self.roll.read_bytes().splitlines()]
        event={'timestamp':'2026-10-05T00:00:00Z','type':'event_msg','payload':{'type':'item_completed','thread_id':self.sid,'turn_id':rows[1]['payload']['turn_id'],'item':{'type':'McpToolCall','id':str(uuid.uuid4()),'server':'codex_app','tool':'read_thread','arguments':{'threadId':self.sid},'pluginId':'codex-app-tools@openai-bundled','status':'completed','result':{'content':[{'type':'text','text':'test result'}],'isError':False},'duration':{'secs':0,'nanos':1}},'started_at_ms':1791158400000,'completed_at_ms':1791158400001}}
        rows.insert(-1,event)
        for ordinal,row in enumerate(rows):row['ordinal']=ordinal
        self.roll.write_bytes(b''.join(encoded(row) for row in rows))
        cli='/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
        with CodexRPC(codex=cli,codex_home=self.home) as rpc:rpc.call('thread/resume',{'threadId':self.sid,'excludeTurns':True})
        job,m=pack(self.home,self.sid,self.workspace,self.bus,'mini','book',verify_native=True,codex=cli)
        dest,_=unpack(job,self.bus,self.dest,'book');book=self.base/'tool-book';book.mkdir()
        receipt=import_native(dest,m,self.bus,book,codex=cli)
        with CodexRPC(codex=cli,codex_home=book) as rpc:turns=all_turns(rpc,receipt['thread_id'])
        item=next(i for i in turns[0]['items'] if i['type']=='mcpToolCall')
        self.assertEqual(item['arguments']['threadId'],self.sid)
        self.assertTrue(receipt['verified'])

    def test_native_history_and_return_trip(self):
        with CodexRPC(codex_home=self.home) as rpc:
            rpc.call('thread/resume',{'threadId':self.sid,'excludeTurns':True})
        job,m=self.send(True);dest,_=unpack(job,self.bus,self.dest,'book');book=self.base/'book-codex';book.mkdir()
        receipt=import_native(dest,m,self.bus,book)
        self.assertTrue(receipt['verified']);self.assertEqual(receipt['turn_count'],1)
        with CodexRPC(codex_home=book) as rpc:
            turns=all_turns(rpc,receipt['thread_id']);self.assertIn('Remember MOVE-TEST-8267.',json.dumps(turns));self.assertIn('Ready: MOVE-TEST-8267.',json.dumps(turns))
        (dest/'workspace/.hidden').write_bytes(b'edited on receiving device')
        job2,m2=pack(book,receipt['thread_id'],dest/'workspace',self.bus,'book','mini','Move test',verify_native=True)
        self.assertEqual(len(m2['histories']),2)
        back,_=unpack(job2,self.bus,self.base/'returned','mini')
        receipt2=import_native(back,m2,self.bus,self.home)
        self.assertTrue(receipt2['verified']);self.assertEqual((back/'workspace/.hidden').read_bytes(),b'edited on receiving device')
        self.assertEqual((self.workspace/'.hidden').read_bytes(),bytes(range(256)))

if __name__=='__main__':unittest.main(verbosity=2)
