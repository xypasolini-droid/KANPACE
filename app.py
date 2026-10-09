#!/usr/bin/env python3
"""KANPACE compatibility entry point.

Runtime architecture lives in kanpace/: core/domain rules, application services,
SQLite infrastructure and HTTP adapters. Existing app.Store/app.Server imports
and python3 app.py startup remain supported.

Distribution: see LICENSING.md and THIRD_PARTY_NOTICES.md.
"""
from kanpace.core.constants import BASE, MAX_UPLOAD, MAX_BODY, ROLES, CATEGORIES, PAUSE_REASONS, COLLECTIONS, DEFAULT_SETTINGS
from kanpace.core.errors import APIError
from kanpace.core.validation import now, uid, number, short_text, whole_number
from kanpace.core.records import part_aliases, task_aliases, project_aliases
from kanpace.domain.parts import part_blockers
from kanpace.infrastructure.sqlite import ClosingConnection
from kanpace.application.store import Store
from kanpace.http.server import Handler, Server
from kanpace.bootstrap import main

# Legacy consumers access these named domain/adapter modules through app.
import engine
import analytics
import order_drafts
import model_workspace
import fulfillment
import planning
import schedule_reference
import operations
import production
import file_exchange
import scheduling
import calibration
import access_control
import agent_assistant
import engineering_readiness
import langgraph_agent
import factory_instances
import factory_config
import control_platform
import project_sources
import intelligence
import optimization_engines
import badge_media
from device_bridge import DeviceBridge, DeviceError

if __name__ == "__main__":
    main()
