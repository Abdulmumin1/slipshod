"""Field paths like ``property.locations[LS11 5QT].construction``.

List items are addressed by a key in brackets: locations by postcode. Keys are
normalised (upper case, no spaces) so ``[ls11 5qt]`` and ``[LS115QT]`` match.
"""

from __future__ import annotations

import re

_SEG = re.compile(r"([^.\[\]]+)(?:\[([^\]]*)\])?")


def norm_key(key: str) -> str:
    return re.sub(r"\s+", "", str(key)).upper()


def parse(path: str) -> list[str]:
    """Split into tokens; bracket keys become '[KEY]' tokens."""
    tokens: list[str] = []
    for part in path.strip().split("."):
        m = _SEG.fullmatch(part.strip())
        if not m:
            tokens.append(part.strip().lower())
            continue
        tokens.append(m.group(1).strip().lower())
        if m.group(2) is not None:
            tokens.append(f"[{norm_key(m.group(2))}]")
    return tokens


def normalize(path: str) -> str:
    out = ""
    for t in parse(path):
        out += t if t.startswith("[") or not out else "." + t
    return out


def location_key(loc: dict) -> str:
    return norm_key((loc.get("address") or {}).get("postcode") or "")


def _find(items: list, key: str):
    for item in items:
        if isinstance(item, dict) and location_key(item) == key:
            return item
    raise KeyError(key)


def set_path(obj: dict, path: str, value) -> None:
    tokens = parse(path)
    cur = obj
    for t in tokens[:-1]:
        cur = _find(cur, t[1:-1]) if t.startswith("[") else cur[t]
    cur[tokens[-1]] = value


def flatten(answer: dict) -> dict[str, object]:
    """Scalar leaves keyed by normalised path. Claims, flags and ids are scored separately."""
    out: dict[str, object] = {}

    def walk(prefix: str, v) -> None:
        if isinstance(v, dict):
            for k, sub in v.items():
                walk(f"{prefix}.{k}" if prefix else k, sub)
        elif isinstance(v, list) and v and all(isinstance(i, dict) for i in v):
            for item in v:
                walk(f"{prefix}[{location_key(item)}]", item)
        else:
            out[normalize(prefix)] = v

    for section in ("insured", "policy", "proposal_form", "property", "cyber", "cargo"):
        if answer.get(section) is not None:
            walk(section, answer[section])
    return out


def segments(path: str) -> int:
    return len(parse(path))


def covers(expected: str, predicted: str) -> bool:
    """A predicted flag field satisfies an expected one if it is the same field or more specific."""
    e, p = parse(expected), parse(predicted)
    return p[: len(e)] == e
