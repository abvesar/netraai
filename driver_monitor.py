import math
import time
from typing import Dict, Optional

import cv2
import mediapipe as mp
import numpy as np


class EdgeAIClassifier:
    """Lightweight edge-AI decision layer for local driver-state inference."""

    def __init__(self) -> None:
        self.drowsiness_weight = 0.45
        self.distraction_weight = 0.35
        self.yawning_weight = 0.15
        self.phone_usage_weight = 0.20

    def classify(
        self,
        drowsy: bool = False,
        distracted: bool = False,
        yawning: bool = False,
        phone_usage: bool = False,
        speed_kph: float = 0.0,
    ) -> Dict[str, object]:
        risk_score = 0.0

        if drowsy:
            risk_score += self.drowsiness_weight
        if distracted:
            risk_score += self.distraction_weight
        if yawning:
            risk_score += self.yawning_weight
        if phone_usage:
            risk_score += self.phone_usage_weight
        if speed_kph >= 100.0:
            risk_score += 0.15

        if risk_score >= 0.8:
            risk_level = "HIGH"
        elif risk_score >= 0.45:
            risk_level = "MODERATE"
        else:
            risk_level = "NORMAL"

        reasons: list[str] = []
        if drowsy:
            reasons.append("drowsiness_high")
        if distracted:
            reasons.append("distraction_high")
        if yawning:
            reasons.append("yawning_detected")
        if phone_usage:
            reasons.append("phone_usage_detected")
        if speed_kph >= 100.0:
            reasons.append("speeding_detected")
        if not reasons:
            reasons.append("behavior_normal")

        confidence = min(0.99, 0.6 + (risk_score * 0.5))
        return {
            "risk_level": risk_level,
            "risk_score": round(risk_score, 3),
            "confidence": round(confidence, 3),
            "reasons": reasons,
        }


class DrishtiAIDMS:
    def __init__(self):
        # Initialize MediaPipe Face Mesh
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        # Hardcoded Indices for MediaPipe Face Mesh landmarks
        self.LEFT_EYE = [362, 385, 387, 263, 373, 380]
        self.RIGHT_EYE = [33, 160, 158, 133, 153, 144]
        self.MOUTH = [78, 81, 13, 311, 308, 402, 14, 178]

        # More realistic fatigue thresholds for driver monitoring.
        self.EAR_THRESHOLD = 0.24
        self.EAR_CRITICAL_THRESHOLD = 0.18
        self.MAR_THRESHOLD = 0.58
        self.YAW_THRESHOLD = 22.0

        # Temporal persistence counters to reduce false positives from brief blinks or glance events.
        self.EYE_CLOSED_COUNTER = 0
        self.DROWSINESS_FRAME_LIMIT = 18
        self.YAWN_COUNTER = 0
        self.YAWN_FRAME_LIMIT = 8
        self.DISTRACTION_COUNTER = 0
        self.DISTRACTION_FRAME_LIMIT = 24
        self.FATIGUE_SCORE = 0.0

    def _draw_tracking_overlay(self, frame, landmarks, status):
        height, width = frame.shape[:2]
        points = np.array(
            [(int(point.x * width), int(point.y * height)) for point in landmarks],
            dtype=np.int32,
        )
        x_min, y_min = np.min(points, axis=0)
        x_max, y_max = np.max(points, axis=0)
        cv2.rectangle(frame, (x_min, y_min), (x_max, y_max), (40, 220, 180), 2)

        for connection in self.mp_face_mesh.FACEMESH_TESSELATION:
            start, end = connection
            cv2.line(frame, tuple(points[start]), tuple(points[end]), (80, 130, 80), 1)

        for eye_indices in (self.LEFT_EYE, self.RIGHT_EYE):
            eye_points = points[eye_indices].reshape((-1, 1, 2))
            cv2.polylines(frame, [eye_points], True, (0, 255, 255), 2)

        label = "FACE TRACKED"
        if status["drowsy"]:
            label = "DROWSINESS ALERT"
        elif status["yawning"]:
            label = "YAWN DETECTED"
        elif status["distracted"]:
            label = "DISTRACTION ALERT"
        cv2.putText(
            frame,
            label,
            (max(10, x_min), max(30, y_min - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 220, 255) if label == "FACE TRACKED" else (0, 80, 255),
            2,
        )

    def calculate_ear(self, landmarks, eye_indices):
        # Coordinates of vertical and horizontal landmarks around the eyelids
        p = [np.array([landmarks[i].x, landmarks[i].y]) for i in eye_indices]
        # Vertical distances
        v1 = np.linalg.norm(p[1] - p[5])
        v2 = np.linalg.norm(p[2] - p[4])
        # Horizontal distance
        h = np.linalg.norm(p[0] - p[3])
        return (v1 + v2) / (2.0 * h)

    def calculate_mar(self, landmarks):
        p = [np.array([landmarks[i].x, landmarks[i].y]) for i in self.MOUTH]
        # Vertical distances between lips
        v = np.linalg.norm(p[1] - p[6]) + np.linalg.norm(p[3] - p[5])
        # Horizontal width of mouth
        h = np.linalg.norm(p[0] - p[4])
        return v / (2.0 * h)

    def estimate_head_pose(self, landmarks, img_w, img_h):
        # Standard 3D generic facial feature model points
        model_points = np.array([
            (0.0, 0.0, 0.0),             # Nose tip
            (0.0, -330.0, -65.0),        # Chin
            (-225.0, 170.0, -135.0),     # Left eye left corner
            (225.0, 170.0, -135.0),      # Right eye right corner
            (-150.0, -150.0, -125.0),    # Left Mouth corner
            (150.0, -150.0, -125.0)      # Right mouth corner
        ], dtype=np.float32)

        # Corresponding 2D points from MediaPipe mapping
        image_points = np.array([
            (landmarks[1].x * img_w, landmarks[1].y * img_h),     # Nose tip
            (landmarks[152].x * img_w, landmarks[152].y * img_h), # Chin
            (landmarks[33].x * img_w, landmarks[33].y * img_h),   # Left eye corner
            (landmarks[263].x * img_w, landmarks[263].y * img_h), # Right eye corner
            (landmarks[61].x * img_w, landmarks[61].y * img_h),   # Left mouth corner
            (landmarks[291].x * img_w, landmarks[291].y * img_h)  # Right mouth corner
        ], dtype=np.float32)

        # Camera Intrinsic Matrix approximation
        focal_length = img_w
        center = (img_w / 2, img_h / 2)
        camera_matrix = np.array([[focal_length, 0, center[0]],
                                  [0, focal_length, center[1]],
                                  [0, 0, 1]], dtype=np.float32)

        dist_coeffs = np.zeros((4, 1))

        try:
            _, rotation_vector, _ = cv2.solvePnP(
                model_points,
                image_points,
                camera_matrix,
                dist_coeffs,
                flags=cv2.SOLVEPNP_ITERATIVE,
            )
        except cv2.error:
            return 0.0, 0.0, 0.0

        rmat, _ = cv2.Rodrigues(rotation_vector)
        sy = math.sqrt(rmat[0, 0] * rmat[0, 0] + rmat[1, 0] * rmat[1, 0])

        if sy > 1e-6:
            pitch = math.degrees(math.atan2(rmat[2, 1], rmat[2, 2]))
            yaw = math.degrees(math.atan2(-rmat[2, 0], sy))
            roll = math.degrees(math.atan2(rmat[1, 0], rmat[0, 0]))
        else:
            pitch = math.degrees(math.atan2(-rmat[1, 2], rmat[1, 1]))
            yaw = math.degrees(math.atan2(-rmat[2, 0], sy))
            roll = 0.0

        return pitch, yaw, roll

    def process_frame(self, frame):
        h, w, _ = frame.shape
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb_frame)

        status = {
            "drowsy": False,
            "distracted": False,
            "yawning": False,
            "fatigue_score": 0.0,
            "ear": 0.0,
            "mar": 0.0,
            "yaw": 0.0,
        }

        if results.multi_face_landmarks:
            landmarks = results.multi_face_landmarks[0].landmark

            left_ear = self.calculate_ear(landmarks, self.LEFT_EYE)
            right_ear = self.calculate_ear(landmarks, self.RIGHT_EYE)
            avg_ear = (left_ear + right_ear) / 2.0
            status["ear"] = avg_ear

            if avg_ear < self.EAR_CRITICAL_THRESHOLD:
                self.EYE_CLOSED_COUNTER += 2
            elif avg_ear < self.EAR_THRESHOLD:
                self.EYE_CLOSED_COUNTER += 1
            else:
                self.EYE_CLOSED_COUNTER = max(0, self.EYE_CLOSED_COUNTER - 2)

            if self.EYE_CLOSED_COUNTER >= self.DROWSINESS_FRAME_LIMIT:
                status["drowsy"] = True

            mar = self.calculate_mar(landmarks)
            status["mar"] = mar
            if mar > self.MAR_THRESHOLD:
                self.YAWN_COUNTER += 1
            else:
                self.YAWN_COUNTER = max(0, self.YAWN_COUNTER - 1)

            if self.YAWN_COUNTER >= self.YAWN_FRAME_LIMIT:
                status["yawning"] = True

            _, yaw, _ = self.estimate_head_pose(landmarks, w, h)
            status["yaw"] = abs(yaw)
            if abs(yaw) > self.YAW_THRESHOLD:
                self.DISTRACTION_COUNTER += 1
            else:
                self.DISTRACTION_COUNTER = max(0, self.DISTRACTION_COUNTER - 2)

            if self.DISTRACTION_COUNTER >= self.DISTRACTION_FRAME_LIMIT:
                status["distracted"] = True

            fatigue_score = 0.0
            if status["drowsy"]:
                fatigue_score += 0.45
            if status["yawning"]:
                fatigue_score += 0.2
            if status["distracted"]:
                fatigue_score += 0.25
            if avg_ear < self.EAR_THRESHOLD:
                fatigue_score += 0.15
            if mar > self.MAR_THRESHOLD:
                fatigue_score += 0.1
            status["fatigue_score"] = min(1.0, fatigue_score)

            self._draw_tracking_overlay(frame, landmarks, status)

        edge_result = EdgeAIClassifier().classify(
            drowsy=status["drowsy"],
            distracted=status["distracted"],
            yawning=status["yawning"],
            phone_usage=False,
            speed_kph=0.0,
        )
        status["edge_ai"] = edge_result
        return status

# Local testing loop (Simulating Edge Cam Execution)
if __name__ == "__main__":
    import os

    stream_source = os.environ.get("DRISHTI_STREAM_URL")
    if stream_source is None:
        stream_source = "0"

    cap = cv2.VideoCapture(stream_source)
    dms_system = DrishtiAIDMS()

    print(f"[INFO] DrishtiAI DMS Core Module Initialized. Using source: {stream_source}")
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            print("[ERROR] Lost connection to the configured stream source.")
            break

        alerts = dms_system.process_frame(frame)

        if alerts["drowsy"]:
            cv2.putText(frame, "!!! DROWSINESS CRITICAL !!!", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
        elif alerts["distracted"]:
            cv2.putText(frame, "WARNING: DISTRACTED DRIVING", (30, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 165, 255), 2)
        elif alerts["yawning"]:
            cv2.putText(frame, "ALERT: Yawn Detected (Fatigue)", (30, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

        cv2.imshow("DrishtiAI - Edge DMS Processor Mock", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
