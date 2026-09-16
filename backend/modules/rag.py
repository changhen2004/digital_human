# modules/rag.py
# RAG知识库模块 - 文档管理、向量化、检索

import os
import re
import shutil
from pathlib import Path
from typing import List, Dict, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import TextLoader
from rich.console import Console
from rich.table import Table
import config

console = Console()


class RAGSystem:
    """RAG知识库系统"""

    def __init__(self, embed_model=None, data_dir=None):
        # data_dir 不为空时使用该用户自己的知识库目录和向量库
        self.chroma_dir = str(Path(data_dir) / "chroma_db") if data_dir else config.CHROMA_DB_DIR
        self.knowledge_dir = Path(data_dir) / "knowledge_base" if data_dir else Path(config.KNOWLEDGE_BASE_DIR)
        self.embed_model = embed_model
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.RAG_CONFIG["chunk_size"],
            chunk_overlap=config.RAG_CONFIG["chunk_overlap"],
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
        )
        self.vectorstore = None
        self._load_vectorstore()

    def set_embedding_model(self, embed_model):
        self.embed_model = embed_model
        self.vectorstore = None
        self._load_vectorstore()

    def _load_vectorstore(self):
        if self.embed_model is None:
            return
        try:
            if os.path.exists(self.chroma_dir) and os.listdir(self.chroma_dir):
                self.vectorstore = Chroma(
                    persist_directory=self.chroma_dir,
                    embedding_function=self.embed_model,
                    collection_name="knowledge_base"
                )
                console.print("[green]✓ 知识库加载成功[/green]")
            else:
                console.print("[yellow]⚠ 知识库为空，请先添加文档[/yellow]")
        except Exception as e:
            console.print(f"[red]✗ 知识库加载失败: {str(e)}[/red]")

    def validate_category(self, category: str) -> str:
        if not isinstance(category, str):
            raise ValueError("分类名格式不正确")
        category = category.strip()
        if not category or category in {".", ".."}:
            raise ValueError("分类名不能为空")
        if len(category) > 50 or not re.fullmatch(r"[A-Za-z0-9_\- \u4e00-\u9fff]+", category):
            raise ValueError("分类名仅支持中文、英文、数字、空格、下划线和短横线")
        reserved = {"CON", "PRN", "AUX", "NUL"}
        reserved.update(f"COM{i}" for i in range(1, 10))
        reserved.update(f"LPT{i}" for i in range(1, 10))
        if category.upper() in reserved:
            raise ValueError("分类名不合法")
        return category

    def validate_filename(self, filename: str) -> str:
        if not isinstance(filename, str) or not filename:
            raise ValueError("未选择文件")
        if "/" in filename or "\\" in filename or Path(filename).name != filename:
            raise ValueError("文件名包含非法字符")
        if filename in {".", ".."}:
            raise ValueError("文件名包含非法字符")
        if Path(filename).suffix.lower() != ".txt":
            raise ValueError("仅允许TXT文件")
        if re.search(r'[<>:"|?*\x00-\x1f]', filename):
            raise ValueError("文件名包含非法字符")
        if filename.endswith((" ", ".")):
            raise ValueError("文件名包含非法字符")
        return filename

    def get_category_path(self, category: str) -> Path:
        category = self.validate_category(category)
        root = self.knowledge_dir.resolve()
        path = (root / category).resolve()
        if path.parent != root:
            raise ValueError("分类路径不合法")
        return path

    def get_categories_info(self) -> List[Dict]:
        root = self.knowledge_dir.resolve()
        root.mkdir(parents=True, exist_ok=True)
        categories = []
        for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_dir():
                continue
            try:
                category_id = self.validate_category(path.name)
                if self.get_category_path(category_id) != path.resolve():
                    continue
            except ValueError:
                continue
            files = sorted(
                [item.name for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".txt"],
                key=str.lower,
            )
            categories.append({
                "id": category_id,
                "name": config.KNOWLEDGE_CATEGORIES.get(category_id, category_id),
                "files": files,
                "indexed": self._category_is_indexed(category_id),
            })
        return categories

    def _category_is_indexed(self, category: str) -> bool:
        if self.vectorstore is None:
            return False
        try:
            result = self.vectorstore._collection.get(
                where={"category": category},
                limit=1,
                include=[],
            )
            return bool(result.get("ids"))
        except Exception:
            return False

    def create_category(self, category: str):
        path = self.get_category_path(category)
        if path.exists():
            raise FileExistsError("知识库分类已存在")
        path.mkdir(parents=False)

    def save_txt_file(self, category: str, filename: str, file_storage):
        path = self.get_category_path(category)
        if not path.is_dir():
            raise FileNotFoundError("知识库分类不存在")
        filename = self.validate_filename(filename)
        target = (path / filename).resolve()
        if target.parent != path:
            raise ValueError("文件路径不合法")
        if hasattr(file_storage, "save"):
            file_storage.save(target)
        else:
            content = file_storage.file.read()
            if isinstance(content, str):
                content = content.encode("utf-8")
            target.write_bytes(content)
        return filename

    def delete_txt_file(self, category: str, filename: str):
        path = self.get_category_path(category)
        filename = self.validate_filename(filename)
        target = (path / filename).resolve()
        if target.parent != path:
            raise ValueError("文件路径不合法")
        if not target.is_file():
            raise FileNotFoundError("TXT文件不存在")
        target.unlink()
        self._delete_vectors(category, filename)

    def delete_category(self, category: str):
        category = self.validate_category(category)
        path = self.get_category_path(category)
        if not path.is_dir():
            raise FileNotFoundError("知识库分类不存在")
        self._delete_vectors(category)
        shutil.rmtree(path)

    def _delete_vectors(self, category: str, filename: str = None):
        if self.vectorstore is None:
            return
        if filename:
            where = {"$and": [{"category": category}, {"source_file": filename}]}
        else:
            where = {"category": category}
        self.vectorstore._collection.delete(where=where)
        self.vectorstore.persist()

    def rebuild_category(self, category: str) -> bool:
        if self.embed_model is None:
            raise RuntimeError("尚未配置向量模型，请先在对话设置中选择向量化模型")
        category = self.validate_category(category)
        path = self.get_category_path(category)
        if not path.is_dir():
            raise FileNotFoundError("知识库分类不存在")
        txt_files = sorted(path.glob("*.txt"))
        if not txt_files:
            raise ValueError("该分类下没有TXT文件")

        all_chunks = []
        for file_path in txt_files:
            loader = TextLoader(str(file_path), encoding="utf-8")
            chunks = self.text_splitter.split_documents(loader.load())
            for chunk in chunks:
                chunk.metadata["category"] = category
                chunk.metadata["source_file"] = file_path.name
            all_chunks.extend(chunks)
        if not all_chunks:
            raise ValueError("没有可索引的文档内容")

        self._delete_vectors(category)
        if self.vectorstore is None:
            self.vectorstore = Chroma.from_documents(
                documents=all_chunks,
                embedding=self.embed_model,
                persist_directory=self.chroma_dir,
                collection_name="knowledge_base",
            )
        else:
            self.vectorstore.add_documents(all_chunks)
        self.vectorstore.persist()
        return True

    def add_documents(self, category: str, show_progress: bool = True) -> bool:
        try:
            result = self.rebuild_category(category)
            if result and show_progress:
                console.print(f"[green]✓ {category} 知识库索引完成[/green]")
            return result
        except Exception as e:
            console.print(f"[red]✗ 索引失败: {str(e)}[/red]")
            return False

    def search(self, query: str, category: Optional[str] = None) -> List[Dict]:
        if self.vectorstore is None or self.embed_model is None or not category:
            return []
        try:
            results = self.vectorstore.similarity_search_with_score(
                query,
                k=config.RAG_CONFIG["top_k"],
                filter={"category": category},
            )
            results.sort(key=lambda item: item[1])
            return [
                {
                    "content": doc.page_content,
                    "category": doc.metadata.get("category", "unknown"),
                    "source": doc.metadata.get("source_file", "unknown"),
                    "distance": round(float(distance), 6),
                }
                for doc, distance in results
            ]
        except Exception as e:
            console.print(f"[red]✗ 检索失败: {str(e)}[/red]")
            return []

    def get_all_categories(self) -> List[str]:
        return [category["id"] for category in self.get_categories_info()]

    def rebuild_index(self):
        if self.embed_model is None:
            console.print("[yellow]⚠ 尚未配置向量模型[/yellow]")
            return False
        categories = self.get_all_categories()
        if not categories:
            return False
        return all(self.add_documents(category, show_progress=True) for category in categories)

    def show_knowledge_base_info(self):
        table = Table(title="知识库信息")
        table.add_column("分类", style="cyan")
        table.add_column("文档数量", style="green")
        table.add_column("状态", style="yellow")
        for category in self.get_categories_info():
            table.add_row(
                category["name"],
                str(len(category["files"])),
                "✓ 已索引" if category["indexed"] else "✗ 未索引",
            )
        console.print(table)
        console.print()


if __name__ == "__main__":
    rag = RAGSystem()
    rag.show_knowledge_base_info()
