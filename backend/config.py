# config.py
# 配置文件 - 集中管理所有配置项

import os

# ==================== 项目路径配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 数据根目录，可用环境变量 DIGITAL_HUMAN_DATA_DIR 覆盖（测试或多实例部署时用）
DATA_DIR = os.environ.get("DIGITAL_HUMAN_DATA_DIR") or os.path.join(BASE_DIR, "data")
USERS_DIR = os.path.join(DATA_DIR, "users")
KNOWLEDGE_BASE_DIR = os.path.join(DATA_DIR, "knowledge_base")
CHROMA_DB_DIR = os.path.join(DATA_DIR, "chroma_db")
MEMORY_DB_PATH = os.path.join(DATA_DIR, "memories.db")
CHAT_HISTORY_PATH = os.path.join(DATA_DIR, "chat_history.json")

# 确保数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(USERS_DIR, exist_ok=True)
os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)
os.makedirs(CHROMA_DB_DIR, exist_ok=True)

# ==================== API配置 ====================
# Ollama本地服务配置
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_CHAT_MODEL = "qwen2.5:7b"
OLLAMA_EMBED_MODEL = "nomic-embed-text"

# 硅基流动API配置（语音识别STT）
SILICONFLOW_API_KEY = os.environ  # 替换成真实的Key
SILICONFLOW_STT_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"
SILICONFLOW_STT_MODEL = "FunAudioLLM/SenseVoiceSmall"

# ==================== 模型参数配置 ====================
# LLM对话参数
LLM_CONFIG = {
    "temperature": 0.7,        # 温度：控制随机性，0-2，越高越随机
    "max_tokens": 2000,        # 最大输出token数
    "top_p": 0.9,              # 核采样：保留累积概率前90%的词
    "stream": True,            # 是否流式输出
}

# RAG检索参数
RAG_CONFIG = {
    "chunk_size": 500,         # 文档切块大小（字符数）
    "chunk_overlap": 50,       # 切块重叠大小
    "top_k": 3,                # 检索返回的文本块数量
    "similarity_threshold": 0.7,  # 相似度阈值（0-1）
}

# 记忆系统参数
MEMORY_CONFIG = {
    "summarize_trigger": 20,   # 消息数超过此值触发总结
    "summarize_count": 10,     # 每次总结的消息数
    "vectorize_days": 7,       # 超过N天的记忆自动向量化
    "vectorize_count": 5,      # 单日超过N条记忆触发向量化
    "recall_vector_top_k": 2,  # 召回向量化记忆的数量
    "recall_text_count": 5,    # 召回原文记忆的数量
    "context_window": 20,      # 当前对话保留的消息数
}

# ==================== 语音配置 ====================
# TTS语音合成配置（edge-tts）
TTS_CONFIG = {
    "voice": "zh-CN-XiaoxiaoNeural",  # 微软晓晓音色（女声）
    "rate": "+0%",                     # 语速：-50%到+100%
    "volume": "+0%",                   # 音量：-50%到+100%
}

# STT语音识别配置
STT_CONFIG = {
    "sample_rate": 16000,      # 采样率
    "channels": 1,             # 单声道
    "format": "wav",           # 音频格式
    "max_duration": 30,        # 最大录音时长（秒）
}

# ==================== 系统提示词 ====================
SYSTEM_PROMPT = """你是一个智能数字人助手，可以结合知识库、长期记忆和用户信息提供帮助。

请自然、简洁地回应用户，像正常交流一样说话。不要使用客服式套话，不要说“很高兴为您服务”“请问有什么可以帮您”“请告诉我您需要了解什么”“无论是工作还是生活”等固定寒暄。用户只说“你好”时，简短回应即可，不要主动罗列服务范围。

当知识库提供了相关内容时，优先依据知识库回答；当长期记忆或用户信息与问题相关时，可以自然利用，但不要声称自己记得不存在的事情。信息不足时如实说明，不编造内容。
"""

# ==================== 知识库预设分类 ====================
KNOWLEDGE_CATEGORIES = {
    "medical": "医疗健康",
    "legal": "法律常识",
    "campus": "校园助手"
}

# ==================== 终端显示配置 ====================
TERMINAL_CONFIG = {
    "user_color": "cyan",      # 用户消息颜色
    "ai_color": "green",       # AI消息颜色
    "system_color": "yellow",  # 系统提示颜色
    "error_color": "red",      # 错误提示颜色
    "width": 80,               # 终端显示宽度
}

# ==================== 调试模式 ====================
DEBUG_MODE = False  # 开启后会打印详细日志