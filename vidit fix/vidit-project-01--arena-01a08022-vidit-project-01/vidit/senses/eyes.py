"""Vidit's eyes (Constitution section 6): the laptop camera, fully local.

* Presence & attention: is someone in front of the laptop? (Haar cascade,
  ships with OpenCV — no download, no cloud.)
* Mood reading: a light heuristic from face geometry (smile cascade) plus,
  when a local vision model such as ``llava`` is installed, a richer
  description ("looks tired, frowning, wearing headphones").
* Friend recognition: if ``face_recognition`` (dlib) is installed, known
  faces are matched against encodings stored in Vidit's folder; otherwise he
  simply notices "a new person" and asks you to introduce them.

The camera is *never* opened without the CAMERA permission. Frames stay in
RAM; nothing is written to disk unless you explicitly ask for a snapshot.
"""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..events import EventBus, bus as global_bus

log = logging.getLogger("vidit.senses.eyes")


class Eyes:
    def __init__(self, models_dir: Path, event_bus: EventBus | None = None, describe_image: Optional[Callable[[str, str], str]] = None):
        self.models_dir = Path(models_dir) / "faces"
        self.bus = event_bus or global_bus
        self._describe = describe_image
        self._cap = None
        # cv2.VideoCapture is a native handle and NOT thread-safe: the watch
        # loop and look()/snapshot() may run on different threads.
        self._cap_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self.last_observation: Dict[str, Any] = {}
        self.known_faces: Dict[str, List[float]] = {}
        self._load_known_faces()

    # ------------------------------------------------------------ status
    @staticmethod
    def available() -> bool:
        try:
            import cv2  # type: ignore # noqa: F401

            return True
        except ImportError:
            return False

    def status(self) -> Dict[str, Any]:
        return {"available": self.available(), "watching": self._running.is_set(), "known_faces": list(self.known_faces),
                "last": self.last_observation}

    # ----------------------------------------------------------- snapshot
    def snapshot(self):
        """Grab a single frame (BGR ndarray) or None."""
        if not self.available():
            return None
        import cv2  # type: ignore

        with self._cap_lock:
            cap = self._cap or cv2.VideoCapture(0)
            try:
                ok, frame = cap.read()
            finally:
                if cap is not self._cap:
                    cap.release()
        return frame if ok else None

    def observe(self, with_llm: bool = False) -> Dict[str, Any]:
        """Look once and describe what's there."""
        frame = self.snapshot()
        if frame is None:
            return {"ok": False, "reason": "no camera frame"}
        obs = self._analyze(frame)
        if with_llm and self._describe is not None:
            obs["description"] = self._describe(_to_b64_jpeg(frame), "Describe the person's apparent mood and surroundings briefly.")
        self.last_observation = obs
        self.bus.emit("eyes.observation", **obs)
        return obs

    def _analyze(self, frame) -> Dict[str, Any]:
        import cv2  # type: ignore

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        smile_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_smile.xml")
        faces = face_cascade.detectMultiScale(gray, 1.2, 5, minSize=(60, 60))
        people: List[Dict[str, Any]] = []
        for (x, y, w, h) in faces:
            roi = gray[y + h // 2: y + h, x: x + w]
            smiles = smile_cascade.detectMultiScale(roi, 1.7, 20)
            mood = "smiling" if len(smiles) else "neutral"
            name = self._identify(frame[y: y + h, x: x + w])
            people.append({"box": [int(x), int(y), int(w), int(h)], "mood": mood, "name": name})
        brightness = float(gray.mean())
        return {"ok": True, "t": time.time(), "people": people, "count": len(people),
                "lighting": "dark" if brightness < 50 else "dim" if brightness < 100 else "bright"}

    # ------------------------------------------------------- recognition
    def _load_known_faces(self) -> None:
        path = self.models_dir / "known_faces.json"
        if path.exists():
            try:
                self.known_faces = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.known_faces = {}

    def _save_known_faces(self) -> None:
        self.models_dir.mkdir(parents=True, exist_ok=True)
        (self.models_dir / "known_faces.json").write_text(json.dumps(self.known_faces), encoding="utf-8")

    def _identify(self, face_bgr) -> Optional[str]:
        try:
            import face_recognition  # type: ignore
            import numpy as np  # type: ignore
        except ImportError:
            return None
        rgb = face_bgr[:, :, ::-1]
        encodings = face_recognition.face_encodings(rgb)
        if not encodings or not self.known_faces:
            return None
        names = list(self.known_faces)
        known = [np.array(self.known_faces[n]) for n in names]
        distances = face_recognition.face_distance(known, encodings[0])
        best = int(distances.argmin())
        return names[best] if distances[best] < 0.55 else None

    def learn_face(self, name: str) -> bool:
        """'This is Rahul' — remember the face currently in front of the camera."""
        try:
            import face_recognition  # type: ignore
        except ImportError:
            log.info("face_recognition not installed; remembering %s without a face signature", name)
            return False
        frame = self.snapshot()
        if frame is None:
            return False
        encodings = face_recognition.face_encodings(frame[:, :, ::-1])
        if not encodings:
            return False
        self.known_faces[name] = [float(v) for v in encodings[0]]
        self._save_known_faces()
        return True

    # ------------------------------------------------------------- watch
    def start_watching(self, interval: float = 5.0) -> bool:
        if self._running.is_set():
            return True
        if not self.available():
            return False
        import cv2  # type: ignore

        with self._cap_lock:
            self._cap = cv2.VideoCapture(0)
            if not self._cap.isOpened():
                self._cap = None
                return False
        self._running.set()

        def loop() -> None:
            last_count = -1
            while self._running.is_set():
                try:
                    obs = self.observe()
                    if obs.get("ok") and obs["count"] != last_count:
                        last_count = obs["count"]
                        self.bus.emit("eyes.presence", count=last_count, people=obs["people"])
                except Exception:  # noqa: BLE001
                    log.exception("eyes loop error")
                time.sleep(interval)

        self._thread = threading.Thread(target=loop, name="vidit-eyes", daemon=True)
        self._thread.start()
        return True

    def stop_watching(self) -> None:
        self._running.clear()
        with self._cap_lock:
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:  # noqa: BLE001
                    pass
                self._cap = None


def _to_b64_jpeg(frame) -> str:
    import cv2  # type: ignore

    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    return base64.b64encode(buf.tobytes()).decode() if ok else ""
