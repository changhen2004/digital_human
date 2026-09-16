from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from routers.auth import create_auth_router
from routers.conversation import create_conversation_router
from routers.knowledge import create_knowledge_router
from routers.platforms import create_platforms_router
from routers.profile import create_profile_router
from routers.settings import create_settings_router
from services.workspace import PerUser

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST_DIR = BASE_DIR.parent / "frontend" / "dist"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 这里的服务都由 PerUser 代理，请求进来后按登录用户落到各自的 Workspace
app.include_router(create_auth_router())
app.include_router(create_platforms_router(PerUser("api_repository")))
app.include_router(create_knowledge_router(PerUser("rag_system")))
app.include_router(create_settings_router(PerUser("api_repository"), PerUser("chat_settings"), PerUser("rag_system"), PerUser("memory_system")))
app.include_router(create_profile_router(PerUser("user_profile"), PerUser("memory_system")))
app.include_router(create_conversation_router(
    PerUser("api_repository"),
    PerUser("chat_settings"),
    PerUser("chat_manager"),
    PerUser("memory_system"),
    PerUser("rag_system"),
    PerUser("user_profile"),
))

if FRONTEND_DIST_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST_DIR / "assets"), name="static-assets")


@app.get("/")
def index():
    index_file = FRONTEND_DIST_DIR / "index.html"
    if not index_file.is_file():
        return JSONResponse({"error": "前端尚未构建，请先进入frontend目录执行npm run build"}, status_code=503)
    return StreamingResponse(index_file.open("rb"), media_type="text/html")


@app.get("/favicon.svg")
def frontend_favicon():
    return FileResponse(FRONTEND_DIST_DIR / "favicon.svg")


@app.exception_handler(HTTPException)
def http_error_handler(request: Request, error: HTTPException):
    # 前端统一读 data.error，这里把 HTTPException 的 detail 转成同样的结构
    return JSONResponse({"error": error.detail}, status_code=error.status_code)


@app.get("/api/health")
def health():
    return {"status": "ok", "message": "数字人后端已启动"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5000)
