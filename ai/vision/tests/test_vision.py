"""Tests du service vision, sans webcam. YOLO n'est utilisé que par le dernier test (ignoré s'il est absent).

    cd ai/vision && python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

VISION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VISION))

from app.analysis import (  # noqa: E402
    BadgeReader,
    MotionGate,
    Persistence,
    PresenceTracker,
    assign_badges,
    check_integrity,
    in_polygon,
)
from app.config import VisionSettings  # noqa: E402
from app.faces import FaceEngine, FaceMatch, Gallery, IdentityVotes  # noqa: E402
from app.pipeline import VisionPipeline  # noqa: E402
from app.service import Publisher  # noqa: E402

ZONE = ((0.2, 0.25), (0.8, 0.25), (0.8, 0.95), (0.2, 0.95))


def scene(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.full((480, 640, 3), 140, np.uint8)
    cv2.rectangle(img, (400, 80), (600, 300), (60, 70, 80), -1)
    cv2.circle(img, (120, 160), 50, (200, 200, 210), -1)
    return np.clip(img + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)


def with_badge(img: np.ndarray, badge: int, x: int, y: int, size: int = 60) -> np.ndarray:
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    m = cv2.copyMakeBorder(cv2.aruco.generateImageMarker(d, badge, size), 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=255)
    out = img.copy()
    out[y:y + m.shape[0], x:x + m.shape[1]] = cv2.cvtColor(m, cv2.COLOR_GRAY2BGR)
    return out


class FakeDetector:
    """Rejoue des détections écrites à l'avance : [(id, boîte normalisée, confiance)] par image."""

    def __init__(self, script):
        self.script, self.i = script, 0

    def track(self, frame):
        out = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return out


class GeometryTest(unittest.TestCase):
    def test_polygon(self):
        self.assertTrue(in_polygon(0.5, 0.5, ZONE))
        self.assertFalse(in_polygon(0.1, 0.5, ZONE))
        self.assertFalse(in_polygon(0.5, 0.99, ZONE))

    def test_person_cut_by_bottom_edge_uses_box_center(self):
        from app.analysis import foot_point
        self.assertAlmostEqual(foot_point((0.4, 0.3, 0.6, 0.8))[1], 0.79)            # pieds visibles
        x, y = foot_point((0.251, 0.322, 0.999, 0.998))                              # assis devant la webcam
        self.assertTrue(in_polygon(x, y, ZONE))


class IntegrityTest(unittest.TestCase):
    def test_normal_masked_dark(self):
        gray = cv2.cvtColor(scene(), cv2.COLOR_BGR2GRAY)
        ok = check_integrity(gray)
        self.assertFalse(ok.masked)
        self.assertFalse(ok.low_light)
        covered = np.full_like(gray, 25) + np.random.default_rng(1).integers(0, 3, gray.shape, dtype=np.uint8)
        self.assertTrue(check_integrity(covered).masked)                 # main sur l'objectif
        self.assertTrue(check_integrity(np.full_like(gray, 230)).masked)  # papier blanc devant
        # doigt devant une webcam : lueur rouge, dégradé et bruit (contraste > 10) mais aucun contour
        yy, xx = np.mgrid[0:gray.shape[0], 0:gray.shape[1]]
        glow = 60 + 70 * np.exp(-((xx - 320) ** 2 + (yy - 200) ** 2) / (2 * 180.0 ** 2))
        finger = np.clip(glow + np.random.default_rng(2).normal(0, 2, gray.shape), 0, 255).astype(np.uint8)
        f = check_integrity(finger)
        self.assertGreater(f.contrast, 10)
        self.assertTrue(f.masked)
        dark = (gray * 0.12).astype(np.uint8)
        d = check_integrity(dark)
        self.assertFalse(d.masked)                                       # pièce dans le noir : pas un sabotage
        self.assertTrue(d.low_light)

    def test_persistence(self):
        p = Persistence(2.0)
        self.assertFalse(p.update(True, 0.0))
        self.assertFalse(p.update(True, 1.0))
        self.assertTrue(p.update(True, 2.1))
        self.assertFalse(p.update(False, 2.2))

    def test_motion_gate(self):
        g = MotionGate()
        base = cv2.cvtColor(scene(), cv2.COLOR_BGR2GRAY)
        for i in range(20):
            moving, _ = g.update(cv2.cvtColor(scene(i), cv2.COLOR_BGR2GRAY))
        self.assertFalse(moving)
        moved = base.copy()
        cv2.rectangle(moved, (200, 150), (320, 420), 20, -1)
        self.assertTrue(g.update(moved)[0])


class BadgeTest(unittest.TestCase):
    def test_read_and_assign(self):
        img = with_badge(scene(), 7, 300, 200)
        found = BadgeReader().read(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        self.assertEqual([b[0] for b in found], [7])
        boxes = {1: (0.40, 0.30, 0.60, 0.90), 2: (0.70, 0.30, 0.90, 0.90)}
        self.assertEqual(assign_badges(found, boxes), {1: 7})


class PresenceTest(unittest.TestCase):
    def test_dwell_and_badge_memory(self):
        tr = PresenceTracker(ZONE)
        tr.update([(5, (0.05, 0.3, 0.15, 0.8), 0.9)], 0.0)                 # hors zone
        tr.update([(5, (0.40, 0.3, 0.60, 0.8), 0.9)], 1.0, {5: 12})        # entre, badge lu
        tr.update([(5, (0.42, 0.3, 0.62, 0.8), 0.9)], 6.0)                 # badge plus visible
        t5 = tr.tracks[5]
        self.assertTrue(t5.in_zone)
        self.assertAlmostEqual(t5.dwell(6.0), 5.0)
        self.assertEqual(t5.badge, 12)
        tr.update([], 9.0)                                                  # perdu depuis 3 s
        self.assertNotIn(5, tr.tracks)


class PipelineTest(unittest.TestCase):
    def test_states_and_messages(self):
        s = VisionSettings(zone=ZONE, authorized_badges={7: "A. Martin"}, mqtt_enabled=False)
        inside, outside = (0.40, 0.30, 0.60, 0.90), (0.02, 0.30, 0.15, 0.90)
        # YOLO ne tourne qu'une fois la porte de mouvement prête (6e image) : le script démarre là
        script = [[(1, outside, 0.9)]] * 2 + [[(1, inside, 0.9)]] * 40
        p = VisionPipeline(s, FakeDetector(script))
        pub = Publisher(s)
        msgs, t = [], 0.0
        for i in range(36):
            img = scene(i)
            if i >= 3:                                    # quelqu'un bouge : la porte de mouvement s'ouvre
                cv2.rectangle(img, (250 + i, 150), (380 + i, 430), 30, -1)
                img = with_badge(img, 7, 290 + i, 220) if i < 14 else img     # badge visible puis caché
            st, annotated = p.process(img, t)
            m = pub.maybe_publish(st)
            if m:
                msgs.append(m)
            t += 0.1
        self.assertEqual(annotated.shape, (480, 640, 3))
        last = msgs[-1]
        self.assertEqual(last["persons"][0]["badge"], 7)       # badge conservé même quand il n'est plus visible
        self.assertTrue(last["persons"][0]["in_zone"])
        self.assertTrue(last["persons"][0]["authorized"])
        self.assertEqual(len({m["seq"] for m in msgs}), len(msgs))     # seq croissant, jamais répété
        for k in ("device_id", "seq", "boot_id", "ts", "masked", "low_light", "persons", "zone_count"):
            self.assertIn(k, last)

    def test_masking_raises_flag(self):
        s = VisionSettings(zone=ZONE, mqtt_enabled=False)
        p = VisionPipeline(s, FakeDetector([[]]))
        st = None
        for i in range(30):
            st, _ = p.process(np.full((480, 640, 3), 20, np.uint8), i * 0.1)
        self.assertTrue(st.masked)


def unit(*xs: float) -> np.ndarray:
    v = np.zeros(128, np.float32)
    v[:len(xs)] = xs
    return v


class FacesTest(unittest.TestCase):
    """Logique de la reconnaissance, sans réseau neuronal (vecteurs fabriqués)."""

    def gallery(self) -> Gallery:
        feats = [unit(1, 0.1), unit(1, -0.1), unit(1, 0), unit(0, 1, 0.1), unit(0, 1, -0.1), unit(0, 1)]
        return Gallery(["Michel", "Jeffrick"], np.array(feats), np.array([0, 0, 0, 1, 1, 1]))

    def test_match_known_unknown_and_ambiguous(self):
        g = self.gallery()
        self.assertEqual(g.match(unit(1, 0.05))[0], "Michel")
        self.assertEqual(g.match(unit(0.05, 1))[0], "Jeffrick")
        self.assertIsNone(g.match(unit(0, 0, 1))[0])            # personne inconnue : loin des deux
        self.assertIsNone(g.match(unit(1, 1))[0])               # entre les deux : marge insuffisante, inconnu

    def test_save_and_load_keeps_no_image(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "visages.npz"
            self.gallery().save(path)
            self.assertEqual(sorted(np.load(path).files), ["feats", "labels", "names"])
            self.assertEqual(Gallery.load(path).match(unit(1, 0))[0], "Michel")

    def test_identity_needs_two_concordant_votes(self):
        v = IdentityVotes()
        box = (0, 0, 1, 1)
        v.add(FaceMatch("Michel", 0.6, box))
        self.assertIsNone(v.name)                               # une seule reconnaissance : pas encore
        v.add(FaceMatch(None, 0.2, box))                        # visage flou : ne compte ni pour ni contre
        v.add(FaceMatch("Michel", 0.7, box))
        self.assertEqual(v.name, "Michel")
        v.add(FaceMatch("Jeffrick", 0.6, box))                  # autre visage sur la même piste : on repart de zéro
        self.assertIsNone(v.name)

    def test_profile_face_is_not_compared(self):
        face = np.zeros(15, np.float32)
        face[4:10] = [100, 100, 140, 100, 120, 120]              # oeil droit, oeil gauche, nez au milieu
        self.assertTrue(FaceEngine.frontal(face))
        face[8] = 150                                            # nez hors des yeux : tête de profil
        self.assertFalse(FaceEngine.frontal(face))


class FakeFaces:
    def __init__(self, name):
        self.name, self.calls = name, 0

    def identify(self, frame, box):
        self.calls += 1
        return FaceMatch(self.name, 0.62, box)


class FacePipelineTest(unittest.TestCase):
    def test_recognized_face_is_published_and_authorized(self):
        s = VisionSettings(zone=ZONE, mqtt_enabled=False, authorized_faces={"Michel": "Michel"})
        faces = FakeFaces("Michel")
        p = VisionPipeline(s, FakeDetector([[(1, (0.4, 0.3, 0.6, 0.9), 0.9)]]), faces)
        st = None
        for i in range(20):
            st, img = p.process(scene(i), i * 0.1)
        person = st.persons[0]
        self.assertEqual(person["face"], "Michel")
        self.assertTrue(person["authorized"])
        self.assertLess(faces.calls, 10)                         # reconnue : contrôles espacés (5 s)
        self.assertIn("face", Publisher(s).message(st)["persons"][0])

    def test_face_outside_whitelist_is_not_authorized(self):
        s = VisionSettings(zone=ZONE, mqtt_enabled=False, authorized_faces={})
        p = VisionPipeline(s, FakeDetector([[(1, (0.4, 0.3, 0.6, 0.9), 0.9)]]), FakeFaces("Michel"))
        for i in range(20):
            st, _ = p.process(scene(i), i * 0.1)
        self.assertEqual(st.persons[0]["face"], "Michel")
        self.assertFalse(st.persons[0]["authorized"])


@unittest.skipUnless(FaceEngine.available(VISION / "models"), "modèles YuNet/SFace absents (tools/visages.py modeles)")
class FaceModelsTest(unittest.TestCase):
    def test_models_load_and_find_no_face_in_empty_scene(self):
        e = FaceEngine(VISION / "models")
        self.assertEqual(len(e.detect(scene())), 0)


@unittest.skipUnless((VISION / "models" / "yolov8n.pt").exists(), "modèle yolov8n.pt absent")
class YoloTest(unittest.TestCase):
    def test_bus_image(self):
        import ultralytics
        from app.detector import YoloPersonDetector
        det = YoloPersonDetector(str(VISION / "models" / "yolov8n.pt"), 320, 0.5)
        img = cv2.imread(str(Path(ultralytics.__file__).parent / "assets" / "bus.jpg"))
        dets = []
        for _ in range(3):                                  # ByteTrack confirme les pistes dès la 2e image
            dets = det.track(img)
        self.assertGreaterEqual(len(dets), 3)


if __name__ == "__main__":
    unittest.main()
