import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests


class ApiRepositoryError(Exception):
    pass


class ValidationError(ApiRepositoryError):
    pass


class NotFoundError(ApiRepositoryError):
    pass


class ConflictError(ApiRepositoryError):
    pass


class UpstreamError(ApiRepositoryError):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


class ApiRepository:
    def __init__(self, file_path=None):
        project_root = Path(__file__).resolve().parent.parent
        self.file_path = Path(file_path) if file_path else project_root / "data" / "api_repository.json"
        self.lock = threading.RLock()

    def get_platforms(self):
        with self.lock:
            data = self._read()
            return [self._public_platform(platform) for platform in data["platforms"]]

    def get_platform(self, platform_id, include_api_key=False):
        with self.lock:
            platform = self._find_platform(self._read(), platform_id)
            if include_api_key:
                return self._copy(platform)
            return self._public_platform(platform)

    def get_model_config(self, platform_id, model_id):
        with self.lock:
            platform = self._find_platform(self._read(), platform_id)
            model = self._find_model(platform, model_id)
            if not model.get("enabled"):
                raise ValidationError("所选模型未启用")
            return {
                "baseUrl": platform["baseUrl"],
                "apiKey": platform.get("apiKey", ""),
                "model": model["name"],
            }

    def create_platform(self, name, base_url, api_key=""):
        name = self._validate_name(name, "平台名称不能为空")
        base_url = self._validate_base_url(base_url)
        api_key = self._validate_api_key(api_key)
        now = self._now()
        platform = {
            "id": str(uuid.uuid4()),
            "name": name,
            "baseUrl": base_url,
            "apiKey": api_key,
            "models": [],
            "createdAt": now,
            "updatedAt": now,
        }

        with self.lock:
            data = self._read()
            data["platforms"].append(platform)
            self._save(data)

        return self._public_platform(platform)

    def update_platform(self, platform_id, name, base_url, api_key=None, update_api_key=False):
        name = self._validate_name(name, "平台名称不能为空")
        base_url = self._validate_base_url(base_url)
        if update_api_key:
            api_key = self._validate_api_key(api_key)

        with self.lock:
            data = self._read()
            platform = self._find_platform(data, platform_id)
            platform["name"] = name
            platform["baseUrl"] = base_url
            if update_api_key:
                platform["apiKey"] = api_key
            platform["updatedAt"] = self._now()
            self._save(data)
            return self._public_platform(platform)

    def delete_platform(self, platform_id):
        with self.lock:
            data = self._read()
            platform = self._find_platform(data, platform_id)
            data["platforms"].remove(platform)
            self._save(data)

    def fetch_models(self, platform_id):
        platform = self.get_platform(platform_id, include_api_key=True)
        model_names = self._request_models(platform, require_model_list=True)

        with self.lock:
            data = self._read()
            current_platform = self._find_platform(data, platform_id)
            existing_names = {model["name"] for model in current_platform["models"]}
            for model_name in model_names:
                if model_name not in existing_names:
                    current_platform["models"].append({
                        "id": str(uuid.uuid4()),
                        "name": model_name,
                        "enabled": True,
                    })
                    existing_names.add(model_name)
            current_platform["updatedAt"] = self._now()
            self._save(data)
            return self._public_platform(current_platform)

    def test_connection(self, platform_id):
        platform = self.get_platform(platform_id, include_api_key=True)
        self._request_models(platform, require_model_list=False)

    def add_model(self, platform_id, name):
        name = self._validate_name(name, "模型名称不能为空")

        with self.lock:
            data = self._read()
            platform = self._find_platform(data, platform_id)
            if any(model["name"] == name for model in platform["models"]):
                raise ConflictError("模型名称已存在")

            model = {
                "id": str(uuid.uuid4()),
                "name": name,
                "enabled": True,
            }
            platform["models"].append(model)
            platform["updatedAt"] = self._now()
            self._save(data)
            return self._copy(model)

    def update_model(
        self,
        platform_id,
        model_id,
        name=None,
        enabled=None,
        update_name=False,
        update_enabled=False,
    ):
        if not update_name and not update_enabled:
            raise ValidationError("至少提供一个可修改字段")
        if update_name:
            name = self._validate_name(name, "模型名称不能为空")
        if update_enabled and not isinstance(enabled, bool):
            raise ValidationError("enabled必须是布尔值")

        with self.lock:
            data = self._read()
            platform = self._find_platform(data, platform_id)
            model = self._find_model(platform, model_id)
            if update_name:
                if any(item["id"] != model_id and item["name"] == name for item in platform["models"]):
                    raise ConflictError("模型名称已存在")
                model["name"] = name
            if update_enabled:
                model["enabled"] = enabled
            platform["updatedAt"] = self._now()
            self._save(data)
            return self._copy(model)

    def delete_model(self, platform_id, model_id):
        with self.lock:
            data = self._read()
            platform = self._find_platform(data, platform_id)
            model = self._find_model(platform, model_id)
            platform["models"].remove(model)
            platform["updatedAt"] = self._now()
            self._save(data)

    def _request_models(self, platform, require_model_list):
        headers = {"Accept": "application/json"}
        if platform["apiKey"]:
            headers["Authorization"] = f"Bearer {platform['apiKey']}"

        try:
            response = requests.get(
                f"{platform['baseUrl']}/models",
                headers=headers,
                timeout=20,
            )
        except requests.Timeout as error:
            raise UpstreamError("API请求超时", 504) from error
        except requests.RequestException as error:
            raise UpstreamError("无法连接API服务", 502) from error

        if response.status_code in (401, 403):
            raise UpstreamError("API认证失败", 502)
        if not response.ok:
            raise UpstreamError("API服务返回错误", 502)

        try:
            result = response.json()
        except ValueError as error:
            raise UpstreamError("API返回格式不正确", 502) from error

        if not require_model_list:
            return []
        if not isinstance(result, dict):
            raise UpstreamError("API返回格式不正确", 502)

        items = result.get("data")
        if not isinstance(items, list):
            raise UpstreamError("API返回格式不正确", 502)

        model_names = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            model_name = item.get("id")
            if not isinstance(model_name, str) or not model_name.strip():
                continue
            model_name = model_name.strip()
            if model_name not in seen:
                model_names.append(model_name)
                seen.add(model_name)
        return model_names

    def _read(self):
        if not self.file_path.exists():
            return {"platforms": []}

        try:
            with self.file_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError) as error:
            raise ApiRepositoryError("API仓库文件读取失败或格式损坏") from error

        if not isinstance(data, dict) or not isinstance(data.get("platforms"), list):
            raise ApiRepositoryError("API仓库文件格式不正确")
        return data

    def _save(self, data):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.file_path.with_name(f"{self.file_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.flush()
            temp_path.replace(self.file_path)
        except OSError as error:
            if temp_path.exists():
                temp_path.unlink()
            raise ApiRepositoryError("API仓库文件保存失败") from error

    def _find_platform(self, data, platform_id):
        for platform in data["platforms"]:
            if platform.get("id") == platform_id:
                return platform
        raise NotFoundError("API平台不存在")

    def _find_model(self, platform, model_id):
        for model in platform["models"]:
            if model.get("id") == model_id:
                return model
        raise NotFoundError("模型不存在")

    def _public_platform(self, platform):
        result = self._copy(platform)
        api_key = result.pop("apiKey", "")
        result["hasApiKey"] = bool(api_key)
        result["apiKeyMask"] = self._mask_api_key(api_key)
        return result

    def _mask_api_key(self, api_key):
        if not api_key:
            return ""
        if len(api_key) <= 4:
            return "****"
        prefix = api_key[:3] if api_key.startswith("sk-") else ""
        return f"{prefix}****{api_key[-4:]}"

    def _validate_name(self, value, error_message):
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(error_message)
        return value.strip()

    def _validate_base_url(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("API Base URL不能为空")
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValidationError("API Base URL必须以http://或https://开头")
        return value

    def _validate_api_key(self, value):
        if not isinstance(value, str):
            raise ValidationError("apiKey必须是字符串")
        return value

    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    def _copy(self, value):
        return json.loads(json.dumps(value, ensure_ascii=False))
