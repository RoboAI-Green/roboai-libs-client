# RoboAI LIBS Client

[![PyPI version](https://img.shields.io/pypi/v/roboai-libs-client.svg)](https://pypi.org/project/roboai-libs-client/)
[![Python versions](https://img.shields.io/pypi/pyversions/roboai-libs-client.svg)](https://pypi.org/project/roboai-libs-client/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Lightweight Python client SDK and command-line helper for the RoboAI LIBS
Spectrum Simulator API.

## Contents

- [Install](#install)
- [Quick Start](#quick-start)
- [Authentication](#authentication)
- [Usage Examples](#usage-examples)
- [API Reference and Parameters](#api-reference-and-parameters)
- [Support](#support)
- [License](#license)

## Install

Prerequisite: Python 3.10 or newer.

From PyPI:

```bash
pip install --upgrade roboai-libs-client
```

From GitHub, if you need the latest repository version:

```bash
pip install git+https://github.com/RoboAI-Green/roboai-libs-client.git
```

## Quick Start

Authenticate once:

```bash
roboai-libs auth login
```

Run a first static spectrum from Python:

```python
from roboai_libs_client import RoboAILIBSClient

client = RoboAILIBSClient()

result = client.simulate_static(
    elements=["Ni"],
    range_min_nm=200,      # start wavelength in nm
    range_max_nm=230,      # end wavelength in nm
    resolution_nm=0.05,    # wavelength step in nm
    te_ev=1.0,             # electron temperature in eV
    ne_cm3=1e17,           # electron density in cm^-3
    fwhm_nm=0.0,           # instrumental FWHM in nm
)

print(result.wls[:5])
print(result.intensity[:5])
```

Or run the same kind of quick export from the command line:

```bash
roboai-libs static --element Ni --range 200 230 --resolution 0.05 --out ni.csv
```

For built-in command help:

```bash
roboai-libs --help
roboai-libs static --help
roboai-libs dynamic --help
```

## Authentication

The client requires a platform Bearer token before calling protected simulation
endpoints. The recommended setup is interactive login:

```bash
roboai-libs auth login
```

Enter your email address, open the verification link from your mailbox, and paste
the returned `access_token` value. The token is stored locally, so future
`RoboAILIBSClient()` calls can use it automatically.

Useful authentication and connection checks:

```bash
roboai-libs doctor
roboai-libs auth status
roboai-libs auth logout
```

`roboai-libs auth status` only checks local token configuration. `roboai-libs
doctor` checks the API connection, validates the token if one is configured, and
queries the elements endpoint.

<details>
<summary>Alternative authentication methods</summary>

Request a login email directly:

```bash
roboai-libs auth login --email you@uni.fi
```

If you already have a token, validate it and store it locally:

```bash
roboai-libs auth login --token tok_...
```

Alternatively, pass a token directly with `api_key=...` or the
`ROBOAI_LIBS_API_KEY` environment variable:

```bash
export ROBOAI_LIBS_API_KEY=tok_...
```

```python
from roboai_libs_client import RoboAILIBSClient

client = RoboAILIBSClient(api_key="tok_...")
```

</details>

## Usage Examples

### 1. List available elements

```python
from roboai_libs_client import RoboAILIBSClient

client = RoboAILIBSClient()

elements = client.list_elements()
print(elements[:20])
```

Command-line equivalent:

```bash
roboai-libs elements
```

### 2. Static spectrum

```python
from roboai_libs_client import RoboAILIBSClient

client = RoboAILIBSClient()

result = client.simulate_static(
    elements=["Ni"],
    range_min_nm=280,
    range_max_nm=330,
    resolution_nm=0.05,
    te_ev=1.0,
    ne_cm3=1e17,
)

print(len(result.wls), len(result.intensity))
print(result.lines[:3])
```

Command-line equivalent:

```bash
roboai-libs static --element Ni --range 280 330 --resolution 0.05 --out ni.csv
```

### 3. Mixture spectrum

`proportions` do not need to sum to 1. The client normalizes them before sending
the request.

```python
from roboai_libs_client import RoboAILIBSClient

client = RoboAILIBSClient()

result = client.simulate_static(
    elements=["Ni", "Fe"],
    proportions=[2, 1],
    range_min_nm=280,
    range_max_nm=330,
    resolution_nm=0.05,
    te_ev=1.0,
    ne_cm3=1e17,
)

print(result.wls[:5])
print(result.intensity[:5])
```

Command-line equivalent:

```bash
roboai-libs static \
  --element Ni \
  --element Fe \
  --proportion 2 \
  --proportion 1 \
  --out ni_fe.csv
```

### 4. Instrument broadening

```python
from roboai_libs_client import RoboAILIBSClient

client = RoboAILIBSClient()

result = client.simulate_static(
    elements=["Ni"],
    range_min_nm=280,
    range_max_nm=330,
    resolution_nm=0.05,
    te_ev=1.0,
    ne_cm3=1e17,
    fwhm_nm=0.10,
    instrument_profile="gaussian",
)

print(result.instrument_profile, result.fwhm_nm)
```

### 5. Custom output wavelength grid

Instead of a uniform `range_min_nm`/`range_max_nm`/`resolution_nm` grid, you can
sample the spectrum on your own wavelength grid — for example one exported from
a real spectrometer. `load_wavelength_grid` reads the same file formats as the
web simulator's grid upload (`.npy`, `.csv`, `.txt`, `.tsv`, `.dat`) and
validates the grid like the API does: 2 to 10,000 finite, strictly monotonic
points (a descending grid is reversed automatically).

```python
from roboai_libs_client import RoboAILIBSClient, load_wavelength_grid

client = RoboAILIBSClient()

grid = load_wavelength_grid("my_spectrometer_grid.csv")

result = client.simulate_static(
    elements=["Ni"],
    te_ev=1.0,
    ne_cm3=1e17,
    output_wavelengths_nm=grid,
    output_wavelength_grid_name="my-spectrometer",  # optional label
)

print(result.output_grid)  # echoes the grid metadata back
```

The same two parameters work for `simulate_exposure` and `save_dynamic_hdf5`
requests. If your grid is already in memory, pass any list of wavelengths to
`output_wavelengths_nm` directly — the file helper is just a convenience. Note
that the API limit is 10,000 points, which is higher than the web simulator's
interactive limit for time-resolved views.

### 6. Dynamic exposure

```python
from roboai_libs_client import RoboAILIBSClient

client = RoboAILIBSClient()

result = client.simulate_exposure(
    elements=["Ni"],
    range_min_nm=200,
    range_max_nm=230,
    resolution_nm=0.05,
    te_ev=1.0,
    ne_cm3=1e17,
    fwhm_nm=0.0,
    integration_time_s=1e-6,
    time_resolution_s=100e-9,
)

print(len(result.time_vector))
print(len(result.snapshot_matrix), len(result.snapshot_matrix[0]))
print(len(result.total_exposure))
```

`snapshot_matrix` is the time-wavelength intensity matrix. `total_exposure` is
the time-integrated spectrum.

### 7. Save dynamic HDF5

```python
from roboai_libs_client import RoboAILIBSClient, ExposureRequest

client = RoboAILIBSClient()

request = ExposureRequest(
    elements=["Ni"],
    range_min_nm=200,
    range_max_nm=230,
    resolution_nm=0.05,
    integration_time_s=1e-6,
    time_resolution_s=100e-9,
)

path = client.save_dynamic_hdf5("ni_dynamic.h5", request)
print(f"Saved {path}")
```

Command-line equivalent:

```bash
roboai-libs dynamic --element Ni --out ni_dynamic.h5
```

The current platform API serves HDF5 for completed dynamic exposure jobs. Static
spectra are available through `simulate_static()` as typed JSON results.

### 8. Job control and progress

Dynamic exposure jobs can take minutes. `save_dynamic_hdf5` (and
`export_dynamic_hdf5`) accept an `on_progress` callback that fires whenever the
job's status or slice counts change:

```python
def show(status):
    print(f"{status.status}: {status.slices_done}/{status.slices_total} slices")

client.save_dynamic_hdf5("ni_dynamic.h5", request, on_progress=show)
```

For full control, drive the job lifecycle yourself:

```python
job = client.submit_exposure_job(request)   # returns immediately
print(job.job_id, job.status)               # job.preview holds a coarse preview

status = client.get_job(job.job_id)         # poll once
status = client.wait_for_job(job.job_id, on_progress=show)  # block until done
data = client.download_job_hdf5(job.job_id) # completed job -> HDF5 bytes

client.cancel_job(job.job_id)               # stop a queued or running job
```

By default a submitted job keeps running on the server even if your process
exits — use `cancel_job` to stop one you no longer need. Pass
`cancel_on_disconnect=True` to `submit_exposure_job` to have the server cancel
the job automatically when your connection drops instead.

## API Reference and Parameters

Main client methods:

- `RoboAILIBSClient()` creates a client using the stored login token or
  `ROBOAI_LIBS_API_KEY`.
- `list_elements()` returns element symbols available from the hosted simulator.
- `load_wavelength_grid(path)` reads a custom output wavelength grid file
  (`.npy`, `.csv`, `.txt`, `.tsv`, `.dat`) and returns a validated list for
  `output_wavelengths_nm`.
- `simulate_static(...)` returns a `StaticSpectrumResult`.
- `simulate_exposure(...)` returns an `ExposureResult`.
- `save_dynamic_hdf5(path, request, on_progress=...)` submits a dynamic exposure
  job, waits for it, downloads the HDF5 result, and returns the written `Path`.
- `submit_exposure_job(...)` submits an async exposure job and returns a
  `JobSubmitResult` with the `job_id` and a coarse preview.
- `get_job(job_id)` polls once; `wait_for_job(job_id, on_progress=...)` blocks
  until completion, reporting slice progress.
- `cancel_job(job_id)` stops a queued or running job.
- `download_job_hdf5(job_id)` downloads a completed job's HDF5 result.

Most spectrum requests use the following parameters:

| Parameter | Meaning |
| --- | --- |
| `elements` | Element symbols to include, for example `["Ni"]` or `["Ni", "Fe"]`. |
| `proportions` | Relative element proportions. Values are normalized automatically, so `[2, 1]` becomes 2/3 and 1/3. |
| `range_min_nm` | Start wavelength of the simulated range, in nanometres. |
| `range_max_nm` | End wavelength of the simulated range, in nanometres. |
| `resolution_nm` | Wavelength spacing, in nanometres. Smaller values give finer spectra but require more computation. |
| `te_ev` | Electron temperature in electronvolts. |
| `ne_cm3` | Electron number density in cm^-3. |
| `fwhm_nm` | Instrumental broadening full width at half maximum, in nanometres. Use `0.0` for no instrumental broadening. |
| `instrument_profile` | Instrument broadening profile, usually `"gaussian"` or `"lorentzian"`. |
| `output_wavelengths_nm` | Optional custom output wavelength grid (2 to 10,000 ascending points, in nanometres). Overrides the uniform range/resolution grid. Use `load_wavelength_grid()` to read one from a file. |
| `output_wavelength_grid_name` | Optional label for the custom grid, echoed back in `result.output_grid`. |
| `integration_time_s` | Total simulated exposure time for dynamic simulations, in seconds. |
| `time_resolution_s` | Time step for dynamic simulations, in seconds. |

Typed request models:

- `StaticSpectrumRequest`
- `ExposureRequest`
- `PlasmaConfig`
- `TemporalConfig`

Typed result models:

- `StaticSpectrumResult`
- `ExposureResult`

## Support

For bugs, questions, or feature requests, please open an issue on the
[GitHub repository](https://github.com/RoboAI-Green/roboai-libs-client/issues).

## License

MIT License.
