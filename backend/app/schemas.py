"""Pydantic request / response models for the VoltSpace API.

Two layers of validation are used on purpose:

1. **Pydantic** (this file) checks the JSON *shape* and rejects obviously malformed
   payloads with HTTP 422 before any calculation runs.
2. **Calculator validation** (``app/calculators/consumption.py``) owns the domain
   rules and is shared by the API and the unit tests, so both paths agree.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --- Shared building blocks --------------------------------------------------

BillingPeriod = Literal["monthly", "bi_monthly"]
SeasonLiteral = Literal["summer", "non_summer"]


def _build_plan_enum() -> type[Enum]:
    """Build the plan-id enum from the tariff data file.

    Deriving the enum instead of hard-coding the ids means adding a plan to
    ``tariffs.json`` needs no code change, and a removed plan cannot linger as an
    accepted value. ``app.data_check`` validates the file before this runs.
    """

    from .calculators.electricity_bill import available_plan_ids

    return Enum("PlanId", {plan_id: plan_id for plan_id in available_plan_ids()}, type=str)


PlanId = _build_plan_enum()

PowerWatts = Annotated[
    float,
    Field(
        gt=0,
        le=100_000,
        description="額定功率（瓦特 W）。冷氣常見 700-2200W，電熱水器可達 4000W 以上。",
        examples=[900],
    ),
]
HoursPerDay = Annotated[
    float,
    Field(
        ge=0,
        le=24,
        description="每日使用時數（小時）。冰箱請填 24。",
        examples=[6],
    ),
]
DaysPerMonth = Annotated[
    int,
    Field(ge=0, le=31, description="每月使用天數。", examples=[30]),
]
Quantity = Annotated[int, Field(ge=1, le=999, description="相同電器的數量。", examples=[1])]
Voltage = Annotated[
    float,
    Field(gt=0, le=1000, description="使用電壓（V）。台灣家用常見 110V 與 220V。", examples=[110]),
]


class ApplianceIn(BaseModel):
    """One appliance sent by the frontend, with the user's usage habit."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "appliance_id": "a1",
                "name": "冷氣機",
                "category": "cooling",
                "power_watts": 900,
                "hours_per_day": 6,
                "days_per_month": 30,
                "quantity": 1,
                "voltage": 220,
            }
        },
    )

    appliance_id: str | None = Field(
        default=None, max_length=64, description="Member B 資料庫的主鍵（可選）。"
    )
    name: str = Field(min_length=1, max_length=80, description="家電名稱。", examples=["冷氣機"])
    category: str | None = Field(
        default=None, max_length=40, description="分類（可選），用於比對參考資料庫。"
    )
    power_watts: PowerWatts
    hours_per_day: HoursPerDay
    days_per_month: DaysPerMonth = 30
    quantity: Quantity = 1
    voltage: Voltage | None = Field(
        default=None,
        description=(
            "使用電壓（V），台灣家用常見 110V 與 220V。未提供時由計算端套用預設值"
            "（用電量計算不影響結果；負載估算會改用 /calculate/load 的 voltage，未提供則為 110V）。"
        ),
        examples=[110],
    )
    power_factor: float | None = Field(
        default=None,
        ge=0.1,
        le=1.0,
        description=(
            "功率因數（0.1–1.0），僅影響 /calculate/load 的電流估算。馬達、壓縮機等電感性"
            "負載可填 0.8–0.9；未提供時以 1.0（純電阻性、電流最小）估算，等於最保守的上限。"
        ),
        examples=[1.0],
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name 不能是空白字串")
        return stripped

    @model_validator(mode="after")
    def _reject_impossible_usage(self) -> "ApplianceIn":
        # A running appliance cannot consume more than 24h * days in a month.
        if self.hours_per_day * self.days_per_month > 24 * 31:
            raise ValueError("hours_per_day * days_per_month 超過一個月的總時數")
        return self


class TariffOptions(BaseModel):
    """Tariff selection shared by the cost, recommendation and simulation endpoints."""

    model_config = ConfigDict(extra="forbid")

    plan_id: PlanId | None = Field(
        default=None,
        description="電價方案。未提供時使用 tariffs.json 的 default_plan_id（住宅累進電價）。",
    )
    month: int | None = Field(
        default=None, ge=1, le=12, description="月份（1-12），用來判斷夏月／非夏月電價。"
    )
    season: SeasonLiteral | None = Field(
        default=None, description="強制指定季節；提供時會覆蓋 month 的判斷。"
    )
    billing_period: BillingPeriod = Field(
        default="monthly",
        description="帳單期間。bi_monthly 時級距上限會依 months 放大（台電兩個月一期）。",
    )
    billing_months: int | None = Field(
        default=None,
        ge=1,
        le=12,
        description="帳單涵蓋月數，會覆蓋 billing_period 的預設值。",
    )
    peak_share: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description="時間電價方案中尖峰時段用電占比（0-1），其他方案會忽略。",
    )


# --- 1. /calculate/consumption ------------------------------------------------


class ConsumptionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "appliances": [
                    {
                        "appliance_id": "a1",
                        "name": "冷氣機",
                        "power_watts": 900,
                        "hours_per_day": 6,
                        "days_per_month": 30,
                        "voltage": 220,
                    },
                    {
                        "appliance_id": "a2",
                        "name": "冰箱",
                        "power_watts": 130,
                        "hours_per_day": 24,
                        "days_per_month": 30,
                        "voltage": 110,
                    },
                ]
            }
        },
    )

    appliances: list[ApplianceIn] = Field(
        min_length=1, max_length=200, description="要計算的家電清單，至少一筆。"
    )


class ApplianceConsumptionOut(BaseModel):
    appliance_id: str | None = None
    name: str
    category: str | None = None
    power_watts: float
    hours_per_day: float
    days_per_month: int
    quantity: int
    daily_kwh: float
    monthly_kwh: float
    share_of_total_percent: float | None = None
    replacement_label: str | None = Field(
        default=None, description="模擬情境中取代此家電的機種名稱（僅 /simulate 會回填）。"
    )
    replaced_from: str | None = Field(
        default=None, description="若此筆是替換後的機種，這裡是它原本的家電名稱。"
    )
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class ConsumptionResponse(BaseModel):
    count: int
    total_daily_kwh: float
    total_monthly_kwh: float
    average_monthly_kwh_per_appliance: float
    highest_consumption_appliance: str | None = None
    appliances: list[ApplianceConsumptionOut]


# --- 2. /calculate/cost -------------------------------------------------------


class CostRequest(TariffOptions):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "consumption_kwh": 520,
                "month": 8,
                "billing_period": "monthly",
                "plan_id": "tw_residential_tiered",
            }
        },
    )

    consumption_kwh: float = Field(
        ge=0, le=1_000_000, description="要估算的用電量（度 kWh）。", examples=[520]
    )
    appliances: list[ApplianceIn] | None = Field(
        default=None,
        max_length=200,
        description="可選。提供時會先計算這些家電的總用電量，並忽略 consumption_kwh。",
    )

    @model_validator(mode="after")
    def _need_a_source_of_consumption(self) -> "CostRequest":
        if self.appliances and len(self.appliances) > 0:
            return self
        if self.consumption_kwh is None:
            raise ValueError("請提供 consumption_kwh 或 appliances 其中之一")
        return self


class BillLineOut(BaseModel):
    tier_index: int
    label_zh: str | None = None
    range_from_kwh: float | None = None
    range_to_kwh: float | None = None
    rate_per_kwh: float
    kwh_in_tier: float
    amount: float


class CostResponse(BaseModel):
    plan_id: str
    plan_name_en: str | None = None
    plan_name_zh: str | None = None
    plan_type: str
    season: str
    season_label_en: str
    season_label_zh: str
    billing_months: int
    consumption_kwh: float
    total_amount: float
    total_amount_rounded: int
    currency: str = "TWD"
    effective_rate_per_kwh: float
    lines: list[BillLineOut]
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    is_estimate: bool = True
    # Present only when the caller supplied an appliance list.
    consumption_source: Literal["input_kwh", "appliance_list"] = "input_kwh"
    computed_total_monthly_kwh: float | None = None


# --- 3. /calculate/load -------------------------------------------------------


class LoadRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "appliances": [
                    {"name": "吹風機", "power_watts": 1200, "hours_per_day": 0.3, "voltage": 110},
                    {"name": "電暖器", "power_watts": 1200, "hours_per_day": 3, "voltage": 110},
                ],
                "voltage": 110,
                "load_limit_amps": 15,
                "safety_margin": 0.8,
                "breaker_amps": 20,
                "circuit_label": "房間插座迴路",
            }
        },
    )

    appliances: list[ApplianceIn] = Field(
        min_length=1, max_length=200, description="要估算電流的家電清單。"
    )
    voltage: Voltage | None = Field(
        default=None, description="住處供電電壓；未提供單一家電電壓時使用（預設 110V）。"
    )
    load_limit_amps: float | None = Field(
        default=None,
        gt=0,
        le=1000,
        description="使用者輸入的迴路／插座負載上限（安培 A）。台灣房間常見 15A 或 20A。",
        examples=[15],
    )
    breaker_amps: float | None = Field(
        default=None, gt=0, le=1000, description="斷路器額定電流（可選），用於補充說明。"
    )
    safety_margin: float = Field(
        default=0.8, ge=0.1, le=1.0, description="建議使用上限的比例，預設 0.8（80%）。"
    )
    phases: Literal[1, 3] = Field(default=1, description="供電相數，一般住家為單相（1）。")
    circuit_label: str | None = Field(
        default=None, max_length=60, description="迴路名稱（可選），方便前端顯示。"
    )
    include_overload_combinations: bool = Field(
        default=False, description="設為 true 時，額外找出會超載的電器同時使用組合。"
    )
    max_combination_size: int = Field(
        default=4, ge=2, le=6, description="超載組合搜尋的最大電器數量。"
    )


class ApplianceLoadOut(BaseModel):
    appliance_id: str | None = None
    name: str
    power_watts: float
    voltage: float
    power_factor: float
    quantity: int
    current_amps: float
    apparent_power_va: float
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class LoadResponse(BaseModel):
    circuit_label: str | None = None
    voltage_used: float
    phases: int
    appliance_count: int
    total_power_watts: float
    total_apparent_power_va: float
    estimated_total_current_amps: float
    limit_amps: float | None = None
    breaker_amps: float | None = None
    safety_margin: float
    recommended_max_current_amps: float | None = None
    usage_percent_of_limit: float | None = None
    verdict: Literal["safe", "near_limit", "over_limit", "no_limit"]
    severity: Literal["ok", "warning", "danger", "info"]
    verdict_message_zh: str
    highest_current_appliance: dict[str, Any] | None = None
    appliances: list[ApplianceLoadOut]
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    disclaimer_zh: str
    disclaimer_en: str
    overload_combinations: dict[str, Any] | None = None


# --- 4. /recommendations ------------------------------------------------------


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "appliances": [
                    {
                        "name": "冷氣機",
                        "power_watts": 900,
                        "hours_per_day": 9,
                        "days_per_month": 30,
                        "voltage": 220,
                    },
                    {
                        "name": "冰箱",
                        "power_watts": 130,
                        "hours_per_day": 24,
                        "days_per_month": 30,
                        "voltage": 110,
                    },
                ],
                "month": 8,
                "top_n": 2,
            }
        },
    )

    appliances: list[ApplianceIn] = Field(
        min_length=1, max_length=200, description="使用者目前的家電清單。"
    )
    plan_id: PlanId | None = None
    month: int | None = Field(default=None, ge=1, le=12, description="用於選擇電價季節。")
    top_n: int | None = Field(
        default=None, ge=1, le=50, description="要標示為高用電量的家電數量，預設為前 3 名。"
    )
    max_recommendations: int = Field(
        default=20, ge=1, le=100, description="回傳的建議數量上限。"
    )


class RecommendationOut(BaseModel):
    id: str = Field(description="規則識別碼（同一條規則可能套用在多台家電上）。")
    recommendation_key: str = Field(
        default="", description="家電 + 規則的唯一鍵（用於列表 key 與去除重複）。"
    )
    appliance: str
    appliance_key: str = Field(
        default="",
        description="家電身分（appliance_id，或電池內的位置索引）：同名電器會各自計數。",
    )
    title_zh: str
    reason_zh: str
    suggestion_zh: str
    estimated_monthly_saving_kwh: float
    estimated_monthly_saving_twd: float
    estimated_annual_saving_twd: float
    assumption_zh: str
    priority: int
    severity: Literal["high", "medium", "low", "info"]
    confidence: Literal["high", "medium", "low"]
    rule_id: str | None = None
    advice_only: bool | None = None
    is_purchase_advice: bool | None = None
    alternative_label_zh: str | None = None
    alternative_power_watts: float | None = None
    share_of_total_percent: float | None = None


class RecommendationResponse(BaseModel):
    currency: str = "TWD"
    month: int | None = None
    plan_id: str | None = None
    total_monthly_kwh: float
    blended_rate_per_kwh: float
    top_consumers: list[dict[str, Any]]
    high_consumption_threshold_percent: float
    recommendation_count: int
    total_potential_monthly_saving_kwh: float = Field(
        description="每台家電只取其最有效的一項建議後加總，避免重複計算。"
    )
    total_potential_monthly_saving_twd: float
    total_potential_annual_saving_twd: float
    potential_saving_percent_of_usage: float
    comprehensive_monthly_saving_kwh: float = Field(
        description="所有建議都落實時的合計（同一台家電可能重複計入，故數字較大）。"
    )
    comprehensive_monthly_saving_twd: float
    aggregation_note_zh: str
    recommendations: list[RecommendationOut]
    per_appliance: list[dict[str, Any]]
    disclaimer_zh: str
    disclaimer_en: str


# --- 5. /simulate -------------------------------------------------------------


class ReplacementIn(BaseModel):
    """A different appliance (e.g. a more efficient brand) used as the "after" side."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=80)
    label: str | None = Field(default=None, max_length=80, description="前端顯示用的名稱。")
    power_watts: float | None = Field(default=None, gt=0, le=100_000)
    voltage: float | None = Field(default=None, gt=0, le=1000)
    power_factor: float | None = Field(default=None, ge=0.1, le=1.0)
    hours_per_day: float | None = Field(default=None, ge=0, le=24)
    days_per_month: int | None = Field(default=None, ge=0, le=31)
    quantity: int | None = Field(default=None, ge=1, le=999)


class ScenarioChange(BaseModel):
    """One what-if edit applied to the *copy* used by the simulator."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "appliance_id": "a1",
                "field": "hours_per_day",
                "value": 5,
                "label_zh": "冷氣每天少吹 1 小時",
            }
        },
    )

    appliance_id: str | None = Field(default=None, description="要修改的家電 id。")
    name: str | None = Field(default=None, description="或用家電名稱指定。")
    field: Literal["hours_per_day", "power_watts", "days_per_month", "quantity", "replace_with"]
    value: float | None = Field(default=None, description="field 為 replace_with 以外的修改值。")
    replacement: ReplacementIn | None = Field(
        default=None, description="field 為 replace_with 時，用來取代的新機種。"
    )
    label_zh: str | None = Field(default=None, max_length=120, description="情境說明的顯示文字。")

    @model_validator(mode="after")
    def _check_target_and_value(self) -> "ScenarioChange":
        if not self.appliance_id and not self.name:
            raise ValueError("每個 change 需要 appliance_id 或 name")
        if self.field == "replace_with":
            if self.replacement is None:
                raise ValueError("field 為 replace_with 時必須提供 replacement")
        elif self.value is None:
            raise ValueError(f"field 為 {self.field} 時必須提供 value")
        elif self.field in ("days_per_month", "quantity") and float(self.value) != int(self.value):
            raise ValueError(f"{self.field} 必須是整數")
        return self


class SimulationRequest(TariffOptions):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "appliances": [
                    {
                        "appliance_id": "a1",
                        "name": "冷氣機",
                        "power_watts": 900,
                        "hours_per_day": 6,
                        "days_per_month": 30,
                        "voltage": 220,
                    }
                ],
                "changes": [
                    {"appliance_id": "a1", "field": "hours_per_day", "value": 5},
                    {
                        "appliance_id": "a1",
                        "field": "replace_with",
                        "replacement": {"label": "一級能效變頻冷氣", "power_watts": 700},
                    },
                ],
                "month": 8,
                "load_limit_amps": 15,
            }
        },
    )

    appliances: list[ApplianceIn] = Field(
        min_length=1, max_length=200, description="使用者目前已儲存的家電（不會被修改）。"
    )
    changes: list[ScenarioChange] = Field(
        min_length=1, max_length=50, description="要模擬的修改清單。"
    )
    load_limit_amps: float | None = Field(
        default=None, gt=0, le=1000, description="提供時會一併比較修改前後的電流。"
    )
    baseline_override_kwh: float | None = Field(
        default=None,
        ge=0,
        le=1_000_000,
        description="可選。若已有實際抄表度數，可用它取代由家電清單推算的基準用電量。",
    )


class SimulationResponse(BaseModel):
    currency: str = "TWD"
    month: int | None = None
    plan_id: str
    billing_period: str
    billing_months: int = Field(
        default=1, description="這一期帳單涵蓋的月數（依 billing_period／billing_months 換算）。"
    )
    season_label_zh: str | None = None
    baseline: dict[str, Any]
    modified: dict[str, Any]
    delta: dict[str, Any]
    comparison_table: list[dict[str, Any]]
    appliance_deltas: list[dict[str, Any]]
    applied_changes: list[dict[str, Any]]
    load: dict[str, Any] | None = None
    notes: list[str] = Field(default_factory=list)


# --- Supporting endpoints ----------------------------------------------------


class PlanSummary(BaseModel):
    id: str
    name_en: str | None = None
    name_zh: str | None = None
    type: str
    currency: str
    unit: str
    applicable_to: str | None = None
    effective_from: str | None = None
    is_estimate: bool = False
    supports_billing_months: bool = False


class TariffListResponse(BaseModel):
    schema_version: str
    updated_at: str | None = None
    default_plan_id: str
    notes: list[str] = Field(default_factory=list)
    plans: list[PlanSummary]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    tariff_schema_version: str
    tariff_default_plan: str
    appliance_catalog_count: int
    storage: Literal["local-sqlite", "supabase", "memory"] = Field(
        default="local-sqlite",
        description="The app currently persists the household in a local SQLite file.",
    )


# --- Saved-household endpoints -----------------------------------------------


class SavedAppliance(BaseModel):
    """One persisted appliance, as returned by the store endpoints."""

    id: int
    name: str
    category: str | None = None
    power_watts: float
    hours_per_day: float
    days_per_month: int = 30
    quantity: int = 1
    voltage: float | None = None
    power_factor: float | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "SavedAppliance":
        return cls(
            id=int(row["id"]),
            name=row["name"],
            category=row.get("category"),
            power_watts=float(row["power_watts"]),
            hours_per_day=float(row["hours_per_day"]),
            days_per_month=int(row["days_per_month"]),
            quantity=int(row["quantity"]),
            voltage=row.get("voltage"),
            power_factor=row.get("power_factor"),
        )


class SavedApplianceList(BaseModel):
    count: int
    total_monthly_kwh: float = Field(
        description="Total monthly consumption of the saved household, so the UI can show it "
        "without a second request."
    )
    appliances: list[SavedAppliance]


class ApplianceCreateRequest(TariffOptions):
    """Add one appliance to the saved household."""

    model_config = ConfigDict(extra="forbid")

    appliance: ApplianceIn


class ApplianceUpdateRequest(BaseModel):
    """Change individual fields of a saved appliance."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    category: str | None = Field(default=None, max_length=40)
    power_watts: PowerWatts | None = None
    hours_per_day: HoursPerDay | None = None
    days_per_month: DaysPerMonth | None = None
    quantity: Quantity | None = None
    voltage: Voltage | None = None
    power_factor: float | None = Field(default=None, ge=0.1, le=1.0)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ApplianceUpdateRequest":
        if not any(
            value is not None
            for value in (
                self.name,
                self.category,
                self.power_watts,
                self.hours_per_day,
                self.days_per_month,
                self.quantity,
                self.voltage,
                self.power_factor,
            )
        ):
            raise ValueError("provide at least one field to update")
        return self


class HouseholdReplaceRequest(BaseModel):
    """Replace the saved household in one call ("save all" from the UI)."""

    model_config = ConfigDict(extra="forbid")

    appliances: list[ApplianceIn] = Field(min_length=0, max_length=200)


class DashboardRequest(TariffOptions):
    """Everything the dashboard needs in a single request.

    ``appliances`` may be omitted, in which case the saved household is used. That lets
    the UI render an unsaved scratchpad *and* the persisted list with one code path.
    """

    model_config = ConfigDict(extra="forbid")

    appliances: list[ApplianceIn] | None = Field(
        default=None,
        max_length=200,
        description="Use these instead of the saved household (for live editing).",
    )
    load_limit_amps: float | None = Field(
        default=None, gt=0, le=1000, description="迴路／插座的上限（安培）。"
    )
    voltage: Voltage | None = Field(
        default=None,
        description="住處供電電壓，用於沒有標示電壓的家電（未提供則為 110V）。",
    )
    breaker_amps: float | None = Field(default=None, gt=0, le=1000)
    safety_margin: float = Field(default=0.8, ge=0.1, le=1.0)
    phases: Literal[1, 3] = Field(default=1)
    include_recommendations: bool = Field(
        default=True, description="設為 false 可略過規則式建議，加快回應。"
    )
    top_n: int | None = Field(default=None, ge=1, le=50)
    max_recommendations: int = Field(default=8, ge=1, le=100)


class DashboardResponse(BaseModel):
    source: Literal["saved", "request"]
    appliance_count: int
    appliances: list[SavedAppliance]
    consumption: ConsumptionResponse
    bill: CostResponse
    load: LoadResponse | None = None
    recommendations: RecommendationResponse | None = None
    summary: dict[str, Any] = Field(
        default_factory=dict,
        description="給 UI 直接顯示的關鍵數字（總度數、電費、電流、可節省量）。",
    )


class CatalogPresetOut(BaseModel):
    key: str
    name_zh: str
    name_en: str
    category: str
    power_watts: float
    power_range_watts: list[float]
    voltage: float
    hours_per_day: float
    days_per_month: int
    is_high_power: bool
    always_on: bool


class CircuitPresetOut(BaseModel):
    label_zh: str
    label_en: str
    amps: float
    voltage: float
    max_watts: float


class PresetsResponse(BaseModel):
    defaults: dict[str, Any]
    presets: list[CatalogPresetOut]
    circuits: list[CircuitPresetOut]
    default_circuit_amps: float
    default_voltage: float
    default_plan_id: str
    reference_rate_per_kwh: float
    reference_season: str


class ErrorResponse(BaseModel):
    """Shape of every 4xx/5xx body VoltSpace returns."""

    error: bool = True
    code: str
    message: str
    field: str | None = None
    details: Any | None = None
