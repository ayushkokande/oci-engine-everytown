"""Resource_Library loader.

Every ``*.md`` file under ``python_api/resource_library/`` becomes one
labeled entry that is injected, in full, into the recommendation prompt.
Only non-confidential material belongs here; confidential references stay in
the git-ignored ``private/`` or ``04_Reference_Materials/`` folders.

Each file starts with a small front-matter block:

    ---
    id: R1
    title: ...
    domains: PL, FR
    source: ...
    ---
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import API_ROOT

LIBRARY_DIR = API_ROOT / "resource_library"


@dataclass(frozen=True)
class Resource:
    id: str
    title: str
    domains: tuple
    source: str
    body: str


def _parse(path: Path) -> Resource:
    text = path.read_text(encoding="utf-8")
    meta: dict = {}
    body = text
    if text.startswith("---"):
        _, header, body = text.split("---", 2)
        for line in header.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return Resource(
        id=meta.get("id", path.stem),
        title=meta.get("title", path.stem),
        domains=tuple(d.strip() for d in meta.get("domains", "").split(",") if d.strip()),
        source=meta.get("source", ""),
        body=body.strip(),
    )


def load_library(directory: Path = LIBRARY_DIR) -> list[Resource]:
    if not directory.exists():
        return []
    return [_parse(p) for p in sorted(directory.glob("*.md")) if p.name.lower() != "readme.md"]


def render_library(resources: list[Resource]) -> str:
    blocks = []
    for r in resources:
        blocks.append(
            '<resource id="%s" title="%s" domains="%s">\n%s\n</resource>'
            % (r.id, r.title, ",".join(r.domains), r.body))
    return "\n\n".join(blocks)
