import json,subprocess
from pathlib import Path

def run(args, expected=0):
 print('$ '+(' '.join(args[:3])+f' <{len(args)-3} active tracked files>' if args[0]=='grep' else ' '.join(args)),flush=True)
 r=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 print(r.stdout.rstrip() or '(no output)');print('EXIT:',r.returncode)
 assert r.returncode==expected
 return r.stdout
# This scan excludes only dated review/evidence files; OPEN-DEPENDENCIES is current and included.
active=[]
for name in subprocess.check_output(['git','ls-files'],text=True).splitlines():
 if not Path(name).is_file():continue
 if '/implementation/' in name and not name.endswith('OPEN-DEPENDENCIES.md'):continue
 active.append(name)
for symbol in ('LIVEKIT.md','AGENT-INSTRUCTIONS.txt','agent-instructions','CORE_RULES'):
 run(['grep','-rnHF',symbol,*active],1)
print('PASS zero references in active tracked files; dated reports/evidence excluded, user temp/ untouched.')
for name in ('docs/handover/LIVEKIT.md','docs/handover/mcp-only/AGENT-INSTRUCTIONS.txt'):
 assert not Path(name).exists();print('PASS deleted:',name)
run(['git','diff','--exit-code','231f10a','--','.claude/agents'])
run(['git','diff','--exit-code','231f10a','--',*[f'services/mcp/src/frontdesk_mcp/{n}.py' for n in
 ['availability','tools','context','identity','summary','ops_client','config','server']]])
print('PASS date validation, dispatch, identity/lifecycle, summary and operational client source unchanged.')
snapshot='services/mcp/tests/contracts/mcp-tools.snapshot.json'
old=json.loads(subprocess.check_output(['git','show','231f10a:'+snapshot]));new=json.loads(Path(snapshot).read_text())
def structural(value):
 if isinstance(value,dict):return {k:structural(v) for k,v in value.items() if k not in ('description','title')}
 if isinstance(value,list):return [structural(v) for v in value]
 return value
assert structural(old['tools'])==structural(new['tools'])
print('PASS all tool names/scopes/annotations/constraints/enums/required fields/defaults identical to baseline.')
rendered=subprocess.check_output(['make','schema'])
assert rendered==Path(snapshot).read_bytes()
print('PASS make schema byte-identical; version',new['schemaVersion'])
print('Server instructions characters:',len(old['instructions']),'->',len(new['instructions']))
for base in ('231f10a','73a0832'):
 data=run(['git','diff',base,'--numstat','--','services/mcp/src'])
 counts=[list(map(int,line.split()[:2])) for line in data.splitlines()]
 print('SOURCE NET',base, sum(a-b for a,b in counts))
for sha in subprocess.check_output(['git','rev-list','--reverse','231f10a..HEAD'],text=True).splitlines():
 files=subprocess.check_output(['git','diff-tree','--no-commit-id','--name-only','-r',sha],text=True).splitlines()
 assert len(files)<=10
 print('PASS commit file limit:',sha[:7],len(files))
run(['git','diff','--check','231f10a','--','.',':(exclude)**/*.patch'])
run(['uvx','vulture','services/mcp/src','--min-confidence','80'])
