"""Archive the licenses shipped with installed optimization dependencies."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'licenses/optimization'; DEST.mkdir(parents=True,exist_ok=True)
records=[]
for dist in importlib.metadata.distributions():
    files=[]
    for item in dist.files or []:
        if ('license' in item.name.lower() or 'copying' in item.name.lower() or 'notice' in item.name.lower()) and '.dist-info' in str(item):
            source=Path(dist.locate_file(item))
            if source.is_file():
                target=DEST/'python'/dist.metadata['Name']/str(item).split('.dist-info/',1)[-1]
                target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,target); files.append(str(target.relative_to(ROOT)))
    records.append({'name':dist.metadata['Name'],'version':dist.version,'licenses':files})
source_roots=[ROOT/'vendor-sources/optimization/packingsolver',ROOT/'vendor-sources/optimization/boost-1.84.0']
source_roots+=list((ROOT/'vendor-sources/optimization/deps').glob('*'))
source_roots+=list((ROOT/'build/optimization/packingsolver/_deps').glob('*-src'))
sources=[]
for folder in source_roots:
    if not folder.is_dir(): continue
    files=[]
    candidates=folder.iterdir() if folder.name.startswith('boost-') else folder.rglob('*')
    for item in candidates:
        if item.is_file() and any(item.name.lower().startswith(k) for k in ('license','licence','copying','notice','copyright')):
            target=DEST/'cpp'/folder.name/item.relative_to(folder); target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(item,target);files.append(str(target.relative_to(ROOT)))
    commit=subprocess.run(['git','-C',str(folder),'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip() if (folder/'.git').exists() else None
    sources.append({'name':folder.name,'commit':commit,'licenses':files})
binary=ROOT/'bin/optimization/packingsolver_rectangleguillotine'
if not binary.is_file(): binary=binary.with_suffix('.exe')
manifest={'ortools':{'version':importlib.metadata.version('ortools'),'license':'Apache-2.0','repository':'https://github.com/google/or-tools'},
          'packingsolver':{'commit':'4ba84e45ab4b7697d2fec2bb62bdca09dab56d29','license':'MIT',
                           'repository':'https://github.com/fontanf/packingsolver','enabled_lp_backend':'HiGHS','clp_enabled':False,'knitro_enabled':False,
                           'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest() if binary.is_file() else None},
          'source_archives':[{'name':'boost-1.84.0.tar.xz','sha256':'2e64e5d79a738d0fa6fb546c6e5c2bd28f88d268a2a080546f74e5ff98f29d0e','url':'https://github.com/boostorg/boost/releases/download/boost-1.84.0/boost-1.84.0.tar.xz'}],
          'platform':platform.platform(),'python':platform.python_version(),'python_dependencies':records,'cpp_dependencies':sources}
(DEST/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'python_packages':len(records),'cpp_sources':len(sources),'manifest':str(DEST/'manifest.json')}))
