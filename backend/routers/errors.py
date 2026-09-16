from fastapi.responses import JSONResponse

from services.api_repository import ApiRepositoryError, ConflictError, NotFoundError, UpstreamError, ValidationError
from services.user_profile import UserProfileBusyError, UserProfileError, UserProfileModelError, UserProfileNotFoundError, UserProfileParseError, UserProfileValidationError


def repository_error_response(error: ApiRepositoryError) -> JSONResponse:
    if isinstance(error, ValidationError):
        status_code = 400
    elif isinstance(error, NotFoundError):
        status_code = 404
    elif isinstance(error, ConflictError):
        status_code = 409
    elif isinstance(error, UpstreamError):
        status_code = error.status_code
    else:
        status_code = 500
        print(f"API仓库错误: {type(error).__name__}")
    return JSONResponse({"error": str(error)}, status_code=status_code)


def profile_error_response(error: UserProfileError) -> JSONResponse:
    if isinstance(error, UserProfileValidationError):
        status_code = 400
    elif isinstance(error, UserProfileNotFoundError):
        status_code = 404
    elif isinstance(error, UserProfileBusyError):
        status_code = 409
    elif isinstance(error, (UserProfileParseError, UserProfileModelError)):
        status_code = 502
    else:
        status_code = 500
        print(f"用户信息错误: {type(error).__name__}")
    return JSONResponse({"error": str(error)}, status_code=status_code)


def knowledge_error_response(error: Exception) -> JSONResponse:
    if isinstance(error, FileNotFoundError):
        status_code = 404
    elif isinstance(error, FileExistsError):
        status_code = 409
    elif isinstance(error, (ValueError, RuntimeError)):
        status_code = 400
    else:
        status_code = 500
        print(f"知识库错误: {type(error).__name__}")
    return JSONResponse({"error": str(error)}, status_code=status_code)
