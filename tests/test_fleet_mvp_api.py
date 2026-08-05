from __future__ import annotations

import unittest

from fleet_mvp_api import create_app


class FleetMvpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app(
            {
                "TESTING": True,
                "DATABASE_URL": "sqlite:///:memory:",
                "AUTO_CREATE_SCHEMA": True,
                "API_KEYS": {
                    "viewer_test": "viewer",
                    "operator_test": "operator",
                    "admin_test": "admin",
                },
            }
        )
        self.client = app.test_client()
        self.viewer_headers = {"X-API-Key": "viewer_test"}
        self.operator_headers = {"X-API-Key": "operator_test"}
        self.admin_headers = {"X-API-Key": "admin_test"}

    def test_rbac_rejects_unauthorized(self) -> None:
        resp = self.client.get("/api/vehicles")
        self.assertEqual(resp.status_code, 401)

    def test_vehicle_driver_crud_and_kpi(self) -> None:
        vehicle_resp = self.client.post(
            "/api/vehicles",
            json={"make": "Tata", "model": "Prima", "license_plate": "MH12AB1234"},
            headers=self.operator_headers,
        )
        self.assertEqual(vehicle_resp.status_code, 201)
        vehicle = vehicle_resp.get_json()

        driver_resp = self.client.post(
            "/api/drivers",
            json={"name": "Rohit", "license_number": "DL-778899", "contact_info": "+91-9000000000"},
            headers=self.operator_headers,
        )
        self.assertEqual(driver_resp.status_code, 201)
        driver = driver_resp.get_json()

        telemetry_resp = self.client.post(
            "/api/telemetry/events",
            json={
                "driver_id": driver["driver_id"],
                "vehicle_id": vehicle["vehicle_id"],
                "gps_lat": 19.076,
                "gps_lng": 72.8777,
                "speed_kph": 95.0,
                "drowsy_alert": True,
                "distracted_alert": False,
            },
            headers=self.operator_headers,
        )
        self.assertEqual(telemetry_resp.status_code, 201)

        kpi_resp = self.client.get("/api/kpi/widgets", headers=self.viewer_headers)
        self.assertEqual(kpi_resp.status_code, 200)
        kpi = kpi_resp.get_json()
        self.assertEqual(kpi["fleet_size"], 1)
        self.assertEqual(kpi["active_drivers"], 1)
        self.assertEqual(kpi["budget_threshold_alerts"], 1)
        self.assertEqual(len(kpi["live_gps_points"]), 1)

        scorecard_resp = self.client.get("/api/safety/scorecards", headers=self.viewer_headers)
        self.assertEqual(scorecard_resp.status_code, 200)
        scorecards = scorecard_resp.get_json()
        self.assertEqual(len(scorecards), 1)
        self.assertEqual(scorecards[0]["drowsy_alerts"], 1)

    def test_delete_vehicle(self) -> None:
        vehicle_resp = self.client.post(
            "/api/vehicles",
            json={"make": "Ashok", "model": "Dost", "license_plate": "DL10CD5555"},
            headers=self.operator_headers,
        )
        vehicle = vehicle_resp.get_json()
        delete_forbidden_resp = self.client.delete(
            f"/api/vehicles/{vehicle['vehicle_id']}",
            headers=self.operator_headers,
        )
        self.assertEqual(delete_forbidden_resp.status_code, 403)

        delete_resp = self.client.delete(
            f"/api/vehicles/{vehicle['vehicle_id']}",
            headers=self.admin_headers,
        )
        self.assertEqual(delete_resp.status_code, 200)

        get_resp = self.client.get(
            f"/api/vehicles/{vehicle['vehicle_id']}",
            headers=self.viewer_headers,
        )
        self.assertEqual(get_resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
