"""AuditService: application behavior, independent of HTTP startup.

The caller owns the transaction. Cross-service work uses the manufacturing port,
so state transitions, source revision checks and audit records stay atomic.
"""
from __future__ import annotations

from kanpace.application.ports import ManufacturingPort
from kanpace.core.validation import now
from kanpace.core.validation import uid
import access_control


class AuditService:
    def __init__(self, store: ManufacturingPort):
        self.store = store

    def event(self, con, project_id, action, message, **details):
        actor = access_control.get_actor()
        event = {'id': uid('ev'), 'project_id': project_id, 'action': action, 'message': message,
                 'created_at': now(), 'actor': actor['name'] if actor else '本机操作员', 'details': details}
        if actor and actor.get('access_enabled'):
            event['actor_id'] = actor['id']
            event['actor_role'] = actor['role']
            event['actor_person_id'] = actor.get('person_id')
        self.store.put(con, 'events', event)
        return event
