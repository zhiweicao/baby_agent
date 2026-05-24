from dataclasses import dataclass


@dataclass
class Command:
    name: str
    description: str
    handler: callable


class CommandRegistry:
    def __init__(self):
        self._commands: dict[str, Command] = {}

    def register(self, name: str, description: str, handler: callable):
        self._commands[name] = Command(name=name, description=description, handler=handler)

    def dispatch(self, agent, name: str, args: str) -> str | None:
        cmd = self._commands.get(name)
        if cmd is None:
            return f"\033[31mUnknown command: {name}. Type /help for available commands.\033[0m"
        return cmd.handler(agent, args)

    def list_commands(self) -> list[Command]:
        return sorted(self._commands.values(), key=lambda c: c.name)


# --- Built-in command handlers ---

def _help(agent, args: str) -> str:
    from commands import CommandRegistry
    # We access the registry via agent; fall back to listing names
    lines = ["\033[1mAvailable commands:\033[0m"]
    for cmd in agent._command_registry.list_commands():
        lines.append(f"  \033[36m/{cmd.name}\033[0m  {cmd.description}")
    return "\n".join(lines)


def _clear(agent, args: str) -> str:
    agent.stm.clear()
    return "\033[32mConversation history cleared.\033[0m"


def _plan(agent, args: str) -> str:
    if agent.plan is None:
        return "No active plan."
    lines = [f"\033[1mPlan: {agent.plan['goal']}\033[0m"]
    for s in agent.plan["steps"]:
        status_color = {"completed": "32", "in_progress": "33", "pending": "90"}.get(s["status"], "0")
        lines.append(f"  {s['id']}. \033[{status_color}m[{s['status']}]\033[0m {s['description']}")
    return "\n".join(lines)


def _memory(agent, args: str) -> str:
    facts = agent.ltm.list_all()
    if not facts:
        return "No memories stored."
    lines = ["\033[1mLong-term memories:\033[0m"]
    for f in facts:
        lines.append(f"  \033[36m{f['key']}\033[0m: {f['value']} \033[90m({f.get('category', 'general')})\033[0m")
    return "\n".join(lines)


def _prompt(agent, args: str) -> str:
    agent.show_prompt = not agent.show_prompt
    status = "ON" if agent.show_prompt else "OFF"
    return f"\033[33mPrompt display: {status}\033[0m"


def _model(agent, args: str) -> str:
    if args.strip():
        old = agent.model
        agent.model = args.strip()
        return f"\033[32mModel changed: {old} -> {agent.model}\033[0m"
    return f"Current model: \033[36m{agent.model}\033[0m"


def _tools(agent, args: str) -> str:
    lines = ["\033[1mAvailable tools:\033[0m"]
    for tool in agent.tools:
        func = tool["function"]
        params = ", ".join(
            f'{p["name"]}: {p.get("description", "")}'
            for p in func["parameters"].get("properties", {}).values()
        )
        lines.append(f"  \033[36m{func['name']}\033[0m({params})")
        lines.append(f"    {func['description']}")
    return "\n".join(lines)


def _quit(agent, args: str) -> None:
    raise SystemExit(0)


def build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register("help", "Show available commands", _help)
    registry.register("clear", "Clear conversation history", _clear)
    registry.register("plan", "Show current plan", _plan)
    registry.register("memory", "List long-term memories", _memory)
    registry.register("prompt", "Toggle prompt display", _prompt)
    registry.register("model", "Show or switch model (e.g. /model gpt-4)", _model)
    registry.register("tools", "List available tools", _tools)
    registry.register("quit", "Exit the agent", _quit)
    return registry
