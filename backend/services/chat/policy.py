from dataclasses import dataclass
import math
import os
import re


def estimate_tokens(text):
    ascii_count = sum(ord(char) < 128 for char in text)
    return math.ceil(ascii_count / 4) + (len(text) - ascii_count) * 2 + 4


def message_windows(messages, budget):
    """Split large messages without losing their original IDs or tail content."""
    window, used = [], 0
    for row in messages:
        remaining = row["content"]
        while remaining:
            low, high = 1, len(remaining)
            while low < high:
                middle = (low + high + 1) // 2
                if estimate_tokens(remaining[:middle]) <= budget:
                    low = middle
                else:
                    high = middle - 1
            part = remaining[:low]
            tokens = estimate_tokens(part)
            if tokens > budget:
                raise ValueError("Token budget is too small for one character")
            if window and used + tokens > budget:
                yield window
                window, used = [], 0
            window.append({"id": row["id"], "role": row["role"], "content": part})
            used += tokens
            remaining = remaining[low:]
    if window:
        yield window


@dataclass(frozen=True)
class MemoryPolicy:
    message_threshold: int = 5
    token_threshold: int = 3000
    idle_seconds: int = 900
    summary_message_threshold: int = 12
    summary_token_threshold: int = 6000
    batch_messages: int = 40
    batch_tokens: int = 4000
    input_tokens: int = 16000

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise ValueError("Memory policy values must be positive integers")
        if self.batch_tokens >= self.input_tokens:
            raise ValueError("Batch budget must leave room for instructions")

    @classmethod
    def from_env(cls):
        return cls(**{name: int(os.environ.get("CHAT_MEMORY_" + name.upper(), default))
                      for name, default in vars(cls()).items()})

    def trigger(self, messages, *, kind, immediate=False, now):
        if immediate:
            return now, 100, "finish"
        users = [row for row in messages if row["role"] == "user"]
        if kind == "memory":
            for row in users:
                text = row["content"]
                if re.search(r"如果|假设|假如|举个?例|比如|他说|她说", text):
                    continue
                if re.search(r"请?记住|帮我记|忘记|删除.*记忆|纠正|更正|记错|重新记录", text):
                    return now, 100, "explicit"
                if re.search(r"只考虑|不再考虑|不考虑|改为|改成|现在.*(?:毕业|实习|到岗|城市)|已经毕业", text):
                    return now, 80, "critical_change"
        count_limit = self.message_threshold if kind == "memory" else self.summary_message_threshold
        token_limit = self.token_threshold if kind == "memory" else self.summary_token_threshold
        if sum(estimate_tokens(row["content"]) for row in messages) >= token_limit:
            return now, 40, "tokens"
        if len(users) >= count_limit:
            return now, 30, "messages"
        return max(row["created_at"] for row in messages) + self.idle_seconds, 0, "idle"
