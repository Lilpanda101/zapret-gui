#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Orchestrator package: Stage 4 auto-selection of presets."""
from .targets import (
    Target,
    ProbeResult,
    DEFAULT_TARGETS,
    default_targets,
    http_probe,
    targets_from_domains,
    make_curl_cffi_probe,
    select_probe,
    select_http_transport,
    get_probe_transport_name,
)
from .history import HistoryStore, RunRecord
from .learning import (
    LearningStore,
    TargetStrategyStat,
    group_subdomains,
    is_russian_white_domain,
    is_ignored_target,
    DEFAULT_IGNORED_TARGETS,
    RUSSIAN_WHITE_DOMAINS,
)
from .orchestrator import Orchestrator, OrchestratorResult, PresetResult, TargetResult

__all__ = [
    'Target', 'ProbeResult', 'DEFAULT_TARGETS', 'default_targets', 'http_probe', 'targets_from_domains', 'make_curl_cffi_probe',
    'select_probe', 'select_http_transport', 'get_probe_transport_name',
    'HistoryStore', 'RunRecord',
    'LearningStore', 'TargetStrategyStat', 'group_subdomains',
    'is_russian_white_domain', 'is_ignored_target',
    'DEFAULT_IGNORED_TARGETS', 'RUSSIAN_WHITE_DOMAINS',
    'Orchestrator', 'OrchestratorResult', 'PresetResult', 'TargetResult',
]
