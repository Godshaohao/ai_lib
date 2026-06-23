from __future__ import annotations

from .base import (
    CdlSummaryBuilder,
    CpfSummaryBuilder,
    FormatSummaryBuilder,
    LefSummaryBuilder,
    LibertySummaryBuilder,
    MacroSummaryBuilder,
    PackageSummaryBuilder,
    PortSummaryBuilder,
    SdcSummaryBuilder,
    SpefSummaryBuilder,
    UpfSummaryBuilder,
    VerilogSummaryBuilder,
    WaiverSummaryBuilder,
)


def build_default_summary_builders(config=None):
    return [
        LibertySummaryBuilder(config),
        LefSummaryBuilder(config),
        VerilogSummaryBuilder(config),
        CdlSummaryBuilder(config),
        SdcSummaryBuilder(config),
        UpfSummaryBuilder(config),
        CpfSummaryBuilder(config),
        SpefSummaryBuilder(config),
        PackageSummaryBuilder(config),
        WaiverSummaryBuilder(config),
        MacroSummaryBuilder(config),
        PortSummaryBuilder(config),
    ]


__all__ = [
    "build_default_summary_builders",
    "FormatSummaryBuilder",
    "CdlSummaryBuilder",
    "CpfSummaryBuilder",
    "LefSummaryBuilder",
    "LibertySummaryBuilder",
    "MacroSummaryBuilder",
    "PackageSummaryBuilder",
    "PortSummaryBuilder",
    "SdcSummaryBuilder",
    "SpefSummaryBuilder",
    "UpfSummaryBuilder",
    "VerilogSummaryBuilder",
    "WaiverSummaryBuilder",
]
