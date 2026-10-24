"""VoltSpace FastAPI application (Member C - calculation core).

Endpoints
---------
POST /calculate/consumption   monthly kWh for one or many appliances
POST /calculate/cost          estimated electricity bill
POST /calculate/load          current estimate + load warning
POST /recommendations         rule-based energy-saving suggestions
POST /simulate                before/after scenario comparison
GET  /tariffs                 tariff plans available to the frontend
GET  /appliances              reference appliance catalogue
GET  /health                  readiness probe

Run locally::

    uvicorn app.main:app --reload --port 8000

Interactive documentation is then available at ``/docs`` (Swagger UI) and
``/redoc``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

from . import __version__
from .calculators.consumption import ValidationError, calculate_consumption
from .calculators.electricity_bill import (
    TariffError,
    calculate_bill,
    list_plans,
    load_tariffs,
)
from .calculators.load_estimator import LoadError, estimate_load, find_overload_combinations
from .data_check import DataIntegrityError, validate_all
from .schemas import (
    ApplianceCreateRequest,
    ApplianceUpdateRequest,
    ConsumptionRequest,
    ConsumptionResponse,
    CostRequest,
    CostResponse,
    DashboardRequest,
    DashboardResponse,
    ErrorResponse,
    HealthResponse,
    HouseholdReplaceRequest,
    LoadRequest,
    LoadResponse,
    PresetsResponse,
    RecommendationRequest,
    RecommendationResponse,
    SavedAppliance,
    SavedApplianceList,
    SimulationRequest,
    SimulationResponse,
    TariffListResponse,
)
from .services.recommendations import (
    catalog_presets,
    catalog_summary,
    generate_recommendations,
    load_appliance_catalog,
)
from .services.simulation import SimulationError, simulate
from .store import ApplianceStore, StoreError, to_api_appliance


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Fail fast when the data files are broken, and open the household store.

    The tariff table and appliance catalogue drive every calculation, so a typo should
    stop the server at boot with a precise message instead of quietly producing wrong
    bills for the first user who calls an endpoint.
    """

    try:
        summary = validate_all()
    except DataIntegrityError as exc:
        raise RuntimeError(f"VoltSpace data file is invalid: {exc}") from exc
    app.state.data_summary = summary

    store = ApplianceStore()
    try:
        # Touch the database once so a permissions problem surfaces at boot, not on the
        # first save. ``count`` is the cheapest read that proves the file is writable.
        store.count()
    except StoreError as exc:
        raise RuntimeError(f"VoltSpace cannot open its local database: {exc}") from exc
    app.state.store = store
    yield

TAGS_METADATA = [
    {
        "name": "calculations",
        "description": "用電量、電費與電流負載計算。These endpoints are pure functions of the "
        "request body: no database access is required, so Member A can integrate them first.",
    },
    {
        "name": "advice",
        "description": "規則式節電建議與情境模擬。",
    },
    {
        "name": "reference",
        "description": "電價方案與家用電器參考資料（供前端顯示選單與預設值）。",
    },
]

app = FastAPI(
    title="VoltSpace Calculation API",
    version=__version__,
    summary="Member C 的 Python 計算核心：用電量、電費、負載估算、節電建議與情境模擬。",
    description=__doc__,
    openapi_tags=TAGS_METADATA,
    contact={"name": "VoltSpace - Group 9 (Member C)"},
    license_info={"name": "Educational project (NTHU)"},
    lifespan=lifespan,
)

# Every calculation endpoint can return these two error shapes; declaring them as a
# single mapping keeps the OpenAPI document consistent without repeating the models.
CALCULATION_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": ErrorResponse,
        "description": "輸入語意上無法計算（例如找不到指定的家電）。",
    },
    422: {
        "model": ErrorResponse,
        "description": "輸入格式或數值不合理，或電器資料無法通過驗證。",
    },
}

# The React Native client runs from a device/emulator, so the origin is not
# predictable during development. Calculations are stateless and read-only, which
# is why a permissive policy is acceptable for the MVP.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# --- Error handling ----------------------------------------------------------


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Turn Pydantic's error list into VoltSpace's flat error shape."""

    first = exc.errors()[0] if exc.errors() else {}
    location = [str(part) for part in first.get("loc", []) if part != "body"]
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            code="validation_error",
            message=first.get("msg", "請求內容格式不正確"),
            field=".".join(location) or None,
            details=[
                {
                    "field": ".".join(str(part) for part in error.get("loc", []) if part != "body"),
                    "message": error.get("msg"),
                    "type": error.get("type"),
                }
                for error in exc.errors()
            ],
        ).model_dump(),
    )


def _calculation_error(status_code: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(code=code, message=message, **extra).model_dump(),
    )


@app.exception_handler(ValidationError)
async def domain_validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return _calculation_error(422, exc.code, str(exc), field=exc.field_name)


@app.exception_handler(TariffError)
async def tariff_error_handler(request: Request, exc: TariffError) -> JSONResponse:
    return _calculation_error(400, exc.code, str(exc))


@app.exception_handler(SimulationError)
async def simulation_error_handler(request: Request, exc: SimulationError) -> JSONResponse:
    return _calculation_error(400, exc.code, str(exc))


@app.exception_handler(LoadError)
async def load_error_handler(request: Request, exc: LoadError) -> JSONResponse:
    return _calculation_error(400, exc.code, str(exc))


@app.exception_handler(StoreError)
async def store_error_handler(request: Request, exc: StoreError) -> JSONResponse:
    # A missing appliance is a client error; a genuine database failure is a server error.
    message = str(exc)
    if "not found" in message:
        return _calculation_error(404, "appliance_not_found", message)
    return _calculation_error(500, "storage_error", message)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return _calculation_error(400, "invalid_value", str(exc))


# --- 1. Consumption ----------------------------------------------------------


@app.post(
    "/calculate/consumption",
    response_model=ConsumptionResponse,
    tags=["calculations"],
    summary="計算單一或多個家電的每月用電量",
    responses=CALCULATION_ERROR_RESPONSES,
)
async def calculate_consumption_endpoint(
    payload: ConsumptionRequest = Body(
        ...,
        openapi_examples={
            "single": {
                "summary": "單一家電",
                "value": {
                    "appliances": [
                        {
                            "name": "冷氣機",
                            "power_watts": 900,
                            "hours_per_day": 6,
                            "days_per_month": 30,
                            "voltage": 220,
                        }
                    ]
                },
            },
            "household": {
                "summary": "租屋處常見家電",
                "value": {
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
                        {
                            "appliance_id": "a3",
                            "name": "桌上型電腦",
                            "power_watts": 250,
                            "hours_per_day": 6,
                            "days_per_month": 30,
                            "voltage": 110,
                        },
                    ]
                },
            },
        },
    )
) -> ConsumptionResponse:
    """Formula: ``kWh/month = W / 1000 * hours/day * days/month * quantity``."""

    result = calculate_consumption([item.model_dump() for item in payload.appliances])
    return ConsumptionResponse(**result)


# --- 2. Cost -----------------------------------------------------------------


@app.post(
    "/calculate/cost",
    response_model=CostResponse,
    tags=["calculations"],
    summary="估算電費（支援級距、季節與帳單期間）",
    responses=CALCULATION_ERROR_RESPONSES,
)
async def calculate_cost_endpoint(
    payload: CostRequest = Body(
        ...,
        openapi_examples={
            "summer_tiers": {
                "summary": "夏月 520 度（住宅累進電價）",
                "value": {
                    "consumption_kwh": 520,
                    "month": 8,
                    "billing_period": "monthly",
                    "plan_id": "tw_residential_tiered",
                },
            },
            "two_month_bill": {
                "summary": "台電兩個月一期（1040 度）",
                "value": {
                    "consumption_kwh": 1040,
                    "month": 8,
                    "billing_period": "bi_monthly",
                },
            },
            "landlord_flat_rate": {
                "summary": "房東單一費率 5.5 元/度",
                "value": {
                    "consumption_kwh": 400,
                    "plan_id": "flat_rate_resell_reference",
                },
            },
            "from_appliances": {
                "summary": "由家電清單直接估算",
                "value": {
                    "consumption_kwh": 0,
                    "month": 8,
                    "appliances": [
                        {
                            "name": "冷氣機",
                            "power_watts": 900,
                            "hours_per_day": 6,
                            "days_per_month": 30,
                            "voltage": 220,
                        }
                    ],
                },
            },
        },
    )
) -> CostResponse:
    """Prices come from ``app/data/tariffs.json``; no rate is hard-coded."""

    tariff_options: dict[str, Any] = {
        "plan_id": payload.plan_id,
        "month": payload.month,
        "season": payload.season,
        "billing_period": payload.billing_period,
        "billing_months": payload.billing_months,
        "peak_share": payload.peak_share,
    }

    computed_total: float | None = None
    if payload.appliances:
        consumption = calculate_consumption(
            [item.model_dump() for item in payload.appliances]
        )
        computed_total = float(consumption["total_monthly_kwh"])
        consumption_kwh = computed_total
        source = "appliance_list"
    else:
        consumption_kwh = float(payload.consumption_kwh)
        source = "input_kwh"

    bill = calculate_bill(consumption_kwh, **tariff_options)
    bill["consumption_source"] = source
    bill["computed_total_monthly_kwh"] = (
        round(computed_total, 4) if computed_total is not None else None
    )
    return CostResponse(**bill)


# --- 3. Load -----------------------------------------------------------------


@app.post(
    "/calculate/load",
    response_model=LoadResponse,
    tags=["calculations"],
    summary="估算電流並比較負載上限（初步警示，不保證電路安全）",
    responses=CALCULATION_ERROR_RESPONSES,
)
async def calculate_load_endpoint(
    payload: LoadRequest = Body(
        ...,
        openapi_examples={
            "room_circuit": {
                "summary": "房間插座迴路 15A",
                "value": {
                    "appliances": [
                        {"name": "吹風機", "power_watts": 1200, "hours_per_day": 0.3, "voltage": 110},
                        {"name": "電暖器", "power_watts": 1200, "hours_per_day": 3, "voltage": 110},
                        {"name": "桌上型電腦", "power_watts": 250, "hours_per_day": 6, "voltage": 110},
                    ],
                    "voltage": 110,
                    "load_limit_amps": 15,
                    "safety_margin": 0.8,
                    "circuit_label": "房間插座迴路",
                    "include_overload_combinations": True,
                },
            },
            "without_limit": {
                "summary": "只估算電流，未提供上限",
                "value": {
                    "appliances": [
                        {"name": "冷氣機", "power_watts": 900, "hours_per_day": 6, "voltage": 220}
                    ]
                },
            },
        },
    )
) -> LoadResponse:
    """``I = P / (V * PF)`` — running current only; inrush current is not modelled."""

    appliances = [item.model_dump() for item in payload.appliances]
    result = estimate_load(
        appliances,
        voltage=payload.voltage,
        load_limit_amps=payload.load_limit_amps,
        safety_margin=payload.safety_margin,
        phases=payload.phases,
        breaker_amps=payload.breaker_amps,
        circuit_label=payload.circuit_label,
    )

    if payload.include_overload_combinations and payload.load_limit_amps:
        result["overload_combinations"] = find_overload_combinations(
            appliances,
            load_limit_amps=payload.load_limit_amps,
            voltage=float(payload.voltage or 110.0),
            max_combination_size=payload.max_combination_size,
            phases=payload.phases,
        )

    return LoadResponse(**result)


# --- 4. Recommendations ------------------------------------------------------


@app.post(
    "/recommendations",
    response_model=RecommendationResponse,
    tags=["advice"],
    summary="產生規則式節電建議（含原因與預估節省量）",
    responses=CALCULATION_ERROR_RESPONSES,
)
async def recommendations_endpoint(
    payload: RecommendationRequest = Body(
        ...,
        openapi_examples={
            "student_room": {
                "summary": "研究生宿舍常見情境",
                "value": {
                    "appliances": [
                        {
                            "appliance_id": "a1",
                            "name": "冷氣機",
                            "category": "cooling",
                            "power_watts": 900,
                            "hours_per_day": 9,
                            "days_per_month": 30,
                            "voltage": 220,
                        },
                        {
                            "appliance_id": "a2",
                            "name": "冰箱",
                            "category": "cooling",
                            "power_watts": 130,
                            "hours_per_day": 24,
                            "days_per_month": 30,
                            "voltage": 110,
                        },
                        {
                            "appliance_id": "a3",
                            "name": "電熱水器",
                            "category": "heating",
                            "power_watts": 4000,
                            "hours_per_day": 1,
                            "days_per_month": 30,
                            "voltage": 220,
                        },
                    ],
                    "month": 8,
                    "top_n": 3,
                },
            }
        },
    )
) -> RecommendationResponse:
    """Rule-based only: no machine-learning model is trained or required."""

    result = generate_recommendations(
        [item.model_dump() for item in payload.appliances],
        month=payload.month,
        plan_id=payload.plan_id,
        top_n=payload.top_n,
        max_recommendations=payload.max_recommendations,
    )
    return RecommendationResponse(**result)


# --- 5. Simulation -----------------------------------------------------------


@app.post(
    "/simulate",
    response_model=SimulationResponse,
    tags=["advice"],
    summary="比較修改前後的用電量與電費（不會修改原始家電資料）",
    responses=CALCULATION_ERROR_RESPONSES,
)
async def simulate_endpoint(
    payload: SimulationRequest = Body(
        ...,
        openapi_examples={
            "reduce_ac_hours": {
                "summary": "冷氣每天少吹 1 小時",
                "value": {
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
                    ],
                    "changes": [
                        {"appliance_id": "a1", "field": "hours_per_day", "value": 5}
                    ],
                    "month": 8,
                    "plan_id": "tw_residential_tiered",
                    "load_limit_amps": 15,
                },
            },
            "swap_efficient_ac": {
                "summary": "更換為一級能效變頻冷氣並調整時數",
                "value": {
                    "appliances": [
                        {
                            "appliance_id": "a1",
                            "name": "冷氣機",
                            "power_watts": 1400,
                            "hours_per_day": 8,
                            "days_per_month": 30,
                            "voltage": 220,
                        }
                    ],
                    "changes": [
                        {
                            "appliance_id": "a1",
                            "field": "replace_with",
                            "replacement": {
                                "label": "一級能效變頻冷氣",
                                "name": "變頻冷氣機",
                                "power_watts": 700,
                                "hours_per_day": 7,
                            },
                        }
                    ],
                    "month": 8,
                    "load_limit_amps": 15,
                },
            },
        },
    )
) -> SimulationResponse:
    """The original appliance list is copied, so saved user data is never mutated."""

    result = simulate(
        [item.model_dump() for item in payload.appliances],
        [change.model_dump() for change in payload.changes],
        month=payload.month,
        plan_id=payload.plan_id,
        billing_period=payload.billing_period,
        billing_months=payload.billing_months,
        load_limit_amps=payload.load_limit_amps,
        baseline_override_kwh=payload.baseline_override_kwh,
    )
    return SimulationResponse(**result)


# --- Saved household (persistence) -------------------------------------------


def _store(request: Request) -> ApplianceStore:
    store = getattr(request.app.state, "store", None)
    if store is None:  # pragma: no cover - only if lifespan did not run
        raise RuntimeError("the appliance store is not initialised")
    return store


def _saved_list(store: ApplianceStore) -> SavedApplianceList:
    rows = store.list_appliances()
    appliances = [SavedAppliance.from_row(row) for row in rows]
    total = 0.0
    if rows:
        total = float(
            calculate_consumption([to_api_appliance(row) for row in rows])["total_monthly_kwh"]
        )
    return SavedApplianceList(
        count=len(appliances), total_monthly_kwh=round(total, 3), appliances=appliances
    )


@app.get(
    "/household/appliances",
    response_model=SavedApplianceList,
    tags=["household"],
    summary="取得已儲存的家電清單",
)
async def list_saved_appliances(request: Request) -> SavedApplianceList:
    """The persisted household. Calculation endpoints stay stateless; this is the store."""

    return _saved_list(_store(request))


@app.post(
    "/household/appliances",
    response_model=SavedAppliance,
    status_code=201,
    tags=["household"],
    summary="新增一台家電到已儲存清單",
    responses=CALCULATION_ERROR_RESPONSES,
)
async def add_saved_appliance(
    request: Request, payload: ApplianceCreateRequest
) -> SavedAppliance:
    # Validate with the same domain rules the calculators use before persisting, so an
    # impossible appliance can never reach the database.
    appliance = payload.appliance.model_dump()
    calculate_consumption([appliance])
    row = _store(request).add_appliance(appliance)
    return SavedAppliance.from_row(row)


@app.put(
    "/household/appliances/{appliance_id}",
    response_model=SavedAppliance,
    tags=["household"],
    summary="修改已儲存家電的欄位",
    responses=CALCULATION_ERROR_RESPONSES,
)
async def update_saved_appliance(
    request: Request, appliance_id: int, payload: ApplianceUpdateRequest
) -> SavedAppliance:
    changes = payload.model_dump(exclude_none=True)
    existing = _store(request).get_appliance(appliance_id)
    if existing is None:
        raise StoreError(f"appliance {appliance_id} not found")
    # Validate the merged record with the domain rules before writing anything.
    calculate_consumption([to_api_appliance({**existing, **changes})])
    row = _store(request).update_appliance(appliance_id, changes)
    if row is None:
        raise StoreError(f"appliance {appliance_id} not found")
    return SavedAppliance.from_row(row)


@app.delete(
    "/household/appliances/{appliance_id}",
    tags=["household"],
    summary="刪除已儲存的家電",
    responses=CALCULATION_ERROR_RESPONSES,
)
async def delete_saved_appliance(request: Request, appliance_id: int) -> dict[str, Any]:
    if not _store(request).delete_appliance(appliance_id):
        raise StoreError(f"appliance {appliance_id} not found")
    return {"deleted": True, "appliance_id": appliance_id}


@app.put(
    "/household/appliances",
    response_model=SavedApplianceList,
    tags=["household"],
    summary="整批覆蓋已儲存的家電（前端「儲存全部」）",
    responses=CALCULATION_ERROR_RESPONSES,
)
async def replace_saved_appliances(
    request: Request, payload: HouseholdReplaceRequest
) -> SavedApplianceList:
    appliances = [item.model_dump() for item in payload.appliances]
    if appliances:
        calculate_consumption(appliances)
    store = _store(request)
    store.replace_appliances(appliances)
    return _saved_list(store)


@app.post(
    "/household/dashboard",
    response_model=DashboardResponse,
    tags=["household"],
    summary="一次取得儀表板所需的全部計算（用電量、電費、負載、建議）",
    responses=CALCULATION_ERROR_RESPONSES,
)
async def household_dashboard(request: Request, payload: DashboardRequest) -> DashboardResponse:
    """One round trip for the whole dashboard.

    Replaces the frontend's client-side arithmetic: every number here comes from the
    tested calculators, so the UI never re-implements a formula or hard-codes a tariff.
    """

    if payload.appliances is not None:
        appliances = [item.model_dump() for item in payload.appliances]
        source = "request"
    else:
        rows = _store(request).list_appliances()
        appliances = [to_api_appliance(row) for row in rows]
        source = "saved"

    rows = [
        {
            "id": int(item.get("appliance_id") or index + 1),
            "name": item["name"],
            "category": item.get("category"),
            "power_watts": item["power_watts"],
            "hours_per_day": item["hours_per_day"],
            "days_per_month": item.get("days_per_month", 30),
            "quantity": item.get("quantity", 1),
            "voltage": item.get("voltage"),
            "power_factor": item.get("power_factor"),
        }
        for index, item in enumerate(appliances)
    ]

    tariff_options = {
        "plan_id": payload.plan_id,
        "month": payload.month,
        "season": payload.season,
        "billing_period": payload.billing_period,
        "billing_months": payload.billing_months,
        "peak_share": payload.peak_share,
    }

    consumption = calculate_consumption(appliances)
    # Even an empty household must render: bill 0 kWh and show the applicable rate.
    bill = calculate_bill(float(consumption["total_monthly_kwh"]), **tariff_options)

    load = None
    if appliances:
        load = estimate_load(
            appliances,
            voltage=payload.voltage,
            load_limit_amps=payload.load_limit_amps,
            safety_margin=payload.safety_margin,
            phases=payload.phases,
            breaker_amps=payload.breaker_amps,
        )

    recommendations = None
    if payload.include_recommendations and appliances:
        recommendations = generate_recommendations(
            appliances,
            month=payload.month,
            plan_id=payload.plan_id,
            top_n=payload.top_n,
            max_recommendations=payload.max_recommendations,
        )

    summary = {
        "total_monthly_kwh": consumption["total_monthly_kwh"],
        "total_daily_kwh": consumption["total_daily_kwh"],
        "estimated_monthly_cost_twd": bill["total_amount"],
        "effective_rate_per_kwh": bill["effective_rate_per_kwh"],
        "season_label_zh": bill["season_label_zh"],
        "estimated_total_current_amps": load["estimated_total_current_amps"] if load else None,
        "load_verdict": load["verdict"] if load else None,
        "load_severity": load["severity"] if load else None,
        "highest_consumption_appliance": consumption["highest_consumption_appliance"],
        "potential_monthly_saving_kwh": (
            recommendations["total_potential_monthly_saving_kwh"] if recommendations else None
        ),
        "potential_monthly_saving_twd": (
            recommendations["total_potential_monthly_saving_twd"] if recommendations else None
        ),
        "currency": "TWD",
    }

    return DashboardResponse(
        source=source,
        appliance_count=len(appliances),
        appliances=[SavedAppliance(**row) for row in rows],
        consumption=ConsumptionResponse(**consumption),
        bill=CostResponse(**bill),
        load=LoadResponse(**load) if load else None,
        recommendations=RecommendationResponse(**recommendations) if recommendations else None,
        summary=summary,
    )


# --- Reference endpoints -----------------------------------------------------


@app.get(
    "/appliances/presets",
    response_model=PresetsResponse,
    tags=["reference"],
    summary="前端「家電庫」用的預設值（功率、電壓、迴路上限、參考費率）",
)
async def get_appliance_presets() -> PresetsResponse:
    """Replaces the hard-coded appliance list, 1650 W ceiling and 3.5 TWD rate."""

    return PresetsResponse(**catalog_presets())


@app.get(
    "/tariffs",
    response_model=TariffListResponse,
    tags=["reference"],
    summary="取得可用的電價方案與級距資料",
)
async def get_tariffs() -> TariffListResponse:
    """Lets the frontend build the tariff selector and show the official tier table."""

    data = load_tariffs()
    return TariffListResponse(
        schema_version=data.get("schema_version", "unknown"),
        updated_at=data.get("updated_at"),
        default_plan_id=data["default_plan_id"],
        notes=data.get("notes", []),
        plans=list_plans(),
    )


@app.get(
    "/appliances",
    tags=["reference"],
    summary="取得家用電器參考資料（典型功率、電壓與使用時數）",
)
async def get_appliances() -> dict[str, Any]:
    """Reference values Member A can use as form defaults, and Member B can mirror."""

    return catalog_summary()


@app.get("/health", response_model=HealthResponse, tags=["reference"], summary="健康檢查")
async def health() -> HealthResponse:
    data = load_tariffs()
    # The catalogue size is a constant of the data file, so read it directly instead of
    # building the whole summary payload just to count it.
    catalogue = load_appliance_catalog()
    return HealthResponse(
        status="ok",
        service="VoltSpace Calculation API",
        version=__version__,
        tariff_schema_version=data.get("schema_version", "unknown"),
        tariff_default_plan=data["default_plan_id"],
        appliance_catalog_count=len(catalogue["appliances"]),
        storage="local-sqlite",
    )


@app.get("/api", include_in_schema=False)
async def api_index() -> dict[str, Any]:
    """Machine-readable index of the endpoints (the UI itself is served at ``/``)."""

    return {
        "service": "VoltSpace Calculation API",
        "version": __version__,
        "docs": "/docs",
        "ui": "/",
        "endpoints": [
            "POST /calculate/consumption",
            "POST /calculate/cost",
            "POST /calculate/load",
            "POST /recommendations",
            "POST /simulate",
            "GET  /tariffs",
            "GET  /appliances",
            "GET  /appliances/presets",
            "GET  /household/appliances",
            "POST /household/appliances",
            "PUT  /household/appliances/{id}",
            "DELETE /household/appliances/{id}",
            "PUT  /household/appliances",
            "POST /household/dashboard",
            "GET  /health",
        ],
    }


# --- The web UI --------------------------------------------------------------
# Mounted last so it never shadows an API route. ``/`` serves index.html; the assets live
# under ``/app`` so they cannot collide with API paths.
if WEB_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=WEB_DIR), name="app-assets")

    @app.get("/", include_in_schema=False)
    async def ui_index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")
