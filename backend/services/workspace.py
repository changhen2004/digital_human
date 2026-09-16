# services/workspace.py
# 用户工作区 - 每个用户一套独立的数据目录和运行时对象

import shutil
import threading
from contextvars import ContextVar
from pathlib import Path

from fastapi import HTTPException, Request

import config
from modules.chat import ChatManager
from modules.memory import MemorySystem
from modules.rag import RAGSystem
from services.api_repository import ApiRepository, ApiRepositoryError
from services.auth import SESSION_COOKIE, AuthService
from services.chat_settings import ChatSettings, ChatSettingsError
from services.model_clients import OpenAIEmbeddingsAdapter, get_model_config
from services.user_profile import UserProfile

auth_service = AuthService()
WORKSPACES_DIR = Path(config.USERS_DIR)
LEGACY_ITEMS = ("api_repository.json", "chat_settings.json", "user_profile.json", "memories.db", "chroma_db", "chroma_db_memories", "knowledge_base")


class Workspace:
    """一个用户的全部数据和运行时对象，用户之间不共用任何文件和内存对象。"""

    def __init__(self, user_id):
        self.user_id = user_id
        self.data_dir = WORKSPACES_DIR / user_id
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.api_repository = ApiRepository(self.data_dir / "api_repository.json")
        self.chat_settings = ChatSettings(self.data_dir / "chat_settings.json")
        self.user_profile = UserProfile(self.data_dir / "user_profile.json")
        try:
            settings = self.chat_settings.get()
        except ChatSettingsError:
            settings = {}
        summary_config = self._model_config(settings, "summaryPlatformId", "summaryModelId")
        embedding_config = self._model_config(settings, "embeddingPlatformId", "embeddingModelId")
        embed_model = OpenAIEmbeddingsAdapter(embedding_config) if embedding_config else None
        self.rag_system = RAGSystem(embed_model=embed_model, data_dir=self.data_dir)
        self.memory_system = MemorySystem(summary_model_config=summary_config, embed_model=embed_model, data_dir=self.data_dir)
        self.chat_manager = ChatManager(rag_system=self.rag_system, memory_system=self.memory_system, user_profile=self.user_profile)

    def _model_config(self, settings, platform_field, model_field):
        try:
            return get_model_config(self.api_repository, settings.get(platform_field, ""), settings.get(model_field, ""))
        except ApiRepositoryError:
            return None


_workspaces = {}
_workspaces_lock = threading.Lock()
_current_workspace = ContextVar("current_workspace", default=None)


def get_workspace(user_id):
    with _workspaces_lock:
        workspace = _workspaces.get(user_id)
        if workspace is None:
            workspace = Workspace(user_id)
            _workspaces[user_id] = workspace
        return workspace


def current_workspace():
    workspace = _current_workspace.get()
    if workspace is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return workspace


async def bind_current_user(request: Request):
    """路由依赖：校验登录状态，并把本次请求绑定到对应用户的工作区。

    必须是 async，否则 ContextVar 会写在线程池的上下文副本里，后续取不到。
    """
    token = request.cookies.get(SESSION_COOKIE)
    user = auth_service.user_for_token(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    request.state.user = user
    _current_workspace.set(get_workspace(user["id"]))


class PerUser:
    """按当前登录用户分发的服务入口。路由拿到的对象就是它，属性访问时才落到具体用户。"""

    def __init__(self, name):
        self.name = name

    def __getattr__(self, attribute):
        return getattr(getattr(current_workspace(), self.name), attribute)


def claim_legacy_data(user_id):
    """第一个注册的用户接管原来单用户模式留下的数据，避免旧聊天记录凭空消失。"""
    if auth_service.count_users() > 1:
        return
    target = WORKSPACES_DIR / user_id
    target.mkdir(parents=True, exist_ok=True)
    for name in LEGACY_ITEMS:
        source = Path(config.DATA_DIR) / name
        if not source.exists() or (target / name).exists():
            continue
        try:
            shutil.move(str(source), str(target / name))
        except OSError as error:
            print(f"旧数据迁移跳过 {name}: {type(error).__name__}")
