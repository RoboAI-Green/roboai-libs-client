from __future__ import annotations

import argparse
import contextlib
import csv
import functools
import getpass
import os
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any, Sequence

from .auth import (
    clear_stored_api_key,
    extract_access_token,
    get_token_file,
    load_stored_api_key,
    token_from_env,
)
from .client import RoboAILIBSClient
from .errors import RoboAILIBSAPIError
from .models import ExposureRequest, StaticSpectrumRequest

_SPECTRUM_FIELDS = StaticSpectrumRequest.model_fields


def _field_default(name: str) -> Any:
    return _SPECTRUM_FIELDS[name].default


def _print_cli_error(exc: Exception) -> int:
    print(f"Error: {exc}", file=sys.stderr)
    return 1


def _missing_token_error() -> int:
    print("Error: API token is not configured.", file=sys.stderr)
    print("Run `roboai-libs auth login` first.", file=sys.stderr)
    return 2


def with_client(
    require_token: bool = False,
) -> Callable[[Callable[..., int]], Callable[[argparse.Namespace], int]]:
    def decorator(fn: Callable[..., int]) -> Callable[[argparse.Namespace], int]:
        @functools.wraps(fn)
        def wrapper(args: argparse.Namespace) -> int:
            try:
                with RoboAILIBSClient(timeout=args.timeout) as client:
                    if require_token and not client.api_key:
                        return _missing_token_error()
                    return fn(args, client)
            except Exception as exc:
                return _print_cli_error(exc)

        return wrapper

    return decorator


def _client_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"timeout": args.timeout}
    if args.base_url:
        kwargs["base_url"] = args.base_url
    return kwargs


def _request_login(args: argparse.Namespace) -> int:
    if args.token:
        raw_token = args.token
    else:
        email = args.email or input("Email: ").strip()
        if not email:
            print("Email is required.", file=sys.stderr)
            return 2

        with RoboAILIBSClient(**_client_kwargs(args)) as client:
            base_url = client.base_url
            try:
                client.request_login_otp(email)
            except RoboAILIBSAPIError as exc:
                print(f"Authentication request failed: {exc}", file=sys.stderr)
                return 1
            except Exception as exc:
                print(f"Authentication request failed against {base_url}: {exc}", file=sys.stderr)
                if not args.base_url and not os.getenv("ROBOAI_LIBS_BASE_URL"):
                    print(
                        "If you are testing a local deployment, set ROBOAI_LIBS_BASE_URL "
                        "or pass --base-url.",
                        file=sys.stderr,
                    )
                return 1

        print("Verification link sent. Open it from your email, then paste the access_token here.")
        raw_token = getpass.getpass("access_token: ")

    try:
        token = extract_access_token(raw_token)
    except ValueError as exc:
        print(f"Token parsing failed: {exc}", file=sys.stderr)
        return 1

    client = RoboAILIBSClient(api_key=token, **_client_kwargs(args))
    try:
        with client:
            token_file = client.save_authenticated_token()
    except Exception as exc:
        print(f"Token validation failed against {client.base_url}: {exc}", file=sys.stderr)
        return 1

    print(f"Saved API token to {token_file}")
    print("Authentication setup complete. RoboAILIBSClient() is ready to use.")
    return 0


def _auth_status(args: argparse.Namespace) -> int:
    if token_from_env():
        print("API token is configured from environment.")
        return 0
    if load_stored_api_key():
        print(f"API token is stored in {get_token_file()}")
        return 0
    print("No API token configured.")
    return 1


def _auth_logout(args: argparse.Namespace) -> int:
    removed = clear_stored_api_key()
    if removed:
        print(f"Removed stored API token from {get_token_file()}")
    else:
        print("No stored API token found.")
    return 0


@with_client()
def _list_elements(args: argparse.Namespace, client: RoboAILIBSClient) -> int:
    for element in client.list_elements():
        print(element)
    return 0


@with_client()
def _doctor(args: argparse.Namespace, client: RoboAILIBSClient) -> int:
    print("RoboAI LIBS client check")
    print()

    print(f"API URL: {client.base_url}")
    token_valid = False
    if client.api_key:
        try:
            client.get_token_info()
            token_valid = True
            print("Token: valid")
        except RoboAILIBSAPIError as exc:
            if exc.status_code == 401:
                print("Token: invalid or revoked")
            else:
                raise
        except Exception as exc:
            print("Token: check failed")
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    else:
        print("Token: missing")

    try:
        elements = client.list_elements()
    except Exception as exc:
        print("Elements: failed")
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Elements: ok, {len(elements)} elements available")
    if token_valid:
        print()
        print("Ready.")
    else:
        print()
        print("Static and dynamic simulations require login:")
        print("  roboai-libs auth login")
    return 0


def _write_static_csv(result, output_path: Path | None) -> None:
    if output_path is None:
        target = contextlib.nullcontext(sys.stdout)
    else:
        target = output_path.open("w", newline="")
    with target as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["wavelength_nm", "intensity"])
        writer.writerows(zip(result.wls, result.intensity, strict=True))


def _static_kwargs_from_args(args: argparse.Namespace) -> dict[str, object]:
    range_min_nm, range_max_nm = args.wavelength_range
    return {
        "elements": args.elements,
        "proportions": args.proportions,
        "range_min_nm": range_min_nm,
        "range_max_nm": range_max_nm,
        "resolution_nm": args.resolution_nm,
        "te_ev": args.te_ev,
        "ne_cm3": args.ne_cm3,
        "fwhm_nm": args.fwhm_nm,
        "instrument_profile": args.instrument_profile,
    }


@with_client(require_token=True)
def _run_static(args: argparse.Namespace, client: RoboAILIBSClient) -> int:
    result = client.simulate_static(**_static_kwargs_from_args(args))
    _write_static_csv(result, args.out)
    if args.out is not None:
        print(f"Saved {len(result.wls)} wavelength points to {args.out}")
    return 0


@with_client(require_token=True)
def _run_dynamic(args: argparse.Namespace, client: RoboAILIBSClient) -> int:
    request = ExposureRequest(
        **_static_kwargs_from_args(args),
        integration_time_s=args.integration_time_s,
        time_resolution_s=args.time_resolution_s,
    )
    path = client.save_dynamic_hdf5(
        args.out,
        request,
        poll_interval_s=args.poll_interval,
        timeout_s=args.job_timeout,
    )
    print(f"Saved dynamic HDF5 result to {path}")
    return 0


def _add_common_spectrum_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--element",
        dest="elements",
        action="append",
        required=True,
        help="Element symbol to include. Repeat for mixtures, for example --element Ni --element Fe.",
    )
    parser.add_argument(
        "--proportion",
        dest="proportions",
        action="append",
        type=float,
        help="Relative element proportion. Repeat once per element. Values are normalized.",
    )
    range_default = [_field_default("range_min_nm"), _field_default("range_max_nm")]
    parser.add_argument(
        "--range",
        dest="wavelength_range",
        nargs=2,
        type=float,
        default=range_default,
        metavar=("MIN_NM", "MAX_NM"),
        help=f"Wavelength range in nm. Default: {range_default[0]} {range_default[1]}.",
    )
    parser.add_argument(
        "--resolution",
        "--resolution-nm",
        dest="resolution_nm",
        type=float,
        default=_field_default("resolution_nm"),
        help=f"Wavelength step in nm. Default: {_field_default('resolution_nm')}.",
    )
    parser.add_argument(
        "--te",
        "--te-ev",
        dest="te_ev",
        type=float,
        default=_field_default("te_ev"),
        help=f"Electron temperature in eV. Default: {_field_default('te_ev')}.",
    )
    parser.add_argument(
        "--ne",
        "--ne-cm3",
        dest="ne_cm3",
        type=float,
        default=_field_default("ne_cm3"),
        help=f"Electron number density in cm^-3. Default: {_field_default('ne_cm3')}.",
    )
    parser.add_argument(
        "--fwhm",
        "--fwhm-nm",
        dest="fwhm_nm",
        type=float,
        default=_field_default("fwhm_nm"),
        help=f"Instrumental FWHM in nm. Default: {_field_default('fwhm_nm')}.",
    )
    parser.add_argument(
        "--instrument-profile",
        choices=["gaussian", "lorentzian"],
        default=_field_default("instrument_profile"),
        help=f"Instrument broadening profile. Default: {_field_default('instrument_profile')}.",
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout in seconds")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="roboai-libs",
        description=(
            "Command-line helper for RoboAI LIBS authentication and quick spectrum exports. "
            "Full workflows are available from Python with RoboAILIBSClient."
        ),
        epilog=textwrap.dedent(
            """\
            Setup and checks:
              roboai-libs auth login
              roboai-libs doctor
              roboai-libs elements

            Quick exports:
              roboai-libs static --element Ni --out ni.csv
              roboai-libs dynamic --element Ni --out ni_dynamic.h5
              roboai-libs static --element Ni --range 200 230 --resolution 0.05 --te 1 --ne 1e17 --out ni.csv

            Auth utilities:
              roboai-libs auth login --email you@uni.fi
              roboai-libs auth login --token tok_...
              roboai-libs auth status
              roboai-libs auth logout

            Python usage:
              from roboai_libs_client import RoboAILIBSClient
              client = RoboAILIBSClient()
              result = client.simulate_static(elements=["Ni"])

            More Python examples:
              https://pypi.org/project/roboai-libs-client/
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    auth_parser = subparsers.add_parser(
        "auth",
        help="Manage RoboAI LIBS API authentication",
        description="Request, store, inspect, or remove a RoboAI LIBS API token.",
        epilog=textwrap.dedent(
            """\
            Examples:
              roboai-libs auth login
              roboai-libs auth login --email you@uni.fi
              roboai-libs auth login --token tok_...
              roboai-libs auth status
              roboai-libs auth logout
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command")

    login_parser = auth_subparsers.add_parser("login", help="Request and store an API token")
    login_parser.add_argument("--email", help="Email address for the verification link")
    login_parser.add_argument("--token", help="Store an existing access_token without requesting email")
    login_parser.add_argument("--base-url", help="API base URL, for example http://localhost:8080/api")
    login_parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds")
    login_parser.set_defaults(func=_request_login)

    status_parser = auth_subparsers.add_parser("status", help="Show whether an API token is configured")
    status_parser.set_defaults(func=_auth_status)
    logout_parser = auth_subparsers.add_parser("logout", help="Remove the stored API token")
    logout_parser.set_defaults(func=_auth_logout)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check API connectivity and local authentication state",
        description="Check the API URL, local token state, and elements endpoint.",
    )
    doctor_parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds")
    doctor_parser.set_defaults(func=_doctor)

    elements_parser = subparsers.add_parser(
        "elements",
        help="List elements available from the hosted simulator",
        description="Print one available element symbol per line.",
    )
    elements_parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout in seconds")
    elements_parser.set_defaults(func=_list_elements)

    static_parser = subparsers.add_parser(
        "static",
        help="Run a quick static spectrum and write CSV",
        description="Run a static spectrum simulation and write wavelength/intensity CSV output.",
        epilog=textwrap.dedent(
            """\
            Examples:
              roboai-libs static --element Ni --out ni.csv
              roboai-libs static --element Ni --range 200 230 --resolution 0.05 --te 1 --ne 1e17 --out ni.csv
              roboai-libs static --element Ni --element Fe --proportion 2 --proportion 1 --out ni_fe.csv
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_common_spectrum_arguments(static_parser)
    static_parser.add_argument("--out", type=Path, help="Output CSV path. Defaults to stdout.")
    static_parser.set_defaults(func=_run_static)

    dynamic_parser = subparsers.add_parser(
        "dynamic",
        help="Run a dynamic exposure job and download HDF5",
        description="Run a dynamic exposure simulation job and save the HDF5 result.",
        epilog=textwrap.dedent(
            """\
            Examples:
              roboai-libs dynamic --element Ni --out ni_dynamic.h5
              roboai-libs dynamic --element Ni --range 200 230 --resolution 0.05 --integration-time 1e-6 --time-resolution 100e-9 --out ni_dynamic.h5
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_common_spectrum_arguments(dynamic_parser)
    dynamic_parser.add_argument(
        "--integration-time",
        "--integration-time-s",
        dest="integration_time_s",
        type=float,
        default=1e-6,
        help="Total simulated exposure time in seconds. Default: 1e-6.",
    )
    dynamic_parser.add_argument(
        "--time-resolution",
        "--time-resolution-s",
        dest="time_resolution_s",
        type=float,
        default=100e-9,
        help="Dynamic simulation time step in seconds. Default: 100e-9.",
    )
    dynamic_parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Job polling interval in seconds. Default: 1.0.",
    )
    dynamic_parser.add_argument(
        "--job-timeout",
        type=float,
        default=600.0,
        help="Maximum time to wait for the job in seconds. Default: 600.",
    )
    dynamic_parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output HDF5 path.",
    )
    dynamic_parser.set_defaults(func=_run_dynamic)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())
