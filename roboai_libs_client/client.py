from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .auth import load_stored_api_key, save_api_key, token_from_env
from .errors import RoboAILIBSAPIError, RoboAILIBSClientError
from .models import (
    ExposureRequest,
    ExposureResult,
    JobStatusResult,
    JobSubmitResult,
    StaticSpectrumRequest,
    StaticSpectrumResult,
)

DEFAULT_BASE_URL = "https://libs.roboai.fi/api"

# Time-resolved fields dropped when the caller only wants the full exposure.
_SNAPSHOT_FIELDS = ("snapshot_matrix",)


def _drop_snapshots(data: dict[str, Any]) -> dict[str, Any]:
    """Remove the per-snapshot matrix before it reaches pydantic.

    The server always sends it today, so this saves memory rather than
    bandwidth: dropping it here means pydantic never builds a second validated
    copy, and the raw lists parsed out of the response body become collectable
    immediately. On a 100-wavelength-point x 100-snapshot exposure the matrix is
    two orders of magnitude larger than ``total_exposure`` itself, which matters
    when many exposures are run in a loop.

    ``time_vector`` and the Te/Ne/length vectors are kept: they are one value
    per snapshot, so they stay cheap and still describe the time grid used.
    """
    for key in _SNAPSHOT_FIELDS:
        data.pop(key, None)
    return data


class RoboAILIBSClient:
    """Synchronous Python client for the RoboAI LIBS Spectrum Simulator API."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float | httpx.Timeout = 60.0,
        http_client: httpx.Client | None = None,
    ):
        resolved_base_url = base_url or os.getenv("ROBOAI_LIBS_BASE_URL") or DEFAULT_BASE_URL
        self.base_url = resolved_base_url.rstrip("/")
        self.api_key = api_key or token_from_env() or load_stored_api_key()
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "RoboAILIBSClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        merged_headers = {**self._headers(), **headers}
        response = self._client.request(method, url, headers=merged_headers, **kwargs)

        if response.status_code >= 400:
            message = response.text
            try:
                detail = response.json().get("detail")
                if detail:
                    message = str(detail)
            except ValueError:
                pass
            raise RoboAILIBSAPIError(
                response.status_code,
                message,
                response_text=response.text,
            )

        return response

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", path, json=payload)
        return response.json()

    def list_elements(self) -> list[str]:
        data = self._request("GET", "/v1/spectra/elements").json()
        return list(data["elements"])

    def get_token_info(self) -> dict[str, Any]:
        return dict(self._request("GET", "/v1/auth/token").json())

    def request_login_otp(self, email: str) -> None:
        self._request("POST", "/v1/auth/otp", json={"email": email})

    def save_authenticated_token(self) -> Path:
        self.get_token_info()
        return save_api_key(self.api_key)

    def simulate_static(
        self,
        request: StaticSpectrumRequest | None = None,
        **kwargs: Any,
    ) -> StaticSpectrumResult:
        if request is None:
            request = StaticSpectrumRequest(**kwargs)
        elif kwargs:
            raise TypeError("Pass either a request or keyword fields, not both.")
        data = self._post_json("/v1/spectra/static", request.api_payload())
        return StaticSpectrumResult.model_validate(data)

    def simulate_exposure(
        self,
        request: ExposureRequest | None = None,
        *,
        include_snapshots: bool = True,
        **kwargs: Any,
    ) -> ExposureResult:
        """Run a time-resolved exposure and return the result.

        With ``include_snapshots=False`` the per-snapshot matrix is discarded on
        arrival and ``result.snapshot_matrix`` comes back empty; the full
        exposure (``result.total_exposure``) is unaffected, since the server
        integrates it over every time step independently of the snapshots.
        """
        if request is None:
            request = ExposureRequest(**kwargs)
        elif kwargs:
            raise TypeError("Pass either a request or keyword fields, not both.")
        data = self._post_json("/v1/spectra/exposure", request.api_payload())
        if not include_snapshots:
            data = _drop_snapshots(data)
        return ExposureResult.model_validate(data)

    def submit_exposure_job(
        self,
        request: ExposureRequest | None = None,
        *,
        cancel_on_disconnect: bool = False,
        **kwargs: Any,
    ) -> JobSubmitResult:
        """Submit an async exposure job and return immediately.

        The result carries the ``job_id`` for ``get_job`` / ``wait_for_job`` /
        ``cancel_job`` / ``download_job_hdf5``, plus a coarse ``preview`` when
        the server could compute one in time. By default the job keeps running
        if this client disconnects; pass ``cancel_on_disconnect=True`` to have
        the server cancel it on disconnect instead.
        """
        if request is None:
            request = ExposureRequest(**kwargs)
        elif kwargs:
            raise TypeError("Pass either a request or keyword fields, not both.")
        path = "/v1/spectra/exposure/jobs"
        if not cancel_on_disconnect:
            path = f"{path}?cancel_on_disconnect=false"
        data = self._post_json(path, request.api_payload())
        return JobSubmitResult.model_validate(data)

    def get_job(self, job_id: str, *, include_snapshots: bool = True) -> JobStatusResult:
        """Fetch a job's status, slice progress, and result once completed.

        ``include_snapshots=False`` drops the per-snapshot matrix from a
        completed job's result; see :meth:`simulate_exposure`.
        """
        data = self._request("GET", f"/v1/jobs/{job_id}").json()
        if not include_snapshots and isinstance(data.get("result"), dict):
            data["result"] = _drop_snapshots(data["result"])
        return JobStatusResult.model_validate(data)

    def cancel_job(self, job_id: str) -> None:
        """Cancel a queued or running job.

        Idempotent for already-cancelled jobs; cancelling a completed or
        failed job raises a 409 ``RoboAILIBSAPIError``.
        """
        self._request("DELETE", f"/v1/jobs/{job_id}")

    def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval_s: float = 1.0,
        timeout_s: float = 600.0,
        on_progress: Callable[[JobStatusResult], None] | None = None,
        include_snapshots: bool = True,
    ) -> JobStatusResult:
        """Poll a job until it completes and return its final status.

        ``on_progress`` is invoked only when the polled status or slice counts
        change (including the terminal poll), so it is safe to print from.

        ``include_snapshots=False`` drops the per-snapshot matrix from every
        polled result; see :meth:`simulate_exposure`.
        """
        deadline = time.monotonic() + timeout_s
        last_progress: tuple[str, int | None, int | None] | None = None
        while True:
            status = self.get_job(job_id, include_snapshots=include_snapshots)
            if on_progress is not None:
                progress = (status.status, status.slices_done, status.slices_total)
                if progress != last_progress:
                    last_progress = progress
                    on_progress(status)
            if status.status == "completed":
                return status
            if status.status in {"failed", "cancelled", "expired"}:
                message = status.error or status.cancel_detail or status.status
                raise RoboAILIBSClientError(f"Exposure job {job_id} ended with {status.status}: {message}")
            if time.monotonic() >= deadline:
                raise RoboAILIBSClientError(f"Timed out waiting for exposure job {job_id}.")
            time.sleep(poll_interval_s)

    def run_exposure_job(
        self,
        request: ExposureRequest,
        *,
        include_snapshots: bool = True,
        poll_interval_s: float = 1.0,
        timeout_s: float = 600.0,
        on_progress: Callable[[JobStatusResult], None] | None = None,
    ) -> ExposureResult:
        """Submit an exposure job, wait for it, and return its result.

        The async path suits long exposures that would time out on the
        synchronous endpoint. Pass ``include_snapshots=False`` to keep only the
        full exposure; see :meth:`simulate_exposure`.
        """
        job = self.submit_exposure_job(request, cancel_on_disconnect=False)
        status = self.wait_for_job(
            job.job_id,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
            on_progress=on_progress,
            include_snapshots=include_snapshots,
        )
        if status.result is None:
            raise RoboAILIBSClientError(
                f"Exposure job {job.job_id} completed without a result."
            )
        return status.result

    def download_job_hdf5(self, job_id: str) -> bytes:
        """Download a completed job's result as self-describing HDF5 bytes."""
        response = self._request(
            "GET",
            f"/v1/jobs/{job_id}/result",
            headers={"Accept": "application/x-hdf5"},
        )
        return response.content

    def export_dynamic_hdf5(
        self,
        request: ExposureRequest,
        *,
        poll_interval_s: float = 1.0,
        timeout_s: float = 600.0,
        on_progress: Callable[[JobStatusResult], None] | None = None,
    ) -> bytes:
        job = self.submit_exposure_job(request, cancel_on_disconnect=False)
        self.wait_for_job(
            job.job_id,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
            on_progress=on_progress,
        )
        return self.download_job_hdf5(job.job_id)

    def save_dynamic_hdf5(
        self,
        path: str | Path,
        request: ExposureRequest,
        *,
        poll_interval_s: float = 1.0,
        timeout_s: float = 600.0,
        on_progress: Callable[[JobStatusResult], None] | None = None,
    ) -> Path:
        output_path = Path(path)
        output_path.write_bytes(
            self.export_dynamic_hdf5(
                request,
                poll_interval_s=poll_interval_s,
                timeout_s=timeout_s,
                on_progress=on_progress,
            )
        )
        return output_path
