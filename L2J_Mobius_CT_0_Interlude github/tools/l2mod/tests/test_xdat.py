"""Stage-4 gates: interface.xdat reads and writes back exactly, and layout patches are verified."""
import os
import tempfile
import unittest

from l2mod import patch, stock, xdat


def _patch_file(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".l2patch", delete=False, encoding="utf-8")
    f.write(text)
    f.close()
    return f.name


class Stage4Xdat(unittest.TestCase):
    def test_roundtrip(self):
        data = stock.stock_bytes("interface.xdat")
        x = xdat.Xdat.read(data)
        self.assertEqual(x.to_bytes(), data)
        self.assertEqual(len(x.windows), 140)
        self.assertEqual(sum(1 for w in x.windows for _ in w.walk()), 2229)  # windows plus every nested control

    def test_clone_and_set(self):
        path = _patch_file("package interface.xdat\n"
                           "clone QuestTreeWnd.btnClose as btnTest\n"
                           "set QuestTreeWnd.btnTest.anchor_x = 170\n"
                           "set QuestTreeWnd.MainTree.size_absolute_height = 250\n")
        try:
            data, report = patch.build("interface.xdat", [patch.PatchFile(path)])
        finally:
            os.unlink(path)
        x = xdat.Xdat.read(data)
        w = x.window("QuestTreeWnd")
        self.assertEqual(w.get_child("btnTest")["anchor_x"], 170)
        self.assertEqual(w.get_child("btnTest").kind, "Button")
        self.assertEqual(w.get_child("MainTree")["size_absolute_height"], 250)
        self.assertEqual(w.get_child("btnClose")["anchor_x"], 91)  # the original is untouched

    def test_bad_field_is_refused(self):
        path = _patch_file("package interface.xdat\nset QuestTreeWnd.btnClose.noSuchField = 1\n")
        try:
            with self.assertRaises(patch.PatchError):
                patch.build("interface.xdat", [patch.PatchFile(path)])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
