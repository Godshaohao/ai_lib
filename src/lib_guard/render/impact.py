from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class RenderImpact:
    kind: str
    library: str | None = None
    version: str | None = None
    reason: str = ""


def version_detail_impact(library: str, version: str, reason: str) -> RenderImpact:
    return RenderImpact("version_detail", library=library, version=version, reason=reason)


def library_page_impact(library: str, reason: str) -> RenderImpact:
    return RenderImpact("library_page", library=library, reason=reason)


def catalog_index_impact(reason: str) -> RenderImpact:
    return RenderImpact("catalog_index", reason=reason)


def impacts_for_versions(library: str, versions: Iterable[str], reason: str) -> list[RenderImpact]:
    seen: set[str] = set()
    impacts: list[RenderImpact] = []
    for version in versions:
        if not version or version in seen:
            continue
        seen.add(version)
        impacts.append(version_detail_impact(library, version, reason))
    impacts.append(library_page_impact(library, reason))
    impacts.append(catalog_index_impact(reason))
    return impacts


def dedup_impacts(impacts: Iterable[RenderImpact]) -> list[RenderImpact]:
    seen: set[tuple[str, str | None, str | None]] = set()
    out: list[RenderImpact] = []
    for item in impacts:
        key = (item.kind, item.library, item.version)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def serialize_impacts(impacts: Iterable[RenderImpact]) -> list[dict[str, Any]]:
    return [asdict(item) for item in impacts]
