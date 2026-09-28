"""The l2mod safety gates. Every tool change must keep these passing: `python tools/l2mod selftest`.

L2MOD_QUICK=1 limits the per-package gates to interface.u.
"""
import os
import unittest

from l2mod import asm, disasm, load, stock
from l2mod.crypto import ver111
from l2mod.upk import bytecode, objects
from l2mod.upk.package import Package


def packages():
    if os.environ.get("L2MOD_QUICK"):
        return ["interface.u"]
    return stock.stock_names()


class Stage1Package(unittest.TestCase):
    def test_stock_hashes(self):
        for name in packages():
            with self.subTest(name):
                stock.stock_bytes(name)  # raises NotStock

    def test_roundtrip_unmodified(self):
        """read -> write -> encrypt gives back the stock file byte for byte."""
        for name in packages():
            with self.subTest(name):
                raw = stock.stock_bytes(name)
                self.assertTrue(ver111.check_crc(raw))
                plain = ver111.decrypt(raw)
                pkg = Package(plain)
                out = pkg.to_bytes()
                self.assertEqual(out, plain)
                self.assertEqual(ver111.encrypt(out, ver111.footer_of(raw)), raw)

    def test_script_objects_fully_parsed(self):
        """Every script object's serial data is consumed exactly: no guessed fields."""
        for name in packages():
            pkg = load.package(name)
            walker = load.script_walker(pkg)
            bad = []
            for i, e in enumerate(pkg.exports):
                if pkg.class_name(i + 1) not in objects.SCRIPT_CLASSES:
                    continue
                o = objects.parse(pkg, i + 1, walker)
                if o["_end"] != e.size:
                    bad.append(pkg.path(i + 1))
            with self.subTest(name):
                self.assertEqual(bad, [])

    def test_relocating_writer(self):
        """Changing one object moves only that object; everything else keeps its bytes and offset."""
        pkg, raw = load.fresh_package("interface.u")
        ref = pkg.find("QuestTreeWnd.OnClickButton")
        before = [(e.offset, e.data) for e in pkg.exports]
        pkg.exports[ref - 1].data = pkg.exports[ref - 1].data  # same bytes, but marked dirty
        pkg.name_index("L2modTestName", add=True)
        out = Package(pkg.to_bytes())
        self.assertIn("L2modTestName", out.names)
        for i, e in enumerate(out.exports):
            if i + 1 == ref:
                self.assertEqual(e.data, before[i][1])
            else:
                self.assertEqual((e.offset, e.data), before[i])


class Stage2Bytecode(unittest.TestCase):
    def test_decode_every_script(self):
        """No unknown tokens, exact ScriptSize, jumps on token boundaries, and re-encoding is identical."""
        for name in packages():
            pkg = load.package(name)
            bad = []
            for ref in load.struct_refs(pkg):
                try:
                    stmts, o = load.script(pkg, ref)
                    starts = {n.mem for s in stmts for n in bytecode.walk(s)}
                    for _, off in bytecode.code_offsets(stmts):
                        if off not in starts and off != o["script_size"]:
                            raise bytecode.DecodeError("jump to %d" % off)
                    data, mem = bytecode.encode(stmts)
                    e = pkg.exports[ref - 1]
                    if mem != o["script_size"] or data != e.data[o["script_start"]:o["script_end"]]:
                        raise bytecode.DecodeError("re-encode differs")
                except Exception as x:
                    bad.append("%s: %s" % (pkg.path(ref), x))
            with self.subTest(name):
                self.assertEqual(bad, [])

    def test_listing_roundtrip(self):
        """asm(disasm(f)) == f for every script."""
        for name in packages():
            pkg = load.package(name)
            refs = disasm.RefNames(pkg)
            lister = disasm.Lister(pkg, refs)
            bad = []
            for ref in load.struct_refs(pkg):
                stmts, o = load.script(pkg, ref)
                e = pkg.exports[ref - 1]
                text = "\n".join(lister.listing(stmts, o["script_size"]))
                try:
                    _, data, mem = asm.assemble(text, pkg, refs)
                    if data != e.data[o["script_start"]:o["script_end"]] or mem != o["script_size"]:
                        bad.append(pkg.path(ref))
                except asm.AsmError as x:
                    bad.append("%s: %s" % (pkg.path(ref), x))
            with self.subTest(name):
                self.assertEqual(bad, [])

    def test_handwritten_labels(self):
        """Hand-written code with named labels assembles to the stock QuestTreeWnd.OnClickButton."""
        pkg = load.package("interface.u")
        refs = disasm.RefNames(pkg)
        text = """
            Switch(0, Local(&QuestTreeWnd.OnClickButton.strID))
            Case(@notclose, "btnClose")
            Virtual(#HandleQuestCancel)
            Jump(@after)
        notclose:
            Case(default)
        after:
            JumpIfNot(@done, N122(N128(Local(&QuestTreeWnd.OnClickButton.strID), IntConstByte(4)), "root"))
            Virtual(#UpdateTargetInfo)
        done:
            Return(Nothing)
        """
        _, data, mem = asm.assemble(text, pkg, refs)
        ref = pkg.find("QuestTreeWnd.OnClickButton")
        o = load.parse(pkg, ref)
        self.assertEqual(mem, 60)
        self.assertEqual(data, pkg.exports[ref - 1].data[o["script_start"]:o["script_end"]])


if __name__ == "__main__":
    unittest.main()
