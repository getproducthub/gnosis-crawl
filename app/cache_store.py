"""
Persistent remote cache store for crawl markdown/content search.
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.config import settings

logger = logging.getLogger(__name__)


class RemoteCacheStore:
    """Simple filesystem-backed cache per customer identifier."""

    def __init__(self, customer_identifier: str):
        user_hash = hashlib.sha256(customer_identifier.encode("utf-8")).hexdigest()[:12]
        self.cache_root = Path(settings.storage_path) / "cache" / user_hash
        self.docs_dir = self.cache_root / "docs"
        self.index_path = self.cache_root / "index.json"
        self.docs_dir.mkdir(parents=True, exist_ok=True)

    def upsert(
        self,
        *,
        url: str,
        markdown: str = "",
        markdown_plain: Optional[str] = None,
        content: Optional[str] = None,
        quality: str = "sufficient",
        status_code: Optional[int] = None,
        extractor_version: str = "",
        normalized_url: Optional[str] = None,
        content_hash: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized = normalized_url or self._normalize_url(url)
        content_value = content or markdown_plain or markdown or ""
        hash_value = content_hash or self._hash_content(content_value)
        doc_id = self._doc_id(normalized)
        now_iso = datetime.now(timezone.utc).isoformat()
        domain = urlparse(normalized).netloc.lower()
        word_count = len(content_value.split())

        document = {
            "doc_id": doc_id,
            "url": url,
            "normalized_url": normalized,
            "domain": domain,
            "markdown": markdown or "",
            "markdown_plain": markdown_plain or markdown or "",
            "content": content_value,
            "quality": quality,
            "status_code": status_code,
            "char_count": len(content_value),
            "word_count": word_count,
            "content_hash": hash_value,
            "extractor_version": extractor_version,
            "updated_at": now_iso,
            "metadata": metadata or {},
        }
        self._write_doc(doc_id, document)

        index = self._read_index()
        index[doc_id] = {
            "doc_id": doc_id,
            "url": url,
            "normalized_url": normalized,
            "domain": domain,
            "quality": quality,
            "char_count": len(content_value),
            "word_count": word_count,
            "content_hash": hash_value,
            "status_code": status_code,
            "extractor_version": extractor_version,
            "updated_at": now_iso,
        }
        self._write_index(index)
        return self._with_source_status(index[doc_id])

    def list_docs(
        self,
        *,
        domain: Optional[str] = None,
        quality: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        docs = list(self._read_index().values())
        if domain:
            domain_lower = domain.lower()
            docs = [d for d in docs if d.get("domain") == domain_lower]
        if quality:
            docs = [d for d in docs if d.get("quality") == quality]

        docs.sort(key=lambda d: d.get("updated_at", ""), reverse=True)
        total = len(docs)
        paged = docs[offset: offset + limit]
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "docs": [self._with_source_status(d) for d in paged],
        }

    def get_doc(self, doc_id: str) -> Optional[Dict[str, Any]]:
        path = self.docs_dir / f"{doc_id}.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["source_status"] = self._source_status(payload.get("updated_at"))
            return payload
        except Exception as exc:
            logger.error("Failed to read cache doc %s: %s", doc_id, exc)
            return None

    def search(
        self,
        *,
        query: str,
        domain: Optional[str] = None,
        url_prefix: Optional[str] = None,
        min_similarity: float = 0.4,
        max_results: int = 20,
        quality_in: Optional[List[str]] = None,
        since_ts: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query_lower = (query or "").strip().lower()
        if not query_lower:
            return []

        quality_filter = quality_in or ["sufficient"]
        since_dt = self._parse_since_ts(since_ts)
        matches: List[Dict[str, Any]] = []

        for entry in self._read_index().values():
            if quality_filter and entry.get("quality") not in quality_filter:
                continue
            if domain and entry.get("domain") != domain.lower():
                continue
            normalized_url = entry.get("normalized_url") or entry.get("url") or ""
            if url_prefix and not normalized_url.startswith(url_prefix):
                continue
            if since_dt and not self._is_newer_than(entry.get("updated_at"), since_dt):
                continue

            doc = self.get_doc(entry.get("doc_id", ""))
            if not doc:
                continue

            line_num, snippet, similarity = self._best_line_match(query_lower, doc.get("content", ""))
            if similarity < min_similarity:
                continue

            matches.append({
                "doc_id": entry.get("doc_id"),
                "url": entry.get("url"),
                "similarity": similarity,
                "quality": entry.get("quality"),
                "char_count": entry.get("char_count", 0),
                "snippet": snippet,
                "line_num": line_num,
                "updated_at": entry.get("updated_at"),
                "content_hash": entry.get("content_hash", ""),
                "source_status": self._source_status(entry.get("updated_at")),
            })

        matches.sort(key=lambda m: m.get("similarity", 0), reverse=True)
        return matches[:max_results]

    def prune(self, *, domain: Optional[str] = None, ttl_hours: Optional[int] = None, dry_run: bool = False) -> Dict[str, Any]:
        index = self._read_index()
        cutoff = None
        if ttl_hours:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)

        to_remove: List[str] = []
        for doc_id, meta in index.items():
            if domain and meta.get("domain") != domain.lower():
                continue
            if cutoff and self._is_newer_than(meta.get("updated_at"), cutoff):
                continue
            to_remove.append(doc_id)

        if not dry_run:
            for doc_id in to_remove:
                doc_path = self.docs_dir / f"{doc_id}.json"
                if doc_path.exists():
                    doc_path.unlink()
                index.pop(doc_id, None)
            self._write_index(index)

        return {
            "removed_count": len(to_remove),
            "removed_doc_ids": to_remove,
            "dry_run": dry_run,
        }

    def _read_index(self) -> Dict[str, Dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception as exc:
            logger.warning("Failed to parse cache index %s: %s", self.index_path, exc)
        return {}

    def _write_index(self, index: Dict[str, Dict[str, Any]]) -> None:
        self.index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    def _write_doc(self, doc_id: str, payload: Dict[str, Any]) -> None:
        path = self.docs_dir / f"{doc_id}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _doc_id(self, normalized_url: str) -> str:
        return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()[:24]

    def _hash_content(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        if not parsed.scheme and not parsed.netloc:
            return url
        path = parsed.path.rstrip("/") or "/"
        return parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            path=path,
            query="",
            fragment=""
        ).geturl()

    def _best_line_match(self, query: str, content: str) -> tuple[int, str, float]:
        lines = (content or "").splitlines()
        if not lines:
            return 0, "", 0.0

        best_similarity = 0.0
        best_line_num = 1
        best_line = lines[0]

        for idx, line in enumerate(lines, start=1):
            candidate = line.strip()
            if not candidate:
                continue
            candidate_lower = candidate.lower()
            if query in candidate_lower:
                return idx, candidate[:240], 1.0

            similarity = SequenceMatcher(None, query, candidate_lower).ratio()
            if similarity > best_similarity:
                best_similarity = similarity
                best_line_num = idx
                best_line = candidate

        return best_line_num, best_line[:240], round(best_similarity, 4)

    def _parse_since_ts(self, since_ts: Optional[str]) -> Optional[datetime]:
        if not since_ts:
            return None
        try:
            # unix timestamp
            if since_ts.isdigit():
                return datetime.fromtimestamp(int(since_ts), tz=timezone.utc)
        except Exception:
            pass

        try:
            parsed = datetime.fromisoformat(since_ts.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    def _is_newer_than(self, updated_at: Optional[str], cutoff: datetime) -> bool:
        if not updated_at:
            return False
        try:
            parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed >= cutoff
        except Exception:
            return False

    def _source_status(self, updated_at: Optional[str], stale_after_hours: int = 24) -> str:
        if not updated_at:
            return "stale"
        try:
            updated_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - updated_dt > timedelta(hours=stale_after_hours):
                return "stale"
            return "fresh"
        except Exception:
            return "stale"

    def _with_source_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        copy = dict(payload)
        copy["source_status"] = self._source_status(copy.get("updated_at"))
        return copy
