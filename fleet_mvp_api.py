from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Optional

from flask import Flask, Response, jsonify, request
from sqlalchemy import Boolean, Float, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Vehicle(Base):
    __tablename__ = "vehicles"

    vehicle_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    make: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    license_plate: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    created_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)


class Driver(Base):
    __tablename__ = "drivers"

    driver_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    license_number: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    contact_info: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    event_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    driver_id: Mapped[str] = mapped_column(String(40), nullable=False)
    vehicle_id: Mapped[str] = mapped_column(String(40), nullable=False)
    gps_lat: Mapped[float] = mapped_column(Float, nullable=False)
    gps_lng: Mapped[float] = mapped_column(Float, nullable=False)
    speed_kph: Mapped[float] = mapped_column(Float, nullable=False)
    drowsy_alert: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    distracted_alert: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    event_ts_ms: Mapped[int] = mapped_column(Integer, nullable=False)


@dataclass(frozen=True)
class SecurityConfig:
    api_keys: dict[str, str]


def _model_to_dict(model: Any) -> dict[str, Any]:
    return {
        column.name: getattr(model, column.name)
        for column in model.__table__.columns  # type: ignore[attr-defined]
    }


def _default_api_keys() -> dict[str, str]:
    return {
        "viewer_key_local": "viewer",
        "operator_key_local": "operator",
        "admin_key_local": "admin",
    }


def _load_security_config(config: dict[str, Any]) -> SecurityConfig:
    configured = config.get("API_KEYS")
    if isinstance(configured, dict) and configured:
        return SecurityConfig(api_keys={str(k): str(v) for k, v in configured.items()})

    env_value = os.getenv("NETRA_API_KEYS_JSON", "")
    if env_value:
        try:
            parsed = json.loads(env_value)
            if isinstance(parsed, dict) and parsed:
                return SecurityConfig(api_keys={str(k): str(v) for k, v in parsed.items()})
        except json.JSONDecodeError:
            pass

    return SecurityConfig(api_keys=_default_api_keys())


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def create_app(config: Optional[dict[str, Any]] = None) -> Flask:
    cfg = config or {}
    app = Flask(__name__)

    database_url = str(cfg.get("DATABASE_URL") or os.getenv("DATABASE_URL") or "sqlite:///artifacts/fleet_mvp.db")
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, connect_args=connect_args)
    session_local = sessionmaker(bind=engine, expire_on_commit=False)

    if bool(cfg.get("AUTO_CREATE_SCHEMA", True)):
        Base.metadata.create_all(engine)

    security = _load_security_config(cfg)

    def require_role(allowed_roles: list[str]) -> Callable[..., Any]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                api_key = request.headers.get("X-API-Key", "")
                role = security.api_keys.get(api_key)
                if role is None:
                    return jsonify({"error": "unauthorized"}), 401
                if role not in allowed_roles:
                    return jsonify({"error": "forbidden", "required_roles": allowed_roles}), 403
                return func(*args, **kwargs)

            return wrapper

        return decorator

    @app.get("/health")
    def health() -> Response:
        return jsonify({"status": "ok"})

    @app.get("/api/vehicles")
    @require_role(["viewer", "operator", "admin"])
    def list_vehicles() -> Response:
        with session_local() as session:
            vehicles = session.scalars(select(Vehicle).order_by(Vehicle.created_at_ms.desc())).all()
        return jsonify([_model_to_dict(v) for v in vehicles])

    @app.post("/api/vehicles")
    @require_role(["operator", "admin"])
    def create_vehicle() -> Response:
        body = request.get_json(silent=True) or {}
        required = ["make", "model", "license_plate"]
        missing = [field for field in required if not body.get(field)]
        if missing:
            return jsonify({"error": "missing_fields", "fields": missing}), 400

        vehicle = Vehicle(
            vehicle_id=_new_id("veh"),
            make=str(body["make"]),
            model=str(body["model"]),
            license_plate=str(body["license_plate"]),
            created_at_ms=_now_ms(),
        )
        with session_local() as session:
            session.add(vehicle)
            session.commit()
        return jsonify(_model_to_dict(vehicle)), 201

    @app.get("/api/vehicles/<vehicle_id>")
    @require_role(["viewer", "operator", "admin"])
    def get_vehicle(vehicle_id: str) -> Response:
        with session_local() as session:
            vehicle = session.get(Vehicle, vehicle_id)
        if vehicle is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify(_model_to_dict(vehicle))

    @app.put("/api/vehicles/<vehicle_id>")
    @require_role(["operator", "admin"])
    def update_vehicle(vehicle_id: str) -> Response:
        with session_local() as session:
            vehicle = session.get(Vehicle, vehicle_id)
            if vehicle is None:
                return jsonify({"error": "not_found"}), 404

            body = request.get_json(silent=True) or {}
            if "make" in body:
                vehicle.make = str(body["make"])
            if "model" in body:
                vehicle.model = str(body["model"])
            if "license_plate" in body:
                vehicle.license_plate = str(body["license_plate"])
            session.commit()
            return jsonify(_model_to_dict(vehicle))

    @app.delete("/api/vehicles/<vehicle_id>")
    @require_role(["admin"])
    def delete_vehicle(vehicle_id: str) -> Response:
        with session_local() as session:
            vehicle = session.get(Vehicle, vehicle_id)
            if vehicle is None:
                return jsonify({"error": "not_found"}), 404
            session.delete(vehicle)
            session.commit()
            return jsonify({"deleted": True})

    @app.get("/api/drivers")
    @require_role(["viewer", "operator", "admin"])
    def list_drivers() -> Response:
        with session_local() as session:
            drivers = session.scalars(select(Driver).order_by(Driver.created_at_ms.desc())).all()
        return jsonify([_model_to_dict(d) for d in drivers])

    @app.post("/api/drivers")
    @require_role(["operator", "admin"])
    def create_driver() -> Response:
        body = request.get_json(silent=True) or {}
        required = ["name", "license_number", "contact_info"]
        missing = [field for field in required if not body.get(field)]
        if missing:
            return jsonify({"error": "missing_fields", "fields": missing}), 400

        driver = Driver(
            driver_id=_new_id("drv"),
            name=str(body["name"]),
            license_number=str(body["license_number"]),
            contact_info=str(body["contact_info"]),
            created_at_ms=_now_ms(),
        )
        with session_local() as session:
            session.add(driver)
            session.commit()
        return jsonify(_model_to_dict(driver)), 201

    @app.get("/api/drivers/<driver_id>")
    @require_role(["viewer", "operator", "admin"])
    def get_driver(driver_id: str) -> Response:
        with session_local() as session:
            driver = session.get(Driver, driver_id)
        if driver is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify(_model_to_dict(driver))

    @app.put("/api/drivers/<driver_id>")
    @require_role(["operator", "admin"])
    def update_driver(driver_id: str) -> Response:
        with session_local() as session:
            driver = session.get(Driver, driver_id)
            if driver is None:
                return jsonify({"error": "not_found"}), 404

            body = request.get_json(silent=True) or {}
            if "name" in body:
                driver.name = str(body["name"])
            if "license_number" in body:
                driver.license_number = str(body["license_number"])
            if "contact_info" in body:
                driver.contact_info = str(body["contact_info"])
            session.commit()
            return jsonify(_model_to_dict(driver))

    @app.delete("/api/drivers/<driver_id>")
    @require_role(["admin"])
    def delete_driver(driver_id: str) -> Response:
        with session_local() as session:
            driver = session.get(Driver, driver_id)
            if driver is None:
                return jsonify({"error": "not_found"}), 404
            session.delete(driver)
            session.commit()
            return jsonify({"deleted": True})

    @app.post("/api/telemetry/events")
    @require_role(["operator", "admin"])
    def ingest_telemetry() -> Response:
        body = request.get_json(silent=True) or {}
        required = ["driver_id", "vehicle_id", "gps_lat", "gps_lng", "speed_kph"]
        missing = [field for field in required if field not in body]
        if missing:
            return jsonify({"error": "missing_fields", "fields": missing}), 400

        event = TelemetryEvent(
            event_id=_new_id("evt"),
            driver_id=str(body["driver_id"]),
            vehicle_id=str(body["vehicle_id"]),
            gps_lat=float(body["gps_lat"]),
            gps_lng=float(body["gps_lng"]),
            speed_kph=float(body["speed_kph"]),
            drowsy_alert=bool(body.get("drowsy_alert", False)),
            distracted_alert=bool(body.get("distracted_alert", False)),
            event_ts_ms=int(body.get("event_ts_ms", _now_ms())),
        )
        with session_local() as session:
            session.add(event)
            session.commit()
        return jsonify(_model_to_dict(event)), 201

    @app.get("/api/kpi/widgets")
    @require_role(["viewer", "operator", "admin"])
    def kpi_widgets() -> Response:
        with session_local() as session:
            events = session.scalars(select(TelemetryEvent).order_by(TelemetryEvent.event_ts_ms.desc())).all()
            fleet_size = session.query(Vehicle).count()
            active_drivers = session.query(Driver).count()

        budget_alerts = sum(1 for evt in events if evt.speed_kph > 90)
        gps_points = [
            {
                "driver_id": evt.driver_id,
                "vehicle_id": evt.vehicle_id,
                "lat": evt.gps_lat,
                "lng": evt.gps_lng,
            }
            for evt in events[:100]
        ]
        payload = {
            "fleet_size": fleet_size,
            "active_drivers": active_drivers,
            "budget_threshold_alerts": budget_alerts,
            "live_gps_points": gps_points,
        }
        return jsonify(payload)

    @app.get("/api/safety/scorecards")
    @require_role(["viewer", "operator", "admin"])
    def safety_scorecards() -> Response:
        with session_local() as session:
            drivers = session.scalars(select(Driver).order_by(Driver.created_at_ms.desc())).all()
            events = session.scalars(select(TelemetryEvent)).all()

        scorecards = []
        for driver in drivers:
            driver_events = [evt for evt in events if evt.driver_id == driver.driver_id]
            if not driver_events:
                score = 100
                drowsy_count = 0
                distracted_count = 0
            else:
                drowsy_count = sum(1 for evt in driver_events if evt.drowsy_alert)
                distracted_count = sum(1 for evt in driver_events if evt.distracted_alert)
                penalty = (drowsy_count * 8) + (distracted_count * 6)
                score = max(0, 100 - penalty)

            scorecards.append(
                {
                    "driver_id": driver.driver_id,
                    "driver_name": driver.name,
                    "safety_score": score,
                    "drowsy_alerts": drowsy_count,
                    "distracted_alerts": distracted_count,
                }
            )

        return jsonify(scorecards)

    @app.post("/internal/reset")
    def internal_reset() -> Response:
        if not cfg.get("TESTING"):
            return jsonify({"error": "forbidden"}), 403
        with session_local() as session:
            session.query(TelemetryEvent).delete()
            session.query(Driver).delete()
            session.query(Vehicle).delete()
            session.commit()
        return jsonify({"reset": True})

    return app


def main() -> int:
    app = create_app()
    app.run(host="0.0.0.0", port=6060, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
