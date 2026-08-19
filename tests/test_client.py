import json

import httpx
import pytest

from roboai_libs_client.auth import load_stored_api_key, save_api_key
from roboai_libs_client import (
    DEFAULT_BASE_URL,
    ExposureRequest,
    RoboAILIBSAPIError,
    RoboAILIBSClient,
    RoboAILIBSClientError,
)


def make_client(handler):
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return RoboAILIBSClient(base_url="https://example.test", http_client=http_client)


def test_list_elements():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/spectra/elements"
        return httpx.Response(200, json={"elements": ["H", "He", "Ni"]})

    client = make_client(handler)

    assert client.list_elements() == ["H", "He", "Ni"]


def test_static_spectrum_normalizes_missing_proportions():
    seen_payload = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/spectra/static"
        seen_payload.update(json.loads(request.content.decode("utf-8")))
        assert seen_payload["temperature_ev"] == 1.0
        assert "te_ev" not in seen_payload
        return httpx.Response(
            200,
            json={
                "wls": [200.0, 200.05],
                "intensity": [1.0, 2.0],
                "lines": [],
                "instrument_profile": "gaussian",
                "fwhm_nm": 0.0,
                "output_grid": {"source": "uniform_resolution", "point_count": 2},
            },
        )

    client = make_client(handler)
    result = client.simulate_static(elements=["Ni", "Fe"])

    assert seen_payload["proportions"] == [0.5, 0.5]
    assert result.wls == [200.0, 200.05]
    assert result.intensity == [1.0, 2.0]


def test_exposure_parses_dynamic_result():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/spectra/exposure"
        return httpx.Response(
            200,
            json={
                "wls": [200.0, 200.05],
                "total_exposure": [3.0, 4.0],
                "snapshot_matrix": [[1.0, 2.0], [2.0, 2.0]],
                "time_vector": [0.0, 1e-7],
                "te_vector": [1.0, 0.9],
                "ne_vector": [1e17, 9e16],
                "length_vector": [0.0, 1e-4],
                "compute_seconds": 0.1,
                "lines": [],
            },
        )

    client = make_client(handler)
    result = client.simulate_exposure(elements=["Ni"])

    assert result.total_exposure == [3.0, 4.0]
    assert len(result.snapshot_matrix) == 2
    assert result.time_vector == [0.0, 1e-7]


def test_dynamic_hdf5_export_returns_bytes():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.url.query.decode()))
        if request.method == "POST" and request.url.path == "/v1/spectra/exposure/jobs":
            assert request.url.query == b"cancel_on_disconnect=false"
            return httpx.Response(202, json={"job_id": "job_123", "status": "queued", "preview": None})
        if request.method == "GET" and request.url.path == "/v1/jobs/job_123":
            return httpx.Response(
                200,
                json={
                    "job_id": "job_123",
                    "status": "completed",
                    "result": {
                        "wls": [200.0],
                        "total_exposure": [1.0],
                        "snapshot_matrix": [[1.0]],
                        "time_vector": [0.0],
                        "te_vector": [1.0],
                        "ne_vector": [1e17],
                        "length_vector": [0.0],
                    },
                },
            )
        if request.method == "GET" and request.url.path == "/v1/jobs/job_123/result":
            assert request.headers["Accept"] == "application/x-hdf5"
            return httpx.Response(200, content=b"Dynamic HDF5 bytes")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = make_client(handler)
    data = client.export_dynamic_hdf5(
        ExposureRequest(elements=["Ni"]),
        poll_interval_s=0.0,
        timeout_s=1.0,
    )

    assert data == b"Dynamic HDF5 bytes"
    assert calls[0] == ("POST", "/v1/spectra/exposure/jobs", "cancel_on_disconnect=false")


def test_request_login_otp_posts_email():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/auth/otp"
        seen.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(202)

    client = make_client(handler)
    client.request_login_otp("user@example.test")

    assert seen == {"email": "user@example.test"}


def test_request_login_otp_surfaces_error_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": "too many requests"})

    client = make_client(handler)

    with pytest.raises(RoboAILIBSAPIError) as exc_info:
        client.request_login_otp("user@example.test")

    assert exc_info.value.status_code == 429
    assert "too many requests" in str(exc_info.value)


def test_save_authenticated_token_validates_then_saves(tmp_path, monkeypatch):
    monkeypatch.delenv("ROBOAI_LIBS_API_KEY", raising=False)
    monkeypatch.delenv("ROBOAI_LIBS_TOKEN", raising=False)
    monkeypatch.setenv("ROBOAI_LIBS_CONFIG_DIR", str(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/auth/token"
        return httpx.Response(200, json={"email": "user@example.test"})

    client = RoboAILIBSClient(
        base_url="https://example.test",
        api_key="tok_new",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    token_file = client.save_authenticated_token()

    assert token_file.exists()
    assert load_stored_api_key() == "tok_new"


def test_save_authenticated_token_skips_save_when_invalid(tmp_path, monkeypatch):
    monkeypatch.delenv("ROBOAI_LIBS_API_KEY", raising=False)
    monkeypatch.delenv("ROBOAI_LIBS_TOKEN", raising=False)
    monkeypatch.setenv("ROBOAI_LIBS_CONFIG_DIR", str(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid or revoked token"})

    client = RoboAILIBSClient(
        base_url="https://example.test",
        api_key="tok_bad",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(RoboAILIBSAPIError):
        client.save_authenticated_token()

    assert load_stored_api_key() is None


def test_hdf5_save_methods_write_files(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/spectra/exposure/jobs":
            return httpx.Response(202, json={"job_id": "job_123", "status": "queued", "preview": None})
        if request.method == "GET" and request.url.path == "/v1/jobs/job_123":
            return httpx.Response(
                200,
                json={
                    "job_id": "job_123",
                    "status": "completed",
                    "result": {
                        "wls": [200.0],
                        "total_exposure": [1.0],
                        "snapshot_matrix": [[1.0]],
                        "time_vector": [0.0],
                        "te_vector": [1.0],
                        "ne_vector": [1e17],
                        "length_vector": [0.0],
                    },
                },
            )
        if request.method == "GET" and request.url.path == "/v1/jobs/job_123/result":
            return httpx.Response(200, content=b"dynamic")
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = make_client(handler)

    dynamic_path = client.save_dynamic_hdf5(
        tmp_path / "dynamic.h5",
        ExposureRequest(elements=["Ni"]),
    )

    assert dynamic_path.read_bytes() == b"dynamic"


def test_api_key_can_come_from_environment(monkeypatch):
    monkeypatch.setenv("ROBOAI_LIBS_API_KEY", "tok_test")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok_test"
        return httpx.Response(200, json={"elements": ["Ni"]})

    client = RoboAILIBSClient(
        base_url="https://example.test",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.list_elements() == ["Ni"]


def test_api_error_raises_client_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "service unavailable"})

    client = make_client(handler)

    with pytest.raises(RoboAILIBSAPIError) as exc_info:
        client.list_elements()

    assert exc_info.value.status_code == 503
    assert "service unavailable" in str(exc_info.value)


def test_default_base_url_matches_hosted_service(monkeypatch):
    monkeypatch.delenv("ROBOAI_LIBS_BASE_URL", raising=False)
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    client = RoboAILIBSClient(http_client=httpx.Client(transport=transport))

    assert client.base_url == DEFAULT_BASE_URL


def test_api_key_can_come_from_stored_login(monkeypatch, tmp_path):
    monkeypatch.delenv("ROBOAI_LIBS_API_KEY", raising=False)
    monkeypatch.delenv("ROBOAI_LIBS_TOKEN", raising=False)
    monkeypatch.setenv("ROBOAI_LIBS_CONFIG_DIR", str(tmp_path))
    save_api_key("tok_stored")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok_stored"
        return httpx.Response(200, json={"elements": ["Ni"]})

    client = RoboAILIBSClient(
        base_url="https://example.test",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.list_elements() == ["Ni"]
    assert load_stored_api_key() == "tok_stored"


def test_job_lifecycle_submit_get_cancel():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.url.query.decode()))
        if request.method == "POST" and request.url.path == "/v1/spectra/exposure/jobs":
            return httpx.Response(202, json={"job_id": "job_9", "status": "queued", "preview": None})
        if request.method == "GET" and request.url.path == "/v1/jobs/job_9":
            return httpx.Response(
                200,
                json={"job_id": "job_9", "status": "running", "slices_done": 2, "slices_total": 5},
            )
        if request.method == "DELETE" and request.url.path == "/v1/jobs/job_9":
            return httpx.Response(204)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = make_client(handler)

    job = client.submit_exposure_job(elements=["Ni"])
    assert job.job_id == "job_9"
    assert calls[0] == ("POST", "/v1/spectra/exposure/jobs", "cancel_on_disconnect=false")

    status = client.get_job(job.job_id)
    assert status.status == "running"
    assert (status.slices_done, status.slices_total) == (2, 5)

    client.cancel_job(job.job_id)
    assert calls[-1] == ("DELETE", "/v1/jobs/job_9", "")


def test_submit_job_can_opt_into_cancel_on_disconnect():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.query == b""
        return httpx.Response(202, json={"job_id": "job_9", "status": "queued", "preview": None})

    client = make_client(handler)
    job = client.submit_exposure_job(ExposureRequest(elements=["Ni"]), cancel_on_disconnect=True)

    assert job.status == "queued"


def test_wait_for_job_reports_only_progress_changes():
    polls = [
        {"job_id": "job_9", "status": "queued"},
        {"job_id": "job_9", "status": "running", "slices_done": 1, "slices_total": 4},
        {"job_id": "job_9", "status": "running", "slices_done": 1, "slices_total": 4},
        {"job_id": "job_9", "status": "running", "slices_done": 3, "slices_total": 4},
        {"job_id": "job_9", "status": "completed", "slices_done": 4, "slices_total": 4},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=polls.pop(0))

    client = make_client(handler)
    seen = []
    status = client.wait_for_job(
        "job_9",
        poll_interval_s=0.0,
        on_progress=lambda s: seen.append((s.status, s.slices_done, s.slices_total)),
    )

    assert status.status == "completed"
    # The duplicate running-1/4 poll must not re-fire the callback.
    assert seen == [
        ("queued", None, None),
        ("running", 1, 4),
        ("running", 3, 4),
        ("completed", 4, 4),
    ]


def test_wait_for_job_raises_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"job_id": "job_9", "status": "failed", "error": "GPU exploded"}
        )

    client = make_client(handler)

    with pytest.raises(RoboAILIBSClientError, match="GPU exploded"):
        client.wait_for_job("job_9", poll_interval_s=0.0)


def test_cancel_finished_job_surfaces_409():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "Cannot cancel a completed job"})

    client = make_client(handler)

    with pytest.raises(RoboAILIBSAPIError) as exc_info:
        client.cancel_job("job_9")

    assert exc_info.value.status_code == 409


def test_save_dynamic_hdf5_threads_on_progress(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/spectra/exposure/jobs":
            return httpx.Response(202, json={"job_id": "job_123", "status": "queued", "preview": None})
        if request.method == "GET" and request.url.path == "/v1/jobs/job_123":
            return httpx.Response(
                200,
                json={"job_id": "job_123", "status": "completed", "slices_done": 2, "slices_total": 2},
            )
        if request.method == "GET" and request.url.path == "/v1/jobs/job_123/result":
            return httpx.Response(200, content=b"dynamic")
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = make_client(handler)
    seen = []
    client.save_dynamic_hdf5(
        tmp_path / "dynamic.h5",
        ExposureRequest(elements=["Ni"]),
        on_progress=lambda s: seen.append(s.status),
    )

    assert seen == ["completed"]


def _exposure_payload():
    return {
        "wls": [200.0, 200.05],
        "total_exposure": [1.0, 2.0],
        "snapshot_matrix": [[0.4, 0.8], [0.6, 1.2]],
        "time_vector": [1e-7, 2e-7],
        "te_vector": [1.0, 0.9],
        "ne_vector": [1e17, 9e16],
        "length_vector": [1e-3, 1.1e-3],
    }


def test_new_request_fields_reach_the_api():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json=_exposure_payload())

    client = make_client(handler)
    client.simulate_exposure(
        ExposureRequest(
            elements=["Cu"],
            stark_model="mse",
            continuum_model="merlin_physical",
        )
    )

    assert seen["stark_model"] == "mse"
    assert seen["continuum_model"] == "merlin_physical"
    assert seen["planck_empirical_scale"] == 0.0
    # Already-wired nested configs must still travel.
    assert seen["plasma_config"]["number_of_layers"] == 2
    assert seen["temporal_config"]["gamma_dens"] == 2.0


def test_simulate_exposure_keeps_snapshots_by_default():
    client = make_client(lambda request: httpx.Response(200, json=_exposure_payload()))

    result = client.simulate_exposure(ExposureRequest(elements=["Cu"]))

    assert result.snapshot_matrix == [[0.4, 0.8], [0.6, 1.2]]
    assert result.total_exposure == [1.0, 2.0]


def test_simulate_exposure_total_only_drops_the_matrix():
    client = make_client(lambda request: httpx.Response(200, json=_exposure_payload()))

    result = client.simulate_exposure(
        ExposureRequest(elements=["Cu"]), include_snapshots=False
    )

    assert result.snapshot_matrix == []
    # The full exposure is unaffected: the server integrates it independently.
    assert result.total_exposure == [1.0, 2.0]
    # Per-snapshot vectors stay: one value each, cheap and still descriptive.
    assert result.time_vector == [1e-7, 2e-7]


def test_exposure_result_parses_a_response_without_snapshots():
    payload = _exposure_payload()
    del payload["snapshot_matrix"]
    client = make_client(lambda request: httpx.Response(200, json=payload))

    result = client.simulate_exposure(ExposureRequest(elements=["Cu"]))

    assert result.snapshot_matrix == []


def test_run_exposure_job_total_only():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/spectra/exposure/jobs":
            return httpx.Response(200, json={"job_id": "job_1", "status": "queued"})
        return httpx.Response(
            200,
            json={"job_id": "job_1", "status": "completed", "result": _exposure_payload()},
        )

    client = make_client(handler)

    result = client.run_exposure_job(
        ExposureRequest(elements=["Cu"]), include_snapshots=False
    )

    assert result.snapshot_matrix == []
    assert result.total_exposure == [1.0, 2.0]
