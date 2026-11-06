import ast
import json
from pathlib import Path
import pytest

HEALER_PY = Path("healer.py")
MAIN_PY = Path("main.py")
HARDCODED_PRESET_NAMES = {"general ALT", "Default (circular)", "general FAKE TLS AUTO", "ALL TCP & UDP hostfakesplit"}


def get_ast(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_healer_no_txt_literals():
    """Статический AST-тест: в healer.py нет строковых литералов '.txt'."""
    tree = get_ast(HEALER_PY)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.endswith(".txt") or node.value == ".txt":
                violations.append(f"Line {node.lineno}: {repr(node.value)}")
    assert not violations, "Found banned '.txt' string literals in healer.py:\n" + "\n".join(violations)


def test_healer_no_hardcoded_preset_lists():
    """Статический AST-тест: в healer.py нет захардкоженных списков пресетов."""
    tree = get_ast(HEALER_PY)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            elements = [elt.value for elt in node.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
            if any(p in HARDCODED_PRESET_NAMES for p in elements):
                violations.append(f"Line {node.lineno}: Hardcoded preset list: {elements}")
    assert not violations, "Found hardcoded preset lists in healer.py:\n" + "\n".join(violations)


def test_main_no_hardcoded_preset_lists():
    """Статический AST-тест: в main.py нет захардкоженных списков пресетов."""
    tree = get_ast(MAIN_PY)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            elements = [elt.value for elt in node.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
            if any(p in HARDCODED_PRESET_NAMES for p in elements):
                violations.append(f"Line {node.lineno}: Hardcoded preset list: {elements}")
    assert not violations, "Found hardcoded preset lists in main.py:\n" + "\n".join(violations)


def test_healer_state_does_not_store_preset_copy():
    """Проверяет, что HealerState не хранит собственную копию пресета (current_preset)."""
    import healer
    state = healer.HealerState()
    assert not hasattr(state, "current_preset"), "HealerState must not store an internal current_preset"


def test_healer_reads_active_preset_from_engine_params_ssot(monkeypatch, tmp_path):
    """Проверяет, что AutoHealer.get_status() читает активный пресет из единого источника (EngineParams/конфиг)."""
    import healer
    fake_config = {
        "engine_mode": "nfqws2",
        "zapret2_preset": "Default (circular).txt",
        "preset": "general",
    }
    monkeypatch.setattr(healer, "load_config", lambda: fake_config)
    h = healer.AutoHealer()
    status = h.get_status()
    assert status.get("current_preset") == "Default (circular).txt"

    # При смене в конфиге статус отражает новый пресет без мутации state
    fake_config["zapret2_preset"] = "general ALT 1.10.3.txt"
    assert h.get_status().get("current_preset") == "general ALT 1.10.3.txt"
