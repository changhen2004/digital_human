from urllib.parse import urlparse

import httpx
from openai import OpenAI


class ModelClientError(Exception):
    pass


def get_model_config(api_repository, platform_id, model_id):
    if not platform_id or not model_id:
        return None
    return api_repository.get_model_config(platform_id, model_id)


def create_openai_client(model_config):
    hostname = urlparse(model_config["baseUrl"]).hostname
    is_local = hostname in {"localhost", "127.0.0.1", "::1"}
    http_client = httpx.Client(trust_env=not is_local, timeout=60.0)
    return OpenAI(
        base_url=model_config["baseUrl"],
        api_key=model_config["apiKey"] or "local-api-key",
        http_client=http_client,
    )


def _field(value, name):
    """兼容两种返回形态：部分网关回 dict，官方 SDK 回对象"""
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _as_messages(prompt):
    """prompt 可以是单个字符串（老调用方式），也可以是完整的 messages 列表"""
    return prompt if isinstance(prompt, list) else [{"role": "user", "content": prompt}]


def chat_completion(model_config, prompt, temperature=None, top_p=None, max_tokens=None):
    client = create_openai_client(model_config)
    parameters = {"model": model_config["model"], "messages": _as_messages(prompt)}
    if temperature is not None: parameters["temperature"] = temperature
    if top_p is not None: parameters["top_p"] = top_p
    if max_tokens is not None: parameters["max_tokens"] = max_tokens
    try:
        result = client.chat.completions.create(**parameters)
        return result.choices[0].message.content or ""
    finally:
        client.close()


def stream_chat_completion(model_config, prompt, tools=None, temperature=None, top_p=None, max_tokens=None):
    """流式请求：把上游增量翻译成内部事件流。

    产出三种事件，调用方按 type 分支处理，不再依赖生成器的 return 值：
      {"type": "text_delta", "content": ...}  文本增量，保持上游顺序，不整轮缓冲
      {"type": "tool_call", "call": ...}      分片按 index 合并后的完整调用，位于文本之后
      {"type": "model_end"}                   单次上游请求正常结束；不代表整轮聊天成功

    失败仍以异常传播；提前关闭生成器时，finally 依次关闭上游响应和客户端。
    """
    client = create_openai_client(model_config)
    parameters = {"model": model_config["model"], "messages": _as_messages(prompt), "stream": True}
    if tools: parameters["tools"] = tools
    if temperature is not None: parameters["temperature"] = temperature
    if top_p is not None: parameters["top_p"] = top_p
    if max_tokens is not None: parameters["max_tokens"] = max_tokens
    stream = None
    tool_calls = {}
    try:
        stream = client.chat.completions.create(**parameters)
        for chunk in stream:
            choices = _field(chunk, "choices")
            if not choices: continue
            delta = _field(choices[0], "delta")
            if not delta: continue
            content = _field(delta, "content")
            if isinstance(content, str) and content:
                yield {"type": "text_delta", "content": content}
            for call in _field(delta, "tool_calls") or []:
                # 流式工具调用按 index 分片到达：id 和 name 一次性给出，arguments 逐段拼接
                slot = tool_calls.setdefault(
                    _field(call, "index") or 0,
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                call_id = _field(call, "id")
                if call_id: slot["id"] = call_id
                function = _field(call, "function")
                if function:
                    name = _field(function, "name")
                    if name: slot["function"]["name"] += name
                    arguments = _field(function, "arguments")
                    if arguments: slot["function"]["arguments"] += arguments
        # 索引只在流结束后才能确定不再收到分片，此时统一发出完整调用
        for index in sorted(tool_calls):
            yield {"type": "tool_call", "call": tool_calls[index]}
        yield {"type": "model_end"}
    except Exception as error:
        raise ModelClientError("模型流式请求失败") from error
    finally:
        if stream is not None and hasattr(stream, "close"):
            stream.close()
        client.close()


class OpenAIEmbeddingsAdapter:
    def __init__(self, model_config):
        self.model_config = model_config

    def embed_documents(self, texts):
        return self._embed(texts)

    def embed_query(self, text):
        return self._embed([text])[0]

    def _embed(self, texts):
        client = create_openai_client(self.model_config)
        try:
            result = client.embeddings.create(model=self.model_config["model"], input=texts)
            return [item.embedding for item in result.data]
        finally:
            client.close()
