from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

StarkModel = Literal["hydrogenic", "mse"]
ContinuumModel = Literal["none", "merlin_physical", "planck_empirical"]


def equal_proportions(elements: list[str]) -> list[float]:
    if not elements:
        raise ValueError("At least one element is required.")
    value = 1.0 / len(elements)
    return [value] * len(elements)


class PlasmaConfig(BaseModel):
    number_of_layers: int = 2
    Te_layer_ratio: float = 0.95
    Ne_layer_ratio: float = 0.95
    length_proportion: float = 0.80
    max_length_m: float = 1e-3


class TemporalConfig(BaseModel):
    beta_temp: float = 0.00233
    gamma_temp: float = 0.24
    beta_dens: float = 0.005
    gamma_dens: float = 2.0
    expansion_tau_ns: float = 800.0
    time_of_highest_temp_ns: float = 100.0
    time_of_highest_dens_ns: float = 100.0


class StaticSpectrumRequest(BaseModel):
    elements: list[str]
    proportions: list[float] | None = None
    te_ev: float = Field(1.0, ge=0.1, le=10.0)
    ne_cm3: float = Field(1e17, ge=1e13, le=1e21)
    resolution_nm: float = Field(0.05, ge=0.0001, le=1.0)
    fwhm_nm: float = Field(0.0, ge=0.0, le=2.0)
    instrument_profile: str = "gaussian"
    range_min_nm: float = Field(200.0, ge=100.0, le=2000.0)
    range_max_nm: float = Field(230.0, ge=101.0, le=2001.0)
    output_wavelengths_nm: list[float] | None = None
    output_wavelength_grid_name: str | None = None
    set_max_charge: int = Field(3, ge=1)
    plasma_config: PlasmaConfig = Field(default_factory=PlasmaConfig)
    stark_model: StarkModel = "hydrogenic"
    continuum_model: ContinuumModel = "none"
    planck_empirical_scale: float = Field(0.0, ge=0.0)

    @field_validator("proportions", mode="after")
    @classmethod
    def validate_proportions(cls, value: list[float] | None, info) -> list[float] | None:
        if value is None:
            return value
        elements = info.data.get("elements") or []
        if len(value) != len(elements):
            raise ValueError("proportions must have the same length as elements.")
        total = sum(value)
        if total <= 0:
            raise ValueError("proportions must sum to a positive value.")
        return [float(x) / total for x in value]

    def api_payload(self) -> dict[str, Any]:
        payload = self.model_dump(exclude_none=True)
        payload["temperature_ev"] = payload.pop("te_ev")
        if payload.get("proportions") is None:
            payload["proportions"] = equal_proportions(self.elements)
        return payload


class ExposureRequest(StaticSpectrumRequest):
    integration_time_s: float = Field(10e-6, ge=1e-9)
    time_resolution_s: float = Field(20e-9, ge=1e-9)
    worker_count: int = Field(4, ge=1, le=16)
    temporal_config: TemporalConfig = Field(default_factory=TemporalConfig)


class OutputGrid(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str | None = None
    name: str | None = None
    point_count: int | None = None
    range_min_nm: float | None = None
    range_max_nm: float | None = None
    step_min_nm: float | None = None
    step_max_nm: float | None = None
    step_median_nm: float | None = None


class SpectrumResultBase(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    wls: list[float] = Field(validation_alias=AliasChoices("wls", "wavelength_nm", "wavelengths_nm"))
    lines: list[dict[str, Any]] = Field(default_factory=list)
    instrument_profile: str | None = None
    fwhm_nm: float | None = Field(None, validation_alias=AliasChoices("fwhm_nm", "instrument_fwhm_nm"))
    output_grid: OutputGrid | None = None

    @property
    def wavelengths_nm(self) -> list[float]:
        return self.wls


class StaticSpectrumResult(SpectrumResultBase):
    intensity: list[float]

    @model_validator(mode="after")
    def validate_dimensions(self) -> "StaticSpectrumResult":
        if len(self.wls) != len(self.intensity):
            raise ValueError("wls and intensity must have the same length.")
        return self


class ExposureResult(SpectrumResultBase):
    total_exposure: list[float] = Field(validation_alias=AliasChoices("total_exposure", "intensity"))
    # Defaults to empty so a total-only result parses: the caller may have asked
    # for the snapshots to be dropped, and a future server-side opt-out would
    # omit the field entirely.
    snapshot_matrix: list[list[float]] = Field(default_factory=list)
    time_vector: list[float] = Field(default_factory=list, validation_alias=AliasChoices("time_vector", "time_s"))
    te_vector: list[float] = Field(default_factory=list, validation_alias=AliasChoices("te_vector", "temperature_eV", "temperature_ev"))
    ne_vector: list[float] = Field(default_factory=list, validation_alias=AliasChoices("ne_vector", "electron_density_cm3", "ne_cm3"))
    length_vector: list[float] = Field(default_factory=list, validation_alias=AliasChoices("length_vector", "length_m"))
    compute_seconds: float | None = None

    @property
    def intensity(self) -> list[float]:
        return self.total_exposure

    @model_validator(mode="after")
    def validate_dimensions(self) -> "ExposureResult":
        if len(self.wls) != len(self.total_exposure):
            raise ValueError("wls and total_exposure must have the same length.")
        if self.snapshot_matrix:
            if len(self.snapshot_matrix) != len(self.time_vector):
                raise ValueError("snapshot_matrix row count must match time_vector length.")
            if any(len(row) != len(self.wls) for row in self.snapshot_matrix):
                raise ValueError("Each snapshot_matrix row must match wls length.")
        return self


class JobSubmitResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str
    status: str
    preview: ExposureResult | None = None


class JobStatusResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str
    status: str
    result: ExposureResult | None = None
    error: str | None = None
    slices_total: int | None = None
    slices_done: int | None = None
    cancel_reason: str | None = None
    cancel_detail: str | None = None
