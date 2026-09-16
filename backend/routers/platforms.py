from fastapi import APIRouter, Body, Depends

from services.api_repository import ApiRepository, ApiRepositoryError, ValidationError
from services.workspace import bind_current_user
from routers.errors import repository_error_response


def create_platforms_router(api_repository: ApiRepository) -> APIRouter:
    router = APIRouter(dependencies=[Depends(bind_current_user)])

    @router.get("/api/platforms")
    def get_platforms():
        try:
            return {"platforms": api_repository.get_platforms()}
        except ApiRepositoryError as error:
            return repository_error_response(error)

    @router.post("/api/platforms", status_code=201)
    def create_platform(data: dict = Body()):
        try:
            return api_repository.create_platform(data.get("name"), data.get("baseUrl"), data.get("apiKey", ""))
        except ApiRepositoryError as error:
            return repository_error_response(error)

    @router.put("/api/platforms/{platform_id}")
    def update_platform(platform_id: str, data: dict = Body()):
        try:
            return api_repository.update_platform(platform_id, data.get("name"), data.get("baseUrl"), data.get("apiKey"), "apiKey" in data)
        except ApiRepositoryError as error:
            return repository_error_response(error)

    @router.delete("/api/platforms/{platform_id}")
    def delete_platform(platform_id: str):
        try:
            api_repository.delete_platform(platform_id)
            return {"message": "API平台已删除"}
        except ApiRepositoryError as error:
            return repository_error_response(error)

    @router.post("/api/platforms/{platform_id}/fetch-models")
    def fetch_platform_models(platform_id: str):
        try:
            return {"models": api_repository.fetch_models(platform_id)["models"]}
        except ApiRepositoryError as error:
            return repository_error_response(error)

    @router.post("/api/platforms/{platform_id}/models", status_code=201)
    def add_platform_model(platform_id: str, data: dict = Body()):
        try:
            return api_repository.add_model(platform_id, data.get("name"))
        except ApiRepositoryError as error:
            return repository_error_response(error)

    @router.put("/api/platforms/{platform_id}/models/{model_id}")
    def update_platform_model(platform_id: str, model_id: str, data: dict = Body()):
        try:
            if "name" not in data and "enabled" not in data:
                raise ValidationError("至少提供一个可修改字段")
            return api_repository.update_model(platform_id, model_id, data.get("name"), data.get("enabled"), "name" in data, "enabled" in data)
        except ApiRepositoryError as error:
            return repository_error_response(error)

    @router.delete("/api/platforms/{platform_id}/models/{model_id}")
    def delete_platform_model(platform_id: str, model_id: str):
        try:
            api_repository.delete_model(platform_id, model_id)
            return {"message": "模型已删除"}
        except ApiRepositoryError as error:
            return repository_error_response(error)

    @router.post("/api/platforms/{platform_id}/test")
    def test_platform(platform_id: str):
        try:
            api_repository.test_connection(platform_id)
            return {"success": True, "message": "连接成功"}
        except ApiRepositoryError as error:
            return repository_error_response(error)

    return router
