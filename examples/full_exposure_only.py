"""Run a dynamic exposure and keep only the full exposure spectrum.

``total_exposure`` is what the web simulator plots as "full exposure": the
spectrum integrated over every simulated time step. It is computed on the server
independently of the per-snapshot matrix, so discarding the snapshots costs
nothing in accuracy — it just avoids carrying a [time x wavelength] matrix that
is far larger than the spectrum itself.
"""

from roboai_libs_client import RoboAILIBSClient


def main() -> None:
    client = RoboAILIBSClient()

    request = dict(
        elements=["Ni"],
        range_min_nm=200,
        range_max_nm=230,
        resolution_nm=0.05,
        te_ev=1.0,
        ne_cm3=1e17,
        integration_time_s=1e-6,
        time_resolution_s=100e-9,
    )

    full = client.simulate_exposure(**request)
    lean = client.simulate_exposure(**request, include_snapshots=False)

    print(f"with snapshots: {len(full.snapshot_matrix)} rows")
    print(f"total only    : {len(lean.snapshot_matrix)} rows")
    print(f"full exposure identical: {full.total_exposure == lean.total_exposure}")

    # Write the full exposure as two columns.
    with open("full_exposure.csv", "w") as handle:
        handle.write("wavelength_nm,full_exposure\n")
        for wavelength, intensity in zip(lean.wls, lean.total_exposure):
            handle.write(f"{wavelength},{intensity}\n")
    print(f"Wrote full_exposure.csv with {len(lean.wls)} points.")


if __name__ == "__main__":
    main()
