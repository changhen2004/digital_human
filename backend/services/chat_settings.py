import json
import threading
import uuid
from pathlib import Path


class ChatSettingsError(Exception):
    pass


class ChatSettings:
    def __init__(self, file_path=None):
        project_root = Path(__file__).resolve().parent.parent
        self.file_path = Path(file_path) if file_path else project_root / "data" / "chat_settings.json"
        self.lock = threading.RLock()

    def get(self):
        with self.lock:
            return self._read()

    def save(self, settings):
        with self.lock:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.file_path.with_name(f"{self.file_path.name}.{uuid.uuid4().hex}.tmp")
            try:
                with temp_path.open("w", encoding="utf-8") as file:
                    json.dump(settings, file, ensure_ascii=False, indent=2)
                    file.flush()
                temp_path.replace(self.file_path)
            except OSError as error:
                if temp_path.exists():
                    temp_path.unlink()
                raise ChatSettingsError("对话设置保存失败") from error
            return dict(settings)

    def _read(self):
        defaults = {
            "platformId": "",
            "modelId": "",
            "summaryPlatformId": "",
            "summaryModelId": "",
            "embeddingPlatformId": "",
            "embeddingModelId": "",
            "temperature": 0.7,
            "topP": 0.9,
            "maxTokens": 2000,
            "activeCategories": [],
        }
        if not self.file_path.exists():
            return defaults
        try:
            with self.file_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError) as error:
            raise ChatSettingsError("对话设置文件读取失败或格式损坏") from error
        if not isinstance(data, dict):
            raise ChatSettingsError("对话设置文件格式不正确")
        return {**defaults, **data}
