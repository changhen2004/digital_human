import json

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse

from modules.chat import ChatManager
from modules.memory import MemorySystem
from modules.rag import RAGSystem
from services.api_repository import ApiRepository, ApiRepositoryError
from services.chat_settings import ChatSettings, ChatSettingsError
from services.user_profile import UserProfile, UserProfileError
from services.workspace import bind_current_user
from routers.errors import profile_error_response


def sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def create_conversation_router(
    api_repository: ApiRepository,
    chat_settings: ChatSettings,
    chat_manager: ChatManager,
    memory_system: MemorySystem,
    rag_system: RAGSystem,
    user_profile: UserProfile,
) -> APIRouter:
    router = APIRouter(dependencies=[Depends(bind_current_user)])

    @router.get("/api/chat-history")
    def get_chat_history(limit: int = Query(100)):
        try:
            if not 1 <= limit <= 200:
                raise ValueError
            return {"messages": memory_system.get_chat_history(limit), "limit": limit}
        except ValueError:
            return JSONResponse({"error": "limit必须是1到200之间的整数"}, status_code=400)
        except Exception as error:
            print(f"读取聊天历史失败: {type(error).__name__}")
            return JSONResponse({"error": "读取聊天历史失败"}, status_code=500)

    @router.delete("/api/chat-history")
    def clear_chat_history():
        try:
            deleted = memory_system.clear_chat_history()
        except Exception as error:
            print(f"清空聊天记录失败: {type(error).__name__}")
            return JSONResponse({"error": "清空聊天记录失败"}, status_code=500)
        message = f"已清空{deleted['deletedCount']}条聊天消息"
        try:
            user_profile.remove_processed_message_ids(deleted["deletedMessageIds"])
        except UserProfileError as error:
            print(f"同步用户信息失败: {type(error).__name__}")
            return {"message": message, "warning": "用户信息的已处理记录未能同步清理"}
        return {"message": message}

    @router.delete("/api/chat-turn")
    def delete_chat_turn(data: dict = Body()):
        user_content, assistant_content = data.get("userContent"), data.get("assistantContent")
        if not isinstance(user_content, str) or not user_content or not isinstance(assistant_content, str) or not assistant_content:
            return JSONResponse({"error": "消息内容不能为空"}, status_code=400)
        try:
            if not memory_system.delete_conversation_turn(user_content, assistant_content):
                return JSONResponse({"error": "未找到匹配的对话记录"}, status_code=404)
            return {"message": "对话已删除"}
        except Exception as error:
            print(f"删除对话失败: {type(error).__name__}")
            return JSONResponse({"error": "删除对话失败"}, status_code=500)

    @router.post("/api/chat")
    def chat(data: dict = Body()):
        if not isinstance(data.get("message"), str):
            return JSONResponse({"error": "message必须是字符串"}, status_code=400)
        user_input = data["message"].strip()
        if not user_input:
            return JSONResponse({"error": "消息不能为空"}, status_code=400)
        try:
            settings = chat_settings.get()
            if not settings["platformId"] or not settings["modelId"]:
                return JSONResponse({"error": "请先在对话设置中选择模型"}, status_code=400)
            chat_manager.set_active_categories([item for item in settings.get("activeCategories", []) if item in set(rag_system.get_all_categories())])
            response = chat_manager.chat_with_api(user_input, api_repository.get_model_config(settings["platformId"], settings["modelId"]), settings)
            if response.startswith("对话出错:"):
                return JSONResponse({"error": "生成回复失败"}, status_code=500)
            user_profile.trigger_auto_extraction(memory_system.db_path, memory_system.summary_model_config)
            return {"reply": response}
        except Exception as error:
            print(f"生成回复失败: {type(error).__name__}")
            return JSONResponse({"error": "生成回复失败"}, status_code=500)

    @router.post("/api/chat/stream")
    def chat_stream(data: dict = Body()):
        if not isinstance(data.get("message"), str):
            return JSONResponse({"error": "message必须是字符串"}, status_code=400)
        user_input = data["message"].strip()
        if not user_input:
            return JSONResponse({"error": "消息不能为空"}, status_code=400)
        try:
            settings = chat_settings.get()
            if not settings["platformId"] or not settings["modelId"]:
                return JSONResponse({"error": "请先在对话设置中选择模型"}, status_code=400)
            chat_manager.set_active_categories([item for item in settings.get("activeCategories", []) if item in set(rag_system.get_all_categories())])
            model_config = api_repository.get_model_config(settings["platformId"], settings["modelId"])
        except (ApiRepositoryError, ChatSettingsError):
            return JSONResponse({"error": "请先在对话设置中选择模型"}, status_code=400)

        def generate():
            stream = chat_manager.stream_chat_with_api(user_input, model_config, settings)
            try:
                for content in stream:
                    yield sse_event({"type": "delta", "content": content})
                user_profile.trigger_auto_extraction(memory_system.db_path, memory_system.summary_model_config)
                yield sse_event({"type": "done"})
            except GeneratorExit:
                stream.close()
                raise
            except Exception as error:
                print(f"流式聊天失败: {type(error).__name__}")
                stream.close()
                yield sse_event({"type": "error", "message": "模型请求失败，请检查API配置"})
            finally:
                if hasattr(stream, "close"):
                    stream.close()

        return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router
