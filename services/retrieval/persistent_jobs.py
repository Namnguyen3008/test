"""PostgreSQL checkpoint ledger for safe, resumable dual-embedding backfill."""

from __future__ import annotations

import asyncio
import json
import math
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final, TypeAlias

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from .spaces import EMBEDDING_DIMENSIONS, EmbeddingSpace

Vector: TypeAlias = tuple[float, ...]
DocumentEmbedder: TypeAlias = Callable[[str, EmbeddingSpace], Awaitable[Vector]]

_ELIGIBLE_TABLES: Final = (
    "adult_emergency_phrases",
    "adult_emergency_rules",
    "maternal_emergency_rules",
    "newborn_rules",
    "pediatric_emergency_rules",
    "postpartum_rules",
    "urgent_exclusions",
    "routing_rows",
    "specialty_reference",
    "clarifying_questions",
    "faq",
    "human_support_content",
    "visit_preparation",
)
_TABLE_SQL: Final = ",".join(f"'{value}'" for value in _ELIGIBLE_TABLES)
_ELIGIBILITY_SQL: Final = f"""
    kr.release_id = (
      SELECT CASE
        WHEN :data_mode = 'production' AND :release_id = 'vmec-production-v1' THEN (
          SELECT active_release_id FROM governance_release_routes
          WHERE route_name='vmec-production-v1' AND state='ACTIVE'
        )
        ELSE (SELECT id FROM dataset_releases
              WHERE logical_release_id = :release_id AND status = 'completed')
      END
    )
    AND kr.mode = :data_mode
    AND kr.origin_table IN ({_TABLE_SQL})
    AND coalesce(upper(kr.canonical_status),'') <> 'REJECTED'
    AND coalesce(upper(kr.conflict_status),'') NOT IN ('CONFLICT','REJECTED','BLOCKED')
    AND (
      :data_mode <> 'production'
      OR (
        upper(coalesce(kr.canonical_status,'')) IN ('APPROVED','ACCEPTED','GOLD')
        AND upper(coalesce(kr.review_status,'')) IN ('APPROVED','CLINICALLY_APPROVED')
      )
    )
    AND EXISTS (
      SELECT 1 FROM knowledge_record_sources eligible_krs
      JOIN global_sources eligible_gs ON eligible_gs.id = eligible_krs.source_id
      WHERE eligible_krs.record_id = kr.id
        AND eligible_gs.canonical_url IS NOT NULL
        AND eligible_gs.canonical_url ~ '^(https?://|internal://|//)'
    )
"""

_PREPARE_ITEMS_SQL: Final = text(
    f"""
    INSERT INTO embedding_job_items(job_id,content_hash,status,attempts,available_at)
    SELECT DISTINCT :job_id, kc.content_hash, 'pending', 0, now()
    FROM knowledge_chunks kc
    JOIN knowledge_records kr ON kr.id = kc.record_id
    WHERE {_ELIGIBILITY_SQL}
      AND NOT EXISTS (
        SELECT 1 FROM knowledge_embeddings existing
        WHERE existing.chunk_id = kc.id
          AND existing.model_id = :model_id
          AND existing.dimensions = :dimensions
          AND existing.status = 'ready'
      )
    ON CONFLICT(job_id,content_hash) DO NOTHING
    """
)

_CLAIM_SQL: Final = text(
    f"""
    WITH candidates AS (
      SELECT eji.content_hash
      FROM embedding_job_items eji
      WHERE eji.job_id = :job_id
        AND eji.status IN ('pending','failed')
        AND eji.available_at <= now()
      ORDER BY eji.content_hash
      FOR UPDATE SKIP LOCKED
      LIMIT :batch_limit
    ), claimed AS (
      UPDATE embedding_job_items eji
      SET status='processing', attempts=eji.attempts+1,
          last_attempt_at=now(), error_code=NULL
      FROM candidates
      WHERE eji.job_id=:job_id AND eji.content_hash=candidates.content_hash
      RETURNING eji.content_hash,eji.attempts
    )
    SELECT claimed.content_hash,claimed.attempts,min(kc.normalized_text) AS normalized_text
    FROM claimed
    JOIN knowledge_chunks kc ON kc.content_hash=claimed.content_hash
    JOIN knowledge_records kr ON kr.id=kc.record_id
    WHERE {_ELIGIBILITY_SQL}
    GROUP BY claimed.content_hash,claimed.attempts
    ORDER BY claimed.content_hash
    """
)

_INSERT_EMBEDDINGS_SQL: Final = text(
    f"""
    INSERT INTO knowledge_embeddings(
      chunk_id,model_id,dimensions,embedding,content_hash,status,embedded_at
    )
    SELECT kc.id,:model_id,:dimensions,cast(:embedding AS vector(768)),kc.content_hash,'ready',now()
    FROM knowledge_chunks kc
    JOIN knowledge_records kr ON kr.id=kc.record_id
    WHERE kc.content_hash=:content_hash AND {_ELIGIBILITY_SQL}
    ON CONFLICT(chunk_id,model_id) DO UPDATE SET
      dimensions=excluded.dimensions,
      embedding=excluded.embedding,
      content_hash=excluded.content_hash,
      status='ready',
      embedded_at=excluded.embedded_at
    """
)


@dataclass(frozen=True, slots=True)
class ClaimedEmbedding:
    content_hash: str
    text: str
    attempts: int


@dataclass(frozen=True, slots=True)
class PersistentJobDiagnostics:
    job_id: str
    model_id: str
    pending: int
    processing: int
    failed: int
    complete: int
    quarantined: int
    attempts: int


class PersistentEmbeddingBackfill:
    """One provider call per content hash; one vector row per eligible chunk."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        embed_document: DocumentEmbedder,
        *,
        max_attempts: int = 3,
        retry_base_seconds: int = 30,
        rate_limit_seconds: float = 0.0,
    ) -> None:
        if max_attempts < 1 or retry_base_seconds < 1 or rate_limit_seconds < 0:
            raise ValueError("Invalid persistent backfill retry/rate-limit policy")
        self._factory = factory
        self._embed_document = embed_document
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._rate_limit_seconds = rate_limit_seconds

    @staticmethod
    def job_id(release_id: str, data_mode: str, space: EmbeddingSpace) -> str:
        identity = f"vmec-embedding-backfill:{release_id}:{data_mode}:{space.model_id}:{space.dimensions}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))

    @staticmethod
    def vector_literal(vector: Sequence[float]) -> str:
        if len(vector) != EMBEDDING_DIMENSIONS or any(not math.isfinite(float(value)) for value in vector):
            raise ValueError("Document embedding must contain exactly 768 finite values")
        return "[" + ",".join(format(float(value), ".9g") for value in vector) + "]"

    def prepare(self, *, release_id: str, data_mode: str, space: EmbeddingSpace) -> str:
        if data_mode not in {"development", "review", "production"}:
            raise ValueError("Unsupported backfill data mode")
        job_id = self.job_id(release_id, data_mode, space)
        checkpoint = {
            "release_id": release_id,
            "data_mode": data_mode,
            "model_id": space.model_id,
            "dimensions": space.dimensions,
        }
        parameters = {
            **checkpoint,
            "job_id": job_id,
            "checkpoint": json.dumps(checkpoint, sort_keys=True, separators=(",", ":")),
        }
        with self._factory() as session, session.begin():
            session.execute(
                text(
                    "INSERT INTO embedding_jobs(id,model_id,dimensions,status,checkpoint,created_at,updated_at) "
                    "VALUES(:job_id,:model_id,:dimensions,'running',cast(:checkpoint AS jsonb),now(),now()) "
                    "ON CONFLICT(id) DO UPDATE SET status='running',updated_at=now() "
                    "WHERE embedding_jobs.model_id=excluded.model_id "
                    "AND embedding_jobs.dimensions=excluded.dimensions"
                ),
                parameters,
            )
            session.execute(
                text(
                    "UPDATE embedding_job_items SET status='failed',available_at=now(),error_code='worker_recovered' "
                    "WHERE job_id=:job_id AND status='processing' "
                    "AND last_attempt_at < now() - interval '15 minutes'"
                ),
                {"job_id": job_id},
            )
            session.execute(_PREPARE_ITEMS_SQL, parameters)
        return job_id

    def _claim(
        self,
        *,
        job_id: str,
        release_id: str,
        data_mode: str,
        batch_limit: int,
    ) -> tuple[ClaimedEmbedding, ...]:
        with self._factory() as session, session.begin():
            rows = session.execute(
                _CLAIM_SQL,
                {
                    "job_id": job_id,
                    "release_id": release_id,
                    "data_mode": data_mode,
                    "batch_limit": batch_limit,
                },
            ).mappings()
            return tuple(
                ClaimedEmbedding(str(row["content_hash"]), str(row["normalized_text"]), int(row["attempts"]))
                for row in rows
            )

    def _complete(
        self,
        *,
        job_id: str,
        release_id: str,
        data_mode: str,
        space: EmbeddingSpace,
        item: ClaimedEmbedding,
        vector: Sequence[float],
    ) -> None:
        with self._factory() as session, session.begin():
            session.execute(
                _INSERT_EMBEDDINGS_SQL,
                {
                    "job_id": job_id,
                    "release_id": release_id,
                    "data_mode": data_mode,
                    "model_id": space.model_id,
                    "dimensions": space.dimensions,
                    "content_hash": item.content_hash,
                    "embedding": self.vector_literal(vector),
                },
            )
            session.execute(
                text(
                    "UPDATE embedding_job_items SET status='complete',error_code=NULL "
                    "WHERE job_id=:job_id AND content_hash=:content_hash AND status='processing'"
                ),
                {"job_id": job_id, "content_hash": item.content_hash},
            )

    def _fail(self, *, job_id: str, space: EmbeddingSpace, item: ClaimedEmbedding, exc: Exception) -> None:
        reason_code = type(exc).__name__[:100]
        quarantined = item.attempts >= self._max_attempts
        retry_delay = self._retry_base_seconds * (2 ** max(0, item.attempts - 1))
        with self._factory() as session, session.begin():
            session.execute(
                text(
                    "UPDATE embedding_job_items SET status=:status,error_code=:reason_code,"
                    "available_at=now() + make_interval(secs => :retry_delay) "
                    "WHERE job_id=:job_id AND content_hash=:content_hash AND status='processing'"
                ),
                {
                    "status": "quarantined" if quarantined else "failed",
                    "reason_code": reason_code,
                    "retry_delay": retry_delay,
                    "job_id": job_id,
                    "content_hash": item.content_hash,
                },
            )
            if quarantined:
                session.execute(
                    text(
                        "INSERT INTO embedding_quarantine(job_id,model_id,content_hash,reason_code,safe_metadata) "
                        "VALUES(:job_id,:model_id,:content_hash,:reason_code,cast(:safe_metadata AS jsonb)) "
                        "ON CONFLICT(job_id,model_id,content_hash) DO NOTHING"
                    ),
                    {
                        "job_id": job_id,
                        "model_id": space.model_id,
                        "content_hash": item.content_hash,
                        "reason_code": reason_code,
                        "safe_metadata": json.dumps({"attempts": item.attempts}, separators=(",", ":")),
                    },
                )

    def diagnostics(self, *, job_id: str, model_id: str) -> PersistentJobDiagnostics:
        with self._factory() as session, session.begin():
            rows = session.execute(
                text(
                    "SELECT status,count(*) AS count,coalesce(sum(attempts),0) AS attempts "
                    "FROM embedding_job_items WHERE job_id=:job_id GROUP BY status"
                ),
                {"job_id": job_id},
            ).mappings()
            counts: dict[str, int] = {}
            attempts = 0
            for row in rows:
                counts[str(row["status"])] = int(row["count"])
                attempts += int(row["attempts"])
            unfinished = counts.get("pending", 0) + counts.get("processing", 0) + counts.get("failed", 0)
            status = (
                "running" if unfinished else ("complete_with_quarantine" if counts.get("quarantined") else "complete")
            )
            checkpoint = json.dumps(
                {"counts": dict(sorted(counts.items())), "attempts": attempts},
                sort_keys=True,
                separators=(",", ":"),
            )
            session.execute(
                text(
                    "UPDATE embedding_jobs SET status=:status,checkpoint=checkpoint || cast(:checkpoint AS jsonb),"
                    "updated_at=now() WHERE id=:job_id"
                ),
                {"job_id": job_id, "status": status, "checkpoint": checkpoint},
            )
        return PersistentJobDiagnostics(
            job_id=job_id,
            model_id=model_id,
            pending=counts.get("pending", 0),
            processing=counts.get("processing", 0),
            failed=counts.get("failed", 0),
            complete=counts.get("complete", 0),
            quarantined=counts.get("quarantined", 0),
            attempts=attempts,
        )

    async def run(
        self,
        *,
        release_id: str,
        data_mode: str,
        space: EmbeddingSpace,
        batch_limit: int = 10,
        max_items: int | None = None,
    ) -> PersistentJobDiagnostics:
        if not 1 <= batch_limit <= 100 or (max_items is not None and max_items < 1):
            raise ValueError("Invalid persistent backfill batch/item bound")
        job_id = await asyncio.to_thread(self.prepare, release_id=release_id, data_mode=data_mode, space=space)
        handled = 0
        while max_items is None or handled < max_items:
            remaining = batch_limit if max_items is None else min(batch_limit, max_items - handled)
            claimed = await asyncio.to_thread(
                self._claim,
                job_id=job_id,
                release_id=release_id,
                data_mode=data_mode,
                batch_limit=remaining,
            )
            if not claimed:
                break
            for item in claimed:
                try:
                    vector = await self._embed_document(item.text, space)
                    await asyncio.to_thread(
                        self._complete,
                        job_id=job_id,
                        release_id=release_id,
                        data_mode=data_mode,
                        space=space,
                        item=item,
                        vector=vector,
                    )
                except Exception as exc:
                    await asyncio.to_thread(self._fail, job_id=job_id, space=space, item=item, exc=exc)
                handled += 1
                if self._rate_limit_seconds:
                    await asyncio.sleep(self._rate_limit_seconds)
                if max_items is not None and handled >= max_items:
                    break
        return await asyncio.to_thread(self.diagnostics, job_id=job_id, model_id=space.model_id)
