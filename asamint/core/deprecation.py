"""Shared deprecation machinery for subpackage ``__getattr__`` hooks.

Every subpackage that exposes a ``_DEPRECATED_ALIASES`` dict can use
:func:`make_module_getattr` and :func:`make_module_dir` to get a pair
of ``__getattr__`` / ``__dir__`` that emit :class:`DeprecationWarning`
for renamed or removed symbols.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from types import ModuleType
from warnings import warn


@dataclass(frozen=True)
class DeprecatedAlias:
    """Descriptor for a deprecated name re-exported by a module.

    Attributes:
        target: Dotted ``module:attr`` path *or* plain attribute name
            resolvable in the owning module's globals.
        remove_in_version: Version string when the alias will be dropped.
        replacement: Human-readable replacement hint shown in the warning.
            Falls back to *target* when ``None``.
    """

    target: str
    remove_in_version: str
    replacement: str | None = None


def _resolve_target(target: str, module_globals: dict[str, object]) -> object:
    """Resolve a *target* string to the actual object."""
    if ":" in target:
        module_name, attr_name = target.split(":", 1)
        module = import_module(module_name)
        return getattr(module, attr_name)
    return module_globals[target]


def deprecated_getattr(
    name: str,
    aliases: dict[str, DeprecatedAlias],
    module_globals: dict[str, object],
    module_name: str,
) -> object:
    """``__getattr__`` implementation shared by all subpackages.

    Raises :class:`AttributeError` for unknown names, emits
    :class:`DeprecationWarning` for known aliases.
    """
    alias = aliases.get(name)
    if alias is None:
        raise AttributeError(f"module {module_name!r} has no attribute {name!r}")

    replacement = alias.replacement or alias.target
    warn(
        (f"{name!r} is deprecated. Use {replacement!r} instead. It will be removed in {alias.remove_in_version}."),
        category=DeprecationWarning,
        stacklevel=2,
    )
    return _resolve_target(alias.target, module_globals)


def deprecated_dir(
    aliases: dict[str, DeprecatedAlias],
    module_globals: dict[str, object],
) -> list[str]:
    """``__dir__`` implementation that includes deprecated names."""
    return sorted(set(module_globals) | set(aliases))
