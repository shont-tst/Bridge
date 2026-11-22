// DDS functions that take a struct by value, given versions that take a pointer instead. Python's ctypes in the
// browser (Pyodide's libffi) can't pass a struct by value, so endplay's wrappers call these there.
#include "dll.h"  // DDS's own header (libs/dds/include)

extern "C" {
int STDCALL SolveBoardPtr(deal *dl, int target, int solutions, int mode, futureTricks *futp, int threadIndex)
{ return SolveBoard(*dl, target, solutions, mode, futp, threadIndex); }
int STDCALL SolveBoardPBNPtr(dealPBN *dl, int target, int solutions, int mode, futureTricks *futp, int threadIndex)
{ return SolveBoardPBN(*dl, target, solutions, mode, futp, threadIndex); }
int STDCALL CalcDDtablePtr(ddTableDeal *d, ddTableResults *t) { return CalcDDtable(*d, t); }
int STDCALL CalcDDtablePBNPtr(ddTableDealPBN *d, ddTableResults *t) { return CalcDDtablePBN(*d, t); }
int STDCALL CalcParPtr(ddTableDeal *d, int vul, ddTableResults *t, parResults *p) { return CalcPar(*d, vul, t, p); }
int STDCALL CalcParPBNPtr(ddTableDealPBN *d, ddTableResults *t, int vul, parResults *p) { return CalcParPBN(*d, t, vul, p); }
int STDCALL AnalysePlayBinPtr(deal *dl, playTraceBin *play, solvedPlay *solved, int thrId)
{ return AnalysePlayBin(*dl, *play, solved, thrId); }
int STDCALL AnalysePlayPBNPtr(dealPBN *dl, playTracePBN *play, solvedPlay *solved, int thrId)
{ return AnalysePlayPBN(*dl, *play, solved, thrId); }
}
