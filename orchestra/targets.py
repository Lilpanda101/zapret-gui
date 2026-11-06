#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe targets for the orchestrator."""
from __future__ import annotations
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass(frozen=True)
class Target:
    key: str
    name: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    latency_ms: int
    status: int | None = None
    error: str = ''


DEFAULT_TARGETS: Tuple[Target, ...] = (
    Target('youtube', 'YouTube', 'https://www.youtube.com/generate_204'),
    Target('googlevideo', 'YouTube Video (googlevideo)', 'https://redirector.googlevideo.com/report_mapping'),
    Target('discord', 'Discord', 'https://discord.com/api/v10/gateway'),
    Target('google', 'Google', 'https://www.google.com/generate_204'),
    Target('cloudflare', 'Cloudflare', 'https://1.1.1.1/dns-query?name=cloudflare.com&type=A', {'Accept': 'application/dns-json'}),
    Target('rutracker', 'RuTracker', 'https://rutracker.org'),
)


def default_targets():
    return list(DEFAULT_TARGETS)


def targets_from_domains(domains):
    results = []
    for raw in domains or []:
        value = str(raw).strip()
        if not value:
            continue
        url = value if value.startswith(('http://', 'https://')) else 'https://' + value
        host = re.sub(r'^https?://', '', url).split('/')[0]
        key = re.sub(r'[^a-z0-9]+', '_', host.casefold()).strip('_') or 'custom'
        results.append(Target(key, host, url))
    return results


def http_probe(target, timeout=3.5):
    t0 = time.time()
    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0'}
    headers.update(target.headers or {})
    try:
        req = urllib.request.Request(target.url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as res:
            dt = int((time.time() - t0) * 1000)
            return ProbeResult(200 <= res.status < 400, dt, res.status, '')
    except urllib.error.HTTPError as exc:
        dt = int((time.time() - t0) * 1000)
        return ProbeResult(exc.code < 500, dt, exc.code, str(exc))
    except Exception as exc:
        return ProbeResult(False, 9999, None, str(exc))
