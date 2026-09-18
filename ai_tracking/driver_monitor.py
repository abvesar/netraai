import math
import os
from pathlib import Path
from typing import Dict

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision


class EdgeAIClassifier:
    """Lightweight edge-AI decision layer for local driver-state inference."""

    def __init__(self) -> None:
        self.drowsiness_weight = 0.45
        self.distraction_weight = 0.35
        self.yawning_weight = 0.15
        self.phone_usage_weight = 0.20

    def classify(self, drowsy=False, distracted=False, yawning=False, phone_usage=False, speed_kph=0.0) -> Dict[str, object]:
        risk_score = sum([
            self.drowsiness_weight if drowsy else 0.0,
            self.distraction_weight if distracted else 0.0,
            self.yawning_weight if yawning else 0.0,
            self.phone_usage_weight if phone_usage else 0.0,
            0.15 if speed_kph >= 100.0 else 0.0,
        ])
        risk_level = "HIGH" if risk_score >= 0.8 else "MODERATE" if risk_score >= 0.45 else "NORMAL"
        reasons = []
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
        return {"risk_level": risk_level, "risk_score": round(risk_score, 3), "confidence": round(min(0.99, 0.6 + risk_score * 0.5), 3), "reasons": reasons}


class DrishtiAIDMS:
    def __init__(self):
        self.phone_detector = self._create_phone_detector()
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(max_num_faces=1, refine_landmarks=True, min_detection_confidence=0.5, min_tracking_confidence=0.5)
        self.LEFT_EYE = [362, 385, 387, 263, 373, 380]
        self.RIGHT_EYE = [33, 160, 158, 133, 153, 144]
        self.MOUTH = [78, 81, 13, 311, 308, 402, 14, 178]
        self.EAR_THRESHOLD = 0.24
        self.EAR_CRITICAL_THRESHOLD = 0.18
        self.MAR_THRESHOLD = 0.58
        self.YAW_THRESHOLD = 22.0
        self.EYE_CLOSED_COUNTER = 0
        self.DROWSINESS_FRAME_LIMIT = 8
        self._eyes_closed_since: float | None = None
        self.YAWN_COUNTER = 0
        self.YAWN_FRAME_LIMIT = 8
        self.DISTRACTION_COUNTER = 0
        self.DISTRACTION_FRAME_LIMIT = 24
        self.ENROLLED_DRIVER_ID = "roh_01"
        self.FACE_MATCH_THRESHOLD = 0.12
        self._enrolled_face = None
        self.hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.phone_usage_counter = 0
        self.PHONE_USAGE_FRAME_LIMIT = 12

    def _create_phone_detector(self):
        model_path = Path(os.environ.get("DRISHTI_PHONE_MODEL", "models/phone_detector.tflite"))
        if not model_path.is_file():
            return None
        try:
            options = vision.ObjectDetectorOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
                running_mode=vision.RunningMode.IMAGE,
                max_results=5,
                score_threshold=0.35,
            )
            return vision.ObjectDetector.create_from_options(options)
        except (OSError, RuntimeError, ValueError):
            return None

    @staticmethod
    def _box_distance(first, second):
        first_x, first_y, first_w, first_h = first
        second_x, second_y, second_w, second_h = second
        first_right, first_bottom = first_x + first_w, first_y + first_h
        second_right, second_bottom = second_x + second_w, second_y + second_h
        horizontal_gap = max(second_x - first_right, first_x - second_right, 0)
        vertical_gap = max(second_y - first_bottom, first_y - second_bottom, 0)
        return math.hypot(horizontal_gap, vertical_gap)

    def _phone_signal(self, frame, landmarks, pitch):
        empty_signal = {"detected": False, "held": False, "looking_down": False, "score": 0.0}
        if self.phone_detector is None:
            return empty_signal

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        detection_result = self.phone_detector.detect(image)
        phone_boxes = []
        for detection in detection_result.detections:
            category = detection.categories[0] if detection.categories else None
            label = ((category.category_name or category.display_name) if category else "").lower()
            if category and "phone" in label:
                box = detection.bounding_box
                phone_boxes.append((box.origin_x, box.origin_y, box.width, box.height, category.score))
        if not phone_boxes:
            self.phone_usage_counter = max(0, self.phone_usage_counter - 2)
            return empty_signal

        hand_result = self.hands.process(rgb_frame)
        height, width = frame.shape[:2]
        hand_boxes = []
        for hand in hand_result.multi_hand_landmarks or []:
            points = [(point.x * width, point.y * height) for point in hand.landmark]
            x_values, y_values = zip(*points)
            hand_boxes.append((min(x_values), min(y_values), max(x_values) - min(x_values), max(y_values) - min(y_values)))

        held_phone = any(
            any(self._box_distance(phone[:4], hand_box) <= max(phone[2], phone[3]) * 0.75 for hand_box in hand_boxes)
            for phone in phone_boxes
        )
        face_y = float(np.mean([landmarks[index].y for index in [10, 152]])) * height
        phone_below_face = any(phone[1] + phone[3] * 0.5 > face_y for phone in phone_boxes)
        looking_down = phone_below_face and abs(pitch) > 10.0
        candidate = held_phone and looking_down
        self.phone_usage_counter = min(
            self.PHONE_USAGE_FRAME_LIMIT,
            self.phone_usage_counter + 1 if candidate else max(0, self.phone_usage_counter - 1),
        )
        confirmed = self.phone_usage_counter >= self.PHONE_USAGE_FRAME_LIMIT
        return {
            "detected": True,
            "held": held_phone,
            "looking_down": looking_down,
            "score": 0.95 if confirmed else 0.0,
        }

    def _face_embedding(self, landmarks):
        points = np.array([(point.x, point.y) for point in landmarks], dtype=np.float32)
        points -= np.mean(points, axis=0)
        scale = np.max(np.ptp(points, axis=0))
        return None if scale <= 1e-6 else (points / scale).reshape(-1)

    def _recognize_face(self, landmarks):
        embedding = self._face_embedding(landmarks)
        if embedding is None:
            return False, "NO FACE DETECTED"
        if self._enrolled_face is None:
            self._enrolled_face = embedding
            return True, self.ENROLLED_DRIVER_ID
        return (True, self.ENROLLED_DRIVER_ID) if float(np.mean(np.abs(embedding - self._enrolled_face))) <= self.FACE_MATCH_THRESHOLD else (False, "DRIVER NOT RECOGNIZED")

    def _draw_tracking_overlay(self, frame, landmarks, status):
        height, width = frame.shape[:2]
        points = np.array([(int(point.x * width), int(point.y * height)) for point in landmarks], dtype=np.int32)
        x_min, y_min = np.min(points, axis=0)
        x_max, y_max = np.max(points, axis=0)
        cv2.rectangle(frame, (x_min, y_min), (x_max, y_max), (40, 220, 180), 2)
        for connection in self.mp_face_mesh.FACEMESH_TESSELATION:
            start, end = connection
            cv2.line(frame, tuple(points[start]), tuple(points[end]), (80, 130, 80), 1)
        for eye_indices in (self.LEFT_EYE, self.RIGHT_EYE):
            cv2.polylines(frame, [points[eye_indices].reshape((-1, 1, 2))], True, (0, 255, 255), 2)
        label = "FACE TRACKED"
        if status["phone_usage"]:
            label = "PHONE USAGE ALERT"
        elif status["drowsy"]:
            label = "DROWSINESS ALERT"
        elif status["yawning"]:
            label = "YAWN DETECTED"
        elif status["distracted"]:
            label = "DISTRACTION ALERT"
        cv2.putText(frame, label, (max(10, x_min), max(30, y_min - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255) if label == "FACE TRACKED" else (0, 80, 255), 2)

    def calculate_ear(self, landmarks, eye_indices):
        p = [np.array([landmarks[i].x, landmarks[i].y]) for i in eye_indices]
        return (np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4])) / (2.0 * np.linalg.norm(p[0] - p[3]))

    def calculate_mar(self, landmarks):
        p = [np.array([landmarks[i].x, landmarks[i].y]) for i in self.MOUTH]
        return (np.linalg.norm(p[1] - p[6]) + np.linalg.norm(p[3] - p[5])) / (2.0 * np.linalg.norm(p[0] - p[4]))

    def estimate_head_pose(self, landmarks, img_w, img_h):
        model_points = np.array([(0.0, 0.0, 0.0), (0.0, -330.0, -65.0), (-225.0, 170.0, -135.0), (225.0, 170.0, -135.0), (-150.0, -150.0, -125.0), (150.0, -150.0, -125.0)], dtype=np.float32)
        image_points = np.array([(landmarks[1].x * img_w, landmarks[1].y * img_h), (landmarks[152].x * img_w, landmarks[152].y * img_h), (landmarks[33].x * img_w, landmarks[33].y * img_h), (landmarks[263].x * img_w, landmarks[263].y * img_h), (landmarks[61].x * img_w, landmarks[61].y * img_h), (landmarks[291].x * img_w, landmarks[291].y * img_h)], dtype=np.float32)
        camera_matrix = np.array([[img_w, 0, img_w / 2], [0, img_w, img_h / 2], [0, 0, 1]], dtype=np.float32)
        try:
            _, rotation_vector, _ = cv2.solvePnP(model_points, image_points, camera_matrix, np.zeros((4, 1)), flags=cv2.SOLVEPNP_ITERATIVE)
        except cv2.error:
            return 0.0, 0.0, 0.0
        rmat, _ = cv2.Rodrigues(rotation_vector)
        sy = math.sqrt(rmat[0, 0] ** 2 + rmat[1, 0] ** 2)
        pitch = math.degrees(math.atan2(rmat[2, 1], rmat[2, 2])) if sy > 1e-6 else math.degrees(math.atan2(-rmat[1, 2], rmat[1, 1]))
        yaw = math.degrees(math.atan2(-rmat[2, 0], sy))
        roll = math.degrees(math.atan2(rmat[1, 0], rmat[0, 0])) if sy > 1e-6 else 0.0
        return pitch, yaw, roll

    def process_frame(self, frame):
        h, w, _ = frame.shape
        results = self.face_mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        status = {"drowsy": False, "distracted": False, "yawning": False, "phone_usage": False, "phone_detected": False, "phone_held": False, "looking_down": False, "phone_usage_score": 0.0, "face_recognized": False, "driver_id": "DRIVER NOT RECOGNIZED", "fatigue_score": 0.0, "ear": 0.0, "mar": 0.0, "yaw": 0.0, "face_detected": bool(results.multi_face_landmarks)}
        if results.multi_face_landmarks:
            landmarks = results.multi_face_landmarks[0].landmark
            status["face_recognized"], status["driver_id"] = self._recognize_face(landmarks)
            avg_ear = (self.calculate_ear(landmarks, self.LEFT_EYE) + self.calculate_ear(landmarks, self.RIGHT_EYE)) / 2.0
            status["ear"] = avg_ear
            eyes_closed = avg_ear < self.EAR_THRESHOLD
            if eyes_closed:
                self._eyes_closed_since = self._eyes_closed_since or time.monotonic()
                self.EYE_CLOSED_COUNTER += 1
            else:
                self._eyes_closed_since = None
                self.EYE_CLOSED_COUNTER = max(0, self.EYE_CLOSED_COUNTER - 2)
            closed_duration = 0.0 if self._eyes_closed_since is None else time.monotonic() - self._eyes_closed_since
            status["drowsy"] = closed_duration >= 1.5
            mar = self.calculate_mar(landmarks)
            status["mar"] = mar
            self.YAWN_COUNTER = self.YAWN_COUNTER + 1 if mar > self.MAR_THRESHOLD else max(0, self.YAWN_COUNTER - 1)
            status["yawning"] = self.YAWN_COUNTER >= self.YAWN_FRAME_LIMIT
            pitch, yaw, _ = self.estimate_head_pose(landmarks, w, h)
            status["yaw"] = abs(yaw)
            self.DISTRACTION_COUNTER = self.DISTRACTION_COUNTER + 1 if abs(yaw) > self.YAW_THRESHOLD else max(0, self.DISTRACTION_COUNTER - 2)
            status["distracted"] = self.DISTRACTION_COUNTER >= self.DISTRACTION_FRAME_LIMIT
            phone_signal = self._phone_signal(frame, landmarks, pitch)
            status["phone_detected"] = phone_signal["detected"]
            status["phone_held"] = phone_signal["held"]
            status["looking_down"] = phone_signal["looking_down"]
            status["phone_usage_score"] = phone_signal["score"]
            status["phone_usage"] = phone_signal["score"] >= 0.8
            status["fatigue_score"] = min(1.0, 0.45 * status["drowsy"] + 0.2 * status["yawning"] + 0.25 * status["distracted"] + 0.15 * (avg_ear < self.EAR_THRESHOLD) + 0.1 * (mar > self.MAR_THRESHOLD))
            self._draw_tracking_overlay(frame, landmarks, status)
        status["edge_ai"] = EdgeAIClassifier().classify(drowsy=status["drowsy"], distracted=status["distracted"], yawning=status["yawning"], phone_usage=status["phone_usage"])
        return status
