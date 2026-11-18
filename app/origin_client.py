from dataclasses import dataclass


@dataclass
class OriginMentorStatus:
    mentor_id: str
    is_active: bool
    available_slots: int


class FakeOriginClient:
    """Simula a consulta em lote ao Sistema de Origem (Etapa 3 do fluxo)."""

    _ORIGIN_STATE: dict[str, OriginMentorStatus] = {
        "m_001": OriginMentorStatus("m_001", is_active=True, available_slots=2),
        "m_002": OriginMentorStatus("m_002", is_active=True, available_slots=1),
        "m_003": OriginMentorStatus("m_003", is_active=True, available_slots=4),
        "m_004": OriginMentorStatus("m_004", is_active=True, available_slots=2),
        "m_005": OriginMentorStatus(
            "m_005", is_active=True, available_slots=0
        ),  # Sem vagas na origem
        "m_006": OriginMentorStatus("m_006", is_active=True, available_slots=2),
        "m_007": OriginMentorStatus("m_007", is_active=True, available_slots=2),
        "m_008": OriginMentorStatus(
            "m_008", is_active=False, available_slots=2
        ),  # Inativo na origem
    }

    def revalidate_batch(self, mentor_ids: list[str]) -> dict[str, OriginMentorStatus]:
        return {
            mid: self._ORIGIN_STATE[mid]
            for mid in mentor_ids
            if mid in self._ORIGIN_STATE
        }
