# modules/tools.py
# 工具调用 - 工具定义、Schema 生成、统一执行入口

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests
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


# ==================== 校园宣讲会（湖南科技大学就业信息网）====================

CAREER_TALK_LIST_URL = "https://jy.hnust.edu.cn/module/getcareers"
_MEET_TYPE_LABELS = {"0": "线下宣讲", "1": "直播云宣讲", "2": "录播云宣讲"}


def _fetch_career_talks(day: str) -> list:
    """按日期拉取校内宣讲会列表。

    站点是云就业平台，列表由 /js/page/careers.js 异步取，接口就是这个 getcareers。
    day 既接受 2026-09-16 也接受 2026-9-16。
    """
    parameters = {
        "is_total": 0, "start": 0, "count": 100, "k": "", "panel_name": "",
        "type": "inner",          # inner=校内宣讲会（企业来校），outer=校外
        "day": day,
        "panel_id": "", "professionals": "", "work_city": "", "is_yun_career": "",
    }
    response = requests.get(
        CAREER_TALK_LIST_URL,
        params=parameters,
        headers={"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 1:
        raise ValueError(f"接口返回异常：{payload.get('msg') or payload.get('code')}")
    return payload.get("data") or []


def _format_talk(talk: dict) -> str:
    company = re.sub(r"\s+", " ", talk.get("company_name") or "").strip() or "未知企业"
    parts = [company]

    start = (talk.get("meet_time") or "").strip()
    end = (talk.get("meet_end_time") or "").strip()
    if start:
        parts.append(f"{start}-{end}" if end else start)

    place = re.sub(r"\s+", " ", talk.get("address") or "").strip()
    parts.append(place or _MEET_TYPE_LABELS.get(str(talk.get("meet_type")), "地点待定"))

    if str(talk.get("career_state")) == "1":
        parts.append("已取消")
    return " | ".join(parts)


def _day_talks_text(day: str) -> str:
    """抓一天并排版好；失败和空结果都只变成一行文本，两天互不影响"""
    try:
        talks = _fetch_career_talks(day)
    except Exception as error:
        return f"：查询失败（{type(error).__name__}）"
    if not talks:
        return "：暂无宣讲会"
    ordered = sorted(talks, key=lambda item: (item.get("meet_time") or "", item.get("company_name") or ""))
    body = "\n".join(f"  {index}. {_format_talk(talk)}" for index, talk in enumerate(ordered, 1))
    return f"共 {len(talks)} 场：\n{body}"


@tool
def get_campus_talks() -> str:
    """获取今明两天来湖南科技大学宣讲的企业名单，含宣讲时间和地点"""
    today = datetime.now().date()
    days = [(today + timedelta(days=offset), "今天" if offset == 0 else "明天") for offset in (0, 1)]
    # 两天并发抓：串行约 3.5s，并发约 2s，界面等待时间直接减半
    with ThreadPoolExecutor(max_workers=len(days)) as pool:
        texts = list(pool.map(lambda item: _day_talks_text(item[0].isoformat()), days))
    return "\n".join(f"{day.isoformat()}（{label}）{text}" for (day, label), text in zip(days, texts))


ALL_TOOLS = [get_system_time, get_system_ip, get_campus_talks]
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
    assert [item["function"]["name"] for item in schemas] == ["get_system_time", "get_system_ip", "get_campus_talks"], schemas
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

    # 宣讲会：只断言结构，站点数据本身会变
    talks = run_tool("get_campus_talks", "")
    assert talks.count("（今天）") == 1 and talks.count("（明天）") == 1, talks
    print("\nget_campus_talks ->")
    print(talks)

    print("\n自检通过")
