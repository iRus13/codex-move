"""Small client for the installed Codex app-server's public stdio protocol."""
import json, os, selectors, subprocess, time

class CodexRPC:
    def __init__(self, codex='codex', codex_home=None):
        env=os.environ.copy()
        if codex_home is not None: env['CODEX_HOME']=str(codex_home)
        self.proc=subprocess.Popen([codex,'app-server','--stdio'], stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env)
        self.sel=selectors.DefaultSelector();self.sel.register(self.proc.stdout,selectors.EVENT_READ)
        self.buf=b'';self.next_id=0
        try:
            self.call('initialize',{'clientInfo':{'name':'move-skill','title':'Move skill','version':'2.0'},'capabilities':{'experimentalApi':True,'requestAttestation':False}})
            self.send({'method':'initialized'})
        except BaseException:
            self.close();raise
    def send(self,item):
        self.proc.stdin.write(json.dumps(item).encode()+b'\n');self.proc.stdin.flush()
    def call(self,method,params,timeout=40):
        self.next_id+=1; wanted=self.next_id
        self.send({'id':wanted,'method':method,'params':params})
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            while b'\n' in self.buf:
                line,self.buf=self.buf.split(b'\n',1)
                if not line.strip():continue
                r=json.loads(line)
                if r.get('id')==wanted:
                    if 'error' in r: raise RuntimeError(f'{method}: {r["error"]}')
                    return r['result']
            if not self.sel.select(min(1,max(0,deadline-time.monotonic()))):continue
            chunk=os.read(self.proc.stdout.fileno(),1024*1024)
            if not chunk:raise RuntimeError('Codex app-server closed before responding')
            self.buf+=chunk
        raise TimeoutError(f'{method} outcome is unknown; do not repeat a mutating request without reconciliation')
    def close(self):
        self.sel.close()
        if self.proc.poll() is None:
            self.proc.terminate()
            try:self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait()
        for stream in (self.proc.stdin,self.proc.stdout):
            if stream:stream.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
