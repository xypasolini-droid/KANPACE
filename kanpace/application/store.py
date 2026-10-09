"""Application composition root and backwards-compatible manufacturing API.

HTTP, device execution and other adapters share this same application. The
repository persists records; services own production behavior. No HTTP startup
or platform UI is needed to instantiate a factory's application.
"""
from __future__ import annotations

from kanpace.infrastructure.sqlite import SQLiteRepository
from kanpace.application.projects import ProjectService
from kanpace.application.engineering import EngineeringService
from kanpace.application.execution import ExecutionService
from kanpace.application.device_execution import DeviceExecutionService
from kanpace.application.resources import ResourceService
from kanpace.application.queries import QueryService
from kanpace.application.audit import AuditService
from kanpace.application.bootstrap import BootstrapService
from kanpace.application.daily_workflow import DailyWorkflowService


class Store(SQLiteRepository):
    def __init__(self, data_dir, seed=True, empty=False):
        self.projects = ProjectService(self)
        self.engineering = EngineeringService(self)
        self.execution = ExecutionService(self)
        self.device_execution = DeviceExecutionService(self)
        self.resources = ResourceService(self)
        self.queries = QueryService(self)
        self.audit = AuditService(self)
        self.bootstrap = BootstrapService(self)
        self.daily_workflow = DailyWorkflowService(self)
        super().__init__(data_dir)
        self.bootstrap.initialize(seed=seed, empty=empty)

    def new_project(self, con, data, demo=False):
        return self.projects.new_project(con, data, demo)

    @staticmethod
    def require_project_open(project):
        return ProjectService.require_project_open(project)

    def set_fulfillment(self, con, project_id, data):
        return self.projects.set_fulfillment(con, project_id, data)

    def invalidate(self, con, project, reason, part_id=None):
        return self.engineering.invalidate(con, project, reason, part_id)

    def create_part(self, con, data):
        return self.engineering.create_part(con, data)

    def apply_part_edits(self, part, edits):
        return self.engineering.apply_part_edits(part, edits)

    def review_part(self, con, identifier, data):
        return self.engineering.review_part(con, identifier, data)

    def related_order_drafts(self, con, digest, projects=None):
        return self.engineering.related_order_drafts(con, digest, projects)

    def import_file(self, con, data):
        return self.engineering.import_file(con, data)

    def import_process_basis(self, con, project, filename, content, digest, existing):
        return self.engineering.import_process_basis(con, project, filename, content, digest, existing)

    def process_basis_verified(self, con, project, doc):
        return self.engineering.process_basis_verified(con, project, doc)

    def import_render(self, con, project, filename, content, digest, existing, scope='project'):
        return self.engineering.import_render(con, project, filename, content, digest, existing, scope)

    def import_order_draft(self, con, data):
        return self.engineering.import_order_draft(con, data)

    def generate(self, con, project_id):
        return self.engineering.generate(con, project_id)

    def release(self, con, project_id):
        return self.engineering.release(con, project_id)

    def resolve_document(self, con, identifier, data):
        return self.engineering.resolve_document(con, identifier, data)

    def assign(self, con, task_id, person_id, data=None):
        return self.execution.assign(con, task_id, person_id, data)

    def auto_assign(self, con, project_id):
        return self.execution.auto_assign(con, project_id)

    @staticmethod
    def bump_execution(task):
        return ExecutionService.bump_execution(task)

    @staticmethod
    def check_execution_version(task, data, key='expected_execution_version'):
        return ExecutionService.check_execution_version(task, data, key)

    @staticmethod
    def remaining_minutes(task):
        return ExecutionService.remaining_minutes(task)

    def execution_task(self, con, task_id, data=None, allow_done=False):
        return self.execution.execution_task(con, task_id, data, allow_done)

    def start_blockers(self, con, task, ignore_task_id=None, completing=False):
        return self.execution.start_blockers(con, task, ignore_task_id, completing)

    def require_start(self, con, task, ignore_task_id=None, completing=False):
        return self.execution.require_start(con, task, ignore_task_id, completing)

    @staticmethod
    def progress_value(task, value):
        return ExecutionService.progress_value(task, value)

    def save_execution(self, con, task, action, message, **details):
        return self.execution.save_execution(con, task, action, message, **details)

    def report_progress(self, con, task_id, data):
        return self.execution.report_progress(con, task_id, data)

    def pause_values(self, task, data, legacy=False):
        return self.execution.pause_values(task, data, legacy)

    def pause_task(self, con, task_id, data, legacy=False):
        return self.execution.pause_task(con, task_id, data, legacy)

    def resume_task(self, con, task_id, data, to_ready=False):
        return self.execution.resume_task(con, task_id, data, to_ready)

    def set_priority(self, con, task_id, data):
        return self.execution.set_priority(con, task_id, data)

    def switch_task(self, con, task_id, data):
        return self.execution.switch_task(con, task_id, data)

    def task_queue(self, con, person_id=None, project_id=None, from_task_id=None):
        return self.execution.task_queue(con, person_id, project_id, from_task_id)

    def set_status(self, con, task_id, data):
        return self.execution.set_status(con, task_id, data)

    def handle_device_execution(self, frame):
        return self.device_execution.handle_device_execution(frame)

    def save_person(self, con, data, person_id=None):
        return self.resources.save_person(con, data, person_id)

    def update_settings(self, con, data):
        return self.resources.update_settings(con, data)

    def update_project_costs(self, con, project_id, data):
        return self.resources.update_project_costs(con, project_id, data)

    def quote(self, con, project_id):
        return self.resources.quote(con, project_id)

    def state(self, con):
        return self.queries.state(con)

    def event(self, con, project_id, action, message, **details):
        return self.audit.event(con, project_id, action, message, **details)

    def seed(self, con):
        return self.bootstrap.seed(con)
