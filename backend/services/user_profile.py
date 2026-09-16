import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from services.model_clients import chat_completion


class UserProfileError(Exception):
    pass


class UserProfileValidationError(UserProfileError):
    pass


class UserProfileNotFoundError(UserProfileError):
    pass


class UserProfileBusyError(UserProfileError):
    pass


class UserProfileModelError(UserProfileError):
    pass


class UserProfileParseError(UserProfileError):
    pass


class UserProfile:
    CATEGORIES = {"basic", "preference", "interest", "habit", "other"}

    def __init__(self, file_path=None, completion_function=None):
        project_root = Path(__file__).resolve().parent.parent
        self.file_path = Path(file_path) if file_path else project_root / "data" / "user_profile.json"
        self.completion_function = completion_function or chat_completion
        self.lock = threading.RLock()
        self.extraction_lock = threading.Lock()

    def get(self):
        with self.lock:
            return self._copy(self._read())

    def get_prompt_contents(self, max_entries=30, max_characters=2000):
        try:
            entries = self.get()["entries"]
        except UserProfileError:
            return []
        contents = []
        length = 0
        for entry in entries[:max_entries]:
            content = entry.get("content", "").strip()
            if not content or length + len(content) > max_characters:
                break
            contents.append(content)
            length += len(content)
        return contents

    def add_entry(self, category, content, source="用户手动添加", confidence=1.0, locked=False):
        entry = self._validate_entry(category, content, source, confidence, locked)
        now = self._now()
        entry.update({"id": str(uuid.uuid4()), "createdAt": now, "updatedAt": now})
        with self.lock:
            data = self._read()
            if self._find_duplicate(data["entries"], entry["category"], entry["content"]):
                raise UserProfileValidationError("相同用户信息已存在")
            data["entries"].append(entry)
            self._save(data)
        return self._copy(entry)

    def update_entry(self, entry_id, category, content, source, confidence, locked):
        updated = self._validate_entry(category, content, source, confidence, locked)
        with self.lock:
            data = self._read()
            entry = self._find_entry(data, entry_id)
            if self._find_duplicate(data["entries"], updated["category"], updated["content"], entry_id):
                raise UserProfileValidationError("相同用户信息已存在")
            entry.update(updated)
            entry["updatedAt"] = self._now()
            self._save(data)
            return self._copy(entry)

    def set_locked(self, entry_id, locked):
        if not isinstance(locked, bool):
            raise UserProfileValidationError("locked必须是布尔值")
        with self.lock:
            data = self._read()
            entry = self._find_entry(data, entry_id)
            entry["locked"] = locked
            entry["updatedAt"] = self._now()
            self._save(data)
            return self._copy(entry)

    def delete_entry(self, entry_id):
        with self.lock:
            data = self._read()
            entry = self._find_entry(data, entry_id)
            data["entries"].remove(entry)
            self._save(data)

    def remove_processed_message_ids(self, message_ids):
        removed_ids = set(message_ids)
        if not removed_ids:
            return 0
        with self.extraction_lock:
            with self.lock:
                data = self._read()
                original_count = len(data["processedMessageIds"])
                data["processedMessageIds"] = [
                    message_id
                    for message_id in data["processedMessageIds"]
                    if message_id not in removed_ids
                ]
                removed_count = original_count - len(data["processedMessageIds"])
                if removed_count:
                    self._save(data)
                return removed_count

    def update_settings(self, auto_enabled, extraction_interval):
        if not isinstance(auto_enabled, bool):
            raise UserProfileValidationError("autoExtractionEnabled必须是布尔值")
        if isinstance(extraction_interval, bool) or not isinstance(extraction_interval, int) or not 3 <= extraction_interval <= 20:
            raise UserProfileValidationError("extractionInterval必须在3到20之间")
        with self.lock:
            data = self._read()
            data["autoExtractionEnabled"] = auto_enabled
            data["extractionInterval"] = extraction_interval
            self._save(data)
            return self._copy(data)

    def get_pending_user_messages(self, db_path):
        processed = set(self.get()["processedMessageIds"])
        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                "SELECT id, content FROM messages WHERE role = 'user' ORDER BY rowid ASC"
            ).fetchall()
        finally:
            connection.close()
        return [{"id": row[0], "content": row[1]} for row in rows if row[0] not in processed]

    def trigger_auto_extraction(self, db_path, model_config):
        try:
            data = self.get()
            if not data["autoExtractionEnabled"] or model_config is None:
                return False
            pending = self.get_pending_user_messages(db_path)
            if len(pending) < data["extractionInterval"] or not self.extraction_lock.acquire(blocking=False):
                return False
            thread = threading.Thread(target=self._background_extract, args=(pending, model_config), daemon=True)
            thread.start()
            return True
        except Exception as error:
            print(f"用户信息自动提取跳过: {type(error).__name__}")
            return False

    def extract_pending(self, db_path, model_config):
        if model_config is None:
            raise UserProfileValidationError("尚未配置记忆总结模型")
        if not self.extraction_lock.acquire(blocking=False):
            raise UserProfileBusyError("用户信息提取正在进行")
        try:
            pending = self.get_pending_user_messages(db_path)
            if not pending:
                return self._result(0, 0, 0, 0, True, "没有待提取的用户消息")
            return self._extract_and_save(pending, model_config)
        finally:
            self.extraction_lock.release()

    def _background_extract(self, pending, model_config):
        try:
            result = self._extract_and_save(pending, model_config)
            print(f"用户信息自动提取: {result['message']}")
        except Exception as error:
            print(f"用户信息自动提取失败: {type(error).__name__}")
        finally:
            self.extraction_lock.release()

    def _extract_and_save(self, messages, model_config):
        original_messages = [message["content"] for message in messages]
        prompt = self._build_extraction_prompt(original_messages)
        try:
            response = self.completion_function(model_config, prompt, temperature=0, top_p=1, max_tokens=1200)
        except Exception as error:
            raise UserProfileModelError("用户信息提取失败") from error
        valid_entries, filtered_count, raw_count = self._parse_response(response, original_messages)
        with self.lock:
            data = self._read()
            added_count, duplicate_count = self._merge_entries(data, valid_entries)
            processed = data["processedMessageIds"]
            processed_set = set(processed)
            for message in messages:
                if message["id"] not in processed_set:
                    processed.append(message["id"])
                    processed_set.add(message["id"])
            self._save(data)
        processed_count = len(messages)
        empty_result = raw_count == 0
        if empty_result:
            message = f"已分析{processed_count}条消息，未发现可保存的稳定信息"
        elif added_count == 0 and duplicate_count > 0 and filtered_count == 0:
            message = f"已分析{processed_count}条消息，信息已存在"
        else:
            parts = [f"已分析{processed_count}条消息"]
            if added_count:
                parts.append(f"新增{added_count}条")
            if duplicate_count:
                parts.append(f"重复{duplicate_count}条")
            if filtered_count:
                parts.append(f"过滤{filtered_count}条")
            if len(parts) == 1:
                parts.append("未新增信息")
            message = "，".join(parts)
        return self._result(processed_count, added_count, duplicate_count, filtered_count, empty_result, message)

    def _build_extraction_prompt(self, messages):
        numbered = "\n".join(f"{index + 1}. {content}" for index, content in enumerate(messages))
        return f"""请从以下用户原始话语中提取稳定的用户信息，只输出严格JSON：
{{"entries":[{{"category":"interest","content":"用户正在学习Flutter","source":"最近在长期学习Flutter","confidence":0.98}}]}}
规则：
1. 只提取用户明确说过的信息，禁止猜测和推断。
2. 只保存稳定事实，短期状态不要保存。
3. 姓名、称呼、专业、职业归入basic；喜恶归入preference；长期学习或关注归入interest；稳定习惯归入habit；其他长期事实归入other。
4. 不提取密码、验证码、API Key、身份证号、银行卡号、精确住址等敏感信息。
5. 不确定时不输出，没有内容时返回{{"entries":[]}}。
6. source必须完整复制某条原始话语，或复制其中连续片段，不得概括或编造。

用户原始话语：
{numbered}"""

    def _parse_response(self, response, original_messages):
        text = response.strip()
        match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1)
        try:
            result = json.loads(text)
        except json.JSONDecodeError as error:
            raise UserProfileParseError("模型返回格式无法解析") from error
        if not isinstance(result, dict) or not isinstance(result.get("entries"), list):
            raise UserProfileParseError("模型返回格式无法解析")
        valid = []
        filtered_count = 0
        for item in result["entries"]:
            if not isinstance(item, dict):
                filtered_count += 1
                continue
            source = item.get("source")
            if not self._source_matches(source, original_messages):
                filtered_count += 1
                continue
            try:
                entry = self._validate_entry(
                    item.get("category"), item.get("content"), source,
                    item.get("confidence"), False,
                )
            except UserProfileValidationError:
                filtered_count += 1
                continue
            if self._contains_sensitive_information(entry["content"]) or self._contains_sensitive_information(entry["source"]):
                filtered_count += 1
                continue
            valid.append(entry)
        return valid, filtered_count, len(result["entries"])

    def _source_matches(self, source, original_messages):
        if not isinstance(source, str) or not source.strip():
            return False
        normalized_source = self._normalize_source(source)
        if not normalized_source:
            return False
        for message in original_messages:
            normalized_message = self._normalize_source(message)
            if normalized_source == normalized_message or normalized_source in normalized_message:
                return True
        return False

    def _merge_entries(self, data, extracted):
        added_count = 0
        duplicate_count = 0
        for item in extracted:
            duplicate = self._find_duplicate(data["entries"], item["category"], item["content"])
            if duplicate:
                duplicate_count += 1
                if not duplicate["locked"] and item["confidence"] > duplicate["confidence"]:
                    duplicate["source"] = item["source"]
                    duplicate["confidence"] = item["confidence"]
                    duplicate["updatedAt"] = self._now()
                continue
            now = self._now()
            data["entries"].append({
                **item, "id": str(uuid.uuid4()), "locked": False,
                "createdAt": now, "updatedAt": now,
            })
            added_count += 1
        return added_count, duplicate_count

    def _validate_entry(self, category, content, source, confidence, locked):
        if category not in self.CATEGORIES:
            raise UserProfileValidationError("用户信息分类不合法")
        if not isinstance(content, str) or not content.strip():
            raise UserProfileValidationError("用户信息内容不能为空")
        if not isinstance(source, str) or not source.strip():
            raise UserProfileValidationError("来源不能为空")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise UserProfileValidationError("confidence必须在0到1之间")
        if not isinstance(locked, bool):
            raise UserProfileValidationError("locked必须是布尔值")
        return {
            "category": category, "content": content.strip(), "source": source.strip(),
            "confidence": float(confidence), "locked": locked,
        }

    def _contains_sensitive_information(self, content):
        patterns = [r"\bsk-[A-Za-z0-9_-]{8,}\b", r"\b\d{6}\b", r"\b\d{17}[0-9Xx]\b", r"\b\d{16,19}\b"]
        return any(re.search(pattern, content) for pattern in patterns)

    def _find_entry(self, data, entry_id):
        for entry in data["entries"]:
            if entry.get("id") == entry_id:
                return entry
        raise UserProfileNotFoundError("用户信息不存在")

    def _find_duplicate(self, entries, category, content, exclude_id=None):
        normalized = self._normalize(content)
        for entry in entries:
            if entry.get("id") != exclude_id and entry.get("category") == category and self._normalize(entry.get("content", "")) == normalized:
                return entry
        return None

    def _read(self):
        if not self.file_path.exists():
            data = self._default_data()
            self._save(data)
            return data
        try:
            with self.file_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError) as error:
            raise UserProfileError("用户信息文件读取失败或格式损坏") from error
        required = {"entries", "autoExtractionEnabled", "extractionInterval", "processedMessageIds"}
        if not isinstance(data, dict) or not required.issubset(data):
            raise UserProfileError("用户信息文件格式不正确")
        if not isinstance(data["entries"], list) or not isinstance(data["processedMessageIds"], list):
            raise UserProfileError("用户信息文件格式不正确")
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
            raise UserProfileError("用户信息文件保存失败") from error

    def _default_data(self):
        return {"entries": [], "autoExtractionEnabled": True, "extractionInterval": 5, "processedMessageIds": []}

    def _result(self, processed, added, duplicate, filtered, empty, message):
        return {
            "success": True, "processedCount": processed, "addedCount": added,
            "duplicateCount": duplicate, "filteredCount": filtered,
            "emptyResult": empty, "message": message,
        }

    def _normalize(self, text):
        return re.sub(r"[\s，。！？、,.!?]", "", text).lower()

    def _normalize_source(self, text):
        return re.sub(r"[。．，,？?！!]+$", "", text.strip())

    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    def _copy(self, value):
        return json.loads(json.dumps(value, ensure_ascii=False))
