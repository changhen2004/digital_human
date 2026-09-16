# modules/memory.py
# 记忆系统模块 - 对话总结、向量化、记忆召回

import os
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from typing import List, Dict
from langchain_community.vectorstores import Chroma
from rich.console import Console
from rich.table import Table
from services.model_clients import chat_completion
import config

console = Console()


class MemorySystem:
    """记忆系统"""

    def __init__(self, summary_model_config=None, embed_model=None, data_dir=None):
        # data_dir 不为空时使用该用户自己的数据库和记忆向量库
        self.db_path = os.path.join(data_dir, "memories.db") if data_dir else config.MEMORY_DB_PATH
        self.chroma_dir = os.path.join(data_dir, "chroma_db_memories") if data_dir else config.CHROMA_DB_DIR + "_memories"
        self.summary_model_config = summary_model_config
        self.embed_model = embed_model
        self._init_database()
        self.memory_vectorstore = None
        self._load_memory_vectorstore()

    def set_model_configs(self, summary_model_config=None, embed_model=None):
        self.summary_model_config = summary_model_config
        self.embed_model = embed_model
        self.memory_vectorstore = None
        self._load_memory_vectorstore()

    def _init_database(self):
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                message_range TEXT,
                vectorized INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                summarized INTEGER DEFAULT 0,
                hidden INTEGER DEFAULT 0
            )
        """)
        connection.commit()
        connection.close()

    def _load_memory_vectorstore(self):
        if self.embed_model is None:
            return
        memory_db_dir = self.chroma_dir
        try:
            if os.path.exists(memory_db_dir) and os.listdir(memory_db_dir):
                self.memory_vectorstore = Chroma(
                    persist_directory=memory_db_dir,
                    embedding_function=self.embed_model,
                    collection_name="memories"
                )
        except Exception as error:
            if config.DEBUG_MODE:
                console.print(f"[yellow]记忆向量库加载失败: {error}[/yellow]")

    def add_message(self, role: str, content: str) -> str:
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        message_id = f"msg_{uuid.uuid4().hex}"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO messages (id, role, content, timestamp, summarized, hidden)
            VALUES (?, ?, ?, ?, 0, 0)
        """, (message_id, role, content, timestamp))
        connection.commit()
        connection.close()
        return message_id

    def get_chat_history(self, limit: int = 100) -> List[Dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit必须是1到200之间的整数")
        connection = sqlite3.connect(self.db_path)
        try:
            rows = connection.execute("""
                SELECT id, role, content, timestamp FROM (
                    SELECT rowid, id, role, content, timestamp
                    FROM messages
                    WHERE role IN ('user', 'assistant')
                    ORDER BY rowid DESC
                    LIMIT ?
                )
                ORDER BY rowid ASC
            """, (limit,)).fetchall()
        finally:
            connection.close()
        return [
            {"id": row[0], "role": row[1], "content": row[2], "timestamp": row[3]}
            for row in rows
        ]

    def clear_chat_history(self):
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT id FROM messages").fetchall()
            message_ids = [row[0] for row in rows]
            connection.execute("DELETE FROM messages")
            connection.commit()
            return {"deletedCount": len(message_ids), "deletedMessageIds": message_ids}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def delete_conversation_turn(self, user_content: str, assistant_content: str) -> bool:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.cursor()
            cursor.execute("""
                SELECT rowid, id FROM messages
                WHERE role = 'assistant' AND content = ?
                ORDER BY rowid DESC
            """, (assistant_content,))
            for assistant_rowid, assistant_id in cursor.fetchall():
                cursor.execute("""
                    SELECT id, role, content FROM messages
                    WHERE rowid < ? ORDER BY rowid DESC LIMIT 1
                """, (assistant_rowid,))
                previous = cursor.fetchone()
                if previous and previous[1] == "user" and previous[2] == user_content:
                    cursor.execute("DELETE FROM messages WHERE id IN (?, ?)", (previous[0], assistant_id))
                    connection.commit()
                    return cursor.rowcount == 2
            connection.rollback()
            return False
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_recent_messages(self, limit: int = 20, include_hidden: bool = False) -> List[Dict]:
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        if include_hidden:
            query = "SELECT * FROM messages ORDER BY timestamp DESC LIMIT ?"
        else:
            query = "SELECT * FROM messages WHERE hidden = 0 ORDER BY timestamp DESC LIMIT ?"
        cursor.execute(query, (limit,))
        rows = cursor.fetchall()
        connection.close()
        messages = []
        for row in rows:
            messages.append({
                "id": row[0], "role": row[1], "content": row[2], "timestamp": row[3],
                "summarized": bool(row[4]), "hidden": bool(row[5])
            })
        return list(reversed(messages))

    def check_and_summarize(self) -> bool:
        if self.summary_model_config is None:
            return False
        messages = self.get_recent_messages(limit=100, include_hidden=False)
        unsummarized = [message for message in messages if not message["summarized"]]
        if len(unsummarized) < config.MEMORY_CONFIG["summarize_trigger"]:
            return False
        to_summarize = unsummarized[:config.MEMORY_CONFIG["summarize_count"]]
        conversation_text = "\n".join(
            f"{'用户' if message['role'] == 'user' else 'AI'}: {message['content']}"
            for message in to_summarize
        )
        prompt = f"""请将以下对话内容总结成一段简洁的记忆，保留关键信息：

{conversation_text}

总结（一段话，100字以内）："""
        try:
            summary = chat_completion(self.summary_model_config, prompt).strip()
            self._save_memory(summary, f"{to_summarize[0]['id']} 到 {to_summarize[-1]['id']}")
            self._mark_messages_summarized([message["id"] for message in to_summarize])
            console.print(f"[green]✓ 已生成记忆: {summary[:50]}...[/green]")
            return True
        except Exception as error:
            console.print(f"[red]✗ 总结失败: {str(error)}[/red]")
            return False

    def _save_memory(self, content: str, message_range: str) -> str:
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        memory_id = f"mem_{uuid.uuid4().hex}"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO memories (id, content, timestamp, message_range, vectorized, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
        """, (memory_id, content, timestamp, message_range, timestamp))
        connection.commit()
        connection.close()
        return memory_id

    def _mark_messages_summarized(self, message_ids: List[str]):
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        for message_id in message_ids:
            cursor.execute("UPDATE messages SET summarized = 1, hidden = 1 WHERE id = ?", (message_id,))
        connection.commit()
        connection.close()

    def auto_vectorize_memories(self):
        if self.embed_model is None:
            return
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        days_ago = (datetime.now() - timedelta(days=config.MEMORY_CONFIG["vectorize_days"])).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("SELECT id, content FROM memories WHERE vectorized = 0 AND created_at < ?", (days_ago,))
        old_memories = cursor.fetchall()
        cursor.execute("""
            SELECT DATE(created_at), COUNT(*) FROM memories WHERE vectorized = 0
            GROUP BY DATE(created_at) HAVING COUNT(*) > ?
        """, (config.MEMORY_CONFIG["vectorize_count"],))
        busy_days = cursor.fetchall()
        to_vectorize = list(old_memories)
        for day, _ in busy_days:
            cursor.execute("""
                SELECT id, content FROM memories WHERE vectorized = 0 AND DATE(created_at) = ?
                ORDER BY created_at ASC LIMIT 3
            """, (day,))
            to_vectorize.extend(cursor.fetchall())
        connection.close()
        to_vectorize = list(set(to_vectorize))
        if not to_vectorize:
            return
        memory_db_dir = self.chroma_dir
        os.makedirs(memory_db_dir, exist_ok=True)
        try:
            from langchain_core.documents import Document
            documents = [Document(page_content=content, metadata={"memory_id": memory_id}) for memory_id, content in to_vectorize]
            if self.memory_vectorstore is None:
                self.memory_vectorstore = Chroma.from_documents(
                    documents=documents, embedding=self.embed_model,
                    persist_directory=memory_db_dir, collection_name="memories"
                )
            else:
                self.memory_vectorstore.add_documents(documents)
            self.memory_vectorstore.persist()
            connection = sqlite3.connect(self.db_path)
            cursor = connection.cursor()
            for memory_id, _ in to_vectorize:
                cursor.execute("UPDATE memories SET vectorized = 1 WHERE id = ?", (memory_id,))
            connection.commit()
            connection.close()
            console.print(f"[green]✓ 已向量化 {len(to_vectorize)} 条记忆[/green]")
        except Exception as error:
            console.print(f"[red]✗ 向量化失败: {str(error)}[/red]")

    def recall_memories(self, query: str) -> Dict:
        result = {"vectorized": [], "recent_text": []}
        if self.embed_model is not None and self.memory_vectorstore:
            try:
                vector_results = self.memory_vectorstore.similarity_search_with_score(
                    query, k=config.MEMORY_CONFIG["recall_vector_top_k"]
                )
                for document, score in vector_results:
                    similarity = 1 - score
                    if similarity >= 0.7:
                        result["vectorized"].append({
                            "content": document.page_content, "similarity": round(similarity, 3)
                        })
            except Exception as error:
                if config.DEBUG_MODE:
                    console.print(f"[yellow]向量记忆召回失败: {error}[/yellow]")
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        cursor.execute("SELECT content FROM memories ORDER BY created_at DESC LIMIT ?", (config.MEMORY_CONFIG["recall_text_count"],))
        rows = cursor.fetchall()
        connection.close()
        result["recent_text"] = [row[0] for row in rows]
        return result

    def clear_all_memories(self):
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        cursor.execute("DELETE FROM memories")
        cursor.execute("DELETE FROM messages")
        connection.commit()
        connection.close()
        import shutil
        memory_db_dir = self.chroma_dir
        if os.path.exists(memory_db_dir):
            shutil.rmtree(memory_db_dir)
        self.memory_vectorstore = None
        console.print("[green]✓ 已清空所有记忆[/green]")

    def show_memory_stats(self):
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        counts = []
        for query in (
            "SELECT COUNT(*) FROM memories",
            "SELECT COUNT(*) FROM memories WHERE vectorized = 1",
            "SELECT COUNT(*) FROM messages",
            "SELECT COUNT(*) FROM messages WHERE hidden = 1",
        ):
            cursor.execute(query)
            counts.append(cursor.fetchone()[0])
        connection.close()
        table = Table(title="记忆系统统计")
        table.add_column("项目", style="cyan")
        table.add_column("数量", style="green")
        for label, count in zip(("总记忆条目", "已向量化", "总消息数", "已隐藏消息"), counts):
            table.add_row(label, str(count))
        console.print(table)


if __name__ == "__main__":
    memory = MemorySystem()
    memory.show_memory_stats()
