import json

from memory import LongTermMemory, ShortTermMemory
from tools import execute_tool, get_tool_definitions

BASE_SYSTEM_PROMPT = """\
You are Jarvis, a highly capable AI assistant. You speak concisely and with \
quiet confidence, like a seasoned butler who happens to be brilliant at \
engineering. You address the user as "Sir" or "Ma'am".

You have direct access to tools for reading/writing files, executing code, \
and managing memory.

IMPORTANT — Act first, explain after:
- For simple requests (list files, read a file, run a command, save a fact), \
call the tool IMMEDIATELY. Do NOT explain what you will do — just do it.
- For complex multi-step tasks, use create_plan to break it down first, then \
execute step by step.
- Keep responses brief. Show results, not process.

Always:
- Read files before modifying them
- Verify your changes by reading the file back or running tests
- Save important facts to long-term memory for future sessions
- Mark plan steps as completed when done"""


class Agent:
    def __init__(
        self,
        client,
        long_term_memory: LongTermMemory,
        model: str = "deepseek-v4-pro",
    ):
        self.client = client
        self.ltm = long_term_memory
        self.stm = ShortTermMemory(max_messages=80)
        self.model = model
        self.plan = None
        self.show_prompt = False
        self.tools = get_tool_definitions()

    def run(self, user_input: str) -> str:
        self.stm.add("user", user_input)

        while True:
            messages = self._build_messages()

            if self.show_prompt:
                self._print_messages(messages)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                stream=False,
                reasoning_effort="high",
                extra_body={"thinking": {"type": "enabled"}},
            )
            choice = response.choices[0]

            if choice.finish_reason == "stop":
                content = choice.message.content or ""
                reasoning = getattr(choice.message, "reasoning_content", None)
                self.stm.add("assistant", content, reasoning_content=reasoning)
                return content

            if choice.finish_reason == "tool_calls":
                self.stm.add_tool_call_message(choice.message)

                for tool_call in choice.message.tool_calls:
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    print(f"  [tool] {name}({json.dumps(args, ensure_ascii=False)})")
                    result = execute_tool(name, args, agent=self)
                    self.stm.add("tool", str(result), tool_call_id=tool_call.id)

                # Loop back — next LLM call will see tool results

    def _build_messages(self) -> list[dict]:
        system = self._build_system_prompt()
        messages = [{"role": "system", "content": system}]
        messages.extend(self.stm.get_messages())
        return messages

    def _build_system_prompt(self) -> str:
        parts = [BASE_SYSTEM_PROMPT]

        facts = self.ltm.list_all()
        if facts:
            fact_lines = [f"- {f['key']}: {f['value']}" for f in facts]
            parts.append("\n[Long-term Memory]\n" + "\n".join(fact_lines))

        if self.plan:
            plan_lines = [
                f"  {s['id']}. [{s['status']}] {s['description']}"
                for s in self.plan["steps"]
            ]
            parts.append(
                f"\n[Current Plan: {self.plan['goal']}]\n" + "\n".join(plan_lines)
            )

        return "\n".join(parts)

    @staticmethod
    def _print_messages(messages: list[dict]):
        print("\n\033[90m--- PROMPT ---")
        for msg in messages:
            role = msg["role"].upper()
            content = msg.get("content") or "(empty)"
            # Truncate long content for readability
            if len(content) > 500:
                content = content[:500] + f"... ({len(content)} chars total)"
            print(f"[{role}] {content}")
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    print(f"  -> {tc['function']['name']}({tc['function']['arguments']})")
        print("--- END PROMPT ---\033[0m")
