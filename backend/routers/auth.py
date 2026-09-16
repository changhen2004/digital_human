from fastapi import APIRouter, Body, Request, Response
from fastapi.responses import JSONResponse

from services.auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    AuthConflictError,
    AuthError,
    AuthUnauthorizedError,
)
from services.workspace import auth_service, claim_legacy_data


def auth_error_response(error: AuthError) -> JSONResponse:
    if isinstance(error, AuthConflictError):
        status_code = 409
    elif isinstance(error, AuthUnauthorizedError):
        status_code = 401
    else:
        status_code = 400
    return JSONResponse({"error": str(error)}, status_code=status_code)


def create_auth_router() -> APIRouter:
    router = APIRouter(prefix="/api/auth")

    def current_user(request: Request):
        token = request.cookies.get(SESSION_COOKIE)
        return auth_service.user_for_token(token) if token else None

    def start_session(response: Response, user: dict):
        response.set_cookie(
            SESSION_COOKIE,
            auth_service.create_session(user["id"]),
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
            path="/",
        )

    @router.post("/register", status_code=201)
    def register(response: Response, data: dict = Body()):
        try:
            user = auth_service.register(data.get("username"), data.get("password"))
        except AuthError as error:
            return auth_error_response(error)
        claim_legacy_data(user["id"])
        start_session(response, user)
        return user

    @router.post("/login")
    def login(response: Response, data: dict = Body()):
        try:
            user = auth_service.login(data.get("username"), data.get("password"))
        except AuthError as error:
            return auth_error_response(error)
        start_session(response, user)
        return user

    @router.post("/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            auth_service.logout(token)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"message": "已退出登录"}

    @router.get("/me")
    def me(request: Request):
        user = current_user(request)
        if user is None:
            return JSONResponse({"error": "未登录"}, status_code=401)
        return user

    return router
