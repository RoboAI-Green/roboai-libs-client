"""Load custom output wavelength grids from files.

Mirrors the web simulator's grid upload: the same file formats, the same
parsing rules, and the same validation the API applies server-side, so a grid
that works in the browser works here and vice versa.
"""

from __future__ import annotations

import ast
import math
import re
import struct
from pathlib import Path

from .errors import RoboAILIBSClientError

# Hard cap on output wavelength points, mirroring the platform's
# MAX_OUTPUT_WAVELENGTH_POINTS. Checked locally so an oversized grid fails
# with a clear message instead of an HTTP 422.
MAX_WAVELENGTH_POINTS = 10_000

# struct format characters for the supported little-endian .npy dtypes,
# keyed by "<kind><byte size>" from the dtype descr (e.g. "<f8" -> "f8").
_NPY_STRUCT_FORMATS = {"f8": "d", "f4": "f", "i4": "i", "u4": "I", "i2": "h", "u2": "H"}


def load_wavelength_grid(path: str | Path) -> list[float]:
    """Read a wavelength grid file and return ascending wavelengths in nm.

    Accepts the same formats as the web simulator's grid upload: ``.npy``
    arrays and delimited text (``.csv``/``.txt``/``.tsv``/``.dat`` with
    comma, semicolon, or whitespace separators; ``#`` starts a comment).
    The grid is validated like the API validates ``output_wavelengths_nm``
    (2 to 10,000 finite, strictly monotonic points; a descending grid is
    reversed), so the returned list is ready to pass to ``simulate_static``
    or ``simulate_exposure``.
    """
    file_path = Path(path)
    name = file_path.name
    if file_path.suffix.lower() == ".npy":
        values = _parse_npy(file_path.read_bytes(), name)
    else:
        values = _parse_text(file_path.read_text(encoding="utf-8", errors="replace"), name)
    return _normalize(values, name)


def _numeric_token(token: str) -> float | None:
    try:
        value = float(token)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _parse_text(text: str, name: str) -> list[float]:
    rows: list[list[float | None]] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line:
            rows.append([_numeric_token(token) for token in re.split(r"[\s,;]+", line)])

    if not rows:
        raise RoboAILIBSClientError(f"{name} is empty.")

    # First column with at least 2 numeric values wins, so files with header
    # rows or trailing intensity columns still yield the wavelength column.
    max_cols = max(len(row) for row in rows)
    for col in range(max_cols):
        values = [row[col] for row in rows if col < len(row) and row[col] is not None]
        if len(values) >= 2:
            return values

    # Single-row files have one value per column; fall back to all tokens.
    flat = [value for row in rows for value in row if value is not None]
    if len(flat) >= 2:
        return flat
    raise RoboAILIBSClientError(f"{name} must contain at least one numeric wavelength column.")


def _parse_npy(data: bytes, name: str) -> list[float]:
    if len(data) < 12 or data[:6] != b"\x93NUMPY":
        raise RoboAILIBSClientError(f"{name} is not a valid .npy file.")

    major = data[6]
    if major == 1:
        (header_len,) = struct.unpack_from("<H", data, 8)
        data_offset = 10
    elif major in (2, 3):
        (header_len,) = struct.unpack_from("<I", data, 8)
        data_offset = 12
    else:
        raise RoboAILIBSClientError(f"{name} uses unsupported .npy version {major}.")

    try:
        header = ast.literal_eval(data[data_offset : data_offset + header_len].decode("latin1").strip())
        descr = str(header["descr"])
        shape = tuple(header["shape"])
    except Exception:
        raise RoboAILIBSClientError(f"{name} has an unreadable .npy header.") from None

    dtype_match = re.fullmatch(r"([<>=|])([fiu])(\d+)", descr)
    if not dtype_match:
        raise RoboAILIBSClientError(f"{name} has unsupported dtype {descr}.")
    endian, kind, size = dtype_match.groups()
    if endian == ">":
        raise RoboAILIBSClientError(f"{name} uses big-endian data, not supported.")
    fmt = _NPY_STRUCT_FORMATS.get(f"{kind}{size}")
    if fmt is None:
        raise RoboAILIBSClientError(f"{name} has unsupported dtype {descr}.")

    count = math.prod(shape)
    start = data_offset + header_len
    if len(data) < start + count * int(size):
        raise RoboAILIBSClientError(f"{name} is truncated.")
    return [float(v) for v in struct.unpack_from(f"<{count}{fmt}", data, start)]


def _normalize(values: list[float], name: str) -> list[float]:
    wavelengths = [float(v) for v in values if math.isfinite(v)]

    if len(wavelengths) < 2:
        raise RoboAILIBSClientError(f"{name} must contain at least 2 wavelength points.")
    if len(wavelengths) > MAX_WAVELENGTH_POINTS:
        raise RoboAILIBSClientError(
            f"{name} has {len(wavelengths)} points; limit is {MAX_WAVELENGTH_POINTS}."
        )

    if all(b < a for a, b in zip(wavelengths, wavelengths[1:])):
        wavelengths.reverse()
    if not all(b > a for a, b in zip(wavelengths, wavelengths[1:])):
        raise RoboAILIBSClientError(
            f"{name} must be strictly monotonic with no duplicate wavelengths."
        )
    return wavelengths
