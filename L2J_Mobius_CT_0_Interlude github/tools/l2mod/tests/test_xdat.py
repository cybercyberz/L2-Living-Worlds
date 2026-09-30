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

    def _build(self, text):
        path = _patch_file(text)
        try:
            return patch.build("interface.xdat", [patch.PatchFile(path)])[0]
        finally:
            os.unlink(path)

    def test_add_window_copy_and_shortcut(self):
        data = self._build("package interface.xdat\n"
                           "add window L2modTestWnd from PartyWndOption\n"
                           "copy QuestTreeWnd.btnClose to L2modTestWnd as btnClose\n"
                           "shortcut GamingState Alt+L = \"ShowL2modTestWnd\"\n")
        x = xdat.Xdat.read(data)
        w = x.window("L2modTestWnd")
        self.assertEqual(w["script"], "L2modTestWnd")
        self.assertEqual({c["ownerWnd"] for c in w.walk() if c is not w}, {"L2modTestWnd"})
        self.assertEqual(w.get_child("btnClose").kind, "Button")
        self.assertEqual(x.window("PartyWndOption")["script"], "PartyWndOption")  # the source is untouched
        gaming = [s for s in x.shortcuts if s["state"] == "GamingState"][0]
        last = gaming["actions"][-1]
        self.assertEqual((last["key_1"], last["key_2"], last["key_3"], last["action"]),
                         (76, 18, 0, "ShowL2modTestWnd"))

    def test_taken_shortcut_is_refused(self):
        with self.assertRaises(patch.PatchError):  # Alt+P is ApplyMinFrame
            self._build("package interface.xdat\nshortcut GamingState Alt+P = \"Foo\"\n")

    def test_existing_window_is_refused(self):
        with self.assertRaises(patch.PatchError):
            self._build("package interface.xdat\nadd window QuestTreeWnd from PartyWndOption\n")


if __name__ == "__main__":
    unittest.main()
