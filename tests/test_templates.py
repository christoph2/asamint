#!/usr/bin/env python
"""Tests for asamint.utils.templates – Mako wrapper functions."""
from __future__ import annotations

from mako.template import Template

from asamint.utils.templates import (
    call_def,
    do_template,
    do_template_from_text,
    indent_text,
)

# ---------------------------------------------------------------------------
# indent_text
# ---------------------------------------------------------------------------


def test_indent_text_zero_margin_unchanged() -> None:
    text = "line1\nline2\nline3"
    assert indent_text(text) == text


def test_indent_text_positive_margin_adds_spaces() -> None:
    result = indent_text("hello\nworld", left_margin=4)
    assert result == "    hello\n    world"


def test_indent_text_empty_line_not_indented() -> None:
    result = indent_text("a\n\nb", left_margin=2)
    assert result == "  a\n\n  b"


def test_indent_text_single_line() -> None:
    assert indent_text("only", left_margin=3) == "   only"


def test_indent_text_empty_string() -> None:
    assert indent_text("", left_margin=4) == ""


def test_indent_text_large_margin() -> None:
    result = indent_text("x", left_margin=10)
    assert result.startswith(" " * 10)


# ---------------------------------------------------------------------------
# do_template_from_text
# ---------------------------------------------------------------------------


def test_do_template_from_text_simple_substitution() -> None:
    tmpl = "Hello ${name}!"
    result = do_template_from_text(tmpl, {"name": "World"})
    assert result == "Hello World!"


def test_do_template_from_text_no_namespace() -> None:
    result = do_template_from_text("static text")
    assert result == "static text"


def test_do_template_from_text_arithmetic() -> None:
    result = do_template_from_text("${2 + 2}")
    assert result == "4"


def test_do_template_from_text_for_loop() -> None:
    tmpl = "% for i in items:\n${i}\n% endfor"
    result = do_template_from_text(tmpl, {"items": [1, 2, 3]})
    assert "1" in result
    assert "2" in result
    assert "3" in result


def test_do_template_from_text_conditional() -> None:
    tmpl = "% if flag:\nyes\n% else:\nno\n% endif"
    assert "yes" in do_template_from_text(tmpl, {"flag": True})
    assert "no" in do_template_from_text(tmpl, {"flag": False})


def test_do_template_from_text_with_left_margin() -> None:
    result = do_template_from_text("hello", leftMargin=2)
    assert result.startswith("  hello")


def test_do_template_from_text_syntax_error_returns_none() -> None:
    bad_tmpl = "${unclosed"
    result = do_template_from_text(bad_tmpl)
    assert result is None


def test_do_template_from_text_runtime_error_returns_none() -> None:
    # formatExceptions=False ensures the exception propagates to the try/except → None
    tmpl = "${undefined_variable.no_such_attr}"
    result = do_template_from_text(tmpl, formatExceptions=False)
    assert result is None


def test_do_template_from_text_multiline() -> None:
    tmpl = "line1\nline2\n${val}"
    result = do_template_from_text(tmpl, {"val": "line3"})
    assert "line1" in result
    assert "line3" in result


def test_do_template_from_text_empty_template() -> None:
    result = do_template_from_text("")
    assert result == ""


# ---------------------------------------------------------------------------
# do_template (file-based)
# ---------------------------------------------------------------------------


def test_do_template_renders_file(tmp_path) -> None:
    tmpl_file = tmp_path / "test.tmpl"
    tmpl_file.write_text("Value is ${val}!", encoding="utf-8")
    result = do_template(str(tmpl_file), {"val": 42})
    assert result == "Value is 42!"


def test_do_template_no_namespace(tmp_path) -> None:
    tmpl_file = tmp_path / "plain.tmpl"
    tmpl_file.write_text("hello world", encoding="utf-8")
    result = do_template(str(tmpl_file))
    assert result == "hello world"


def test_do_template_missing_file_returns_none() -> None:
    result = do_template("/nonexistent/path/template.tmpl")
    assert result is None


def test_do_template_runtime_error_returns_none(tmp_path) -> None:
    tmpl_file = tmp_path / "bad.tmpl"
    tmpl_file.write_text("${missing_var.attr}", encoding="utf-8")
    result = do_template(str(tmpl_file), formatExceptions=False)
    assert result is None


def test_do_template_with_latin1_encoding(tmp_path) -> None:
    tmpl_file = tmp_path / "latin.tmpl"
    tmpl_file.write_text("Wert: ${val}", encoding="latin-1")
    result = do_template(str(tmpl_file), {"val": "ok"}, encoding="latin-1")
    assert result is not None
    assert "ok" in result


# ---------------------------------------------------------------------------
# call_def
# ---------------------------------------------------------------------------


def test_call_def_simple_def() -> None:
    tobj = Template("<%def name='greet(name)'>Hello ${name}</%def>")  # nosec B702
    result = call_def(tobj, "greet", name="World")
    assert "Hello World" in result


def test_call_def_with_positional_arg() -> None:
    tobj = Template("<%def name='double(x)'>${x * 2}</%def>")  # nosec B702
    result = call_def(tobj, "double", x=21)
    assert "42" in result


def test_call_def_no_args() -> None:
    tobj = Template("<%def name='static()'>fixed</%def>")  # nosec B702
    result = call_def(tobj, "static")
    assert "fixed" in result
