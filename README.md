# jupyterlab_commands_toolkit

[![Github Actions Status](https://github.com/jupyter-ai-contrib/jupyterlab-commands-toolkit/workflows/Build/badge.svg)](https://github.com/jupyter-ai-contrib/jupyterlab-commands-toolkit/actions/workflows/build.yml)
[![PyPI version](https://img.shields.io/pypi/v/jupyterlab-commands-toolkit.svg)](https://pypi.org/project/jupyterlab-commands-toolkit/)
[![conda-forge version](https://img.shields.io/conda/vn/conda-forge/jupyterlab-commands-toolkit.svg)](https://anaconda.org/conda-forge/jupyterlab-commands-toolkit)

A Jupyter extension that provides an AI toolkit for JupyterLab commands.

This extension is composed of a Python package named `jupyterlab_commands_toolkit`
for the server extension and a NPM package named `jupyterlab-commands-toolkit`
for the frontend extension.

## Features

- **Command Discovery**: List all available JupyterLab commands with their metadata
- **Command Execution**: Execute any JupyterLab command programmatically from Python
- **MCP Integration**: Automatically exposes tools to AI assistants via [jupyter-server-mcp](https://github.com/jupyter-ai-contrib/jupyter-server-mcp)
- **Web Client Routing**: Execute a command on a specific browser tab only (see below)
- **Command Namespaces**: Expose curated sets of commands as dedicated tools (see below)

## Web client routing

By default, a command is executed by all the connected web clients (browser tabs).
To execute a command on a single web client, set the `target_client_id` context
variable before calling `execute_command`:

```python
from jupyterlab_commands_toolkit.tools import execute_command, target_client_id

token = target_client_id.set(client_id)
try:
    result = await execute_command("notebook:run-all-cells")
finally:
    target_client_id.reset(token)
```

Each web client has a unique id, which the
`jupyterlab-commands-toolkit:get-web-client-id` command returns.

## Requirements

- JupyterLab >= 4.5.0a3

## Install

To install the extension, execute:

```bash
pip install jupyterlab_commands_toolkit
```

To install with `jupyter-server-mcp` integration support:

```bash
pip install jupyterlab_commands_toolkit[mcp]
```

## Usage

### With jupyter-server-mcp (Recommended)

This extension automatically registers its tools with [jupyter-server-mcp](https://github.com/jupyter-ai-contrib/jupyter-server-mcp) via Python entrypoints, making them available to AI assistants and other MCP clients.

1. Install both packages:

```bash
pip install jupyterlab_commands_toolkit[mcp]
```

2. Start Jupyter Lab (the MCP server starts automatically):

```bash
jupyter lab
```

3. Configure your MCP client (e.g., Claude Desktop) to connect to `http://localhost:3001/mcp`

The following tools will be automatically available:

- `list_all_commands` - List all available JupyterLab commands with their metadata
- `execute_command` - Execute any JupyterLab command programmatically

To only give access to a subset of the commands, see [Command namespaces](#command-namespaces).

### Server-Side Python Usage

Use the toolkit directly from server-side Python to execute JupyterLab commands.
These functions must run in the initialized Jupyter Server process, such as via
`jupyter-server-mcp` or another server extension.

```python
from jupyterlab_commands_toolkit.tools import execute_command, list_all_commands

async def main():
    # List all available commands
    commands = await list_all_commands()

    # Toggle the file browser
    result = await execute_command("filebrowser:toggle-main")

    # Run notebook cells
    result = await execute_command("notebook:run-all-cells")
```

For a full list of available commands in JupyterLab, refer to the [JupyterLab Command Registry documentation](https://jupyterlab.readthedocs.io/en/latest/user/commands.html#commands-list).

## Command namespaces

JupyterLab registers several hundred commands, and `execute_command` gives an
agent access to all of them. A namespace is a named set of commands, exposed
with its own pair of tools:

- `<name>_list_commands` - List the commands of the namespace
- `<name>_execute_command` - Execute a command of the namespace. Other commands
  are rejected by the server before reaching JupyterLab.

Namespaces are defined in the Jupyter Server configuration, for example in
`jupyter_server_config.py`:

```python
c.CommandsToolkit.namespaces = {
    "notebook": {
        "description": "Edit and run the cells of the active notebook.",
        "commands": ["notebook:*", "docmanager:save"],
        "exclude": ["notebook:export-to-format", "notebook:*kernel*"],
    },
    "layout": ["application:toggle-*", "application:reset-layout"],
}

# Only expose the tools of the namespaces, not list_all_commands and execute_command
c.CommandsToolkit.expose_all_commands = False
```

Or in `jupyter_server_config.json`:

```json
{
  "CommandsToolkit": {
    "namespaces": {
      "notebook": {
        "description": "Edit and run the cells of the active notebook.",
        "commands": ["notebook:*", "docmanager:save"],
        "exclude": ["notebook:export-to-format", "notebook:*kernel*"]
      },
      "layout": ["application:toggle-*", "application:reset-layout"]
    },
    "expose_all_commands": false
  }
}
```

With this configuration, `jupyter-server-mcp` exposes the
`notebook_list_commands`, `notebook_execute_command`, `layout_list_commands` and
`layout_execute_command` tools.

A namespace is either a list of command patterns, or an object with:

- `commands` - The patterns of the commands of the namespace
- `exclude` - Optional patterns of commands to leave out
- `description` - An optional description, added to the descriptions of the
  tools to tell the agent what the namespace is for

The patterns are matched against the command IDs, and support `*` (any sequence
of characters) and `?` (any single character). The name of a namespace prefixes
the names of its tools: it must start with a letter and only contain letters,
digits, `_` and `-`.

Some tips to craft namespaces:

- Call `list_all_commands` to find the IDs of the commands to include, or see
  the [list of JupyterLab commands](https://jupyterlab.readthedocs.io/en/latest/user/commands.html#commands-list).
- The namespaces are logged when the server starts, and an invalid
  configuration is reported in the server logs.
- To use different namespaces per project, pass a configuration file when
  starting JupyterLab: `jupyter lab --config=path/to/jupyter_server_config.py`.
- Namespaces are a guardrail, not a sandbox: some commands run other commands
  passed as arguments, such as `apputils:run-first-enabled` and
  `apputils:run-all-enabled`. Avoid broad patterns such as `apputils:*`.

## Restricting commands in the browser

The frontend extension also has two settings, under the plugin id
`jupyterlab-commands-toolkit:plugin`, to restrict the commands that can be
listed and executed through the toolkit in a JupyterLab instance, whatever the
tool requesting them:

- `allowedPatterns` — glob patterns matched against command IDs. If non-empty,
  only commands whose ID matches at least one pattern are allowed.
- `deniedPatterns` — glob patterns of the commands that are not allowed, even if
  they match `allowedPatterns`.

Both support `*` (any sequence) and `?` (single character). Empty arrays mean
"no restriction", which is the default. The commands run from the JupyterLab
user interface are not restricted.

The settings can be edited from the JupyterLab Settings Editor, or shipped as
defaults via `etc/jupyter/labconfig/default_setting_overrides.d/<n>-jupyterlab-commands-toolkit.json`:

```json
{
  "jupyterlab-commands-toolkit:plugin": {
    "allowedPatterns": ["notebook:*", "docmanager:*", "filebrowser:*"]
  }
}
```

Changes to the settings apply to the open JupyterLab tabs when made from the
Settings Editor, and to the other tabs after a reload.

## Uninstall

To remove the extension, execute:

```bash
pip uninstall jupyterlab_commands_toolkit
```

## Troubleshoot

If you are seeing the frontend extension, but it is not working, check
that the server extension is enabled:

```bash
jupyter server extension list
```

If the server extension is installed and enabled, but you are not seeing
the frontend extension, check the frontend extension is installed:

```bash
jupyter labextension list
```

## Contributing

### Development install

Note: You will need Node.js to build the extension package.
You may install it from [nodejs.org](https://nodejs.org/en/download). We
recommend using the latest LTS version of Node.js.

The `jlpm` command is JupyterLab's pinned version of
[yarn](https://yarnpkg.com/) that is installed with JupyterLab. You may use
`yarn` or `npm` in lieu of `jlpm` below.

```bash
# Clone the repo to your local environment
# Change directory to the jupyterlab_commands_toolkit directory

# Set up a virtual environment and install package in development mode
python -m venv .venv
source .venv/bin/activate
pip install --editable ".[dev,test]"

# Link your development version of the extension with JupyterLab
jupyter-builder develop . --overwrite
# Server extension must be manually installed in develop mode
jupyter server extension enable jupyterlab_commands_toolkit

# Rebuild extension Typescript source after making changes
# IMPORTANT: Unlike the steps above which are performed only once, do this step
# every time you make a change.
jlpm build
```

You can watch the source directory and run JupyterLab at the same time in different terminals to watch for changes in the extension's source and automatically rebuild the extension.

```bash
# Watch the source directory in one terminal, automatically rebuilding when needed
jlpm watch
# Run JupyterLab in another terminal
jupyter lab
```

With the watch command running, every saved change will immediately be built locally and available in your running JupyterLab. Refresh JupyterLab to load the change in your browser (you may need to wait several seconds for the extension to be rebuilt).

By default, the `jlpm build` command generates the source maps for this extension to make it easier to debug using the browser dev tools. To also generate source maps for the JupyterLab core extensions, you can run the following command:

```bash
jupyter lab build --minimize=False
```

### Development uninstall

```bash
# Server extension must be manually disabled in develop mode
jupyter server extension disable jupyterlab_commands_toolkit
pip uninstall jupyterlab_commands_toolkit
```

In development mode, you will also need to remove the symlink created by `jupyter-builder develop`
command. To find its location, you can run `jupyter labextension list` to figure out where the `labextensions`
folder is located. Then you can remove the symlink named `jupyterlab-commands-toolkit` within that folder.

### Packaging the extension

See [RELEASE](RELEASE.md)
