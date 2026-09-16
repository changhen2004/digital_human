# modules/tools.py
# 工具调用 - 工具定义、Schema 生成、统一执行入口

import json
import subprocess
from datetime import datetime

from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool


# ==================== 工具定义 ====================

@tool
def get_system_time() -> str:
    """获取当前系统时间，返回格式为 YYYY-MM-DD HH:MM:SS"""
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")


@tool
def get_system_ip() -> str:
    """获取当前系统的公网IP地址"""
    result = subprocess.run(
        ["curl", "-s", "cip.cc"],
        capture_output=True, text=True, encoding="utf-8", timeout=10
    )
    if result.returncode == 0 and result.stdout:
        return result.stdout.strip()
    return f"获取失败：{result.stderr.strip() if result.stderr else '未知错误'}"


ALL_TOOLS = [get_system_time, get_system_ip]
_TOOLS_BY_NAME = {item.name: item for item in ALL_TOOLS}


# ==================== 对外接口 ====================

def tool_schemas() -> list:
    """转成 OpenAI 兼容接口的 tools 参数"""
    return [convert_to_openai_tool(item) for item in ALL_TOOLS]


def run_tool(name: str, arguments_json: str) -> str:
    """执行模型请求的工具调用。

    任何异常都转成文本回给模型，不让单次工具失败崩掉整轮对话。
    """
    selected = _TOOLS_BY_NAME.get(name)
    if selected is None:
        return f"错误：不存在名为 {name} 的工具"
    try:
        arguments = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        return f"错误：工具 {name} 的参数不是合法 JSON：{arguments_json}"
    try:
        return str(selected.invoke(arguments))
    except Exception as error:
        return f"工具 {name} 执行失败：{type(error).__name__}: {error}"


if __name__ == "__main__":
    import re

    schemas = tool_schemas()
    assert [item["function"]["name"] for item in schemas] == ["get_system_time", "get_system_ip"], schemas
    for item in schemas:
        assert item["type"] == "function"
        assert item["function"]["description"], item
        assert item["function"]["parameters"]["type"] == "object", item
    print("工具 Schema：")
    print(json.dumps(schemas, ensure_ascii=False, indent=2))

    now = run_tool("get_system_time", "")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", now), now
    print(f"\nget_system_time -> {now}")

    print(f"get_system_ip   -> {run_tool('get_system_ip', '{}')}")

    # 失败路径必须返回文本而不是抛异常
    assert run_tool("no_such_tool", "{}").startswith("错误：不存在")
    assert run_tool("get_system_time", "{bad json").startswith("错误：工具")
    print("\n自检通过")
