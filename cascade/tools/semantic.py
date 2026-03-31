"""Semantic code search using AST chunking with optional Ollama embeddings."""

from __future__ import annotations

import ast
import math
from pathlib import Path
from typing import Any

import httpx

from cascade.tools.base import BaseTool, ToolCapability, ToolResult, ToolScope


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


class SemanticCodeSearchTool(BaseTool):
    """Search Python code chunks semantically with lexical fallback."""

    name = "semantic_code_search"
    description = (
        "Search Python code by semantic intent using AST chunking and optional local embeddings. "
        "Falls back to lexical scoring when embeddings are unavailable."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural language or code query."},
            "path": {"type": "string", "description": "Directory to search. Defaults to project root."},
            "top_k": {"type": "integer", "description": "Maximum results to return. Default is 5."},
        },
        "required": ["query"],
    }
    capabilities = (ToolCapability.READ,)
    scope = ToolScope.FILE
    cache_ttl_seconds = 15

    def __init__(
        self,
        project_root: str = ".",
        base_url: str = "http://localhost:11434",
        embedding_model: str = "nomic-embed-text",
    ):
        self.project_root = Path(project_root).resolve()
        self.base_url = base_url.rstrip("/")
        self.model = embedding_model

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "")
        search_path = Path(kwargs.get("path", ".") or ".")
        top_k = int(kwargs.get("top_k", 5))

        if not query:
            return ToolResult(success=False, error="No semantic query provided")

        if not search_path.is_absolute():
            search_path = self.project_root / search_path
        search_path = search_path.resolve()

        chunks = self._collect_python_chunks(search_path)
        if not chunks:
            return ToolResult(output="No Python code chunks available for semantic search.")

        query_embedding = await self._embed_text(query)
        scored: list[tuple[float, dict[str, str]]] = []

        for chunk in chunks:
            if query_embedding:
                chunk_embedding = await self._embed_text(chunk["content"])
                score = _cosine_similarity(query_embedding, chunk_embedding)
            else:
                score = self._lexical_score(query, chunk["content"], chunk["symbol"])
            scored.append((score, chunk))

        ranked = sorted(scored, key=lambda item: item[0], reverse=True)[:top_k]
        lines = []
        for score, chunk in ranked:
            lines.append(
                f"{chunk['path']}:{chunk['line']} [{chunk['symbol']}] score={score:.3f}\n{chunk['preview']}"
            )
        return ToolResult(output="\n\n".join(lines))

    def _collect_python_chunks(self, search_path: Path) -> list[dict[str, str]]:
        chunks: list[dict[str, str]] = []
        for path in search_path.rglob("*.py"):
            if any(part.startswith(".") for part in path.parts):
                continue
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except Exception:
                continue

            lines = source.splitlines()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    start = max(node.lineno - 1, 0)
                    end = getattr(node, "end_lineno", node.lineno)
                    chunk_lines = lines[start:end]
                    preview = "\n".join(chunk_lines[:6])
                    chunks.append(
                        {
                            "path": str(path.relative_to(self.project_root)),
                            "line": str(node.lineno),
                            "symbol": getattr(node, "name", "<anonymous>"),
                            "content": "\n".join(chunk_lines),
                            "preview": preview,
                        }
                    )
        return chunks

    async def _embed_text(self, text: str) -> list[float]:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                response.raise_for_status()
                data = response.json()
                embedding = data.get("embedding", [])
                return [float(item) for item in embedding]
        except Exception:
            return []

    def _lexical_score(self, query: str, content: str, symbol: str) -> float:
        lowered_query = query.lower()
        haystack = f"{symbol}\n{content}".lower()
        tokens = [token for token in lowered_query.split() if token]
        if not tokens:
            return 0.0
        return sum(1.0 for token in tokens if token in haystack) / len(tokens)
