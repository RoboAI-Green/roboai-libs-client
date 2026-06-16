from roboai_libs_client import RoboAILIBSClient


def main() -> None:
    client = RoboAILIBSClient()
    result = client.simulate_static(
        elements=["Ni"],
        range_min_nm=200,
        range_max_nm=230,
        resolution_nm=0.05,
        te_ev=1.0,
        ne_cm3=1e17,
        fwhm_nm=0.0,
    )

    print(f"Received {len(result.wls)} wavelength points.")
    print(f"First wavelength: {result.wls[0]:.3f} nm")
    print(f"First intensity: {result.intensity[0]:.6g}")


if __name__ == "__main__":
    main()
