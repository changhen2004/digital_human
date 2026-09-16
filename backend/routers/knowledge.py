from fastapi import APIRouter, Body, Depends, File, UploadFile

from modules.rag import RAGSystem
from services.workspace import bind_current_user
from routers.errors import knowledge_error_response


def create_knowledge_router(rag_system: RAGSystem) -> APIRouter:
    router = APIRouter(dependencies=[Depends(bind_current_user)])

    @router.get("/api/knowledge-bases")
    def get_knowledge_bases():
        try:
            return {"categories": rag_system.get_categories_info()}
        except Exception as error:
            return knowledge_error_response(error)

    @router.post("/api/knowledge-bases", status_code=201)
    def create_knowledge_base(data: dict = Body()):
        try:
            rag_system.create_category(data.get("name"))
            return {"message": "知识库分类已创建"}
        except Exception as error:
            return knowledge_error_response(error)

    @router.post("/api/knowledge-bases/{category}/files", status_code=201)
    def upload_knowledge_file(category: str, file: UploadFile = File()):
        try:
            if not file.filename:
                raise ValueError("请选择TXT文件")
            saved_name = rag_system.save_txt_file(category, file.filename, file)
            return {"message": "TXT文件上传成功", "filename": saved_name}
        except Exception as error:
            return knowledge_error_response(error)

    @router.post("/api/knowledge-bases/{category}/rebuild")
    def rebuild_knowledge_base(category: str):
        try:
            rag_system.rebuild_category(category)
            return {"message": "知识库索引构建完成"}
        except Exception as error:
            return knowledge_error_response(error)

    @router.delete("/api/knowledge-bases/{category}/files/{filename}")
    def delete_knowledge_file(category: str, filename: str):
        try:
            rag_system.delete_txt_file(category, filename)
            return {"message": "TXT文件已删除"}
        except Exception as error:
            return knowledge_error_response(error)

    @router.delete("/api/knowledge-bases/{category}")
    def delete_knowledge_base(category: str):
        try:
            rag_system.delete_category(category)
            return {"message": "知识库分类已删除"}
        except Exception as error:
            return knowledge_error_response(error)

    return router
