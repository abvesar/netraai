from flask import Flask, Response, render_template_string
import cv2
from driver_monitor import DrishtiAIDMS

app = Flask(__name__)
dms_system = DrishtiAIDMS()

# Initialize Camera (Use 0 for local webcam, or your phone IP URL string)
camera = cv2.VideoCapture(0) 


def generate_frames():
    while True:
        success, frame = camera.read()
        if not success:
            break
        else:
            # 1. Run the image matrix through your Edge AI pipeline
            alerts = dms_system.process_frame(frame)
            
            # 2. Draw the visual Edge AI feedback overlays directly on the frame
            # This visually proves to the user/investor that the AI is working in real time!
            if alerts["drowsy"]:
                cv2.putText(frame, "!!! DROWSINESS CRITICAL !!!", (30, 50), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
                # Draw visual bounding box hints over eyes or face to look like enterprise tech
                cv2.rectangle(frame, (10, 10), (frame.shape[1]-10, frame.shape[0]-10), (0,0,255), 5)
            elif alerts["distracted"]:
                cv2.putText(frame, "WARNING: DISTRACTED DRIVING", (30, 50), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 165, 255), 2)
            elif alerts["yawning"]:
                cv2.putText(frame, "ALERT: Yawn Detected", (30, 50), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            else:
                # Show an "All Clear" status to look like an operating system monitor
                cv2.putText(frame, "SYSTEM ACTIVE: DRIVER ALERT", (30, 50), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # 3. Compress the processed OpenCV frame into a JPEG memory buffer
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ret:
                continue
            frame_bytes = buffer.tobytes()
            
            # 4. Yield the frame in an MJPEG format sequence block
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/video_feed')
def video_feed():
    # Returns the streaming response using the content type multipart/x-mixed-replace
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    # A quick HTML layout simulating your Central Management Dashboard UI
    dashboard_html = """
    <html>
    <head>
        <title>DRISHTI AI Central Fleet Command</title>
        <style>
            body { font-family: 'Segoe UI', sans-serif; background: #121214; color: #fff; padding: 20px; }
            .dashboard-container { max-width: 1200px; margin: auto; display: flex; gap: 20px; }
            .video-card { background: #1e1e24; border-radius: 12px; padding: 15px; border: 1px solid #2e2e38; }
            .telemetry-card { flex: 1; background: #1e1e24; border-radius: 12px; padding: 15px; border: 1px solid #2e2e38; }
            h1, h2 { color: #00ff66; margin-top: 0; }
            .status-badge { background: #00ff66; color: #121214; padding: 5px 10px; border-radius: 5px; font-weight: bold; }
            .remote-link { margin-top: 12px; font-size: 14px; color: #aaffcc; }
        </style>
    </head>
    <body>
        <h1>DRISHTI AI Operations Dashboard <span class="status-badge">Live Connection</span></h1>
        <div class="remote-link">Remote access URL: http://&lt;this-machine-ip&gt;:5000/</div>
        <div class="dashboard-container">
            <!-- The Live Cam Stream Card -->
            <div class="video-card">
                <h2>In-Cab Vehicle Feed (Vehicle #VEH-001)</h2>
                <!-- The magic happens here: Pointing directly to our Flask Python video route -->
                <img src="/video_feed" width="640" height="480" style="border-radius: 8px; border: 2px solid #2e2e38;" />
            </div>
            
            <!-- Mock Telemetry Panel to look like a full startup system -->
            <div class="telemetry-card">
                <h2>Telemetry Signals</h2>
                <p><strong>Driver ID:</strong> drv_001 (Verified via FaceID)</p>
                <p><strong>Ignition State:</strong> UNLOCKED (Breathalyzer Passed: 0.00% BAC)</p>
                <p><strong>Current Speed:</strong> 62 km/h</p>
                <hr style="border-color: #2e2e38;">
                <button style="background: #ff3333; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: bold; cursor: pointer;">
                    Remote Intervene: Push Cab Audio
                </button>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(dashboard_html)

if __name__ == '__main__':
    # Start the server on port 5000
    app.run(host='0.0.0.0', port=5000, debug=False)
