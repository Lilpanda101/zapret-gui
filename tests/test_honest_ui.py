import ast
import os
import subprocess
import time
from unittest.mock import MagicMock, patch
import pytest

MAIN_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")


def find_dialog_calls(tree):
    """Finds all AST call nodes calling show_dialog with 'Успех' as first arg."""
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            is_dialog = False
            if isinstance(node.func, ast.Attribute) and node.func.attr == "show_dialog":
                is_dialog = True
            elif isinstance(node.func, ast.Name) and node.func.id == "show_dialog":
                is_dialog = True

            if is_dialog and node.args:
                first_arg = node.args[0]
                if isinstance(first_arg, ast.Constant) and first_arg.value == "Успех":
                    results.append(node)
    return results


def is_guarded_by_returncode_or_callback(node, parent_map):
    """
    Checks that the show_dialog('Успех', ...) call is either inside an 'if returncode == 0'
    block, or inside an on_ok/on_success callback.
    """
    curr = node
    while curr in parent_map:
        curr = parent_map[curr]

        if isinstance(curr, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if curr.name in ("on_ok", "on_success", "finish", "on_complete"):
                return True

        if isinstance(curr, ast.If):
            test_src = ast.unparse(curr.test) if hasattr(ast, "unparse") else ""
            if "returncode == 0" in test_src or "res.returncode == 0" in test_src:
                return True

    return False


def test_no_unguarded_success_dialogs():
    with open(MAIN_PY, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source, filename=MAIN_PY)

    parent_map = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_map[child] = parent

    success_calls = find_dialog_calls(tree)
    assert len(success_calls) > 0, "Expected at least one success dialog in main.py"

    unguarded = []
    for call in success_calls:
        if not is_guarded_by_returncode_or_callback(call, parent_map):
            lineno = getattr(call, "lineno", "?")
            code_snippet = ast.unparse(call) if hasattr(ast, "unparse") else "show_dialog"
            unguarded.append(f"Line {lineno}: {code_snippet}")

    assert not unguarded, f"Found unguarded 'Успех' dialog calls without returncode check:\n" + "\n".join(unguarded)


def test_run_engine_async_success():
    import main

    completed = subprocess.CompletedProcess(args=["engine.sh", "tune"], returncode=0, stdout="OK tuned\n", stderr="")
    with patch("main.run_engine", return_value=completed) as mock_run:
        ok_mock = MagicMock()
        err_mock = MagicMock()

        # Mock safe_idle to invoke directly
        with patch("main.safe_idle", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            main.run_engine_async(["tune"], on_success=ok_mock, on_error=err_mock)
            time.sleep(0.1)

            ok_mock.assert_called_once_with("OK tuned")
            err_mock.assert_not_called()


def test_run_engine_async_failure():
    import main

    failed = subprocess.CompletedProcess(args=["engine.sh", "tune"], returncode=1, stdout="", stderr="Permission denied\n")
    with patch("main.run_engine", return_value=failed) as mock_run:
        ok_mock = MagicMock()
        err_mock = MagicMock()

        with patch("main.safe_idle", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            main.run_engine_async(["tune"], on_success=ok_mock, on_error=err_mock)
            time.sleep(0.1)

            ok_mock.assert_not_called()
            err_mock.assert_called_once_with("Permission denied")


def test_safe_idle_runner_returns_false():
    import main

    recorded_runner = []
    with patch("main.GLib.idle_add", side_effect=lambda r: recorded_runner.append(r)):
        called = []
        main.safe_idle(lambda x: called.append(x), 42)

        assert len(recorded_runner) == 1
        runner = recorded_runner[0]
        ret = runner()
        assert ret is False
        assert called == [42]
