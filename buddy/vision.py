"""
Pi Camera 3 and the Lepton (PureThermal 3 shows up as a UVC webcam) as MJPEG
over HTTP:  http://<pi>:8080/cam  /thermal  and / for both side by side.
No camera, no problem: you get a moving test pattern instead of a crash.
"""
import io
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config


class TestPattern:
    __test__ = False

    def __init__(self, label):
        self.label, self.n = label, 0

    def jpeg(self):
        from PIL import Image, ImageDraw
        self.n += 1
        im = Image.new("RGB", (320, 240), (20, 20, 40))
        d = ImageDraw.Draw(im)
        x = self.n * 4 % 320
        d.rectangle([x, 80, x + 40, 160], fill=(255, 120, 0))
        d.text((10, 10), f"{self.label} (no camera) {self.n}", fill=(255, 255, 255))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=70)
        return buf.getvalue()


class PiCam:
    def __init__(self):
        from picamera2 import Picamera2
        import cv2
        self.cv2 = cv2
        self.cam = Picamera2()
        self.cam.configure(self.cam.create_video_configuration(main={"size": (1280, 720), "format": "RGB888"}))
        self.cam.start()

    def jpeg(self):
        return self.cv2.imencode(".jpg", self.cam.capture_array(), [self.cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()


class Thermal:
    def __init__(self, device=config.THERMAL_DEVICE):
        import cv2
        self.cv2 = cv2
        self.cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise OSError(f"can't open {device}")

    def jpeg(self):
        cv2 = self.cv2
        ok, frame = self.cap.read()
        if not ok:
            raise OSError("thermal frame dropped")
        if frame.ndim == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # 160x120 is tiny, blow it up with nearest so the pixels stay honest
        frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_NEAREST)
        return cv2.imencode(".jpg", cv2.applyColorMap(frame, cv2.COLORMAP_INFERNO))[1].tobytes()


def detect_people(jpeg: bytes) -> list:
    # TODO: Coral Edge TPU hook. Plan is pycoral + SSD MobileNet v2 COCO on the
    # thermal+RGB frames, return [(confidence, bbox)], and call mesh.report_find()
    # when it's confirmed on both. Not wired yet, Gate 3 work.
    return []


def _open(kind, simulate):
    if not simulate:
        try:
            return PiCam() if kind == "cam" else Thermal()
        except Exception as e:
            print(f"[vision] {kind} not available ({e}), using test pattern")
    return TestPattern(kind)


class _Grabber(threading.Thread):
    def __init__(self, source, fps):
        super().__init__(daemon=True)
        self.source, self.period, self.frame, self.running = source, 1 / fps, None, True

    def run(self):
        while self.running:
            try:
                self.frame = self.source.jpeg()
            except Exception as e:
                print(f"[vision] {e}")
                time.sleep(1)
            time.sleep(self.period)


class VideoServer:
    def __init__(self, simulate, host="0.0.0.0", port=config.STREAM_PORT, fps=config.STREAM_FPS):
        self.grabbers = {k: _Grabber(_open(k, simulate), fps) for k in ("cam", "thermal")}
        grabbers = self.grabbers

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                name = self.path.strip("/")
                if not name:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b'<h1>Buddy</h1><img src="/cam" width=640> <img src="/thermal" width=480>')
                    return
                g = grabbers.get(name)
                if not g:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    while True:
                        if g.frame:
                            self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n"
                                             % len(g.frame) + g.frame + b"\r\n")
                        time.sleep(g.period)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.httpd = ThreadingHTTPServer((host, port), Handler)

    def start(self):
        for g in self.grabbers.values():
            g.start()
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        print(f"[vision] streaming on http://{self.httpd.server_address[0]}:{self.httpd.server_address[1]}/")
        return self

    def stop(self):
        for g in self.grabbers.values():
            g.running = False
        self.httpd.shutdown()
        self.httpd.server_close()
