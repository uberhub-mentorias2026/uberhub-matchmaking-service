from dataclasses import dataclass
import logging
import os
import time

from app.config import ORIGIN_MAX_RETRIES, ORIGIN_TIMEOUT_SECONDS

logger = logging.getLogger("matchmaking.origin_client")


class OriginServiceUnavailableError(RuntimeError):
    """Erro disparado quando o Sistema de Origem falha ou excede o timeout."""


@dataclass
class OriginMentorStatus:
    mentor_id: str
    is_active: bool
    available_slots: int


class ResilientOriginClient:
    """Cliente batch com retry, controle de timeout e circuit breaker."""

    _consecutive_failures: int = 0
    _circuit_open_until: float = 0.0
    _FAILURE_THRESHOLD: int = 3
    _CIRCUIT_RESET_SECONDS: float = 15.0

    _ORIGIN_STATE: dict[str, OriginMentorStatus] = {
        "m_001": OriginMentorStatus("m_001", is_active=True, available_slots=2),
        "m_002": OriginMentorStatus("m_002", is_active=True, available_slots=1),
        "m_003": OriginMentorStatus("m_003", is_active=True, available_slots=4),
        "m_004": OriginMentorStatus("m_004", is_active=True, available_slots=2),
        "m_005": OriginMentorStatus("m_005", is_active=True, available_slots=0),
        "m_006": OriginMentorStatus("m_006", is_active=True, available_slots=2),
        "m_007": OriginMentorStatus("m_007", is_active=True, available_slots=2),
        "m_008": OriginMentorStatus("m_008", is_active=False, available_slots=2),
    }

    def __init__(
        self,
        timeout_seconds: float = ORIGIN_TIMEOUT_SECONDS,
        max_retries: int = ORIGIN_MAX_RETRIES,
        force_failure: bool | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.force_failure = force_failure

    def _is_failure_forced(self) -> bool:
        if self.force_failure is not None:
            return self.force_failure
        return os.getenv("SIMULATE_ORIGIN_FAILURE", "false").lower() == "true"

    def _call_origin_batch(
        self, mentor_ids: list[str]
    ) -> dict[str, OriginMentorStatus]:
        start = time.monotonic()
        if self._is_failure_forced():
            raise OriginServiceUnavailableError("Simulated Origin Service timeout/503.")

        result = {
            mid: self._ORIGIN_STATE[mid]
            for mid in mentor_ids
            if mid in self._ORIGIN_STATE
        }

        elapsed = time.monotonic() - start
        if elapsed > self.timeout_seconds:
            raise OriginServiceUnavailableError(
                f"Origin batch exceeded timeout ({elapsed:.2f}s > {self.timeout_seconds}s)."
            )
        return result

    def revalidate_batch(self, mentor_ids: list[str]) -> dict[str, OriginMentorStatus]:
        if not mentor_ids:
            return {}

        now = time.monotonic()
        if now < self.__class__._circuit_open_until:
            raise OriginServiceUnavailableError(
                "Circuit breaker OPEN for Origin Service."
            )

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                statuses = self._call_origin_batch(mentor_ids)
                self.__class__._consecutive_failures = 0
                return statuses
            except OriginServiceUnavailableError as exc:
                last_exc = exc
                self.__class__._consecutive_failures += 1
                logger.warning(
                    "Falha na revalidação (tentativa %d/%d): %s",
                    attempt,
                    self.max_retries + 1,
                    exc,
                )
                if self.__class__._consecutive_failures >= self._FAILURE_THRESHOLD:
                    self.__class__._circuit_open_until = (
                        time.monotonic() + self._CIRCUIT_RESET_SECONDS
                    )
                    logger.error(
                        "Circuit breaker ABERTO por %.0fs.", self._CIRCUIT_RESET_SECONDS
                    )
                    break
                if attempt <= self.max_retries:
                    time.sleep(0.05 * attempt)

        raise OriginServiceUnavailableError(
            "Origin revalidation failed after retries."
        ) from last_exc

    @classmethod
    def reset_circuit(cls) -> None:
        cls._consecutive_failures = 0
        cls._circuit_open_until = 0.0
