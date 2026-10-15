"""Character Forge experiment: reference ingestion, segmentation, region detection and full-body completion."""

import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from forge_character_forge import dna as D
from forge_character_forge import reconstruct as R
from forge_character_forge.character import build_character

REFS = Path(__file__).resolve().parent.parent / "examples/character_forge_aaa/references"


def _figure(path, fmt="PNG", alpha=False):
    im = Image.new("RGBA" if alpha else "RGB", (300, 600), (0, 0, 0, 0) if alpha else (240, 240, 240))
    d = ImageDraw.Draw(im)
    d.ellipse([120, 20, 180, 95], fill=(200, 150, 120))
    d.rectangle([140, 90, 160, 110], fill=(200, 150, 120))
    d.polygon([(95, 110), (205, 110), (190, 300), (110, 300)], fill=(50, 80, 160))
    d.rectangle([115, 300, 145, 560], fill=(40, 40, 40))
    d.rectangle([155, 300, 185, 560], fill=(40, 40, 40))
    im.save(path, fmt)


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_supported_formats(self):
        for ext, fmt in ((".png", "PNG"), (".jpg", "JPEG"), (".jpeg", "JPEG"), (".webp", "WEBP")):
            p = self.tmp / f"f{ext}"
            _figure(p, fmt)
            ref = R.load_reference(p, authorized=True)
            self.assertEqual(ref.meta["format"], fmt)
            self.assertEqual(len(ref.meta["sha256"]), 64)

    def test_rejections(self):
        p = self.tmp / "f.png"
        _figure(p)
        with self.assertRaises(R.ReferenceError):
            R.load_reference(p)  # not authorized
        g = self.tmp / "f.gif"
        Image.new("RGB", (100, 100)).save(g, "GIF")
        with self.assertRaises(R.ReferenceError):
            R.load_reference(g, authorized=True)
        fake = self.tmp / "fake.png"
        Image.new("RGB", (100, 100)).save(fake, "GIF")  # GIF content behind a .png name
        with self.assertRaises(R.ReferenceError):
            R.load_reference(fake, authorized=True)
        broken = self.tmp / "broken.png"
        broken.write_bytes(p.read_bytes()[:60])
        with self.assertRaises(R.ReferenceError):
            R.load_reference(broken, authorized=True)
        tiny = self.tmp / "tiny.png"
        Image.new("RGB", (20, 20)).save(tiny)
        with self.assertRaises(R.ReferenceError):
            R.load_reference(tiny, authorized=True)
        blank = self.tmp / "blank.png"
        Image.new("RGB", (200, 200), (255, 255, 255)).save(blank)
        with self.assertRaises(R.ReferenceError):
            R.analyze(R.load_reference(blank, authorized=True))

    def test_alpha_segmentation(self):
        p = self.tmp / "a.png"
        _figure(p, alpha=True)
        ref = R.load_reference(p, authorized=True)
        mask, seg = R.segment(ref)
        self.assertEqual(seg["method"], "alpha_channel")
        self.assertTrue(mask[50, 150] and not mask[5, 5])


class RegionDetectionTests(unittest.TestCase):
    def _obs(self, name):
        return R.analyze(R.load_reference(REFS / name, authorized=True))

    def test_full_body(self):
        o = self._obs("ref_full_front.png")
        self.assertEqual(o.posture, "standing")
        self.assertEqual(o.style, "realistic")
        self.assertTrue(all(o.regions[r] == "visible" for r in ("head", "chest", "hips_pelvis", "knees", "feet")))
        self.assertAlmostEqual(o.sil.height_hu, 8.0, delta=0.8)

    def test_waist_up_and_portrait_are_partial(self):
        w = self._obs("ref_waist_up.png")
        self.assertEqual(w.regions["chest"], "visible")
        self.assertEqual(w.regions["thighs"], "cropped")
        self.assertEqual(w.regions["feet"], "cropped")
        p = self._obs("ref_portrait.jpg")
        self.assertEqual(p.regions["head"], "visible")
        self.assertEqual(p.regions["waist"], "cropped")
        # the same person measured from different crops agrees on head size and shoulder width
        full = self._obs("ref_full_front.png")
        self.assertAlmostEqual(w.sil.head_h, full.sil.head_h, delta=0.06 * full.sil.head_h)
        self.assertAlmostEqual(w.sil.widths_hu[1.75], full.sil.widths_hu[1.75], delta=0.15)

    def test_seated_and_stylized(self):
        self.assertEqual(self._obs("ref_seated.png").posture, "seated")
        s = self._obs("ref_stylized_drawing.png")
        self.assertEqual(s.style, "stylized")
        self.assertEqual(s.regions["back"], "unobservable")


class CompletionTests(unittest.TestCase):
    """Portrait -> complete head-to-toe editable character, with honest provenance."""

    @classmethod
    def setUpClass(cls):
        ref = R.load_reference(REFS / "ref_portrait.jpg", authorized=True)
        base = D.lock(D.new_dna("neutral"), ["body.shoulder_width"])
        base = D.set_trait(base, "body.shoulder_width", 1.2, lock=True)
        cls.ref = ref
        cls.dna, cls.rep = R.reconstruct([ref], base_dna=base, log=lambda *a: None)

    def test_provenance_is_honest(self):
        t = self.dna["traits"]
        for k in ("body.leg_length", "body.thigh_thickness", "body.calf_thickness", "body.hip_width"):
            self.assertEqual(t[k]["provenance"], "invented", k)
        self.assertNotEqual(t["body.height_m"]["provenance"], "observed")
        self.assertEqual(t["appearance.eye_color"]["provenance"], "invented")
        self.assertIn(t["appearance.hair_color"]["provenance"], ("observed", "estimated"))
        self.assertIsNone(self.dna["reconstruction"]["pretrained_model"])
        self.assertEqual(self.dna["regions"]["front"]["feet"], "cropped")

    def test_locked_trait_preserved(self):
        self.assertEqual(self.dna["traits"]["body.shoulder_width"]["value"], 1.2)

    def test_source_traceability(self):
        self.assertEqual(self.dna["sources"][0]["sha256"], self.ref.meta["sha256"])
        observed = [k for k, v in self.dna["traits"].items() if v["provenance"] == "observed"]
        for k in observed:
            self.assertEqual(self.dna["traits"][k]["sources"], [self.ref.id])

    def test_complete_editable_geometry(self):
        ch = build_character(D.to_spec(self.dna), "public", fast=True)
        v = ch.body.verts
        self.assertLess(v[:, 1].min(), 0.02, "feet exist although they were never seen")
        self.assertGreater(np.ptp(v[:, 1]), 1.4)
        edited = D.set_trait(self.dna, "body.leg_length", 1.15)
        ch2 = build_character(D.to_spec(edited), "public", fast=True)
        self.assertGreater(ch2.skeleton["thigh_l"][1], ch.skeleton["thigh_l"][1])


if __name__ == "__main__":
    unittest.main()
