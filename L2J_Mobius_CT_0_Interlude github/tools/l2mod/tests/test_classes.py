"""Stage 6 gates: the class compiler."""
import unittest

from l2mod import load
from l2mod.compiler import classoracle
from l2mod.compiler.classgen import ClassGenError, add_class
from l2mod.symbols import SymbolTable
from l2mod.upk import objects
from l2mod.upk.package import Package

NEW_CLASS = """class L2modTestWnd extends UICommonAPI;

const MAX_ROWS = 3;

struct RowInfo
{
	var string Label;
	var int Count;
};

var WindowHandle m_hOwnerWnd;
var array<RowInfo> m_Rows;
var int m_Picked[MAX_ROWS];
var string m_Title;

function OnLoad()
{
	RegisterEvent( EV_ShortcutCommand );
	m_hOwnerWnd = GetHandle( "L2modTestWnd" );
}

function OnEvent( int a_EventID, String a_Param )
{
	local String Command;

	if( a_EventID == EV_ShortcutCommand && ParseString( a_Param, "Command", Command ) && Command == "ShowL2modTestWnd" )
	{
		if( m_hOwnerWnd.IsShowWindow() )
			m_hOwnerWnd.HideWindow();
		else
			m_hOwnerWnd.ShowWindow();
	}
}

function int CountRows()
{
	return m_Rows.Length;
}

function OnClickButton( string strID )
{
	switch( strID )
	{
	case "btnPing":
		RequestBypassToServer( "_bbs_test ping " $ CountRows() );
		break;
	}
}

defaultproperties
{
	m_Title="Test"
	m_Picked(1)=2
}
"""


class Stage6Classes(unittest.TestCase):
    def test_every_stock_class_compiles_to_stock_bytes(self):
        """Every interface.u class, compiled from its embedded source (plus its defaults written out as source),
        gives every one of its objects' stock bytes."""
        r = classoracle.run("interface.u")
        self.assertEqual(r.errors, [])
        self.assertEqual(r.missing, [])
        self.assertEqual([m[0] for m in r.mismatches], [])
        self.assertEqual(len(r.classes_matched), 142)

    def test_new_class(self):
        """A class that isn't in the package compiles in, leaves every stock object alone, and reads back."""
        table = SymbolTable().load_all()
        pkg, _ = load.fresh_package("interface.u")
        n = len(pkg.exports)
        add_class(table, pkg, NEW_CLASS.replace("\n", "\r\n"))
        new = Package(pkg.to_bytes())
        stock = load.package("interface.u")
        for i in range(n):
            self.assertEqual(new.exports[i].data, stock.exports[i].data)
            self.assertEqual(new.exports[i].offset, stock.exports[i].offset)
        walker = load.script_walker(new)
        paths = set()
        for ref in range(n + 1, len(new.exports) + 1):
            o = objects.parse(new, ref, walker)
            self.assertEqual(o["_end"], new.exports[ref - 1].size, new.path(ref))
            paths.add(new.path(ref))
        for p in ("L2modTestWnd", "L2modTestWnd.RowInfo.Label", "L2modTestWnd.m_Rows.m_Rows",
                  "L2modTestWnd.CountRows.ReturnValue", "L2modTestWnd.OnEvent.Command", "L2modTestWnd.MAX_ROWS"):
            self.assertIn(p, paths)
        cls = objects.parse(new, new.find("L2modTestWnd", "Class"), walker)
        self.assertEqual([(d["name"], d["index"]) for d in cls["defaults"]], [("m_Picked", 1), ("m_Title", 0)])
        picked = objects.parse(new, new.find("L2modTestWnd.m_Picked"), walker)
        self.assertEqual(picked["array_dim"], 3)

    def test_duplicate_class_is_refused(self):
        table = SymbolTable().load_all()
        pkg, _ = load.fresh_package("interface.u")
        with self.assertRaises(ClassGenError):
            add_class(table, pkg, "class QuestTreeWnd extends UICommonAPI;\r\n")


if __name__ == "__main__":
    unittest.main()
