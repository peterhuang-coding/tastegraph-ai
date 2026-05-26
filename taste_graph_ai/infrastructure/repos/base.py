from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Optional

T = TypeVar("T")


class Repository(ABC, Generic[T]):
    @abstractmethod
    async def get_by_id(self, id: str) -> Optional[T]:
        ...

    @abstractmethod
    async def save(self, entity: T) -> None:
        ...

    @abstractmethod
    async def delete(self, id: str) -> None:
        ...
