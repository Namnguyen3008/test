"""Citation-gated lexical runtime used by the emergency-first agent graph.

The persistent pgvector retriever can replace this adapter without changing the
graph contract. Until that infrastructure is verified, this adapter provides a
safe lexical degradation over retrieval-eligible catalog rows only.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol, cast

from services.retrieval import GeminiQueryEmbeddingGateway, PostgresHybridRetriever
from services.retrieval.registry import (
    CitationRegistry,
    DataMode,
    candidate_from_dataset_row,
    retrieval_eligibility,
)
from src.config import get_settings
from src.persistence.database import get_session_factory

_TOKEN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class RoutingRecord:
    record_id: str
    text: str
    specialty_id: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoutingContext:
    records: tuple[RoutingRecord, ...]
    mode: str
    allowed_specialty_ids: frozenset[str]
    diagnostics: Mapping[str, object] = field(default_factory=dict)

    @property
    def valid_source_ids(self) -> frozenset[str]:
        return frozenset(source_id for record in self.records for source_id in record.source_ids)


class RoutingRetriever(Protocol):
    async def retrieve(self, query: str, *, limit: int = 6) -> RoutingContext: ...


SPECIALTY_CODE_MAP: dict[str, str] = {
    "SP_CARDIOLOGY": "SP_CARDIOLOGY",
    "SP_CARD": "SP_CARDIOLOGY",
    "CARDIOLOGY": "SP_CARDIOLOGY",
    "SP_DERMATOLOGY": "SP_DERMATOLOGY",
    "SP_ENT": "SP_ENT",
    "SP_GASTRO": "SP_GASTRO",
    "SP_GENERAL_MEDICINE": "SP_GENERAL_MEDICINE",
    "SP_INFECTIOUS": "SP_INFECTIOUS",
    "SP_MENTAL_HEALTH": "SP_MENTAL_HEALTH",
    "SP_NEUROLOGY": "SP_NEUROLOGY",
    "SP_OBGYN": "SP_OBGYN",
    "SP_OPHTHALMOLOGY": "SP_OPHTHALMOLOGY",
    "SP_ORTHOPEDICS": "SP_ORTHOPEDICS",
    "SP_PEDIATRICS": "SP_PEDIATRICS",
    "SP_RESPIRATORY": "SP_RESPIRATORY",
    "SP_UROLOGY": "SP_UROLOGY",
    "SP_PED": "SP_PEDIATRICS",
    "SP_RESP": "SP_RESPIRATORY",
    "SP_GENERAL_MED": "SP_GENERAL_MEDICINE",
    "SP_GM": "SP_GENERAL_MEDICINE",
    "GENERAL_MEDICINE": "SP_GENERAL_MEDICINE",
    "SPEC_GENERAL": "SP_GENERAL_MEDICINE",
    "EMERGENCY_MEDICINE": "SP_GENERAL_MEDICINE",
    "HUMAN_TRIAGE": "SP_GENERAL_MEDICINE",
    "K14": "SP_GENERAL_MEDICINE",
    "SP_EM": "SP_GENERAL_MEDICINE",
    "K17": "SP_GENERAL_MEDICINE",
    "SP_NEURO": "SP_NEUROLOGY",
    "SP_MSK": "SP_ORTHOPEDICS",
    "SP_DERM": "SP_DERMATOLOGY",
    "SP_ALLERGY": "SP_DERMATOLOGY",
    "SPEC_ALLERGY_IMMUNOLOGY": "SP_DERMATOLOGY",
    "K13": "SP_DERMATOLOGY",
    "OTOLARYNGOLOGY": "SP_ENT",
    "OPHTHALMOLOGY": "SP_OPHTHALMOLOGY",
    "UROLOGY": "SP_UROLOGY",
    "NEPHROLOGY": "SP_UROLOGY",
    "ENDOCRINOLOGY": "SP_GENERAL_MEDICINE",
    "HEMATOLOGY": "SP_GENERAL_MEDICINE",
    "SP_INF": "SP_INFECTIOUS",
    "K11": "SP_INFECTIOUS",
    "K27": "SP_OBGYN",
    "K15": "SP_MENTAL_HEALTH",
    "K02.1": "SP_GENERAL_MEDICINE",
    "DENTISTRY_ORAL_MAXILLOFACIAL": "SP_GENERAL_MEDICINE",
}

VIETNAMESE_SPECIALTY_NAMES: dict[str, str] = {
    "SP_CARDIOLOGY": "Chuyên khoa Tim mạch",
    "CARDIOLOGY": "Chuyên khoa Tim mạch",
    "CARD": "Chuyên khoa Tim mạch",
    "SP_DERMATOLOGY": "Chuyên khoa Da liễu",
    "DERMATOLOGY": "Chuyên khoa Da liễu",
    "DERM": "Chuyên khoa Da liễu",
    "SP_ENT": "Chuyên khoa Tai Mũi Họng",
    "ENT": "Chuyên khoa Tai Mũi Họng",
    "OTOLARYNGOLOGY": "Chuyên khoa Tai Mũi Họng",
    "EAR_NOSE_THROAT": "Chuyên khoa Tai Mũi Họng",
    "SP_GASTRO": "Chuyên khoa Tiêu hóa",
    "SP_GASTROENTEROLOGY": "Chuyên khoa Tiêu hóa",
    "GASTROENTEROLOGY": "Chuyên khoa Tiêu hóa",
    "GASTRO": "Chuyên khoa Tiêu hóa",
    "SP_GENERAL_MEDICINE": "Chuyên khoa Nội tổng quát",
    "GENERAL_MEDICINE": "Chuyên khoa Nội tổng quát",
    "GENERAL": "Chuyên khoa Nội tổng quát",
    "SP_INFECTIOUS": "Chuyên khoa Truyền nhiễm",
    "INFECTIOUS": "Chuyên khoa Truyền nhiễm",
    "INFECTIOUS_DISEASE": "Chuyên khoa Truyền nhiễm",
    "INFECTIOUS_DISEASES": "Chuyên khoa Truyền nhiễm",
    "SP_MENTAL_HEALTH": "Chuyên khoa Sức khỏe tâm thần",
    "MENTAL_HEALTH": "Chuyên khoa Sức khỏe tâm thần",
    "PSYCHIATRY": "Chuyên khoa Sức khỏe tâm thần",
    "SP_NEUROLOGY": "Chuyên khoa Nội thần kinh",
    "NEUROLOGY": "Chuyên khoa Nội thần kinh",
    "NEURO": "Chuyên khoa Nội thần kinh",
    "SP_OBGYN": "Chuyên khoa Sản phụ khoa",
    "OBGYN": "Chuyên khoa Sản phụ khoa",
    "OBSTETRICS_GYNECOLOGY": "Chuyên khoa Sản phụ khoa",
    "OBSTETRICS": "Chuyên khoa Sản phụ khoa",
    "GYNECOLOGY": "Chuyên khoa Sản phụ khoa",
    "SP_OPHTHALMOLOGY": "Chuyên khoa Mắt",
    "OPHTHALMOLOGY": "Chuyên khoa Mắt",
    "EYE": "Chuyên khoa Mắt",
    "SP_ORTHOPEDICS": "Chuyên khoa Cơ xương khớp",
    "ORTHOPEDICS": "Chuyên khoa Cơ xương khớp",
    "ORTHOPEDIC": "Chuyên khoa Cơ xương khớp",
    "MSK": "Chuyên khoa Cơ xương khớp",
    "SP_PEDIATRICS": "Chuyên khoa Nhi",
    "PEDIATRICS": "Chuyên khoa Nhi",
    "PEDIATRIC": "Chuyên khoa Nhi",
    "PED": "Chuyên khoa Nhi",
    "SP_RESPIRATORY": "Chuyên khoa Hô hấp",
    "SP_PULMONOLOGY": "Chuyên khoa Hô hấp",
    "PULMONOLOGY": "Chuyên khoa Hô hấp",
    "RESPIRATORY": "Chuyên khoa Hô hấp",
    "RESP": "Chuyên khoa Hô hấp",
    "SP_UROLOGY": "Chuyên khoa Nam học - Tiết niệu",
    "UROLOGY": "Chuyên khoa Nam học - Tiết niệu",
    "NEPHROLOGY": "Chuyên khoa Tiết niệu - Thận",
    "ONCOLOGY": "Chuyên khoa Ung bướu",
    "ALLERGY_IMMUNOLOGY": "Chuyên khoa Dị ứng - Miễn dịch",
}

def get_specialty_name_vi(code: str | None) -> str:
    if not code:
        return "Chuyên khoa Nội tổng quát"
    
    normalized_key = str(code).strip().upper().replace(" ", "_")
    raw_key = normalized_key[3:] if normalized_key.startswith("SP_") else normalized_key
        
    if normalized_key in VIETNAMESE_SPECIALTY_NAMES:
        return VIETNAMESE_SPECIALTY_NAMES[normalized_key]
    if raw_key in VIETNAMESE_SPECIALTY_NAMES:
        return VIETNAMESE_SPECIALTY_NAMES[raw_key]
    
    mapped = SPECIALTY_CODE_MAP.get(normalized_key, SPECIALTY_CODE_MAP.get(raw_key, str(code)))
    if mapped in VIETNAMESE_SPECIALTY_NAMES:
        return VIETNAMESE_SPECIALTY_NAMES[mapped]
        
    clean_name = str(code).replace("SP_", "").replace("SPEC_", "").replace("_", " ").title()
    return f"Chuyên khoa {clean_name}"

VI_STOP_WORDS: set[str] = {
    "tôi", "bị", "có", "từ", "ngày", "nay", "muốn", "cho", "và", "nhưng",
    "rồi", "ở", "trong", "đang", "được", "là", "khi", "lại", "sau", "hơn",
    "mình", "nhà", "ra", "đi", "vào", "thì", "mà", "đã", "các", "những",
    "một", "hai", "ba", "với", "đến", "này", "đó", "hay", "hoặc", "cũng"
}


def _extract_ngrams(text: str) -> list[str]:
    tokens = [t.casefold() for t in _TOKEN.findall(text)]
    unigrams = tokens
    bigrams = [" ".join(tokens[i:i+2]) for i in range(len(tokens)-1)]
    trigrams = [" ".join(tokens[i:i+3]) for i in range(len(tokens)-2)]
    return unigrams + bigrams + trigrams


class CatalogRoutingRetriever:
    """Read-only, PHI-minimized runtime snapshot compiled from the VMEC catalog."""

    def __init__(self, records: tuple[RoutingRecord, ...], specialty_ids: frozenset[str]) -> None:
        self._records = records
        self._specialty_ids = specialty_ids

    @classmethod
    def from_catalog(cls, catalog: Path, *, release_id: str, mode: DataMode) -> CatalogRoutingRetriever:
        if not catalog.is_file():
            return cls((), frozenset())
        connection = sqlite3.connect(f"file:{catalog.resolve().as_posix()}?mode=ro", uri=True)
        try:
            release = connection.execute(
                "SELECT status FROM dataset_releases WHERE release_id=?", (release_id,)
            ).fetchone()
            if release is None or release[0] != "completed":
                return cls((), frozenset())
            ledger = CitationRegistry.from_global_ledger(
                json.loads(raw)
                for (raw,) in connection.execute(
                    "SELECT payload_json FROM global_sources WHERE release_id=?", (release_id,)
                )
            )
            specialty_ids = frozenset(
                specialty_id
                for (raw,) in connection.execute(
                    "SELECT payload_json FROM dataset_rows WHERE release_id=? AND table_name='specialty_reference'",
                    (release_id,),
                )
                if (specialty_id := str(json.loads(raw).get("specialty_code", "")).strip())
            )
            records: list[RoutingRecord] = []
            rows = connection.execute(
                "SELECT row_key,content_hash,payload_json FROM dataset_rows "
                "WHERE release_id=? AND table_name='routing_rows'",
                (release_id,),
            )
            for row_id, content_hash, raw in rows:
                payload = cast(Mapping[str, object], json.loads(raw))
                candidate = candidate_from_dataset_row("routing_rows", row_id, content_hash, payload)
                if not retrieval_eligibility(candidate, mode=mode, citations=ledger).eligible:
                    continue
                raw_code = str(payload.get("primary_specialty_code", "")).strip()
                specialty_id = raw_code if raw_code in specialty_ids else SPECIALTY_CODE_MAP.get(raw_code, raw_code)
                if specialty_id not in specialty_ids:
                    continue
                citations = ledger.resolve(candidate.source_ids)
                records.append(
                    RoutingRecord(
                        record_id=str(row_id),
                        text=candidate.text,
                        specialty_id=specialty_id,
                        source_ids=tuple(citation.source_id for citation in citations),
                    )
                )
            return cls(tuple(records), specialty_ids)
        finally:
            connection.close()

    async def retrieve(self, query: str, *, limit: int = 6) -> RoutingContext:
        query_terms = [t for t in _extract_ngrams(query) if t not in VI_STOP_WORDS]
        if not query_terms:
            query_terms = _extract_ngrams(query)
        scored: list[tuple[float, str, RoutingRecord]] = []
        for record in self._records:
            rec_terms = set(_extract_ngrams(record.text))
            score = 0.0
            matched_terms = 0
            for term in query_terms:
                if term in rec_terms:
                    words = len(term.split())
                    mult = 10.0 if words == 3 else (5.0 if words == 2 else 1.0)
                    score += mult
                    matched_terms += 1
            if score > 0 and matched_terms > 0:
                scored.append((score, record.record_id, record))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return RoutingContext(
            tuple(item[2] for item in scored[:limit]),
            "lexical-only",
            self._specialty_ids,
            {"adapter": "catalog", "grounded_records": min(len(scored), limit)},
        )


class PostgresRoutingRetriever:
    """Graph adapter for the persistent citation-gated hybrid repository."""

    def __init__(self, retriever: PostgresHybridRetriever, gateway: GeminiQueryEmbeddingGateway) -> None:
        self._retriever = retriever
        self._gateway = gateway

    async def retrieve(self, query: str, *, limit: int = 6) -> RoutingContext:
        try:
            result = await self._retriever.retrieve(query, limit=limit)
            records = tuple(
                RoutingRecord(
                    record_id=item.record_id,
                    text=item.text,
                    specialty_id=item.specialty_id,
                    source_ids=tuple(citation.source_id for citation in item.citations),
                )
                for item in result.records
            )
            return RoutingContext(
                records,
                result.mode.value,
                frozenset(record.specialty_id for record in records),
                {"adapter": "postgres", **result.diagnostics},
            )
        except Exception as exc:
            import logging
            logging.getLogger("vmec.routing").warning(
                f"PostgreSQL hybrid retrieval unavailable ({exc}) — falling back to Catalog lexical retrieval"
            )
            settings = get_settings()
            fallback = CatalogRoutingRetriever.from_catalog(
                Path(settings.emergency_catalog_path),
                release_id=settings.emergency_release_id or "vmec-development-v2",
                mode=settings.app_data_mode,
            )
            return await fallback.retrieve(query, limit=limit)

    async def aclose(self) -> None:
        await self._gateway.aclose()


@lru_cache
def get_routing_retriever() -> RoutingRetriever:
    settings = get_settings()
    release_id = (
        settings.emergency_release_id
        or {
            "development": "vmec-development-v2",
            "review": "vmec-review-v2",
            "production": "vmec-production-v1",
        }[settings.app_data_mode]
    )
    postgres_url = settings.database_url.startswith(("postgresql://", "postgresql+"))
    persistent_selected = postgres_url and (
        settings.app_env == "production"
        or settings.retrieval_runtime_mode == "postgres"
        or settings.vmec_persistent_pgvector_verified
    )
    if settings.retrieval_runtime_mode == "postgres" and not postgres_url:
        raise RuntimeError("PostgreSQL retrieval was requested without a PostgreSQL DATABASE_URL")
    if persistent_selected and settings.retrieval_runtime_mode != "lexical":
        gateway = GeminiQueryEmbeddingGateway(settings.gemini_api_key.get_secret_value())
        return PostgresRoutingRetriever(
            PostgresHybridRetriever(
                get_session_factory(),
                gateway.embed_query,
                release_id=release_id,
                data_mode=settings.app_data_mode,
                statement_timeout_ms=settings.retrieval_statement_timeout_ms,
                embedding_timeout_seconds=settings.retrieval_embedding_timeout_seconds,
                candidate_limit=settings.retrieval_candidate_limit,
            ),
            gateway,
        )
    return CatalogRoutingRetriever.from_catalog(
        Path(settings.emergency_catalog_path),
        release_id=release_id,
        mode=settings.app_data_mode,
    )
