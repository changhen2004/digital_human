# tests/test_stream_over_http.py
# 端到端流式自检：起真实 uvicorn 服务，走真实 /api/chat/stream + SSE，
# 用假模型量每个增量的到达时间（TestClient 的 ASGI 传输会把整个响应缓冲，量不出真流式）
# 在 backend 目录执行 python tests/test_stream_over_http.py

import json
import os
import socket
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DIGITAL_HUMAN_DATA_DIR"] = tempfile.mkdtemp(prefix="digital_human_stream_")

import httpx
import uvicorn

import services.model_clients as model_clients

DELAY = 0.35
PLATFORM_ID, MODEL_ID = "p1", "m1"


def delta(piece):
    return {"choices": [{"delta": piece}]}


class FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks

    def __iter__(self):
        return iter(self.chunks)

    def close(self):
        pass


class FakeCompletions:
    def create(self, **parameters):
        messages = parameters.get("messages", [])
        if any(item.get("role") == "tool" for item in messages):
            def generate():
                for piece in ["答案", "来了"]:
                    yield delta({"content": piece})
                    time.sleep(DELAY)
            return FakeStream(generate())
        call = {"index": 0, "id": "c1", "function": {"name": "get_system_time", "arguments": "{}"}}
        return FakeStream([delta({"tool_calls": [call]})])


class FakeClient:
    def __init__(self):
        self.chat = types.SimpleNamespace(completions=FakeCompletions())

    def close(self):
        pass


model_clients.create_openai_client = lambda config: FakeClient()

import main   # noqa: E402  （必须在打桩之后导入）

with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()

base = f"http://127.0.0.1:{port}"
for _ in range(100):
    try:
        if httpx.get(f"{base}/api/chat-history", timeout=1).status_code in (200, 401):
            break
    except Exception:
        time.sleep(0.1)
else:
    raise SystemExit("uvicorn 没起来")

with httpx.Client(base_url=base, timeout=30) as http:
    registered = http.post("/api/auth/register", json={"username": "streamprobe", "password": "secret123"})
    assert registered.status_code == 201, registered.text
    user_dir = Path(os.environ["DIGITAL_HUMAN_DATA_DIR"]) / "users" / registered.json()["id"]
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "chat_settings.json").write_text(json.dumps({
        "platformId": PLATFORM_ID, "modelId": MODEL_ID,
        "temperature": 0.7, "topP": 0.9, "maxTokens": 2000, "activeCategories": [],
    }, ensure_ascii=False), encoding="utf-8")
    (user_dir / "api_repository.json").write_text(json.dumps({
        "platforms": [{
            "id": PLATFORM_ID, "name": "mock", "baseUrl": "http://127.0.0.1:1/v1", "apiKey": "x",
            "models": [{"id": MODEL_ID, "name": "mock-model", "enabled": True}],
            "createdAt": "", "updatedAt": "",
        }],
    }, ensure_ascii=False), encoding="utf-8")

    payloads, stamps, tool_events = [], [], []
    started = time.monotonic()
    with http.stream("POST", "/api/chat/stream", json={"message": "现在几点"}) as response:
        assert response.status_code == 200, response.status_code
        assert response.headers["content-type"].startswith("text/event-stream"), response.headers
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            body = json.loads(line[5:].strip())
            if body.get("type") == "delta":
                payloads.append(body["content"])
                stamps.append(time.monotonic() - started)
            elif body.get("type") == "tool":
                tool_events.append(body["name"])

server.should_exit = True

print("SSE delta 内容:", payloads)
print("SSE tool 事件:", tool_events)
print("到达时间点:", [f"{t:.2f}s" for t in stamps])
assert payloads == ["答案", "来了"], payloads
assert tool_events == ["get_system_time"], "工具执行前必须先发 tool 事件，否则界面全程没有反馈"
assert stamps[-1] - stamps[0] > DELAY * 0.7, f"工具轮之后的 SSE 增量被缓冲了: {stamps}"
print("工具轮之后的回复经真实 uvicorn + SSE 仍逐步到达 ok")

print("\n自检通过")
