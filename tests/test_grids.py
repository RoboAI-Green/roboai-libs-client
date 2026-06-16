import struct

import pytest

from roboai_libs_client import MAX_WAVELENGTH_POINTS, RoboAILIBSClientError, load_wavelength_grid


def make_npy(values: list[float], descr: str = "<f8", version: int = 1) -> bytes:
    """Build a minimal .npy file by hand, like numpy.save would."""
    header = f"{{'descr': '{descr}', 'fortran_order': False, 'shape': ({len(values)},), }}"
    header_bytes = header.encode("latin1") + b"\n"
    if version == 1:
        prefix = b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header_bytes))
    else:
        prefix = b"\x93NUMPY\x02\x00" + struct.pack("<I", len(header_bytes))
    fmt = {"<f8": "d", "<f4": "f", "<i4": "i", "<u2": "H"}[descr]
    return prefix + header_bytes + struct.pack(f"<{len(values)}{fmt}", *values)


def write(tmp_path, name: str, content: str | bytes):
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)
    return path


def test_csv_single_column(tmp_path):
    path = write(tmp_path, "grid.csv", "200.0\n200.5\n201.0\n")
    assert load_wavelength_grid(path) == [200.0, 200.5, 201.0]


def test_txt_whitespace_and_comments(tmp_path):
    path = write(tmp_path, "grid.txt", "# wavelengths in nm\n200.0\n  201.0  # mid\n\n202.0\n")
    assert load_wavelength_grid(path) == [200.0, 201.0, 202.0]


def test_two_column_csv_picks_first_column(tmp_path):
    path = write(tmp_path, "grid.csv", "200.0,0.1\n201.0,0.4\n202.0,0.2\n")
    assert load_wavelength_grid(path) == [200.0, 201.0, 202.0]


def test_header_row_is_skipped(tmp_path):
    path = write(tmp_path, "grid.csv", "wavelength_nm,intensity\n200.0,0.1\n201.0,0.4\n")
    assert load_wavelength_grid(path) == [200.0, 201.0]


def test_semicolon_and_tab_delimiters(tmp_path):
    path = write(tmp_path, "grid.tsv", "200.0;0.1\n201.0\t0.4\n")
    assert load_wavelength_grid(path) == [200.0, 201.0]


def test_single_row_falls_back_to_all_tokens(tmp_path):
    path = write(tmp_path, "grid.csv", "200.0, 201.0, 202.0\n")
    assert load_wavelength_grid(path) == [200.0, 201.0, 202.0]


def test_descending_grid_is_reversed(tmp_path):
    path = write(tmp_path, "grid.csv", "202.0\n201.0\n200.0\n")
    assert load_wavelength_grid(path) == [200.0, 201.0, 202.0]


def test_duplicate_wavelengths_rejected(tmp_path):
    path = write(tmp_path, "grid.csv", "200.0\n201.0\n201.0\n")
    with pytest.raises(RoboAILIBSClientError, match="strictly monotonic"):
        load_wavelength_grid(path)


def test_unordered_grid_rejected(tmp_path):
    path = write(tmp_path, "grid.csv", "200.0\n205.0\n201.0\n")
    with pytest.raises(RoboAILIBSClientError, match="strictly monotonic"):
        load_wavelength_grid(path)


def test_too_few_points_rejected(tmp_path):
    # Text parsing rejects single-value files earlier (no numeric column), so
    # the at-least-2 check is reachable only through the .npy path.
    path = write(tmp_path, "grid.npy", make_npy([200.0]))
    with pytest.raises(RoboAILIBSClientError, match="at least 2"):
        load_wavelength_grid(path)


def test_single_value_text_file_rejected(tmp_path):
    path = write(tmp_path, "grid.csv", "200.0\n")
    with pytest.raises(RoboAILIBSClientError, match="numeric wavelength column"):
        load_wavelength_grid(path)


def test_too_many_points_rejected(tmp_path):
    count = MAX_WAVELENGTH_POINTS + 1
    path = write(tmp_path, "grid.csv", "\n".join(str(200.0 + i * 0.01) for i in range(count)))
    with pytest.raises(RoboAILIBSClientError, match=f"limit is {MAX_WAVELENGTH_POINTS}"):
        load_wavelength_grid(path)


def test_empty_file_rejected(tmp_path):
    path = write(tmp_path, "grid.csv", "# only a comment\n")
    with pytest.raises(RoboAILIBSClientError, match="is empty"):
        load_wavelength_grid(path)


def test_non_numeric_file_rejected(tmp_path):
    path = write(tmp_path, "grid.txt", "hello\nworld\n")
    with pytest.raises(RoboAILIBSClientError, match="numeric wavelength column"):
        load_wavelength_grid(path)


def test_npy_float64(tmp_path):
    path = write(tmp_path, "grid.npy", make_npy([200.0, 200.5, 201.0]))
    assert load_wavelength_grid(path) == [200.0, 200.5, 201.0]


def test_npy_float32(tmp_path):
    path = write(tmp_path, "grid.npy", make_npy([200.0, 200.5, 201.0], descr="<f4"))
    assert load_wavelength_grid(path) == [200.0, 200.5, 201.0]


def test_npy_int_dtypes(tmp_path):
    path = write(tmp_path, "grid.npy", make_npy([200, 201, 202], descr="<i4"))
    assert load_wavelength_grid(path) == [200.0, 201.0, 202.0]


def test_npy_version2_header(tmp_path):
    path = write(tmp_path, "grid.npy", make_npy([200.0, 201.0], version=2))
    assert load_wavelength_grid(path) == [200.0, 201.0]


def test_npy_descending_is_reversed(tmp_path):
    path = write(tmp_path, "grid.npy", make_npy([202.0, 201.0, 200.0]))
    assert load_wavelength_grid(path) == [200.0, 201.0, 202.0]


def test_npy_bad_magic_rejected(tmp_path):
    path = write(tmp_path, "grid.npy", b"not a npy file at all")
    with pytest.raises(RoboAILIBSClientError, match="not a valid .npy"):
        load_wavelength_grid(path)


def test_npy_big_endian_rejected(tmp_path):
    header = b"{'descr': '>f8', 'fortran_order': False, 'shape': (2,), }\n"
    data = b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + b"\x00" * 16
    path = write(tmp_path, "grid.npy", data)
    with pytest.raises(RoboAILIBSClientError, match="big-endian"):
        load_wavelength_grid(path)


def test_npy_unsupported_dtype_rejected(tmp_path):
    header = b"{'descr': '<c16', 'fortran_order': False, 'shape': (2,), }\n"
    data = b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + b"\x00" * 32
    path = write(tmp_path, "grid.npy", data)
    with pytest.raises(RoboAILIBSClientError, match="unsupported dtype"):
        load_wavelength_grid(path)


def test_npy_truncated_rejected(tmp_path):
    path = write(tmp_path, "grid.npy", make_npy([200.0, 201.0, 202.0])[:-8])
    with pytest.raises(RoboAILIBSClientError, match="truncated"):
        load_wavelength_grid(path)


def test_result_feeds_request_model(tmp_path):
    from roboai_libs_client import StaticSpectrumRequest

    path = write(tmp_path, "grid.csv", "200.0\n201.0\n202.0\n")
    grid = load_wavelength_grid(path)
    request = StaticSpectrumRequest(
        elements=["Ni"],
        output_wavelengths_nm=grid,
        output_wavelength_grid_name=path.name,
    )
    payload = request.api_payload()
    assert payload["output_wavelengths_nm"] == grid
    assert payload["output_wavelength_grid_name"] == "grid.csv"
