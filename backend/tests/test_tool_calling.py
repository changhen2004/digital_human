# tests/test_tool_calling.py
# 工具调用自检（不联网，用假客户端）：在 backend 目录执行 python tests/test_tool_calling.py

import copy
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import services.model_clients as model_clients
from modules.chat import ChatManager

MODEL_CONFIG = {"baseUrl": "http://127.0.0.1:9/v1", "apiKey": "test", "model": "test-model"}
SETTINGS = {"temperature": 0.7, "topP": 0.9, "maxTokens": 100}


class FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        return iter(self.chunks)

    def close(self):
        self.closed = True


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **parameters):
        # 必须深拷贝：chat.py 会继续往同一个 messages 列表里追加，存引用会看到后续状态
        self.requests.append(copy.deepcopy(parameters))
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.completions = FakeCompletions(responses)
        self.chat = types.SimpleNamespace(completions=self.completions)
        self.closed = False

    def close(self):
        self.closed = True


class FakeMemory:
    def __init__(self):
        self.messages = []
        self.summarized = False

    def recall_memories(self, query):
        return {"vectorized": [], "recent_text": []}

    def get_recent_messages(self, limit):
        return []

    def add_message(self, role, content):
        self.messages.append((role, content))

    def check_and_summarize(self):
        self.summarized = True

    def auto_vectorize_memories(self):
        pass


def delta(**values):
    return {"choices": [{"delta": values}]}


def call(id_, name, arguments):
    return {"index": 0, "id": id_, "function": {"name": name, "arguments": arguments}}


def text_stream(*pieces):
    """每一轮都走流式，所以假响应也必须是流"""
    return FakeStream([delta(content=piece) for piece in pieces])


def drain(generator):
    """驱动生成器，返回 (yield 出来的片段, 生成器的 return 值)"""
    parts = []
    while True:
        try:
            parts.append(next(generator))
        except StopIteration as stop:
            return parts, stop.value


def new_chat(memory=None):
    chat = ChatManager.__new__(ChatManager)   # 绕开 __init__，避免真的去连 Ollama
    chat.llm = None
    chat.rag_system = None
    chat.user_profile = None
    chat.active_categories = []
    chat.memory_system = memory
    return chat


# 1. 流式工具调用：arguments 是分片到达的，必须拼成完整 JSON
model_clients.create_openai_client = lambda config: FakeClient([FakeStream([
    delta(content="让我查一下。"),
    delta(tool_calls=[call("call_a", "get_system_time", "")]),
    delta(tool_calls=[{"index": 0, "function": {"arguments": '{"unused"'}}]),
    delta(tool_calls=[{"index": 0, "function": {"arguments": ": 1}"}}]),
])])
parts, tool_calls = drain(model_clients.stream_chat_completion(MODEL_CONFIG, "现在几点"))
assert parts == ["让我查一下。"], parts
assert tool_calls == [{
    "id": "call_a",
    "type": "function",
    "function": {"name": "get_system_time", "arguments": '{"unused": 1}'},
}], tool_calls
print("1. 流式工具调用分片拼接 ok")

# 2. 完整循环：模型要工具 -> 执行 -> role:tool 回传 -> 再问模型 -> 吐出答案
client = FakeClient([
    FakeStream([
        delta(content="让我查一下。"),
        delta(tool_calls=[call("call_a", "get_system_time", "")]),
        delta(tool_calls=[{"index": 0, "function": {"arguments": "{}"}}]),
    ]),
    text_stream("现在是 ", "2026-09-16 17:50:00。"),
])
model_clients.create_openai_client = lambda config: client
memory = FakeMemory()
parts, _ = drain(new_chat(memory).stream_chat_with_api("现在几点", MODEL_CONFIG, SETTINGS))
assert parts == ["让我查一下。", "现在是 ", "2026-09-16 17:50:00。"], parts
assert memory.messages == [("user", "现在几点"), ("assistant", "让我查一下。现在是 2026-09-16 17:50:00。")], memory.messages
assert memory.summarized

assert len(client.completions.requests) == 2, client.completions.requests
first, second = client.completions.requests
assert first["stream"] is True
assert second["stream"] is True, "工具轮之后的收口回复也必须走流式，否则会整块弹出"
assert [item["function"]["name"] for item in first["tools"]] == ["get_system_time", "get_system_ip", "get_campus_talks"], first["tools"]
assert [item["role"] for item in first["messages"]] == ["user"], first["messages"]

tool_messages = [item for item in second["messages"] if item["role"] == "tool"]
assert len(tool_messages) == 1, second["messages"]
assert tool_messages[0]["tool_call_id"] == "call_a"
assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", tool_messages[0]["content"]), tool_messages
assistant = [item for item in second["messages"] if item["role"] == "assistant"][0]
assert assistant["tool_calls"][0]["function"]["name"] == "get_system_time"
print("2. 工具调用循环与 role:tool 回传 ok")

# 3. 没触发工具调用时，行为和接入工具前一致：只请求一次，纯流式
client = FakeClient([FakeStream([delta(content="你好"), delta(content="呀")])])
model_clients.create_openai_client = lambda config: client
memory = FakeMemory()
parts, _ = drain(new_chat(memory).stream_chat_with_api("你好", MODEL_CONFIG, SETTINGS))
assert parts == ["你好", "呀"], parts
assert len(client.completions.requests) == 1, client.completions.requests
assert memory.messages == [("user", "你好"), ("assistant", "你好呀")], memory.messages
print("3. 无工具调用时保持原有流式行为 ok")

# 4. 非流式入口复用同一条循环
client = FakeClient([FakeStream([delta(content="答案")])])
model_clients.create_openai_client = lambda config: client
assert new_chat().chat_with_api("你好", MODEL_CONFIG, SETTINGS) == "答案"
print("4. chat_with_api 复用流式实现 ok")

# 5. 工具执行失败（工具名不存在）只把错误文本回传，不能崩掉整轮对话
client = FakeClient([
    FakeStream([delta(tool_calls=[call("call_b", "no_such_tool", "{}")])]),
    text_stream("我没法调用那个工具。"),
])
model_clients.create_openai_client = lambda config: client
parts, _ = drain(new_chat().stream_chat_with_api("帮我做点什么", MODEL_CONFIG, SETTINGS))
assert parts == ["我没法调用那个工具。"], parts
tool_message = [item for item in client.completions.requests[1]["messages"] if item["role"] == "tool"][0]
assert tool_message["content"].startswith("错误：不存在"), tool_message
print("5. 工具失败降级为文本回传 ok")

# 6. 模型反复要工具时必须能收口：最后一轮不再提供 tools，强制它出文本
client = FakeClient(
    [FakeStream([delta(tool_calls=[call(f"call_{index}", "get_system_time", "{}")])]) for index in range(5)]
    + [text_stream("收口答案。")]
)
model_clients.create_openai_client = lambda config: client
parts, _ = drain(new_chat().stream_chat_with_api("现在几点", MODEL_CONFIG, SETTINGS))
assert parts == ["收口答案。"], parts
requests = client.completions.requests
assert len(requests) == 6, len(requests)
assert "tools" in requests[-2], "倒数第二轮仍应提供工具"
assert "tools" not in requests[-1], "最后一轮必须去掉 tools 强制收口"
print("6. 工具轮次达上限后强制收口 ok")

print("\n自检通过")
