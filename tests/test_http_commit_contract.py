"""A successful write response must follow the commit, including source binding."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from kanpace.core.errors import APIError
from kanpace.http.commands import CommandRoutes


class SourceCommitContractTests(TestCase):
    def request(self, fail_commit=False):
        events=[]
        @contextmanager
        def transaction():
            events.append('begin')
            yield object()
            if fail_commit:
                events.append('rollback')
                raise APIError(500, 'commit failed')
            events.append('commit')
        handler=CommandRoutes()
        handler.server=SimpleNamespace(store=SimpleNamespace(write_transaction=transaction))
        handler.path='/api/projects/prj_test/sources'
        handler.validate_mutation=lambda: {'expected_revision':1}
        handler.json_response=lambda data,status=200: events.append(('response',status,data))
        handler.error_response=lambda error: handler.json_response({'error':error.message},error.status)
        handler.log_message=lambda *args: None
        with patch('kanpace.http.commands.access_control.handle',return_value=False), \
             patch('kanpace.http.commands.access_control.authorize',side_effect=lambda *a,**k:events.append('authorize')), \
             patch('kanpace.http.commands.project_sources.save_selection',side_effect=lambda *a,**k:events.append('save') or {'saved':True}):
            handler.do_POST()
        return events

    def test_sources_acknowledged_after_commit_and_lock_time_authorization(self):
        self.assertEqual(self.request(),['authorize','begin','authorize','save','commit',('response',200,{'saved':True})])

    def test_commit_failure_never_emits_success(self):
        events=self.request(True)
        self.assertIn('rollback',events)
        responses=[row for row in events if isinstance(row,tuple)]
        self.assertEqual(responses,[('response',500,{'error':'commit failed'})])
