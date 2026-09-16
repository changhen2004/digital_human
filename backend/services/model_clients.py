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


def chat_completion(model_config, prompt, temperature=None, top_p=None, max_tokens=None):
    client = create_openai_client(model_config)
    parameters = {"model": model_config["model"], "messages": [{"role": "user", "content": prompt}]}
    if temperature is not None: parameters["temperature"] = temperature
    if top_p is not None: parameters["top_p"] = top_p
    if max_tokens is not None: parameters["max_tokens"] = max_tokens
    try:
        result = client.chat.completions.create(**parameters)
        return result.choices[0].message.content or ""
    finally:
        client.close()


def stream_chat_completion(model_config, prompt, temperature=None, top_p=None, max_tokens=None):
    client = create_openai_client(model_config)
    parameters = {"model": model_config["model"], "messages": [{"role": "user", "content": prompt}], "stream": True}
    if temperature is not None: parameters["temperature"] = temperature
    if top_p is not None: parameters["top_p"] = top_p
    if max_tokens is not None: parameters["max_tokens"] = max_tokens
    stream = None
    try:
        stream = client.chat.completions.create(**parameters)
        for chunk in stream:
            choices = chunk.get("choices") if isinstance(chunk, dict) else getattr(chunk, "choices", None)
            if not choices: continue
            choice = choices[0]
            delta = choice.get("delta") if isinstance(choice, dict) else getattr(choice, "delta", None)
            if not delta: continue
            content = delta.get("content") if isinstance(delta, dict) else getattr(delta, "content", None)
            if isinstance(content, str) and content:
                yield content
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
