"""End-to-end checks on the example LeetCode cases: real Java tracing through to visual states."""

from __future__ import annotations

import json
from functools import cache
from typing import Any

import pytest

from dsaviz.pipeline import prepare
from dsaviz.tracer import REPO, Tracer

CASES = json.loads((REPO / "examples" / "cases.json").read_text())


@cache
def tracer() -> Tracer:
    return Tracer()


@cache
def traced(name: str) -> dict[str, Any]:
    case = CASES[name]
    code = (REPO / "examples" / "cases" / f"{name}.java").read_text()
    return tracer().run(code, case["method"], None, case["inputs"])


def elements(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {el["key"]: el for el in state["elements"]}


@pytest.mark.parametrize("name", list(CASES))
def test_every_case_traces_and_builds(name: str) -> None:
    result = traced(name)
    assert result["diagnostics"] == []
    ui, states = prepare(result)
    assert len(ui) == len(states) > 0
    for state in states:
        keys = [el["key"] for el in state["elements"]]
        assert len(keys) == len(set(keys)), "element keys must be unique within a state"
        for el in state["elements"]:
            for k in ("x", "y", "x1", "y1", "x2", "y2"):
                if k in el:
                    limit = 7.12 if k.startswith("x") else 4.0
                    assert -limit <= el[k] <= limit, f"{el['key']} is off the canvas"


def test_linked_list_nodes_never_move_during_reversal() -> None:
    _, states = prepare(traced("reverse-linked-list"))
    positions: dict[str, tuple[float, float]] = {}
    for state in states:
        for key, el in elements(state).items():
            if key.startswith("node:"):
                assert positions.setdefault(key, (el["x"], el["y"])) == (el["x"], el["y"])


def test_reversal_rewires_next_pointers_backwards() -> None:
    _, states = prepare(traced("reverse-linked-list"))
    last = elements(states[-1])
    nodes = sorted((el for k, el in last.items() if k.startswith("node:")), key=lambda el: el["x"])
    assert [n["text"] for n in nodes] == ["1", "2", "3", "4", "5"]
    edges = [el for k, el in last.items() if k.startswith("edge:")]
    assert len(edges) == 4 and all(e["x2"] < e["x1"] for e in edges), "every next arrow points left after reversal"
    assert "varname:return" in last


def test_iterations_and_next_iteration_jumps_to_loop_header() -> None:
    ui, _ = prepare(traced("reverse-linked-list"))
    looped = [s for s in ui if s["iteration"]]
    assert {s["iteration"]["total"] for s in looped} == {5}
    first = next(i for i, s in enumerate(ui) if s["iteration"])
    target = ui[first]["nextIteration"]
    assert ui[target]["line"] == ui[first]["iteration"]["header"]
    assert ui[target]["iteration"]["iteration"] == 2


def test_null_pointer_marks_the_null_field_red() -> None:
    result = traced("npe-bug")
    error = result["trace"]["error"]
    assert error["type"] == "java.lang.NullPointerException" and error["line"] == 8
    _, states = prepare(result)
    last = elements(states[-1])
    assert "error:banner" in last
    red = [k for k, el in last.items() if el.get("color") == "#EF4444" and k.startswith("null")]
    assert red, "the null that was dereferenced is drawn in red"


def test_out_of_bounds_draws_a_ghost_cell_past_the_end() -> None:
    result = traced("off-by-one")
    assert result["trace"]["error"]["type"] == "java.lang.ArrayIndexOutOfBoundsException"
    _, states = prepare(result)
    last = elements(states[-1])
    ghost = next(el for k, el in last.items() if k.endswith(":ghost"))
    cells = [el for k, el in last.items() if ":c" in k and el["type"] == "box"]
    assert ghost["text"] == "[3]" and ghost["x"] > max(c["x"] for c in cells)


def test_index_pointers_follow_two_pointer_variables() -> None:
    _, states = prepare(traced("valid-palindrome"))
    seen = {k for state in states for k in elements(state) if ":p:" in k}
    assert any(k.endswith(":p:i") for k in seen) and any(k.endswith(":p:j") for k in seen)


def test_created_nodes_join_the_row_they_link_into() -> None:
    _, states = prepare(traced("doubly-and-set"))
    last = elements(states[-1])
    ys = {el["y"] for k, el in last.items() if k.startswith("node:")}
    assert len(ys) == 1, "appended nodes sit on one row"


def test_compile_errors_are_reported_with_lines() -> None:
    result = tracer().run("class Solution {\n  int f(int n) {\n    return n\n  }\n}", "f", None, {"n": "1"})
    assert result.get("trace") is None
    assert result["diagnostics"][0]["line"] == 3


def test_bad_input_names_the_parameter() -> None:
    code = (REPO / "examples" / "cases" / "two-sum.java").read_text()
    result = tracer().run(code, "twoSum", None, {"nums": "[2,7", "target": "9"})
    assert result["inputError"]["param"] == "nums"


def test_circular_override_draws_a_ring() -> None:
    _, plain = prepare(traced("reverse-linked-list"))
    _, ring = prepare(traced("reverse-linked-list"), {"head": "circular"})
    ys_plain = {el["y"] for k, el in elements(plain[0]).items() if k.startswith("node:")}
    ys_ring = {el["y"] for k, el in elements(ring[0]).items() if k.startswith("node:")}
    assert len(ys_plain) == 1 and len(ys_ring) > 1


def u16(s: str) -> int:
    """Length in UTF-16 code units, the way Java and the browser count string offsets."""
    return len(s.encode("utf-16-le")) // 2


def test_each_step_knows_how_much_output_came_before_it() -> None:
    result = traced("print-pyramid")
    stdout = result["trace"]["stdout"]
    assert stdout == "  * \n * * * \n* * * * * \ndone ✓ 🎉\n"
    assert result["trace"]["stdoutTruncated"] is False
    ui, _ = prepare(result)
    printed = [s["printed"] for s in ui]
    assert printed[0] == 0
    assert printed == sorted(printed)
    assert printed[-1] == u16(stdout)
    first_println = next(i for i, s in enumerate(ui) if s["line"] == 5)
    assert printed[first_println] == u16("  ")
    assert printed[first_println + 1] == u16("  * \n")


def test_a_print_of_nothing_adds_no_output() -> None:
    ui, _ = prepare(traced("print-pyramid"))
    last_print = [i for i, s in enumerate(ui) if s["line"] == 4][-1]  # i == n prints " ".repeat(0)
    assert ui[last_print + 1]["printed"] == ui[last_print]["printed"]


def test_output_before_a_crash_is_kept() -> None:
    code = "class Solution {\n  void f(int n) {\n    System.out.print(\"before\");\n    int[] a = new int[n];\n    a[n] = 1;\n  }\n}"
    result = tracer().run(code, "f", None, {"n": "1"})
    ui, _ = prepare(result)
    assert result["trace"]["stdout"] == "before"
    assert ui[-1]["event"] == "exception" and ui[-1]["printed"] == 6


def test_huge_output_is_capped_and_offsets_stay_inside_it() -> None:
    code = "class Solution {\n  void f(int n) {\n    System.out.print(\"x\".repeat(n));\n  }\n}"
    result = tracer().run(code, "f", None, {"n": "100000"})
    trace = result["trace"]
    assert len(trace["stdout"]) == 64 * 1024 and trace["stdoutTruncated"] is True
    ui, _ = prepare(result)
    assert ui[-1]["printed"] == 64 * 1024


def test_jvm_warnings_never_land_in_the_output(monkeypatch: pytest.MonkeyPatch) -> None:
    # Without large pages configured, this makes every JVM print a warning to stdout before any user output.
    monkeypatch.setenv("JDK_JAVA_OPTIONS", "-XX:+UseLargePages")
    code = "class Solution {\n  void f(int n) {\n    System.out.print(\"ab\");\n  }\n}"
    result = Tracer().run(code, "f", None, {"n": "1"})
    assert result["trace"]["stdout"] == "ab"
