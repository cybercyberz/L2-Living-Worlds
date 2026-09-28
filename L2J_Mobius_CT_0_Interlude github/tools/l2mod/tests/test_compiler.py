"""Stage-3 gates: the compiler reproduces the stock client, and patches build to known bytes."""
import os
import unittest

from l2mod import patch, stock
from l2mod.compiler import oracle

HERE = os.path.dirname(os.path.abspath(__file__))
PATCHES = os.path.join(os.path.dirname(HERE), "patches")

# The Quest Navigator patch as installed and tested in game on 2026-09-28.
QUEST_NAVIGATOR_SHA256 = "144a2f5db80a78c000f68c4540133f772a8b989254dd5374270a8e920ccf8638"


class Stage3Compiler(unittest.TestCase):
    def test_interface_compiles_to_stock(self):
        """Every function in interface.u, compiled from its own embedded source, gives the stock bytes."""
        res = oracle.run("interface.u")
        problems = [p for p, _, _ in res.mismatched] + list(res.errors) + list(res.unsupported)
        self.assertEqual(problems, [], res.summary())
        self.assertEqual(len(res.matched), 1641)

    def test_quest_navigator_patch(self):
        """The Quest Navigator patch, written as source, builds to the file that was tested in game."""
        pf = patch.PatchFile(os.path.join(PATCHES, "quest-navigator.l2patch"))
        data, _ = patch.build("interface.u", [pf])
        self.assertEqual(stock.sha256(data), QUEST_NAVIGATOR_SHA256)

    def test_patch_errors_are_caught(self):
        """A patch that doesn't compile is refused with a clear error, before anything is written."""
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".l2patch", delete=False, encoding="utf-8") as f:
            f.write("package interface.u\nreplace QuestTreeWnd.OnClickButton\n{\n\tNoSuchFunction();\n}\n")
        try:
            with self.assertRaises(patch.PatchError):
                patch.build("interface.u", [patch.PatchFile(f.name)])
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
