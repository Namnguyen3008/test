"""Deterministic emergency screening that always runs before AI services."""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class EmergencyResult:
    emergency: bool
    rule_ids: tuple[str, ...] = ()
    action: str = ""


RULES = {
    "EMERGENCY_BREATHING": ("khong tho duoc", "kho tho du doi", "ngung tho"),
    "EMERGENCY_CHEST": ("dau nguc du doi", "dau that nguc"),
    "EMERGENCY_STROKE": ("meo mieng", "liet nua nguoi", "noi kho dot ngot"),
    "EMERGENCY_BLEEDING": ("chay mau khong cam", "xuat huyet nhieu"),
    "EMERGENCY_UNCONSCIOUS": ("bat tinh", "hon me", "khong danh thuc duoc"),
}
NEGATIONS = ("khong bi", "khong con", "da het", "chua tung")


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFD", text.lower())
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", value)


def screen_emergency(text: str) -> EmergencyResult:
    normalized = _normalize(text)
    matches: list[str] = []
    for rule_id, phrases in RULES.items():
        for phrase in phrases:
            start = normalized.find(phrase)
            if start < 0:
                continue
            prefix = normalized[max(0, start - 24) : start]
            if any(negation in prefix for negation in NEGATIONS):
                continue
            matches.append(rule_id)
            break
    if not matches:
        return EmergencyResult(False)
    return EmergencyResult(
        True,
        tuple(matches),
        "Đây có thể là tình huống khẩn cấp. Hãy gọi 115 hoặc đến cơ sở cấp cứu gần nhất ngay. Không tiếp tục đặt lịch thông thường.",
    )
