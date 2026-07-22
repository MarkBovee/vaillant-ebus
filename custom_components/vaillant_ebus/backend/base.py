"""Abstract backend for Vaillant EEBUS integration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import EbusdRegister, WriteResult


class Backend(ABC):
    @abstractmethod
    async def async_connect(self) -> None:
        ...

    @abstractmethod
    async def async_disconnect(self) -> None:
        ...

    @abstractmethod
    async def async_find(self) -> list[EbusdRegister]:
        ...

    @abstractmethod
    async def async_read(self, circuit: str, name: str, field: str = "value") -> str | None:
        ...

    @abstractmethod
    async def async_write(self, circuit: str, name: str, value: str) -> WriteResult:
        ...

    @abstractmethod
    async def async_poll(self, registers: list[tuple[str, str, str]]) -> dict[str, Any]:
        ...

    @property
    @abstractmethod
    def connected(self) -> bool:
        ...

    @property
    @abstractmethod
    def version(self) -> str | None:
        ...
