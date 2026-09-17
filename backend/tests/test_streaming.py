# tests/test_streaming.py
# 流式输出自检：用本地假模型服务，验证文本增量是"逐步到达"而不是"最后一次性吐出"
# 在 backend 目录执行 python tests/test_streaming.py

import json
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.chat import ChatManager

DELAY = 0.35          # 每个增量之间的间隔，用来区分"逐步到达"和"一次性到达"
SETTINGS = {"temperature": 0.7, "topP": 0.9, "maxTokens": 100}


def chunk(piece):
    return {
        "id": "1", "object": "chat.completion.chunk", "created": 0, "model": "mock",
        "choices": [{"index": 0, "delta": piece, "finish_reason": None}],
    }


class MockModel(BaseHTTPRequestHandler):
    """假 OpenAI 兼容服务。mode 决定这一轮返回纯文本还是先要一个工具。"""

    mode = "text"

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages", [])
        has_tool_result = any(item.get("role") == "tool" for item in messages)

        # 兜底分支：现在的实现每一轮都流式，走不到这里。
        # 留着是为了万一哪天又退回"工具轮走非流式"，下面的时间断言能直接抓出来。
        if self.mode == "tool" and has_tool_result and not body.get("stream"):
            payload = {
                "id": "1", "object": "chat.completion", "created": 0, "model": "mock",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "最终答案"}}],
            }
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if self.mode == "tool" and not has_tool_result:
            call = {"index": 0, "id": "c1", "type": "function",
                    "function": {"name": "get_system_time", "arguments": "{}"}}
            self.wfile.write(f"data: {json.dumps(chunk({'tool_calls': [call]}))}\n\n".encode())
        else:
            for piece in (["最终", "答案"] if self.mode == "tool" else ["你", "好", "呀"]):
                self.wfile.write(f"data: {json.dumps(chunk({'content': piece}))}\n\n".encode())
                self.wfile.flush()
                time.sleep(DELAY)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), MockModel)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
MODEL_CONFIG = {"baseUrl": f"http://127.0.0.1:{port}/v1", "apiKey": "x", "model": "mock"}


def new_chat():
    chat = ChatManager.__new__(ChatManager)
    chat.llm = None
    chat.rag_system = None
    chat.memory_system = None
    chat.user_profile = None
    chat.active_categories = []
    return chat


def collect_with_timing(generator):
    parts, stamps = [], []
    started = time.monotonic()
    for event in generator:
        if event["type"] != "delta":
            continue
        parts.append(event["content"])
        stamps.append(time.monotonic() - started)
    return parts, stamps


# 1. 纯文本回复：三个增量必须在时间上分开到达（真流式）
MockModel.mode = "text"
parts, stamps = collect_with_timing(new_chat().stream_chat_with_api("你好", MODEL_CONFIG, SETTINGS))
print("1. 纯文本增量时间点:", [f"{t:.2f}s" for t in stamps], "内容:", parts)
assert parts == ["你", "好", "呀"], parts
assert stamps[-1] - stamps[0] > DELAY * 0.7, f"增量挤在一起到达，说明被缓冲了: {stamps}"
print("1. 纯文本回复逐步到达 ok")

# 2. 触发工具：工具轮之后的收口回复必须同样逐步到达，不能整块弹出
MockModel.mode = "tool"
parts, stamps = collect_with_timing(new_chat().stream_chat_with_api("现在几点", MODEL_CONFIG, SETTINGS))
print("2. 触发工具后的增量:", [f"{t:.2f}s" for t in stamps], "内容:", parts)
assert parts == ["最终", "答案"], parts
assert stamps[-1] - stamps[0] > DELAY * 0.7, f"工具轮之后的回复被缓冲了: {stamps}"
print("2. 工具轮之后的收口回复仍逐步到达 ok")

server.shutdown()
print("\n自检通过")
