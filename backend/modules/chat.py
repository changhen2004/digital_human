# modules/chat.py
# 对话管理模块 - LLM调用、Prompt拼接、流式输出

from typing import List, Dict
from rich.console import Console
from services.model_clients import stream_chat_completion
from modules.tools import run_tool, tool_schemas
import config

console = Console()


class ChatManager:
    """对话管理器"""

    def __init__(self, rag_system=None, memory_system=None, user_profile=None):
        self.rag_system = rag_system
        self.memory_system = memory_system
        self.user_profile = user_profile
        self.active_categories = []

    def set_active_categories(self, categories: List[str]):
        self.active_categories = categories

    def build_prompt(self, user_input: str) -> str:
        prompt_parts = [f"系统提示：\n{config.SYSTEM_PROMPT}\n"]

        if self.user_profile:
            profile_contents = self.user_profile.get_prompt_contents()
            if profile_contents:
                prompt_parts.append("【用户信息】")
                prompt_parts.extend(f"- {content}" for content in profile_contents)
                prompt_parts.append("")

        if self.memory_system:
            memories = self.memory_system.recall_memories(user_input)
            if memories["vectorized"]:
                prompt_parts.append("相关历史记忆：")
                for i, memory in enumerate(memories["vectorized"], 1):
                    prompt_parts.append(f"{i}. {memory['content']}")
                prompt_parts.append("")
            if memories["recent_text"]:
                prompt_parts.append("最近的对话记录：")
                for i, text in enumerate(memories["recent_text"], 1):
                    prompt_parts.append(f"{i}. {text}")
                prompt_parts.append("")

        if self.rag_system and self.active_categories:
            rag_results = []
            for category in self.active_categories:
                rag_results.extend(self.rag_system.search(user_input, category=category))
            if rag_results:
                prompt_parts.append("参考知识库内容：")
                for i, result in enumerate(rag_results, 1):
                    prompt_parts.append(f"\n[知识{i}] 来源：{config.KNOWLEDGE_CATEGORIES.get(result['category'], result['category'])}")
                    prompt_parts.append(f"内容：{result['content']}")
                    if config.DEBUG_MODE:
                        prompt_parts.append(f"(距离: {result['distance']}，越小越相关)")
                prompt_parts.append("")

        if self.memory_system:
            recent_messages = self.memory_system.get_recent_messages(
                limit=config.MEMORY_CONFIG["context_window"]
            )
            if recent_messages:
                prompt_parts.append("当前对话：")
                for message in recent_messages:
                    role = "用户" if message["role"] == "user" else "AI"
                    prompt_parts.append(f"{role}: {message['content']}")
                prompt_parts.append("")

        prompt_parts.append(f"用户: {user_input}")
        prompt_parts.append("AI:")
        return "\n".join(prompt_parts)


    def chat_with_api(self, user_input: str, model_config: Dict, settings: Dict) -> str:
        """非流式：直接消费流式实现，工具调用循环只维护一份"""
        try:
            return "".join(
                event["content"]
                for event in self.stream_chat_with_api(user_input, model_config, settings)
                if event["type"] == "delta"
            )
        except Exception as error:
            error_message = f"对话出错: {str(error)}"
            console.print(f"[red]✗ {error_message}[/red]")
            return error_message

    def stream_chat_with_api(self, user_input: str, model_config: Dict, settings: Dict):
        """产出事件字典：{"type": "delta", "content": ...} 或 {"type": "tool", "name": ...}

        工具执行期间没有任何文本增量，靠 tool 事件让前端显示进度。
        """
        messages = [{"role": "user", "content": self.build_prompt(user_input)}]
        options = {
            "temperature": settings["temperature"],
            "top_p": settings["topP"],
            "max_tokens": settings["maxTokens"],
        }
        response_parts = []
        completed = False
        try:
            # 每一轮都走真流式：模型边吐字边决定要不要调工具，
            # 工具轮之后的收口回复同样逐字返回，不会整块弹出。
            for round_index in range(config.TOOL_CONFIG["max_rounds"] + 1):
                started_at = len(response_parts)
                last_round = round_index >= config.TOOL_CONFIG["max_rounds"]
                tool_calls = []
                stream = stream_chat_completion(
                    model_config, messages,
                    tools=None if last_round else tool_schemas(),
                    **options,
                )
                try:
                    for event in stream:
                        if event["type"] == "text_delta":
                            response_parts.append(event["content"])
                            yield {"type": "delta", "content": event["content"]}
                        elif event["type"] == "tool_call":
                            tool_calls.append(event["call"])
                        # model_end 只表示这一次上游请求结束，聊天是否成功由下面的完整性判断决定
                finally:
                    stream.close()   # 前端点“停止生成”时，确保内层 HTTP 流和客户端被关掉
                if not tool_calls:
                    break
                messages.append({
                    "role": "assistant",
                    "content": "".join(response_parts[started_at:]).strip(),
                    "tool_calls": tool_calls,
                })
                for call in tool_calls:
                    # 先告诉前端要执行工具了，再执行；否则这段等待界面全黑
                    yield {"type": "tool", "name": call["function"]["name"]}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": run_tool(call["function"]["name"], call["function"]["arguments"]),
                    })

            response = "".join(response_parts)
            if not response.strip():
                raise ValueError("模型没有返回有效内容")
            completed = True
            if self.memory_system:
                self.memory_system.add_message("user", user_input)
                self.memory_system.add_message("assistant", response)
                self.memory_system.check_and_summarize()
                self.memory_system.auto_vectorize_memories()
        finally:
            if not completed:
                response_parts.clear()


    def show_config(self):
        from rich.table import Table
        table = Table(title="对话配置")
        table.add_column("配置项", style="cyan")
        table.add_column("值", style="green")
        table.add_row("模型", config.OLLAMA_CHAT_MODEL)
        table.add_row("温度", str(config.LLM_CONFIG["temperature"]))
        table.add_row("Top P", str(config.LLM_CONFIG["top_p"]))
        table.add_row("最大Token", str(config.LLM_CONFIG["max_tokens"]))
        table.add_row("激活知识库", ", ".join([config.KNOWLEDGE_CATEGORIES.get(c, c) for c in self.active_categories]) if self.active_categories else "无")
        console.print(table)                    


if __name__ == "__main__":
    chat = ChatManager()
    chat.show_config()
