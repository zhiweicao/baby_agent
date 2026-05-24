import json
import os
import subprocess


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read the contents of a file at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative path to the file",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write content to a file. Creates the file if it doesn't exist, overwrites if it does.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_list",
            "description": "List files and directories at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path. Defaults to current directory.",
                        "default": ".",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_execute",
            "description": "Execute a shell command and return its stdout and stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 30)",
                        "default": 30,
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_save",
            "description": "Save a key-value fact to long-term memory. Persists across sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "A short identifier for the fact",
                    },
                    "value": {
                        "type": "string",
                        "description": "The fact or information to remember",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category (e.g. 'project', 'preference')",
                        "default": "general",
                    },
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_recall",
            "description": "Recall a fact from long-term memory by its key.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "The key to look up"}
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_plan",
            "description": "Create a plan with steps to accomplish a goal. Use before starting complex tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "The overall goal of the plan",
                    },
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of step descriptions",
                    },
                },
                "required": ["goal", "steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_plan",
            "description": "Update the status of a step in the current plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "The step number to update",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["completed", "in_progress", "pending"],
                        "description": "New status for the step",
                    },
                },
                "required": ["step_id", "status"],
            },
        },
    },
]


def get_tool_definitions() -> list[dict]:
    return TOOL_DEFINITIONS


def execute_tool(name: str, args: dict, agent) -> str:
    """Dispatch tool call by name. Returns string result."""
    dispatch = {
        "file_read": _file_read,
        "file_write": _file_write,
        "file_list": _file_list,
        "code_execute": _code_execute,
        "memory_save": _memory_save,
        "memory_recall": _memory_recall,
        "create_plan": _create_plan,
        "update_plan": _update_plan,
    }
    handler = dispatch.get(name)
    if handler is None:
        return f"Error: unknown tool '{name}'"
    try:
        return handler(args, agent)
    except Exception as e:
        return f"Error in {name}: {e}"


def _file_read(args: dict, _agent) -> str:
    path = args["path"]
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _file_write(args: dict, _agent) -> str:
    path = args["path"]
    content = args["content"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Successfully wrote to {path}"


def _file_list(args: dict, _agent) -> str:
    path = args.get("path", ".")
    entries = os.listdir(path)
    if not entries:
        return f"(empty directory: {path})"
    return "\n".join(sorted(entries))


def _code_execute(args: dict, _agent) -> str:
    command = args["command"]
    timeout = args.get("timeout", 30)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\nSTDERR:\n" + result.stderr) if output else result.stderr
        if result.returncode != 0:
            output += f"\n(exit code: {result.returncode})"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"


def _memory_save(args: dict, agent) -> str:
    key = args["key"]
    value = args["value"]
    category = args.get("category", "general")
    agent.ltm.save(key, value, category)
    return f"Saved: {key}={value}"


def _memory_recall(args: dict, agent) -> str:
    key = args["key"]
    value = agent.ltm.recall(key)
    if value is None:
        return f"No memory found for key: {key}"
    return value


def _create_plan(args: dict, agent) -> str:
    goal = args["goal"]
    steps = args["steps"]
    agent.plan = {
        "goal": goal,
        "steps": [
            {"id": i + 1, "description": s, "status": "pending"}
            for i, s in enumerate(steps)
        ],
    }
    plan_text = f"Plan: {goal}\n" + "\n".join(
        f"  {s['id']}. [{s['status']}] {s['description']}" for s in agent.plan["steps"]
    )
    return plan_text


def _update_plan(args: dict, agent) -> str:
    if agent.plan is None:
        return "Error: no active plan. Use create_plan first."
    step_id = args["step_id"]
    status = args["status"]
    for step in agent.plan["steps"]:
        if step["id"] == step_id:
            step["status"] = status
            plan_text = f"Plan: {agent.plan['goal']}\n" + "\n".join(
                f"  {s['id']}. [{s['status']}] {s['description']}"
                for s in agent.plan["steps"]
            )
            return plan_text
    return f"Error: step {step_id} not found in current plan"
