"""Adapter für ANTLR-basierte Parser.

Kapselt die Erzeugung von :class:`~asamint.parserlib.ParserWrapper`-Instanzen
hinter der Adapter-Grenze.  Externer Code darf ``antlr4`` nicht direkt
importieren — stattdessen wird diese Funktion genutzt.

Beispiel::

    from asamint.adapters.parsers import create_parser

    parser = create_parser("dcm20", "dcmfile", listener=MyListener)
    result = parser.parseFromFile("demo.dcm")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from asamint.parserlib import ParserWrapper


def create_parser(
    grammar_name: str,
    start_symbol: str,
    listener: type | None = None,
    *,
    debug: bool = False,
) -> ParserWrapper:
    """Erzeuge einen ANTLR-Parser-Wrapper für die angegebene Grammatik.

    Args:
        grammar_name: Name der ANTLR-Grammatik (ohne ``Lexer``/``Parser``-Suffix),
            z. B. ``"dcm20"``.
        start_symbol: Name des Startsymbols (Einstiegsmethode des Parsers),
            z. B. ``"dcmfile"``.
        listener: Optionale Listener-Klasse, die zur Parse-Tree-Traversierung
            verwendet wird.  Muss von ``antlr4.ParseTreeListener`` erben.
        debug: Wenn ``True``, wird das Parser-Tracing aktiviert.

    Returns:
        Konfigurierter :class:`~asamint.parserlib.ParserWrapper`.

    Raises:
        ImportError: Wenn das generierte Lexer-/Parser-Modul nicht gefunden wird.
    """
    return ParserWrapper(grammar_name, start_symbol, listener=listener, debug=debug)


def parse_file(
    grammar_name: str,
    start_symbol: str,
    file_path: str | Path,
    listener: type | None = None,
    *,
    encoding: str = "latin-1",
    trace: bool = False,
) -> Any:
    """Convenience-Funktion: Parse-Datei direkt ohne explizit einen Wrapper zu halten.

    Args:
        grammar_name: Name der ANTLR-Grammatik.
        start_symbol: Name des Startsymbols.
        file_path: Pfad zur zu parsenden Datei.
        listener: Optionaler Listener.
        encoding: Zeichenkodierung der Eingabedatei (Standard: ``"latin-1"``).
        trace: Wenn ``True``, wird der Parse-Trace aktiviert.

    Returns:
        Listener-Instanz mit dem Ergebnis (wenn *listener* angegeben),
        oder den rohen Parse-Tree.
    """
    wrapper = create_parser(grammar_name, start_symbol, listener=listener)
    return wrapper.parseFromFile(file_path, encoding=encoding, trace=trace)


def parse_string(
    grammar_name: str,
    start_symbol: str,
    text: str,
    listener: type | None = None,
    *,
    encoding: str = "latin-1",
    trace: bool = False,
) -> Any:
    """Convenience-Funktion: Parse-String direkt ohne explizit einen Wrapper zu halten.

    Args:
        grammar_name: Name der ANTLR-Grammatik.
        start_symbol: Name des Startsymbols.
        text: Zu parsender Text.
        listener: Optionaler Listener.
        encoding: Zeichenkodierung (Standard: ``"latin-1"``).
        trace: Wenn ``True``, wird der Parse-Trace aktiviert.

    Returns:
        Listener-Instanz mit dem Ergebnis (wenn *listener* angegeben),
        oder den rohen Parse-Tree.
    """
    wrapper = create_parser(grammar_name, start_symbol, listener=listener)
    return wrapper.parseFromString(text, encoding=encoding, trace=trace)


__all__ = [
    "ParserWrapper",
    "create_parser",
    "parse_file",
    "parse_string",
]

