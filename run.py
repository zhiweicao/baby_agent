import argparse
import os
import sys

from openai import OpenAI

from agent import Agent
from commands import build_registry
from memory import LongTermMemory

CTRL_O = "\x0f"


def read_line(prompt_str: str, agent: Agent) -> str:
    """Read a line with Ctrl+O support to toggle prompt display."""
    try:
        import termios
        import tty
    except ImportError:
        # Fallback for non-Unix systems
        return input(prompt_str)

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buffer = ""
    sys.stdout.write(prompt_str)
    sys.stdout.flush()

    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)

            if ch == CTRL_O:
                agent.show_prompt = not agent.show_prompt
                status = "ON" if agent.show_prompt else "OFF"
                sys.stdout.write(f"\r\n\033[33m[Prompt display: {status}]\033[0m\r\n")
                sys.stdout.write(prompt_str + buffer)
                sys.stdout.flush()

            elif ch in ("\r", "\n"):
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                break

            elif ch == "\x03":  # Ctrl+C
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                raise KeyboardInterrupt

            elif ch == "\x04":  # Ctrl+D
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                raise EOFError

            elif ch in ("\x7f", "\x08"):  # Backspace
                if buffer:
                    buffer = buffer[:-1]
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()

            elif ord(ch) >= 32:  # Printable characters
                buffer += ch
                sys.stdout.write(ch)
                sys.stdout.flush()

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
                user_input = read_line("\nYou> ", agent).strip()
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
