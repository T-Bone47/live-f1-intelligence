"""Providers package: vendor adapters live here; canonical events flow out."""

from app.providers.base import Capabilities, Channel, DataProvider, RawItem
from app.providers.fastf1.provider import FastF1Provider
from app.providers.f1db_provider import F1DBProvider
from app.providers.jolpica import JolpicaClient, JolpicaProvider
from app.providers.openf1 import OpenF1Client, OpenF1Provider
from app.providers.replay import ReplayProvider
from app.providers.signalr import SignalRLiveProvider

__all__ = [
    "Capabilities",
    "Channel",
    "DataProvider",
    "FastF1Provider",
    "F1DBProvider",
    "JolpicaClient",
    "JolpicaProvider",
    "OpenF1Client",
    "OpenF1Provider",
    "RawItem",
    "ReplayProvider",
    "SignalRLiveProvider",
]
