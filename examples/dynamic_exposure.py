from roboai_libs_client import RoboAILIBSClient


def main() -> None:
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

    print(f"Received {len(result.wls)} wavelength points.")
    print(f"Received {len(result.time_vector)} time points.")
    print(
        "Snapshot matrix shape: "
        f"{len(result.snapshot_matrix)} x "
        f"{len(result.snapshot_matrix[0]) if result.snapshot_matrix else 0}"
    )
    print(f"First total-exposure intensity: {result.total_exposure[0]:.6g}")


if __name__ == "__main__":
    main()
