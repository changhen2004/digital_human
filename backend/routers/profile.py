from fastapi import APIRouter, Body, Depends

from modules.memory import MemorySystem
from services.user_profile import UserProfile, UserProfileError
from services.workspace import bind_current_user
from routers.errors import profile_error_response


def create_profile_router(user_profile: UserProfile, memory_system: MemorySystem) -> APIRouter:
    router = APIRouter(dependencies=[Depends(bind_current_user)])

    @router.get("/api/user-profile")
    def get_user_profile():
        try:
            return user_profile.get()
        except UserProfileError as error:
            return profile_error_response(error)

    @router.put("/api/user-profile/settings")
    def update_user_profile_settings(data: dict = Body()):
        try:
            return user_profile.update_settings(data.get("autoExtractionEnabled"), data.get("extractionInterval"))
        except UserProfileError as error:
            return profile_error_response(error)

    @router.post("/api/user-profile/extract")
    def extract_user_profile():
        try:
            return user_profile.extract_pending(memory_system.db_path, memory_system.summary_model_config)
        except UserProfileError as error:
            return profile_error_response(error)

    @router.post("/api/user-profile/entries", status_code=201)
    def add_user_profile_entry(data: dict = Body()):
        try:
            return user_profile.add_entry(
                data.get("category"),
                data.get("content"),
                data.get("source"),
                data.get("confidence"),
                data.get("locked"),
            )
        except UserProfileError as error:
            return profile_error_response(error)

    @router.put("/api/user-profile/entries/{entry_id}")
    def update_user_profile_entry(entry_id: str, data: dict = Body()):
        try:
            return user_profile.update_entry(
                entry_id,
                data.get("category"),
                data.get("content"),
                data.get("source"),
                data.get("confidence"),
                data.get("locked"),
            )
        except UserProfileError as error:
            return profile_error_response(error)

    @router.put("/api/user-profile/entries/{entry_id}/lock")
    def lock_user_profile_entry(entry_id: str, data: dict = Body()):
        try:
            return user_profile.set_locked(entry_id, data.get("locked"))
        except UserProfileError as error:
            return profile_error_response(error)

    @router.delete("/api/user-profile/entries/{entry_id}")
    def delete_user_profile_entry(entry_id: str):
        try:
            user_profile.delete_entry(entry_id)
            return {"message": "用户信息已删除"}
        except UserProfileError as error:
            return profile_error_response(error)

    return router
