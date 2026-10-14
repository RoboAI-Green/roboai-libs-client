from pathlib import Path
from types import SimpleNamespace

import pytest

from roboai_libs_client.auth import load_stored_api_key
from roboai_libs_client import cli
from roboai_libs_client.errors import RoboAILIBSAPIError


class FakeClient:
    instances = []
    api_key = "tok_fake"
    base_url = "https://example.test"

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.static_kwargs = None
        self.api_key = FakeClient.api_key
        self.base_url = FakeClient.base_url
        FakeClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def list_elements(self):
        return ["H", "He", "Ni"]

    def get_token_info(self):
        return {"email": "test@example.test", "created_at": "2026-01-01T00:00:00"}

    def request_login_otp(self, email):
        self.otp_email = email

    def save_authenticated_token(self):
        self.get_token_info()
        return Path("/fake/config/auth.json")

    def simulate_static(self, request=None, **kwargs):
        self.static_kwargs = kwargs
        return SimpleNamespace(wls=[200.0, 200.05], intensity=[1.0, 2.0])

    def save_dynamic_hdf5(self, path, request, *, poll_interval_s=1.0, timeout_s=600.0):
        self.dynamic_path = path
        self.dynamic_request = request
        self.dynamic_poll_interval_s = poll_interval_s
        self.dynamic_timeout_s = timeout_s
        path.write_bytes(b"dynamic hdf5")
        return path


def test_elements_command_prints_available_elements(monkeypatch, capsys):
    FakeClient.instances = []
    FakeClient.api_key = "tok_fake"
    monkeypatch.setattr(cli, "RoboAILIBSClient", FakeClient)

    exit_code = cli.main(["elements"])

    assert exit_code == 0
    assert capsys.readouterr().out == "H\nHe\nNi\n"


def test_doctor_reports_ready_when_api_and_token_are_available(monkeypatch, capsys):
    FakeClient.instances = []
    FakeClient.api_key = "tok_fake"
    monkeypatch.setattr(cli, "RoboAILIBSClient", FakeClient)

    exit_code = cli.main(["doctor"])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "RoboAI LIBS client check\n"
        "\n"
        "API URL: https://example.test\n"
        "Token: valid\n"
        "Elements: ok, 3 elements available\n"
        "\n"
        "Ready.\n"
    )


def test_doctor_suggests_login_when_token_is_missing(monkeypatch, capsys):
    FakeClient.instances = []
    FakeClient.api_key = None
    monkeypatch.setattr(cli, "RoboAILIBSClient", FakeClient)

    exit_code = cli.main(["doctor"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Token: missing" in output
    assert "Elements: ok, 3 elements available" in output
    assert "roboai-libs auth login" in output


def test_doctor_reports_invalid_token(monkeypatch, capsys):
    class InvalidTokenClient(FakeClient):
        def get_token_info(self):
            raise RoboAILIBSAPIError(401, "Invalid or revoked token")

    FakeClient.instances = []
    FakeClient.api_key = "bad_token"
    monkeypatch.setattr(cli, "RoboAILIBSClient", InvalidTokenClient)

    exit_code = cli.main(["doctor"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Token: invalid or revoked" in output
    assert "Elements: ok, 3 elements available" in output
    assert "roboai-libs auth login" in output


def test_auth_login_token_validates_before_saving(monkeypatch, tmp_path, capsys):
    FakeClient.instances = []
    FakeClient.api_key = "tok_fake"
    monkeypatch.setattr(cli, "RoboAILIBSClient", FakeClient)
    monkeypatch.setenv("ROBOAI_LIBS_CONFIG_DIR", str(tmp_path))

    exit_code = cli.main(["auth", "login", "--token", "tok_valid"])

    assert exit_code == 0
    assert FakeClient.instances[0].kwargs["api_key"] == "tok_valid"
    assert "Authentication setup complete" in capsys.readouterr().out


def test_auth_login_token_rejects_invalid_token(monkeypatch, tmp_path, capsys):
    class InvalidTokenClient(FakeClient):
        def get_token_info(self):
            raise RoboAILIBSAPIError(401, "Invalid or revoked token")

    FakeClient.instances = []
    FakeClient.api_key = "bad_token"
    monkeypatch.setattr(cli, "RoboAILIBSClient", InvalidTokenClient)
    monkeypatch.setenv("ROBOAI_LIBS_CONFIG_DIR", str(tmp_path))

    exit_code = cli.main(["auth", "login", "--token", "bad_token"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Token validation failed" in captured.err


def test_auth_login_interactive_rejects_invalid_pasted_token(monkeypatch, tmp_path, capsys):
    class InvalidTokenClient(FakeClient):
        def get_token_info(self):
            raise RoboAILIBSAPIError(401, "Invalid or revoked token")

    FakeClient.instances = []
    FakeClient.api_key = "bad_token"
    monkeypatch.setattr(cli, "RoboAILIBSClient", InvalidTokenClient)
    monkeypatch.setenv("ROBOAI_LIBS_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda prompt: "user@example.test")
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "bad_token")

    exit_code = cli.main(["auth", "login"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Verification link sent" in captured.out
    assert "Token validation failed" in captured.err
    assert load_stored_api_key() is None


def test_doctor_reports_connection_failure(monkeypatch, capsys):
    class FailingClient(FakeClient):
        def list_elements(self):
            raise RuntimeError("connection failed")

    FakeClient.instances = []
    FakeClient.api_key = "tok_fake"
    monkeypatch.setattr(cli, "RoboAILIBSClient", FailingClient)

    exit_code = cli.main(["doctor"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Elements: failed" in captured.out
    assert "connection failed" in captured.err


def test_elements_command_does_not_require_token(monkeypatch, capsys):
    FakeClient.instances = []
    FakeClient.api_key = None
    monkeypatch.setattr(cli, "RoboAILIBSClient", FakeClient)

    exit_code = cli.main(["elements"])

    assert exit_code == 0
    assert capsys.readouterr().out == "H\nHe\nNi\n"


def test_static_command_writes_csv(monkeypatch, tmp_path, capsys):
    FakeClient.instances = []
    FakeClient.api_key = "tok_fake"
    monkeypatch.setattr(cli, "RoboAILIBSClient", FakeClient)
    output_path = tmp_path / "ni.csv"

    exit_code = cli.main(
        [
            "static",
            "--element",
            "Ni",
            "--range",
            "200",
            "230",
            "--resolution",
            "0.05",
            "--te",
            "1",
            "--ne",
            "1e17",
            "--out",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert output_path.read_text() == "wavelength_nm,intensity\n200.0,1.0\n200.05,2.0\n"
    captured = capsys.readouterr()
    assert "Saved 2 wavelength points" in captured.out
    # Hydrogenic runs print no Stark summary.
    assert captured.err == ""
    assert FakeClient.instances[0].static_kwargs == {
        "elements": ["Ni"],
        "proportions": None,
        "range_min_nm": 200.0,
        "range_max_nm": 230.0,
        "resolution_nm": 0.05,
        "te_ev": 1.0,
        "ne_cm3": 1e17,
        "fwhm_nm": 0.0,
        "instrument_profile": "gaussian",
        "stark_model": "hydrogenic",
    }


def test_static_command_can_write_csv_to_stdout(monkeypatch, capsys):
    FakeClient.instances = []
    FakeClient.api_key = "tok_fake"
    monkeypatch.setattr(cli, "RoboAILIBSClient", FakeClient)

    exit_code = cli.main(["static", "--element", "Ni"])

    assert exit_code == 0
    assert capsys.readouterr().out == "wavelength_nm,intensity\n200.0,1.0\n200.05,2.0\n"


def test_dynamic_command_saves_hdf5(monkeypatch, tmp_path, capsys):
    FakeClient.instances = []
    FakeClient.api_key = "tok_fake"
    monkeypatch.setattr(cli, "RoboAILIBSClient", FakeClient)
    output_path = tmp_path / "ni_dynamic.h5"

    exit_code = cli.main(
        [
            "dynamic",
            "--element",
            "Ni",
            "--range",
            "200",
            "230",
            "--resolution",
            "0.05",
            "--te",
            "1",
            "--ne",
            "1e17",
            "--integration-time",
            "1e-6",
            "--time-resolution",
            "100e-9",
            "--poll-interval",
            "0.1",
            "--job-timeout",
            "10",
            "--out",
            str(output_path),
        ]
    )

    instance = FakeClient.instances[0]
    assert exit_code == 0
    assert output_path.read_bytes() == b"dynamic hdf5"
    assert "Saved dynamic HDF5 result" in capsys.readouterr().out
    assert instance.dynamic_request.elements == ["Ni"]
    assert instance.dynamic_request.range_min_nm == 200.0
    assert instance.dynamic_request.range_max_nm == 230.0
    assert instance.dynamic_request.resolution_nm == 0.05
    assert instance.dynamic_request.te_ev == 1.0
    assert instance.dynamic_request.ne_cm3 == 1e17
    assert instance.dynamic_request.integration_time_s == 1e-6
    assert instance.dynamic_request.time_resolution_s == 100e-9
    assert instance.dynamic_poll_interval_s == 0.1
    assert instance.dynamic_timeout_s == 10.0


class MseFakeClient(FakeClient):
    """Returns results carrying the line split an mse run reports."""

    _split = {"stark_mse_lines": 12, "stark_fallback_lines": 3}

    def simulate_static(self, request=None, **kwargs):
        self.static_kwargs = kwargs
        return SimpleNamespace(wls=[200.0, 200.05], intensity=[1.0, 2.0], **self._split)

    def run_exposure_job(
        self, request, *, include_snapshots=True, poll_interval_s=1.0, timeout_s=600.0
    ):
        self.dynamic_request = request
        return SimpleNamespace(wls=[200.0, 200.05], total_exposure=[3.0, 4.0], **self._split)


def test_static_command_mse_prints_line_split_to_stderr(monkeypatch, capsys):
    FakeClient.instances = []
    FakeClient.api_key = "tok_fake"
    monkeypatch.setattr(cli, "RoboAILIBSClient", MseFakeClient)

    exit_code = cli.main(["static", "--element", "Ni", "--stark-model", "mse"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert FakeClient.instances[0].static_kwargs["stark_model"] == "mse"
    # The CSV on stdout stays clean; the split goes to stderr.
    assert captured.out == "wavelength_nm,intensity\n200.0,1.0\n200.05,2.0\n"
    assert captured.err == "Stark widths: MSE for 12 lines, hydrogenic fallback for 3\n"


def test_dynamic_command_passes_stark_model(monkeypatch, tmp_path):
    FakeClient.instances = []
    FakeClient.api_key = "tok_fake"
    monkeypatch.setattr(cli, "RoboAILIBSClient", FakeClient)

    exit_code = cli.main(
        ["dynamic", "--element", "Ni", "--stark-model", "mse", "--out", str(tmp_path / "ni.h5")]
    )

    assert exit_code == 0
    assert FakeClient.instances[0].dynamic_request.stark_model == "mse"
    assert FakeClient.instances[0].dynamic_request.api_payload()["stark_model"] == "mse"


def test_dynamic_total_only_mse_prints_line_split_to_stderr(monkeypatch, tmp_path, capsys):
    FakeClient.instances = []
    FakeClient.api_key = "tok_fake"
    monkeypatch.setattr(cli, "RoboAILIBSClient", MseFakeClient)
    output_path = tmp_path / "ni_total.csv"

    exit_code = cli.main(
        [
            "dynamic",
            "--element",
            "Ni",
            "--stark-model",
            "mse",
            "--total-only",
            "--out",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert FakeClient.instances[0].dynamic_request.stark_model == "mse"
    assert output_path.read_text() == "wavelength_nm,full_exposure\n200.0,3.0\n200.05,4.0\n"
    assert "MSE for 12 lines, hydrogenic fallback for 3" in capsys.readouterr().err


def test_stark_model_rejects_unknown_methods(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["static", "--element", "Ni", "--stark-model", "stark-b"])

    assert excinfo.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
