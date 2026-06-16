from roboai_libs_client import RoboAILIBSClient, ExposureRequest


def main() -> None:
    client = RoboAILIBSClient()

    dynamic_request = ExposureRequest(
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
    dynamic_path = client.save_dynamic_hdf5(
        "ni_dynamic.h5",
        dynamic_request,
        poll_interval_s=1.0,
        timeout_s=600.0,
    )
    print(f"Saved dynamic HDF5 export to {dynamic_path}")


if __name__ == "__main__":
    main()
