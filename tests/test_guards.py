#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static guards for Stage 9: architecture invariants that must not regress.

- version has a single source of truth (version.py)
- background thread workers do not create Gtk widgets
- page builders (create_*) do not call subprocess directly on the UI thread
- engine.sh keeps Stage 1 hardening (no pkill -9, no /tmp watchdog/pid)
- CI workflow exists and covers pytest / ruff / shellcheck / py_compile / bash -n
"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PY = os.path.join(ROOT, 'main.py')
ENGINE_SH = os.path.join(ROOT, 'engine.sh')
CI_YML = os.path.join(ROOT, '.github', 'workflows', 'ci.yml')


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _root_py_files():
    return [os.path.join(ROOT, f) for f in sorted(os.listdir(ROOT)) if f.endswith('.py')]


def _walk_without_nested_funcs(node):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield child
        yield from _walk_without_nested_funcs(child)


def test_version_single_source():
    offenders = []
    for path in _root_py_files():
        if os.path.basename(path) == 'version.py':
            continue
        for lineno, line in enumerate(_read(path).splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith('__version__') and '=' in stripped:
                offenders.append(f'{os.path.basename(path)}:{lineno}: {stripped}')
    assert not offenders, 'Version must be defined only in version.py:\n' + '\n'.join(offenders)


def test_no_hardcoded_version_literal_in_code():
    offenders = []
    for path in _root_py_files():
        if os.path.basename(path) == 'version.py':
            continue
        if '21.1.7' in _read(path):
            offenders.append(os.path.basename(path))
    assert not offenders, f'Hardcoded version literal outside version.py: {offenders}'


def test_thread_workers_do_not_create_widgets():
    tree = ast.parse(_read(MAIN_PY), filename=MAIN_PY)
    targets = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            is_thread = (isinstance(func, ast.Attribute) and func.attr == 'Thread') or (isinstance(func, ast.Name) and func.id == 'Thread')
            if is_thread:
                for kw in node.keywords:
                    if kw.arg == 'target' and isinstance(kw.value, ast.Name):
                        targets.add(kw.value.id)
    assert targets, 'Expected at least one threading.Thread target in main.py'
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in targets:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                    if isinstance(sub.func.value, ast.Name) and sub.func.value.id == 'Gtk' and sub.func.attr[:1].isupper():
                        offenders.append(f'{node.name}: Gtk.{sub.func.attr} at line {sub.lineno}')
    assert not offenders, 'Thread workers must not create Gtk widgets, use GLib.idle_add:\n' + '\n'.join(offenders)


def test_page_builders_do_not_call_subprocess_directly():
    tree = ast.parse(_read(MAIN_PY), filename=MAIN_PY)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith('create_'):
                    for sub in _walk_without_nested_funcs(item):
                        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                            if isinstance(sub.func.value, ast.Name) and sub.func.value.id == 'subprocess':
                                offenders.append(f'{item.name}: subprocess.{sub.func.attr} at line {sub.lineno}')
    assert not offenders, 'Page builders run on the UI thread and must not call subprocess:\n' + '\n'.join(offenders)


def test_engine_sh_keeps_stage1_hardening():
    src = _read(ENGINE_SH)
    assert 'pkill -9' not in src, 'engine.sh must not pkill -9 foreign engines'
    assert '/tmp/zapret-watchdog' not in src, 'watchdog must live in /run/zapret-gui, not /tmp'
    assert '/tmp/zapret-gui.pid' not in src, 'PID file must live in /run/zapret-gui, not /tmp'


def test_engine_sh_run_blockcheck2_propagates_returncode_without_swallowing():
    src = _read(ENGINE_SH)
    assert 'run_blockcheck2()' in src, 'run_blockcheck2 function must exist in engine.sh'
    func_body = src.split('run_blockcheck2() {', 1)[1].split('\n}', 1)[0]
    assert '|| true' not in func_body, 'run_blockcheck2 must not swallow errors with || true'
    assert '|| RC=$?' in func_body or 'RC=$?' in func_body, 'run_blockcheck2 must capture returncode via RC=$?'
    assert 'return $RC' in func_body, 'run_blockcheck2 must return $RC to caller'


def test_ci_workflow_covers_required_checks():
    assert os.path.exists(CI_YML), 'Missing .github/workflows/ci.yml'
    text = _read(CI_YML)
    for needle in ('pytest', 'ruff', 'shellcheck', 'py_compile', 'bash -n'):
        assert needle in text, f'CI workflow does not cover: {needle}'
