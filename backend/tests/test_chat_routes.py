# tests/test_chat_routes.py
# 对话路由自检：JSON/SSE 共用准备逻辑后，校验各自的状态码、字段和双用户隔离。
# 在 backend 目录执行 python tests/test_chat_routes.py

import json
import os
import sys
import tempfile
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DIGITAL_HUMAN_DATA_DIR"] = tempfile.mkdtemp(prefix="digital_human_routes_")

import services.model_clients as model_clients


class FakeStream:
    def __init__(self, pieces, delay):
        self.pieces = pieces
        self.delay = delay
        self.closed = False

    def __iter__(self):
        for piece in self.pieces:
            time.sleep(self.delay)
            yield {"choices": [{"delta": {"content": piece}}]}

    def close(self):
        self.closed = True


class FakeCompletions:
    def create(self, **parameters):
        # 回复带上模型名，用来验证每个用户拿到的是自己的模型配置
        return FakeStream([parameters["model"], "-回复"], 0.2)


class FakeClient:
    def __init__(self):
        self.chat = types.SimpleNamespace(completions=FakeCompletions())

    def close(self):
        pass


model_clients.create_openai_client = lambda config: FakeClient()

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402  （必须在打桩之后导入）

alice_client = TestClient(main.app)
bob_client = TestClient(main.app)


def register(client, username):
    response = client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def configure(user_id, model_name):
    user_dir = Path(os.environ["DIGITAL_HUMAN_DATA_DIR"]) / "users" / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "chat_settings.json").write_text(json.dumps({
        "platformId": "p1", "modelId": "m1",
        "temperature": 0.7, "topP": 0.9, "maxTokens": 100, "activeCategories": [],
    }, ensure_ascii=False), encoding="utf-8")
    (user_dir / "api_repository.json").write_text(json.dumps({
        "platforms": [{
            "id": "p1", "name": "mock", "baseUrl": "http://127.0.0.1:1/v1", "apiKey": "x",
            "models": [{"id": "m1", "name": model_name, "enabled": True}],
            "createdAt": "", "updatedAt": "",
        }],
    }, ensure_ascii=False), encoding="utf-8")


alice_id = register(alice_client, "alice")
bob_id = register(bob_client, "bob")

# 1. 消息校验：两个接口保持相同的 400 文案
for path in ("/api/chat", "/api/chat/stream"):
    response = alice_client.post(path, json={"message": 123})
    assert response.status_code == 400 and response.json() == {"error": "message必须是字符串"}, (path, response.text)
    response = alice_client.post(path, json={"message": "   "})
    assert response.status_code == 400 and response.json() == {"error": "消息不能为空"}, (path, response.text)
print("1. JSON/SSE 消息校验状态码与字段一致 ok")

# 2. 未选择模型：两个接口都是 400，文案一致
for path in ("/api/chat", "/api/chat/stream"):
    response = alice_client.post(path, json={"message": "你好"})
    assert response.status_code == 400 and response.json() == {"error": "请先在对话设置中选择模型"}, (path, response.text)
print("2. 未选择模型时两个接口均返回 400 ok")

# 3. 设置文件损坏：JSON 走通用 500，SSE 保持原有的 400 配置错误映射
settings_path = Path(os.environ["DIGITAL_HUMAN_DATA_DIR"]) / "users" / alice_id / "chat_settings.json"
settings_path.write_text("{broken", encoding="utf-8")
response = alice_client.post("/api/chat", json={"message": "你好"})
assert response.status_code == 500 and response.json() == {"error": "生成回复失败"}, response.text
response = alice_client.post("/api/chat/stream", json={"message": "你好"})
assert response.status_code == 400 and response.json() == {"error": "请先在对话设置中选择模型"}, response.text
print("3. 设置读取失败时两个接口保持各自原有映射 ok")

# 4. 正常 JSON 对话：返回 reply 字段，模型配置来自当前用户
configure(alice_id, "alice-model")
response = alice_client.post("/api/chat", json={"message": "alice问"})
assert response.status_code == 200, response.text
assert response.json() == {"reply": "alice-model-回复"}, response.text
print("4. JSON 对话返回 reply ok")

# 5. 正常 SSE 对话：delta 增量 + done 完成事件
response = alice_client.post("/api/chat/stream", json={"message": "alice再问"})
assert response.status_code == 200, response.text
assert response.headers["content-type"].startswith("text/event-stream"), response.headers
events = [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")]
assert [event["content"] for event in events if event["type"] == "delta"] == ["alice-model", "-回复"], events
assert events[-1] == {"type": "done"}, events
print("5. SSE 对话 delta/done 事件 ok")

# 6. 双用户并发：各自使用自己的模型配置，历史互不可见
configure(bob_id, "bob-model")
with ThreadPoolExecutor(max_workers=2) as pool:
    alice_future = pool.submit(alice_client.post, "/api/chat", json={"message": "并发-alice"})
    bob_future = pool.submit(bob_client.post, "/api/chat", json={"message": "并发-bob"})
    alice_response = alice_future.result(timeout=30)
    bob_response = bob_future.result(timeout=30)
assert alice_response.json() == {"reply": "alice-model-回复"}, alice_response.text
assert bob_response.json() == {"reply": "bob-model-回复"}, bob_response.text

alice_messages = alice_client.get("/api/chat-history").json()["messages"]
bob_messages = bob_client.get("/api/chat-history").json()["messages"]
alice_contents = [message["content"] for message in alice_messages]
bob_contents = [message["content"] for message in bob_messages]
assert "并发-alice" in alice_contents and "并发-bob" not in alice_contents, alice_contents
assert "并发-bob" in bob_contents and "并发-alice" not in bob_contents, bob_contents
assert all(content != "alice-model-回复" for content in bob_contents), bob_contents
assert all(content != "bob-model-回复" for content in alice_contents), alice_contents
print("6. 双用户并发聊天配置与历史隔离 ok")

print("\n自检通过")
