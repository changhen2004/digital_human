from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from modules.memory import MemorySystem
from modules.rag import RAGSystem
from services.api_repository import ApiRepository, ApiRepositoryError, ValidationError
from services.chat_settings import ChatSettings, ChatSettingsError
from services.model_clients import OpenAIEmbeddingsAdapter, get_model_config
from services.workspace import bind_current_user
from routers.errors import repository_error_response


def create_settings_router(
    api_repository: ApiRepository,
    chat_settings: ChatSettings,
    rag_system: RAGSystem,
    memory_system: MemorySystem,
) -> APIRouter:
    router = APIRouter(dependencies=[Depends(bind_current_user)])

    def load_optional_model_config(settings, platform_field, model_field):
        try:
            return get_model_config(api_repository, settings.get(platform_field, ""), settings.get(model_field, ""))
        except ApiRepositoryError:
            return None

    def validate_model_selection(data, platform_field, model_field, label, required=False):
        platform_id, model_id = data.get(platform_field, ""), data.get(model_field, "")
        if not isinstance(platform_id, str) or not isinstance(model_id, str):
            raise ValidationError(f"{label}配置格式不正确")
        if bool(platform_id) != bool(model_id):
            raise ValidationError(f"请选择完整的{label}")
        if required and not platform_id:
            raise ValidationError(f"请选择{label}")
        if platform_id:
            api_repository.get_model_config(platform_id, model_id)
        return platform_id, model_id

    def validate_chat_settings(data):
        platform_id, model_id = validate_model_selection(data, "platformId", "modelId", "对话模型", True)
        summary_platform_id, summary_model_id = validate_model_selection(data, "summaryPlatformId", "summaryModelId", "记忆总结模型")
        embedding_platform_id, embedding_model_id = validate_model_selection(data, "embeddingPlatformId", "embeddingModelId", "向量化模型")
        active_categories = data.get("activeCategories", [])
        temperature, top_p, max_tokens = data.get("temperature"), data.get("topP"), data.get("maxTokens")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            raise ValidationError("temperature必须在0到2之间")
        if isinstance(top_p, bool) or not isinstance(top_p, (int, float)) or not 0 <= top_p <= 1:
            raise ValidationError("topP必须在0到1之间")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
            raise ValidationError("maxTokens必须是正整数")
        if not isinstance(active_categories, list) or any(not isinstance(item, str) for item in active_categories):
            raise ValidationError("activeCategories必须是字符串数组")
        available = set(rag_system.get_all_categories())
        return {
            "platformId": platform_id,
            "modelId": model_id,
            "summaryPlatformId": summary_platform_id,
            "summaryModelId": summary_model_id,
            "embeddingPlatformId": embedding_platform_id,
            "embeddingModelId": embedding_model_id,
            "temperature": temperature,
            "topP": top_p,
            "maxTokens": max_tokens,
            "activeCategories": list(dict.fromkeys(item for item in active_categories if item in available)),
        }

    def apply_runtime_model_settings(settings):
        summary_config = load_optional_model_config(settings, "summaryPlatformId", "summaryModelId")
        embedding_config = load_optional_model_config(settings, "embeddingPlatformId", "embeddingModelId")
        embed_model = OpenAIEmbeddingsAdapter(embedding_config) if embedding_config else None
        rag_system.set_embedding_model(embed_model)
        memory_system.set_model_configs(summary_config, embed_model)

    @router.get("/api/chat-settings")
    def get_chat_settings():
        try:
            return chat_settings.get()
        except ChatSettingsError as error:
            return JSONResponse({"error": str(error)}, status_code=500)

    @router.put("/api/chat-settings")
    def update_chat_settings(data: dict = Body()):
        try:
            old = chat_settings.get()
            settings = validate_chat_settings(data)
            changed = old.get("embeddingPlatformId") != settings["embeddingPlatformId"] or old.get("embeddingModelId") != settings["embeddingModelId"]
            saved = chat_settings.save(settings)
            apply_runtime_model_settings(saved)
            result = dict(saved)
            if changed:
                result["message"] = "向量模型已更换，请重新构建知识库索引"
            return result
        except (ApiRepositoryError, ChatSettingsError) as error:
            return repository_error_response(error)

    return router
