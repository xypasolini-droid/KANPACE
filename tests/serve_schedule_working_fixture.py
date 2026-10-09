"""Isolated synthetic R33 schedule browser fixture; never opens production data."""
from pathlib import Path
import json
import signal
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_schedule_working import WorkingScheduleTests

fixture=WorkingScheduleTests()
fixture.setUp()
try:
    project,task,person,tasks=fixture.fixture()
    fixture.draft(two=True)
    print(json.dumps({'url':fixture.url+'/factory/index.html#page=planning','data_dir':fixture.temp.name,'synthetic_only':True}),flush=True)
    signal.pause()
finally:
    fixture.tearDown()
