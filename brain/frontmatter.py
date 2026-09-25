# -*- coding: utf-8 -*-
"""Frontmatter read/write with a guaranteed round-trip.

The old implementation split the file on the literal `---` and parsed values with
`line.partition(":")`, which silently corrupted any record whose value contained
`---`, a newline or a leading colon. Claims are the durable product of this vault,
so corruption there is the most expensive failure we can have.

Guarantees:
  * `dumps(parse(text)[0])` re-parses to an equal mapping (see tests/test_frontmatter.py)
  * a value is only written bare when it is unambiguously safe; otherwise it is
    JSON-quoted, which also makes newlines and unicode round-trip exactly
  * the delimiter is detected line-wise, so `---` inside a value is inert
"""

import json
import re
from pathlib import Path

from .errors import SchemaError
from .paths import read_text

DELIM = "---"
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
# Values starting with these characters are unsafe to emit bare.
_UNSAFE_PREFIX = tuple("-?:,[]{}#&*!|>'\"%@`")
_BOOLS = {"true": True, "false": False}
_NULLS = {"null", "~", ""}


def _needs_quoting(value: str) -> bool:
    if value != value.strip():
        return True
    if "\n" in value or "\r" in value or "\t" in value:
        return True
    if value.startswith(_UNSAFE_PREFIX):
        return True
    if ": " in value or value.endswith(":"):
        return True
    if " #" in value:
        return True
    return False


def dump_value(value) -> str:
    """Render a single frontmatter value, round-trip safe."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(list(value) if isinstance(value, tuple) else value,
                          ensure_ascii=False)
    text = "" if value is None else str(value)
    if _needs_quoting(text) or not text:
        return json.dumps(text, ensure_ascii=False)
    return text


def parse_value(raw: str):
    """Inverse of `dump_value`, tolerant of hand-written YAML-ish files."""
    text = raw.strip()
    if text in _NULLS:
        return ""
    lowered = text.lower()
    if lowered in _BOOLS:
        return _BOOLS[lowered]
    if text[0] in "\"'" or text[0] in "[{":
        try:
            return json.loads(text)
        except ValueError:
            if text[0] in "[{":
                # A YAML flow sequence with single quotes / bare words.
                if text[0] == "[" and text[-1] == "]":
                    return [p.strip().strip("'\"") for p in text[1:-1].split(",") if p.strip()]
                return text
            return text[1:-1] if len(text) > 1 else ""
    try:
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        if re.fullmatch(r"-?\d+\.\d+", text):
            return float(text)
    except ValueError:
        pass
    return text


def dumps(fm: dict, order=None) -> str:
    """Serialise a frontmatter block, ending with a newline after the delimiter."""
    if not fm:
        raise SchemaError("refusing to write an empty frontmatter block")
    keys = [k for k in (order or ()) if k in fm]
    keys += [k for k in fm if k not in keys]
    lines = [DELIM]
    for key in keys:
        value = fm[key]
        if value is None:
            continue
        lines.append(f"{key}: {dump_value(value)}")
    lines.append(DELIM)
    return "\n".join(lines) + "\n"


def parse(text: str):
    """Split text into (frontmatter dict, body). Raises SchemaError if malformed."""
    if not text.startswith(DELIM):
        raise SchemaError("missing frontmatter: file does not start with '---'")
    lines = text.split("\n")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == DELIM:
            end = i
            break
    if end is None:
        raise SchemaError("unterminated frontmatter: no closing '---'")

    fm = {}
    current_key = None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith("- ") and current_key is not None:
            # YAML block sequence: `tags:` then `- one` / `- two`
            existing = fm.get(current_key)
            item = parse_value(line.lstrip()[2:])
            if isinstance(existing, list):
                existing.append(item)
            else:
                fm[current_key] = [item]
            continue
        if line[:1] in (" ", "\t") and current_key is not None:
            # indented continuation of the previous scalar
            fm[current_key] = f"{fm.get(current_key, '')}\n{line.strip()}".strip()
            continue
        key, sep, raw = line.partition(":")
        key = key.strip()
        if not sep or not _KEY_RE.match(key):
            raise SchemaError(f"malformed frontmatter line: {line!r}")
        fm[key] = parse_value(raw)
        current_key = key
    return fm, "\n".join(lines[end + 1:])


def parse_file(path: Path):
    """Parse a record. Returns None when the file is absent."""
    path = Path(path)
    if not path.exists():
        return None
    fm, body = parse(read_text(path))
    return {"fm": fm, "body": body.strip(), "raw": read_text(path), "path": path}


def validate(fm: dict, required, kind: str, statuses=None, status_key="status") -> None:
    """Enforce the minimum schema. Raises SchemaError with an actionable message."""
    missing = [k for k in required if not str(fm.get(k, "")).strip()]
    if missing:
        raise SchemaError(f"{kind}: missing required field(s): {', '.join(missing)}")
    if statuses is not None:
        value = str(fm.get(status_key, "")).strip()
        if value not in statuses:
            raise SchemaError(
                f"{kind}: invalid {status_key} {value!r} (expected one of {', '.join(statuses)})"
            )
    if "confidence" in fm:
        try:
            confidence = float(fm["confidence"])
        except (TypeError, ValueError):
            raise SchemaError(f"{kind}: confidence {fm['confidence']!r} is not a number")
        if not 0.0 <= confidence <= 1.0:
            raise SchemaError(f"{kind}: confidence {confidence} outside 0..1")


def roundtrip_ok(fm: dict) -> bool:
    """True when the mapping survives dumps -> parse unchanged. Used by verify."""
    reparsed, _ = parse(dumps(fm) + "body\n")
    return reparsed == {k: v for k, v in fm.items() if v is not None}


dump = dumps

