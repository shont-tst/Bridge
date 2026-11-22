"""Make endplay's ctypes wrappers call DDS's pointer versions (byref.cpp) for functions that take structs by value."""
import re, sys
p = sys.argv[1]
s = open(p).read()
subs = {
    "_dll.SolveBoard(dl,": "_dll.SolveBoardPtr(ctypes.byref(dl),",
    "_dll.SolveBoardPBN(dlPBN,": "_dll.SolveBoardPBNPtr(ctypes.byref(dlPBN),",
    "_dll.CalcDDtable(tableDeal,": "_dll.CalcDDtablePtr(ctypes.byref(tableDeal),",
    "_dll.CalcDDtablePBN(tableDealPBN,": "_dll.CalcDDtablePBNPtr(ctypes.byref(tableDealPBN),",
    "_dll.CalcPar(tableDeal,": "_dll.CalcParPtr(ctypes.byref(tableDeal),",
    "_dll.CalcParPBN(tableDealPBN,": "_dll.CalcParPBNPtr(ctypes.byref(tableDealPBN),",
    "_dll.AnalysePlayBin(dl, play,": "_dll.AnalysePlayBinPtr(ctypes.byref(dl), ctypes.byref(play),",
    "_dll.AnalysePlayPBN(dlPBN, playPBN,": "_dll.AnalysePlayPBNPtr(ctypes.byref(dlPBN), ctypes.byref(playPBN),",
}
for a, b in subs.items():
    assert s.count(a) == 1, a
    s = s.replace(a, b)
open(p, "w").write(s)
