import asyncio
import time
import uuid
from contextvars import ContextVar
from typing import Any, Callable, Dict, Optional

from jupyter_server.serverapp import ServerApp

from .config import CommandNamespace, CommandsToolkit

# Store for pending command results
pending_requests: Dict[str, Dict[str, Any]] = {}

# The id of the web client that should execute the emitted commands,
# or None to have all connected web clients execute them
target_client_id: ContextVar[Optional[str]] = ContextVar(
    "target_client_id", default=None
)

# The tools giving access to all the JupyterLab commands
TOOLS = [
    "jupyterlab_commands_toolkit.tools:list_all_commands",
    "jupyterlab_commands_toolkit.tools:execute_command",
]


def emit(data, wait_for_result=False):
    """
    Emit an event to the frontend with optional result waiting.

    Args:
        data: Event data to emit
        wait_for_result: Whether to add a request ID for result tracking

    Returns:
        str: Request ID if wait_for_result is True, None otherwise
    """
    server = ServerApp.instance()

    client_id = target_client_id.get()
    if client_id is not None:
        data.setdefault("client_id", client_id)

    # Add request ID if waiting for result
    request_id = None
    if wait_for_result:
        request_id = str(uuid.uuid4())
        data["requestId"] = request_id
        pending_requests[request_id] = {
            "timestamp": time.time(),
            "data": data,
            "result": None,
            "completed": False,
            "future": asyncio.get_running_loop().create_future(),
        }

    server.io_loop.call_later(
        0.1,
        server.event_logger.emit,
        schema_id="https://events.jupyter.org/jupyterlab_command_toolkit/lab_command/v1",
        data=data,
    )

    return request_id


async def emit_and_wait_for_result(data, timeout=10.0):
    """
    Emit a command and wait for its result.

    Args:
        data: Command data to emit
        timeout: How long to wait for a result (seconds)

    Returns:
        dict: Command result from the frontend
    """
    request_id = emit(data, wait_for_result=True)

    try:
        future = pending_requests[request_id]["future"]
        result = await asyncio.wait_for(future, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": f"Command timed out after {timeout} seconds",
            "request_id": request_id,
        }
    finally:
        pending_requests.pop(request_id, None)


def handle_command_result(event_data):
    """Handle incoming command results from the frontend."""
    request_id = event_data.get("requestId")
    if request_id and request_id in pending_requests:
        request_info = pending_requests[request_id]
        request_info["result"] = event_data
        request_info["completed"] = True

        future = request_info.get("future")
        if future and not future.done():
            future.set_result(event_data)


async def list_all_commands(query: Optional[str] = None) -> dict:
    """
    Retrieve a list of all available JupyterLab commands.

    This function emits a request to the JupyterLab frontend to retrieve all
    registered commands in the application. It waits for the response and
    returns the complete list of available commands with their metadata.

    Args:
        query (Optional[str], optional): An optional search query to filter commands.
                                        When provided, only commands whose ID, label,
                                        caption, or description contain the query string
                                        (case-insensitive) will be returned. If None or
                                        omitted, all commands will be returned.
                                        Defaults to None.

    Returns:
        dict: A dictionary containing the command list response from JupyterLab.
              The structure typically includes:
              - success (bool): Whether the operation succeeded
              - commandCount (int): Number of commands returned
              - commands (list): List of available command objects, each with:
                  - id (str): The command identifier
                  - label (str, optional): Human-readable command label
                  - caption (str, optional): Short description
                  - description (str, optional): Detailed usage information
                  - args (dict, optional): Command argument schema
              - error (str, optional): Error message if the operation failed

    Examples:
        >>> # Get all commands
        >>> await list_all_commands()
        {'success': True, 'commandCount': 150, 'commands': [...]}

        >>> # Filter commands by query
        >>> await list_all_commands(query="notebook")
        {'success': True, 'commandCount': 25, 'commands': [...]}
    """
    args = {}
    if query is not None:
        args["query"] = query

    return await emit_and_wait_for_result(
        {"name": "jupyterlab-commands-toolkit:list-all-commands", "args": args}
    )


async def execute_command(command_id: str, args: Optional[dict] = None) -> dict:
    """
    Execute a JupyterLab command with optional arguments.

    This function sends a command execution request to the JupyterLab frontend
    and waits for the result. The command is identified by its unique command_id
    and can be parameterized with optional arguments.

    Args:
        command_id (str): The unique identifier of the JupyterLab command to execute.
                         This should be a valid command ID registered in JupyterLab.
        args (Optional[dict], optional): A dictionary of arguments to pass to the
                                       command. Defaults to None, which is converted
                                       to an empty dictionary.

    Returns:
        dict: A dictionary containing the command execution response from JupyterLab.
              The structure typically includes:
              - success (bool): Whether the command executed successfully
              - result (any): The return value from the executed command
              - error (str, optional): Error message if the command failed
              - request_id (str): The unique identifier for this request

    Examples:
        >>> await execute_command("application:toggle-left-area")
        {'success': True, 'result': None}

        >>> await execute_command("docmanager:open", {"path": "notebook.ipynb"})
        {'success': True, 'result': 'opened'}
    """
    if args is None:
        args = {}
    return await emit_and_wait_for_result({"name": command_id, "args": args})


def _get_toolkit() -> CommandsToolkit:
    """The toolkit configuration of the running server."""
    parent = ServerApp.instance() if ServerApp.initialized() else None
    return CommandsToolkit(parent=parent)


def _format_patterns(patterns) -> str:
    return ", ".join(f"`{pattern}`" for pattern in patterns)


def _namespace_summary(namespace: CommandNamespace) -> str:
    summary = (
        "The namespace contains the commands matching "
        f"{_format_patterns(namespace.commands)}"
    )
    if namespace.exclude:
        summary += f", except the ones matching {_format_patterns(namespace.exclude)}"
    summary += "."
    if namespace.description:
        summary = f"{namespace.description}\n\n{summary}"
    return summary


def _filter_commands(response: dict, namespace: CommandNamespace) -> dict:
    """Only keep the commands of the namespace in a `list_all_commands` response."""
    result = response.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("commands"), list):
        return response
    commands = [
        command
        for command in result["commands"]
        if namespace.matches(command.get("id", ""))
    ]
    return {
        **response,
        "result": {**result, "commandCount": len(commands), "commands": commands},
    }


def namespace_tools(namespace: CommandNamespace) -> list[Callable]:
    """Create the tools listing and executing the commands of a namespace."""
    list_name = f"{namespace.name}_list_commands"
    execute_name = f"{namespace.name}_execute_command"
    summary = _namespace_summary(namespace)

    async def list_commands(query: Optional[str] = None) -> dict:
        response = await list_all_commands(query)
        return _filter_commands(response, namespace)

    async def execute(command_id: str, args: Optional[dict] = None) -> dict:
        if not namespace.matches(command_id):
            return {
                "success": False,
                "error": (
                    f"Command '{command_id}' is not part of the '{namespace.name}' "
                    f"namespace. Use {list_name} to list the available commands."
                ),
            }
        return await execute_command(command_id, args)

    list_commands.__doc__ = f"""List the JupyterLab commands of the "{namespace.name}" namespace.

{summary}

Use {execute_name} to execute them.

Args:
    query: Only list the commands whose id, label, caption or description contains this text (case-insensitive). All the commands of the namespace are listed when omitted.
"""

    execute.__doc__ = f"""Execute a JupyterLab command of the "{namespace.name}" namespace.

{summary}

Commands outside of the namespace are rejected. Use {list_name} to discover the available commands and their arguments.

Args:
    command_id: The id of the command to execute.
    args: The arguments to pass to the command.
"""

    for tool, name in ((list_commands, list_name), (execute, execute_name)):
        tool.__name__ = tool.__qualname__ = name
    return [list_commands, execute]


def get_tools() -> list[str]:
    """
    The tools for jupyter-server-mcp entrypoint discovery.

    Contains the tools giving access to all the commands, unless disabled with
    `CommandsToolkit.expose_all_commands`, and the tools of each namespace
    configured with `CommandsToolkit.namespaces`.
    """
    toolkit = _get_toolkit()
    tools = list(TOOLS) if toolkit.expose_all_commands else []
    for namespace in toolkit.get_namespaces():
        tools.extend(
            f"{__name__}:{tool.__name__}" for tool in namespace_tools(namespace)
        )
    return tools


def __getattr__(name: str) -> Callable:
    """Resolve the namespace tools listed by `get_tools`, such as `notebook_execute_command`."""
    if name.endswith(("_list_commands", "_execute_command")):
        for namespace in _get_toolkit().get_namespaces():
            for tool in namespace_tools(namespace):
                if tool.__name__ == name:
                    return tool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
