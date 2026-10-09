#!/usr/bin/env python3
"""Install reproducible optional workers; never imports app or opens business data."""
import argparse
from pathlib import Path
import json
import hashlib
import tarfile
import urllib.request
import os
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
PACKING_COMMIT='4ba84e45ab4b7697d2fec2bb62bdca09dab56d29'
BOOST_SHA256='2e64e5d79a738d0fa6fb546c6e5c2bd28f88d268a2a080546f74e5ff98f29d0e'

def run(command, **kwargs):
    print(' '.join(map(str,command)),flush=True)
    subprocess.run(list(map(str,command)),check=True,**kwargs)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python',default=shutil.which('python3.12') or shutil.which('python3.11') or sys.executable)
    parser.add_argument('--skip-python',action='store_true')
    parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args()
    if not 1<=args.jobs<=8: parser.error('--jobs must be 1..8')
    env=ROOT/'.venv-optimization'; bindir=env/('Scripts' if os.name=='nt' else 'bin')
    python=bindir/('python.exe' if os.name=='nt' else 'python')
    if not args.skip_python:
        if not python.is_file(): run([args.python,'-m','venv',env])
        lock=ROOT/'requirements-optimization.lock.txt'
        run([python,'-m','pip','install','-r',lock if lock.is_file() else ROOT/'requirements-optimization.txt'])
    # First native-module load can trigger slow OS library validation after download.
    run([python,ROOT/'optimization_worker.py'],input=json.dumps({'operation':'status'}),text=True,timeout=180)
    source=ROOT/'vendor-sources/optimization/packingsolver'
    source.parent.mkdir(parents=True,exist_ok=True)
    if not (source/'.git').is_dir():
        source.mkdir(exist_ok=True); run(['git','init',source]); run(['git','-C',source,'remote','add','origin','https://github.com/fontanf/packingsolver.git'])
    head=subprocess.run(['git','-C',str(source),'rev-parse','HEAD'],capture_output=True,text=True)
    if head.stdout.strip()!=PACKING_COMMIT:
        run(['git','-C',source,'fetch','--depth','1','origin',PACKING_COMMIT]); run(['git','-C',source,'checkout','--detach',PACKING_COMMIT])
    boost_source=ROOT/'vendor-sources/optimization/boost-1.84.0'
    boost_archive=ROOT/'vendor-sources/optimization/archives/boost-1.84.0.tar.xz'
    if not boost_source.is_dir():
        boost_archive.parent.mkdir(parents=True,exist_ok=True)
        if not boost_archive.is_file():
            print('Downloading pinned official Boost 1.84.0 archive',flush=True)
            temporary=boost_archive.with_suffix('.download')
            with urllib.request.urlopen('https://github.com/boostorg/boost/releases/download/boost-1.84.0/boost-1.84.0.tar.xz',timeout=60) as response, temporary.open('wb') as target:
                shutil.copyfileobj(response,target)
            temporary.replace(boost_archive)
        if hashlib.sha256(boost_archive.read_bytes()).hexdigest()!=BOOST_SHA256:
            raise RuntimeError('Boost source archive checksum mismatch')
        with tarfile.open(boost_archive,'r:xz') as archive:
            archive.extractall(boost_source.parent,filter='data')
    cmake=bindir/('cmake.exe' if os.name=='nt' else 'cmake')
    build=ROOT/'build/optimization/packingsolver'
    command=[cmake,'-S',source,'-B',build,'-DCMAKE_BUILD_TYPE=Release','-DPACKINGSOLVER_BUILD_TEST=OFF',
             '-DPACKINGSOLVER_USE_CLP=OFF','-DPACKINGSOLVER_USE_HIGHS=ON','-DPACKINGSOLVER_USE_KNITRO=OFF']
    # Reuse exact upstream sources pre-fetched on slow connections, if present.
    depfile=ROOT/'licenses/optimization/fontanf-sources.json'
    if depfile.is_file():
        for entry in json.loads(depfile.read_text()):
            path=ROOT/'vendor-sources/optimization/deps'/entry['name']
            if path.is_dir(): command.append('-DFETCHCONTENT_SOURCE_DIR_'+entry['name'].upper()+'='+str(path))
    for name,path in [('HIGHS',ROOT/'vendor-sources/optimization/deps/highs'),('BOOST',ROOT/'vendor-sources/optimization/boost-1.84.0')]:
        if path.is_dir(): command.append('-DFETCHCONTENT_SOURCE_DIR_'+name+'='+str(path))
    run(command)
    run([cmake,'--build',build,'--config','Release','--target','PackingSolver_rectangleguillotine_main','--parallel',str(args.jobs)])
    name='packingsolver_rectangleguillotine'+('.exe' if os.name=='nt' else '')
    binaries=[x for x in build.rglob(name) if x.is_file()]
    if not binaries: raise RuntimeError('Official PackingSolver CLI was not built')
    destination=ROOT/'bin/optimization'; destination.mkdir(parents=True,exist_ok=True)
    shutil.copy2(binaries[0],destination/name)
    run([python,ROOT/'tools/archive_optimization_licenses.py'])
    result=subprocess.run([python,'-m','pip','freeze'],capture_output=True,text=True,check=True)
    (ROOT/'requirements-optimization.lock.txt').write_text(result.stdout)
    print('Installed local workers. Run KANPACE_TEST_REAL_ENGINES=1 python -m unittest discover -s tests -p test_optimization_engines.py')

if __name__=='__main__': main()
