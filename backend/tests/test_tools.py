# tests/test_tools.py
# 工具注册表与执行入口自检：不联网，用可控响应验证 Schema、参数接受范围和校园查询降级。
# 在 backend 目录执行 python tests/test_tools.py

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import modules.tools as tools

TIME_PATTERN = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"

# 1. 三个工具的名称、描述、参数定义和顺序保持
schemas = tools.tool_schemas()
assert schemas == [
    {"type": "function", "function": {
        "name": "get_system_time",
        "description": "获取当前系统时间，返回格式为 YYYY-MM-DD HH:MM:SS",
        "parameters": {"properties": {}, "type": "object"},
    }},
    {"type": "function", "function": {
        "name": "get_system_ip",
        "description": "获取当前系统的公网IP地址",
        "parameters": {"properties": {}, "type": "object"},
    }},
    {"type": "function", "function": {
        "name": "get_campus_talks",
        "description": "获取今明两天来湖南科技大学宣讲的企业名单，含宣讲时间和地点",
        "parameters": {"properties": {}, "type": "object"},
    }},
], schemas
print("1. 工具 Schema、描述与顺序保持 ok")

# 2. 无参数工具的参数接受范围：这些合法 JSON 都允许并忽略
for arguments in ("", "{}", '{"extra": 1}', "null", "[]", "5"):
    result = tools.run_tool("get_system_time", arguments)
    assert re.fullmatch(TIME_PATTERN, result), (arguments, result)
print("2. 空串/空对象/多余字段/null/数组/数字均被接受 ok")

# 3. 非法 JSON 与未知工具都返回文本
result = tools.run_tool("get_system_time", "{bad json")
assert result == "错误：工具 get_system_time 的参数不是合法 JSON：{bad json", result
result = tools.run_tool("no_such_tool", "{}")
assert result == "错误：不存在名为 no_such_tool 的工具", result
print("3. 非法 JSON 与未知工具降级为文本 ok")

# 4. 工具执行异常转文本，不向外抛
original_invoke = tools._TOOLS_BY_NAME["get_system_time"]


def explode(arguments):
    raise RuntimeError("模拟执行失败")


tools._TOOLS_BY_NAME["get_system_time"] = explode
try:
    result = tools.run_tool("get_system_time", "{}")
finally:
    tools._TOOLS_BY_NAME["get_system_time"] = original_invoke
assert result == "工具 get_system_time 执行失败：RuntimeError: 模拟执行失败", result
print("4. 工具执行异常降级为文本 ok")


# 5. 校园宣讲会：用可控响应验证排序、格式和单日失败降级
class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


today = datetime.now().date()
tomorrow = today + timedelta(days=1)
original_get = tools.requests.get


def fake_get(url, params=None, headers=None, timeout=None):
    assert url == tools.CAREER_TALK_LIST_URL, url
    if params["day"] == tomorrow.isoformat():
        raise RuntimeError("模拟站点不可用")
    return FakeResponse({"code": 1, "data": [
        {"company_name": "乙公司", "meet_time": f"{today} 16:00", "meet_end_time": "",
         "address": " 逸夫楼 101 ", "meet_type": "0", "career_state": "1"},
        {"company_name": "甲公司", "meet_time": f"{today} 09:00", "meet_end_time": "11:00",
         "address": "", "meet_type": "1", "career_state": "0"},
    ]})


tools.requests.get = fake_get
try:
    output = tools.run_tool("get_campus_talks", "")
finally:
    tools.requests.get = original_get
assert output == (
    f"{today}（今天）共 2 场：\n"
    f"  1. 甲公司 | {today} 09:00-11:00 | 直播云宣讲\n"
    f"  2. 乙公司 | {today} 16:00 | 逸夫楼 101 | 已取消\n"
    f"{tomorrow}（明天）：查询失败（RuntimeError）"
), output
print("5. 校园宣讲会排序、格式与单日失败降级 ok")

# 6. 空数据只输出一行提示，两天互不影响
tools.requests.get = lambda url, params=None, headers=None, timeout=None: FakeResponse({"code": 1, "data": []})
try:
    output = tools.run_tool("get_campus_talks", "")
finally:
    tools.requests.get = original_get
assert output.count("暂无宣讲会") == 2, output
print("6. 无宣讲会时两天各自提示 ok")

print("\n自检通过")
