"""Configuration of the tools exposed by the toolkit."""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

from traitlets import Bool, Dict, TraitError, Unicode, validate
from traitlets.config import LoggingConfigurable

# The namespace name is used as a prefix of the MCP tool names
NAMESPACE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")

NAMESPACE_KEYS = {"description", "commands", "exclude"}


@lru_cache(maxsize=None)
def compile_pattern(pattern: str) -> re.Pattern:
    """Translate a glob pattern (`*`, `?`) into a regular expression."""
    regex = "".join(
        ".*" if char == "*" else "." if char == "?" else re.escape(char)
        for char in pattern
    )
    return re.compile(regex)


def matches_any(command_id: str, patterns: Iterable[str]) -> bool:
    """Whether the command id matches at least one of the glob patterns."""
    return any(compile_pattern(pattern).fullmatch(command_id) for pattern in patterns)


def _patterns(name: str, key: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(pattern, str) and pattern for pattern in value
    ):
        msg = f"'{key}' of namespace '{name}' must be a list of non-empty strings"
        raise ValueError(msg)
    return tuple(value)


@dataclass(frozen=True)
class CommandNamespace:
    """A named set of JupyterLab commands."""

    name: str
    commands: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    description: str = ""

    @classmethod
    def from_config(cls, name: str, value: Any) -> "CommandNamespace":
        """Create a namespace from its configuration.

        The value is either a list of command patterns, or a dict with the
        `commands` patterns and optional `exclude` patterns and `description`.
        """
        if not isinstance(name, str) or not NAMESPACE_NAME_PATTERN.match(name):
            msg = (
                f"Invalid namespace name {name!r}: it must start with a letter and "
                "only contain letters, digits, '_' and '-' (64 characters max)"
            )
            raise ValueError(msg)
        if isinstance(value, list):
            value = {"commands": value}
        if not isinstance(value, dict):
            msg = f"Namespace '{name}' must be a list of command patterns or a dict"
            raise ValueError(msg)
        unknown = set(value) - NAMESPACE_KEYS
        if unknown:
            msg = (
                f"Unknown keys for namespace '{name}': {', '.join(sorted(unknown))}. "
                f"Expected: {', '.join(sorted(NAMESPACE_KEYS))}"
            )
            raise ValueError(msg)
        if not value.get("commands"):
            msg = f"Namespace '{name}' must have at least one command pattern"
            raise ValueError(msg)
        description = value.get("description", "")
        if not isinstance(description, str):
            msg = f"'description' of namespace '{name}' must be a string"
            raise ValueError(msg)
        return cls(
            name=name,
            commands=_patterns(name, "commands", value["commands"]),
            exclude=_patterns(name, "exclude", value.get("exclude", [])),
            description=description.strip(),
        )

    def matches(self, command_id: str) -> bool:
        """Whether the command is part of this namespace."""
        return matches_any(command_id, self.commands) and not matches_any(
            command_id, self.exclude
        )


class CommandsToolkit(LoggingConfigurable):
    """Configuration of the tools exposed by jupyterlab-commands-toolkit."""

    expose_all_commands = Bool(
        True,
        help=(
            "Whether to expose the `list_all_commands` and `execute_command` tools, "
            "which give access to all the JupyterLab commands. Set to False to only "
            "expose the tools of the configured namespaces."
        ),
    ).tag(config=True)

    namespaces = Dict(
        key_trait=Unicode(),
        help="""Named sets of JupyterLab commands to expose as dedicated tools.

        Each namespace is exposed with a `<name>_list_commands` and a
        `<name>_execute_command` tool, which only list and execute the commands
        of the namespace. The value is either a list of glob patterns matched
        against the command ids, or a dict with:

        - `commands`: the glob patterns of the commands of the namespace
        - `exclude`: optional glob patterns of commands to leave out
        - `description`: an optional description, added to the tool descriptions

        The patterns support `*` (any sequence of characters) and `?` (any single
        character). For example:

            c.CommandsToolkit.namespaces = {
                "notebook": {
                    "description": "Edit and run the cells of notebooks",
                    "commands": ["notebook:*", "docmanager:save"],
                    "exclude": ["notebook:export-to-format"],
                },
                "layout": ["application:toggle-*", "application:reset-layout"],
            }
        """,
    ).tag(config=True)

    @validate("namespaces")
    def _validate_namespaces(self, proposal):
        for name, value in proposal["value"].items():
            try:
                CommandNamespace.from_config(name, value)
            except ValueError as e:
                raise TraitError(str(e)) from e
        return proposal["value"]

    def get_namespaces(self) -> list[CommandNamespace]:
        """The configured command namespaces."""
        return [
            CommandNamespace.from_config(name, value)
            for name, value in self.namespaces.items()
        ]
