import json
import os
import tempfile
from datetime import datetime
from typing import Optional


class ShortTermMemory:
    """In-memory conversation history. Cleared per session."""

    def __init__(self, max_messages: int = 80):
        self.messages: list[dict] = []
        self.max_messages = max_messages

    def add(self, role: str, content: str, reasoning_content: str = None, **kwargs):
        msg = {"role": role, "content": content}
        if reasoning_content:
            msg["reasoning_content"] = reasoning_content
        msg.update(kwargs)
        self.messages.append(msg)
        self._trim()

    def add_tool_call_message(self, assistant_message):
        """Add an assistant message that contains tool_calls."""
        msg = {"role": "assistant", "content": assistant_message.content}
        if getattr(assistant_message, "reasoning_content", None):
            msg["reasoning_content"] = assistant_message.reasoning_content
        if assistant_message.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_message.tool_calls
            ]
        self.messages.append(msg)
        self._trim()

    def get_messages(self) -> list[dict]:
        return self.messages

    def clear(self):
        self.messages = []

    def _trim(self):
        if len(self.messages) <= self.max_messages:
            return
        # Keep the most recent messages, drop from the front
        excess = len(self.messages) - self.max_messages
        self.messages = self.messages[excess:]


class LongTermMemory:
    """File-based key-value store. Persists across sessions."""

    def __init__(self, store_dir: str = "memory_store"):
        self.store_dir = store_dir
        os.makedirs(store_dir, exist_ok=True)
        self.index_file = os.path.join(store_dir, "index.json")

    def save(self, key: str, value: str, category: str = "general"):
        data = self._load_index()
        # Remove existing entry with same key
        data = [e for e in data if e["key"] != key]
        data.append({
            "key": key,
            "value": value,
            "timestamp": datetime.now().isoformat(),
            "category": category,
        })
        self._save_index(data)

    def recall(self, key: str) -> Optional[str]:
        data = self._load_index()
        for entry in data:
            if entry["key"] == key:
                return entry["value"]
        return None

    def search(self, query: str) -> list[dict]:
        data = self._load_index()
        query_lower = query.lower()
        return [
            {"key": e["key"], "value": e["value"], "timestamp": e["timestamp"]}
            for e in data
            if query_lower in e["key"].lower() or query_lower in e["value"].lower()
        ]

    def delete(self, key: str):
        data = self._load_index()
        data = [e for e in data if e["key"] != key]
        self._save_index(data)

    def list_all(self) -> list[dict]:
        return self._load_index()

    def _load_index(self) -> list[dict]:
        if not os.path.exists(self.index_file):
            return []
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

    def _save_index(self, data: list[dict]):
        # Atomic write: write to temp file, then rename
        fd, tmp_path = tempfile.mkstemp(dir=self.store_dir, suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.index_file)
        except Exception:
            os.unlink(tmp_path)
            raise
