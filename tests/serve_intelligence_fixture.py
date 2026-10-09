"""Disposable, synthetic browser fixture. Never opens the production data dir."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import operations
from test_engineering_engines import raster_fixture


def main():
    with tempfile.TemporaryDirectory(prefix='kanpace-five-engines-ui-') as directory:
        store=app.Store(directory,seed=False)
        with store.connect() as con:
            factory=operations.save_factory(store,con,{'name':'隔离测试工厂','factory_type':'cabinet'})['factory']
            person=operations.save_person(store,con,{'name':'测试木工','skills':['木工'],'capacity_minutes':480,'factory_id':factory['id']})['person']
            project=store.new_project(con,{'name':'五项引擎 · 隔离验收样本','factory_type':'cabinet','due_date':'2026-09-08'})
            project.update(factory_id=factory['id'],status='released',released_revision=1)
            store.put(con,'projects',project)
            png,pdf=raster_fixture(store.uploads)
            for i,path in enumerate([png,pdf]):
                store.put(con,'documents',{'id':f'qa_engineering_{i}','project_id':project['id'],
                    'filename':path.name,'storage_name':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                    'purpose':'construction','parser_status':'pending_review','created_at':app.now(),'revision':1})
            for i,minutes in enumerate([120,60]):
                store.put(con,'tasks',{'id':f'qa_opt_{i}','project_id':project['id'],'factory_id':factory['id'],'revision':1,
                    'title':['侧板开料','侧板封边'][i],'trade':'木工','process':'cut' if i==0 else 'edge',
                    'status':'ready','assignee':person['id'],'quantity':2,'completed_quantity':0,'execution_version':0,
                    'hours':minutes/60,'dependencies':['qa_opt_0'] if i else [],'priority':0,'start_checks':[]})
        server=app.Server(('127.0.0.1',8766),store)
        info={'url':f'http://127.0.0.1:8766/#page=drawing&project={project["id"]}',
              'project_id':project['id'],'data_dir':directory,'synthetic_only':True}
        infofile=Path(__file__).resolve().parents[1]/'output/intelligence-fixture.json'
        infofile.parent.mkdir(exist_ok=True);infofile.write_text(json.dumps(info,ensure_ascii=False,indent=2))
        print(json.dumps(info,ensure_ascii=False),flush=True)
        try:server.serve_forever()
        finally:server.server_close()


if __name__=='__main__':main()
