"""OPC-UA protocol adapter - stub (Use Case 3, roadmap week 5 "OPC-UA stubs").

Real SCADA/PLC integration is out of scope (Ch. 1.7); this adapter defines the contract a
production OPC-UA client (e.g. ``asyncua``) implements:

1. connect to the server endpoint and browse the address space from ``root_node``
2. map discovered node ids to AquaIntel tags (``discover`` -> mapping file)
3. create a subscription; on every data change emit ``{tag, time, value, quality}`` where
   ``quality`` is the OPC-UA StatusCode severity byte (192 = Good)
4. forward batches to ``POST /v1/telemetry/ingest`` (source ``opcua``)
5. optional write-back of setpoints (pump speed, dosing rate) after operator approval

The :class:`SimulatedOpcUaSource` implements the same interface on top of the plant
simulator so the pipeline can be exercised end-to-end without an OPC-UA server.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


@dataclass
class DataChange:
    node_id: str
    tag: str
    time: datetime
    value: float
    quality: int = 192


class OpcUaSource(Protocol):
    def discover(self, root_node: str) -> dict[str, str]: ...
    def subscribe(self, mapping: dict[str, str]) -> Iterator[DataChange]: ...
    def write_setpoint(self, node_id: str, value: float) -> None: ...


class SimulatedOpcUaSource:
    """Exposes simulator tags as OPC-UA style node ids ``ns=2;s=<tag>``."""

    def __init__(self, seed: int = 7) -> None:
        from app.integration.simulator import PlantModel

        now = datetime.now(UTC)
        self.model = PlantModel(now, now, seed=seed, faults=False)

    def discover(self, root_node: str = "ns=2;s=Plant") -> dict[str, str]:
        values = self.model.step(datetime.now(UTC))
        return {f"ns=2;s={tag}": tag for tag in values}

    def subscribe(self, mapping: dict[str, str]) -> Iterator[DataChange]:
        values = self.model.step(datetime.now(UTC))
        now = datetime.now(UTC)
        for node, tag in mapping.items():
            v = values.get(tag)
            if v is not None:
                yield DataChange(node, tag, now, float(v))

    def write_setpoint(self, node_id: str, value: float) -> None:
        raise PermissionError("Setpoint write-back requires an approved optimization schedule")
