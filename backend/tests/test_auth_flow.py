# tests/test_auth_flow.py
# 登录注册与多用户数据隔离自检：在 backend 目录执行 python tests/test_auth_flow.py

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DIGITAL_HUMAN_DATA_DIR"] = tempfile.mkdtemp(prefix="digital_human_test_")

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

import main
from services.workspace import bind_current_user, current_workspace, get_workspace

# 探针路由：与 /api/chat/stream 同样依赖“登录用户在流式响应里仍然可见”的机制
probe_router = APIRouter(prefix="/api/_probe", dependencies=[Depends(bind_current_user)])


@probe_router.get("/stream")
def probe_stream():
    def generate():
        yield current_workspace().user_id
    return StreamingResponse(generate(), media_type="text/plain")


main.app.include_router(probe_router)
alice_client = TestClient(main.app)
bob_client = TestClient(main.app)
anonymous = TestClient(main.app)

# 旧版单用户数据：第一个注册的用户应当接管
legacy_file = Path(os.environ["DIGITAL_HUMAN_DATA_DIR"]) / "chat_settings.json"
legacy_file.write_text('{"legacy": true}', encoding="utf-8")

# 未登录不能访问业务接口
assert anonymous.get("/api/chat-history").status_code == 401
assert anonymous.get("/api/platforms").status_code == 401

# 注册即登录
response = alice_client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
assert response.status_code == 201, response.text
alice = response.json()
assert alice["username"] == "alice"
assert "password" not in response.text and "salt" not in response.text
assert alice_client.get("/api/auth/me").json()["id"] == alice["id"]
assert alice_client.get("/api/chat-history").json()["messages"] == []
assert alice_client.get("/api/_probe/stream").text == alice["id"]

# 用户名重复、密码过短、密码错误
assert anonymous.post("/api/auth/register", json={"username": "alice", "password": "secret123"}).status_code == 409
assert anonymous.post("/api/auth/register", json={"username": "carol", "password": "123"}).status_code == 400
assert anonymous.post("/api/auth/login", json={"username": "alice", "password": "wrong-pass"}).status_code == 401

# 已有用户登录
assert anonymous.post("/api/auth/login", json={"username": "alice", "password": "secret123"}).status_code == 200
assert anonymous.get("/api/auth/me").json()["username"] == "alice"

# 第一个用户接管旧数据，后面的用户不会
assert (get_workspace(alice["id"]).data_dir / "chat_settings.json").read_text(encoding="utf-8") == '{"legacy": true}'
assert not legacy_file.exists()
legacy_after = Path(os.environ["DIGITAL_HUMAN_DATA_DIR"]) / "user_profile.json"
legacy_after.write_text('{"legacy": true}', encoding="utf-8")

# 两个用户的数据互不可见
assert bob_client.post("/api/auth/register", json={"username": "bob", "password": "secret123"}).status_code == 201
bob = bob_client.get("/api/auth/me").json()
assert get_workspace(alice["id"]).data_dir != get_workspace(bob["id"]).data_dir
assert not (get_workspace(bob["id"]).data_dir / "user_profile.json").exists()
assert legacy_after.exists()
get_workspace(alice["id"]).memory_system.add_message("user", "只属于alice的消息")
assert len(alice_client.get("/api/chat-history").json()["messages"]) == 1
assert bob_client.get("/api/chat-history").json()["messages"] == []

# 退出登录后旧会话失效
assert anonymous.post("/api/auth/logout").status_code == 200
assert anonymous.get("/api/auth/me").status_code == 401
assert anonymous.get("/api/chat-history").status_code == 401

print("登录注册与多用户隔离自检全部通过")
