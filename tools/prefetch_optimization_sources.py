"""Fetch the exact upstream source commits used by the audited PackingSolver build."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'vendor-sources/optimization/packingsolver'
TEXT=(SOURCE/'extern/CMakeLists.txt').read_text()
ENTRIES=re.findall(r'FetchContent_Declare\(\s*(\w+)\s*GIT_REPOSITORY\s+(https://github.com/fontanf/[^\s]+)\s*GIT_TAG\s+([0-9a-f]{40})',TEXT)
ENTRIES=[e for e in ENTRIES if e[0]!='knitrocpp']

def fetch(entry):
 name,url,sha=entry; target=ROOT/'vendor-sources/optimization/deps'/name
 target.mkdir(parents=True,exist_ok=True)
 if not (target/'.git').exists():
  subprocess.run(['git','init','-q',str(target)],check=True)
  subprocess.run(['git','-C',str(target),'remote','add','origin',url],check=True)
 subprocess.run(['git','-C',str(target),'fetch','--depth','1','origin',sha],check=True)
 subprocess.run(['git','-C',str(target),'checkout','--detach',sha],check=True)
 print(name,sha,flush=True)
 return {'name':name,'repository':url,'commit':sha,'source_dir':str(target)}
if __name__=='__main__':
 with ThreadPoolExecutor(max_workers=4) as pool: result=list(pool.map(fetch,ENTRIES))
 (ROOT/'licenses/optimization/fontanf-sources.json').write_text(json.dumps(result,indent=2)+'\n')
