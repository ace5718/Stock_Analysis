"""Broker abstraction stub for future live trading (Phase 6)."""
from abc import ABC, abstractmethod


class BrokerEngine(ABC):
    @abstractmethod
    def place_order(self, symbol: str, action: str, quantity: int) -> dict:
        raise NotImplementedError


class FugleBroker(BrokerEngine):
    def place_order(self, symbol: str, action: str, quantity: int) -> dict:
        raise NotImplementedError("尚未實作真實下單")


class MasterlinkBroker(BrokerEngine):
    def place_order(self, symbol: str, action: str, quantity: int) -> dict:
        raise NotImplementedError("尚未實作真實下單")
