import asyncio
import importlib

import pytest
from traitlets import TraitError

from jupyterlab_commands_toolkit import tools
from jupyterlab_commands_toolkit.config import CommandNamespace, CommandsToolkit

COMMAND_SCHEMA_ID = (
    "https://events.jupyter.org/jupyterlab_command_toolkit/lab_command/v1"
)

NAMESPACES = {
    "notebook": {
        "description": "Edit and run notebooks.",
        "commands": ["notebook:*", "docmanager:save"],
        "exclude": ["notebook:export-*"],
    },
    "layout": ["application:toggle-*-area"],
}


@pytest.fixture
def jp_server_config(jp_server_config):
    return {
        **jp_server_config,
        "CommandsToolkit": {"namespaces": NAMESPACES, "expose_all_commands": False},
    }


@pytest.fixture
def emitted_commands(jp_serverapp):
    """The commands emitted to the frontend, answered with the given results."""
    commands = asyncio.Queue()

    async def listener(logger, schema_id, data):
        await commands.put(data)

    jp_serverapp.event_logger.add_listener(
        schema_id=COMMAND_SCHEMA_ID, listener=listener
    )
    return commands


async def reply(emitted_commands, result):
    """Answer the next emitted command as the frontend would."""
    data = await asyncio.wait_for(emitted_commands.get(), timeout=5)
    tools.handle_command_result(
        {"requestId": data["requestId"], "success": True, "result": result}
    )
    return data


def test_namespace_from_patterns():
    namespace = CommandNamespace.from_config("layout", ["application:*"])
    assert namespace == CommandNamespace(name="layout", commands=("application:*",))


@pytest.mark.parametrize(
    "command_id, expected",
    [
        ("notebook:run-cell", True),
        ("docmanager:save", True),
        ("notebook:export-to-format", False),
        ("docmanager:save-as", False),
        ("docmanager:open", False),
        ("notebook", False),
    ],
)
def test_namespace_matches(command_id, expected):
    namespace = CommandNamespace.from_config("notebook", NAMESPACES["notebook"])
    assert namespace.matches(command_id) is expected


def test_namespace_patterns_are_globs():
    namespace = CommandNamespace.from_config("test", ["a.b?c", "(x)|y"])
    assert namespace.matches("a.b1c")
    assert not namespace.matches("aXb1c")
    assert not namespace.matches("a.bc")
    assert namespace.matches("(x)|y")
    assert not namespace.matches("x")


@pytest.mark.parametrize(
    "namespaces, error",
    [
        ({"has space": ["a:*"]}, "Invalid namespace name"),
        ({"1st": ["a:*"]}, "Invalid namespace name"),
        ({"test": "a:*"}, "must be a list of command patterns or a dict"),
        ({"test": []}, "at least one command pattern"),
        ({"test": {"exclude": ["a:*"]}}, "at least one command pattern"),
        ({"test": ["a:*", ""]}, "list of non-empty strings"),
        ({"test": {"commands": ["a:*"], "exclude": "a:b"}}, "list of non-empty"),
        ({"test": {"commands": ["a:*"], "description": 1}}, "must be a string"),
        ({"test": {"commands": ["a:*"], "include": ["b:*"]}}, "Unknown keys"),
    ],
)
def test_invalid_namespaces(namespaces, error):
    with pytest.raises(TraitError, match=error):
        CommandsToolkit(namespaces=namespaces)


def test_get_tools(jp_serverapp):
    assert tools.get_tools() == [
        "jupyterlab_commands_toolkit.tools:notebook_list_commands",
        "jupyterlab_commands_toolkit.tools:notebook_execute_command",
        "jupyterlab_commands_toolkit.tools:layout_list_commands",
        "jupyterlab_commands_toolkit.tools:layout_execute_command",
    ]


def test_resolve_tools(jp_serverapp):
    for spec in tools.get_tools():
        module_name, name = spec.split(":")
        tool = getattr(importlib.import_module(module_name), name)
        assert tool.__name__ == name
        assert "Args:" in tool.__doc__
    assert "Edit and run notebooks." in tools.notebook_execute_command.__doc__
    with pytest.raises(AttributeError):
        tools.other_execute_command  # noqa: B018


async def test_execute_command_in_namespace(jp_serverapp, emitted_commands):
    task = asyncio.create_task(tools.notebook_execute_command("notebook:run-cell"))
    data = await reply(emitted_commands, "done")
    assert data["name"] == "notebook:run-cell"
    result = await task
    assert result["success"] is True
    assert result["result"] == "done"


async def test_execute_command_outside_namespace(jp_serverapp, emitted_commands):
    result = await tools.notebook_execute_command("terminal:create-new")
    assert result["success"] is False
    assert "not part of the 'notebook' namespace" in result["error"]
    await asyncio.sleep(0.3)
    assert emitted_commands.empty()


async def test_list_commands_in_namespace(jp_serverapp, emitted_commands):
    task = asyncio.create_task(tools.layout_list_commands(query="toggle"))
    commands = [
        {"id": "application:toggle-left-area"},
        {"id": "application:toggle-mode"},
        {"id": "notebook:run-cell"},
    ]
    data = await reply(
        emitted_commands,
        {"success": True, "commandCount": len(commands), "commands": commands},
    )
    assert data["name"] == "jupyterlab-commands-toolkit:list-all-commands"
    assert data["args"] == {"query": "toggle"}
    result = await task
    assert result["result"]["commandCount"] == 1
    assert result["result"]["commands"] == [{"id": "application:toggle-left-area"}]


async def test_register_tools_with_jupyter_server_mcp(jp_serverapp):
    pytest.importorskip("jupyter_server_mcp")
    from jupyter_server_mcp.mcp_server import MCPServer

    server = MCPServer(port=0)
    for spec in tools.get_tools():
        module_name, name = spec.rsplit(":", 1)
        server.register_tool(getattr(importlib.import_module(module_name), name))

    mcp_tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    assert sorted(mcp_tools) == [
        "layout_execute_command",
        "layout_list_commands",
        "notebook_execute_command",
        "notebook_list_commands",
    ]
    execute = mcp_tools["notebook_execute_command"]
    assert "Edit and run notebooks." in execute.description
    assert execute.parameters["required"] == ["command_id"]
