import argparse
import os
import select
import sys

from openai import OpenAI

from agent import Agent
from commands import build_registry
from memory import LongTermMemory

CTRL_O = "\x0f"


def _get_suggestions(buffer: str, registry) -> list:
    """Return commands matching the current buffer (after the leading /)."""
    if not buffer.startswith("/"):
        return []
    partial = buffer[1:].lower()
    return [c for c in registry.list_commands() if c.name.startswith(partial)]


def _render_suggestions(suggestions, selected_idx: int):
    """Print the suggestion dropdown below the current input line."""
    for i, cmd in enumerate(suggestions):
        if i == selected_idx:
            # Highlighted row: inverse + cyan
            line = f"  \033[7m\033[36m/{cmd.name}\033[0m  {cmd.description}"
        else:
            line = f"  \033[36m/{cmd.name}\033[0m  {cmd.description}"
        sys.stdout.write(f"\r\n{line}")
    sys.stdout.flush()


def _show_suggestions(buffer: str, registry, selected_idx: int, prev_count: int):
    """Clear previous dropdown and render new one. Returns new suggestion count."""
    # Clear previous suggestions
    if prev_count > 0:
        for _ in range(prev_count):
            sys.stdout.write("\r\n\033[2K")
        # Move cursor back up
        sys.stdout.write(f"\033[{prev_count}A")
    suggestions = _get_suggestions(buffer, registry)
    if not suggestions:
        sys.stdout.flush()
        return 0
    # Clamp selected_idx
    if selected_idx >= len(suggestions):
        selected_idx = len(suggestions) - 1
    if selected_idx < 0:
        selected_idx = 0
    _render_suggestions(suggestions, selected_idx)
    # Move cursor back up to the input line
    sys.stdout.write(f"\033[{len(suggestions)}A")
    sys.stdout.flush()
    return len(suggestions)


def _clear_dropdown(count: int):
    """Remove the dropdown of `count` lines from the terminal."""
    if count <= 0:
        return
    for _ in range(count):
        sys.stdout.write("\r\n\033[2K")
    sys.stdout.write(f"\033[{count}A")
    sys.stdout.flush()


def _redraw_input(prompt_str: str, buffer: str):
    """Redraw the input line (prompt + buffer). Strips leading \\n from prompt
    since the newline was already emitted when the prompt was first shown."""
    display = prompt_str.lstrip("\n")
    sys.stdout.write("\r" + display + buffer)
    sys.stdout.flush()


def _read_escape_seq(fd) -> str:
    """Read an ANSI escape sequence after receiving ESC (\x1b).
    Returns the full sequence like '[A' for arrow-up, or '' for standalone ESC.
    Uses os.read(fd, ...) for reliable unbuffered reads in raw mode."""
    if not select.select([fd], [], [], 0.1)[0]:
        return ""
    ch = os.read(fd, 1).decode("utf-8", errors="replace")
    if ch != "[":
        return ch
    if not select.select([fd], [], [], 0.05)[0]:
        return "["
    ch = os.read(fd, 1).decode("utf-8", errors="replace")
    return "[" + ch


def read_line(prompt_str: str, agent: Agent, registry) -> str:
    """Read a line with Ctrl+O and slash command autocomplete support."""
    try:
        import termios
        import tty
    except ImportError:
        return input(prompt_str)

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buffer = ""
    selected_idx = 0
    dropdown_count = 0
    sys.stdout.write(prompt_str)
    sys.stdout.flush()

    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)

            # --- Escape sequences (arrow keys, etc.) ---
            if ch == "\x1b":
                seq = _read_escape_seq(fd)
                if seq == "[A":  # Up
                    if dropdown_count > 0:
                        suggestions = _get_suggestions(buffer, registry)
                        if suggestions:
                            selected_idx = (selected_idx - 1) % len(suggestions)
                            dropdown_count = _show_suggestions(
                                buffer, registry, selected_idx, dropdown_count
                            )
                            _redraw_input(prompt_str, buffer)
                    continue
                elif seq == "[B":  # Down
                    if dropdown_count > 0:
                        suggestions = _get_suggestions(buffer, registry)
                        if suggestions:
                            selected_idx = (selected_idx + 1) % len(suggestions)
                            dropdown_count = _show_suggestions(
                                buffer, registry, selected_idx, dropdown_count
                            )
                            _redraw_input(prompt_str, buffer)
                    continue
                elif seq == "[C" or seq == "[D":  # Right / Left — ignore for now
                    continue
                else:
                    # Standalone ESC — dismiss dropdown
                    if dropdown_count > 0:
                        _clear_dropdown(dropdown_count)
                        dropdown_count = 0
                        _redraw_input(prompt_str, buffer)
                    continue

            # --- Tab: autocomplete ---
            if ch == "\t":
                if buffer.startswith("/"):
                    suggestions = _get_suggestions(buffer, registry)
                    if suggestions:
                        # If dropdown is showing, cycle; otherwise accept first
                        if dropdown_count > 0:
                            selected_idx = (selected_idx + 1) % len(suggestions)
                        # Accept current selection
                        cmd = suggestions[selected_idx]
                        buffer = f"/{cmd.name} "
                        _clear_dropdown(dropdown_count)
                        dropdown_count = 0
                        _redraw_input(prompt_str, buffer)
                continue

            # --- Ctrl+O: toggle prompt display ---
            if ch == CTRL_O:
                agent.show_prompt = not agent.show_prompt
                status = "ON" if agent.show_prompt else "OFF"
                _clear_dropdown(dropdown_count)
                dropdown_count = 0
                sys.stdout.write(f"\r\n\033[33m[Prompt display: {status}]\033[0m\r\n")
                _redraw_input(prompt_str, buffer)
                continue

            # --- Enter ---
            if ch in ("\r", "\n"):
                # If dropdown visible and selection highlighted, accept it
                if dropdown_count > 0 and buffer.startswith("/"):
                    suggestions = _get_suggestions(buffer, registry)
                    if suggestions and selected_idx < len(suggestions):
                        cmd = suggestions[selected_idx]
                        buffer = f"/{cmd.name}"
                _clear_dropdown(dropdown_count)
                dropdown_count = 0
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                break

            # --- Ctrl+C ---
            if ch == "\x03":
                _clear_dropdown(dropdown_count)
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                raise KeyboardInterrupt

            # --- Ctrl+D ---
            if ch == "\x04":
                _clear_dropdown(dropdown_count)
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                raise EOFError

            # --- Backspace ---
            if ch in ("\x7f", "\x08"):
                if buffer:
                    buffer = buffer[:-1]
                    if buffer.startswith("/"):
                        suggestions = _get_suggestions(buffer, registry)
                        if suggestions:
                            selected_idx = min(selected_idx, len(suggestions) - 1)
                            dropdown_count = _show_suggestions(
                                buffer, registry, selected_idx, dropdown_count
                            )
                            _redraw_input(prompt_str, buffer)
                        else:
                            if dropdown_count > 0:
                                _clear_dropdown(dropdown_count)
                                dropdown_count = 0
                                _redraw_input(prompt_str, buffer)
                            else:
                                sys.stdout.write("\b \b")
                                sys.stdout.flush()
                    else:
                        if dropdown_count > 0:
                            _clear_dropdown(dropdown_count)
                            dropdown_count = 0
                            _redraw_input(prompt_str, buffer)
                        else:
                            sys.stdout.write("\b \b")
                            sys.stdout.flush()
                continue

            # --- Printable characters ---
            if ord(ch) >= 32:
                buffer += ch
                if buffer.startswith("/"):
                    suggestions = _get_suggestions(buffer, registry)
                    if suggestions:
                        selected_idx = 0
                        dropdown_count = _show_suggestions(
                            buffer, registry, selected_idx, dropdown_count
                        )
                        _redraw_input(prompt_str, buffer)
                    else:
                        if dropdown_count > 0:
                            _clear_dropdown(dropdown_count)
                            dropdown_count = 0
                            _redraw_input(prompt_str, buffer)
                        else:
                            sys.stdout.write(ch)
                            sys.stdout.flush()
                else:
                    if dropdown_count > 0:
                        _clear_dropdown(dropdown_count)
                        dropdown_count = 0
                        _redraw_input(prompt_str, buffer)
                    else:
                        sys.stdout.write(ch)
                        sys.stdout.flush()
                continue

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    return buffer


def parse_args():
    parser = argparse.ArgumentParser(description="Baby Agent - A minimal AI agent with planning, memory, and tool use")
    parser.add_argument("-p", "--prompt", help="Run a single prompt in non-interactive mode")
    parser.add_argument("--model", default="deepseek-v4-pro", help="Model name (default: deepseek-v4-pro)")
    parser.add_argument("--api-key", default=None, help="API key (default: DEEPSEEK_API_KEY env var)")
    parser.add_argument("--base-url", default="https://api.deepseek.com", help="API base URL")
    parser.add_argument("--memory-dir", default="memory_store", help="Long-term memory directory")
    return parser.parse_args()


def main():
    args = parse_args()

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("Error: API key required. Use --api-key or set DEEPSEEK_API_KEY env var.")
        return

    client = OpenAI(api_key=api_key, base_url=args.base_url)
    ltm = LongTermMemory(args.memory_dir)
    agent = Agent(client, ltm, model=args.model)
    registry = build_registry()
    agent._command_registry = registry

    if args.prompt:
        response = agent.run(args.prompt)
        print(response)
    else:
        print(f"Baby Agent | model: {args.model} | /help for commands (Ctrl+O: toggle prompt display)")
        while True:
            try:
                user_input = read_line("\nYou> ", agent, registry).strip()
            except (EOFError, KeyboardInterrupt):
                break

            if user_input.lower() in ("quit", "exit"):
                break
            if not user_input:
                continue

            # Slash command dispatch
            if user_input.startswith("/"):
                parts = user_input[1:].split(None, 1)
                name = parts[0] if parts else ""
                cmd_args = parts[1] if len(parts) > 1 else ""
                try:
                    result = registry.dispatch(agent, name, cmd_args)
                    if result:
                        print(result)
                except SystemExit:
                    break
                continue

            response = agent.run(user_input)
            print(f"\nAgent> {response}")


if __name__ == "__main__":
    main()
