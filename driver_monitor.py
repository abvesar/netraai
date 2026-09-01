import math
import time

import cv2
import mediapipe as mp
import numpy as np

class NetraAIDMS:
    def __init__(self):
        # Initialize MediaPipe Face Mesh
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True, # Required for high-accuracy iris tracking
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        
        # Hardcoded Indices for MediaPipe Face Mesh landmarks
        self.LEFT_EYE = [362, 385, 387, 263, 373, 380]
        self.RIGHT_EYE = [33, 160, 158, 133, 153, 144]
        self.MOUTH = [78, 81, 13, 311, 308, 402, 14, 178]
        
        # Safety Thresholds
        self.EAR_THRESHOLD = 0.22   # Below this = Eye Closed
        self.MAR_THRESHOLD = 0.60   # Above this = Yawning
        self.YAW_THRESHOLD = 25     # Looking too far left/right (Degrees)
        
        # Frame counters for temporal persistence (avoiding false alarms during rapid blinks)
        self.EYE_CLOSED_COUNTER = 0
        self.DROWSINESS_FRAME_LIMIT = 20 # ~1-2 seconds of continuous closure depending on FPS

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
        
        status = {"drowsy": False, "distracted": False, "yawning": False}
        
        if results.multi_face_landmarks:
            landmarks = results.multi_face_landmarks[0].landmark
            
            # 1. Check Drowsiness (EAR)
            left_ear = self.calculate_ear(landmarks, self.LEFT_EYE)
            right_ear = self.calculate_ear(landmarks, self.RIGHT_EYE)
            avg_ear = (left_ear + right_ear) / 2.0
            
            if avg_ear < self.EAR_THRESHOLD:
                self.EYE_CLOSED_COUNTER += 1
                if self.EYE_CLOSED_COUNTER >= self.DROWSINESS_FRAME_LIMIT:
                    status["drowsy"] = True
            else:
                self.EYE_CLOSED_COUNTER = 0
                
            # 2. Check Yawning (MAR)
            mar = self.calculate_mar(landmarks)
            if mar > self.MAR_THRESHOLD:
                status["yawning"] = True
                
            # 3. Check Distraction (Head Yaw angle)
            _, yaw, _ = self.estimate_head_pose(landmarks, w, h)
            if abs(yaw) > self.YAW_THRESHOLD:
                status["distracted"] = True
                
        return status

# Local testing loop (Simulating Edge Cam Execution)
if __name__ == "__main__":
    cap = cv2.VideoCapture(0)
    dms_system = NetraAIDMS()
    
    print("[INFO] NetraAI DMS Core Module Initialized. Press 'q' to exit.")
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break
        
        alerts = dms_system.process_frame(frame)
        
        # Display overlay indicators on the video feed
        if alerts["drowsy"]:
            cv2.putText(frame, "!!! DROWSINESS CRITICAL !!!", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
        elif alerts["distracted"]:
            cv2.putText(frame, "WARNING: DISTRACTED DRIVING", (30, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 165, 255), 2)
        elif alerts["yawning"]:
            cv2.putText(frame, "ALERT: Yawn Detected (Fatigue)", (30, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            
        cv2.imshow("NetraAI - Edge DMS Processor Mock", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'): break
        
    cap.release()
    cv2.destroyAllWindows()
