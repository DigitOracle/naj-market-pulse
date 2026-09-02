// Golden Building — whole-tower unit + room generator v2 (Neufert gate G1–G8), send via revit-mcp send_code_to_revit.
// Set FLOORS / FTYPE at the top and run once per floor group (<= 4 floors per send: revit-mcp client cap is 2 min) (each run first clears F-level content it owns).
//   T13: F10–F22 (13 units) · T11: F23,F25,F27,F29,F31 (11) · T10: F24,F26,F28,F30 (10) · T9: F32 (9) · T33: F33 · T34: F34
// v2 plate: core 14x22 centred; corridor cross-ring 1.8 m — N/S strips y∈±[11000,12800] for x∈[-20000,20000] (dead-end legs
// reach the corner units → every unit has corridor frontage, G1), E/W strips x∈±[7000,8800] for y∈[-11000,11000].
// Per unit (local u = along facade, v = depth from corridor side): hall strip 1.2 m along the corridor wall (G2/G6), bath block
// 2.2 x 2.6 m at the far end of the hall (wet room against the corridor, G8), living + bedrooms as front bays each with a facade
// window (G4) and a door from the hall (G3); balcony 1.5 m outside the facade for living + master (door 910); door widths
// 1010 entry / 910 rooms / 810 bath (G5). Room minimums checked and reported (G7).
var doc = document;
var FLOORS = new[] { "F10","F11","F12","F13","F14","F15","F16","F17","F18","F19","F20","F21","F22" };
var FTYPE = "T13";
Func<double, double> ft = mm => UnitUtils.ConvertToInternalUnits(mm, UnitTypeId.Millimeters);
var levels = new System.Collections.Generic.Dictionary<string, Level>();
foreach (Level lv in new FilteredElementCollector(doc).OfClass(typeof(Level))) levels[lv.Name] = lv;
var wt = new FilteredElementCollector(doc).OfClass(typeof(WallType)).Cast<WallType>().First(w => w.Kind == WallKind.Basic);
var syms = new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>().ToList();
var dEnt = syms.First(s => s.FamilyName == "Doors_IntSgl" && s.Name.StartsWith("1010"));
var dInt = syms.First(s => s.FamilyName == "Doors_IntSgl" && s.Name.StartsWith("910"));
var dBath = syms.First(s => s.FamilyName == "Doors_IntSgl" && s.Name.StartsWith("810"));
var win = syms.First(s => s.FamilyName == "Windows_Sgl_Plain" && s.Name.StartsWith("1810x1210"));
foreach (var s in new[] { dEnt, dInt, dBath, win }) if (!s.IsActive) s.Activate();
double P = 20000, CX = 7000, CY = 11000, CXo = 8800, CYo = 12800, H = 3500;
var CLS = new System.Collections.Generic.Dictionary<string, string[]> {
  {"living", new[]{"SL_45_10_45 : Kitchen-dining-living rooms","11-11 11 11 Residential Spaces - Living Room","brick:Living_Room","space room residential"}},
  {"bedroom", new[]{"SL_45_10_09 : Bedrooms","11-11 11 14 Residential Spaces - Bedroom","brick:Bedroom","space room residential sleep"}},
  {"bath", new[]{"SL_45_10 : Living spaces (bathroom)","11-11 11 31 Residential Spaces - Bathroom","rec:Bathroom","space room toilet"}},
  {"hall", new[]{"SL_90 : Circulation spaces (entrance hall)","11-11 17 11 Circulation Spaces - Corridor","brick:Hallway","space corridor entrance"}},
  {"balcony", new[]{"SL_45 : Residential spaces (balcony)","11-11 11 11 Residential Spaces - Living Room","brick:Outdoor_Area","space outdoor balcony"}},
  {"corridor", new[]{"SL_90 : Circulation spaces (verify code)","11-11 17 11 Circulation Spaces - Corridor","brick:Hallway","space corridor"}} };
// bays: x0,y0,x1,y1, type, back side (S = corridor to the south of the bay, etc.)
var bays = new System.Collections.Generic.List<object[]>();
Action<double,double,double,double,string,string> B = (x0,y0,x1,y1,t,back) => bays.Add(new object[]{x0,y0,x1,y1,t,back});
Action<string> S4 = t0 => { B(7000,-P,P,-CYo,"2BR","N"); B(0,-P,7000,-CYo,"1BR","N"); B(-7000,-P,0,-CYo,"1BR","N"); B(-P,-P,-7000,-CYo,"2BR","N"); };
Action E3 = () => { B(CXo,3667,P,CY,"1BR","W"); B(CXo,-3667,P,3667,"1BR","W"); B(CXo,-CY,P,-3667,"1BR","W"); };
if (FTYPE == "T13") { B(-P,CYo,-9000,P,"MS","S"); B(-9000,CYo,-1000,P,"1BR","S"); B(-1000,CYo,7000,P,"1BR","S"); B(7000,CYo,P,P,"2BR","S"); E3(); S4(""); B(-P,-CY,-CXo,0,"MS","E"); B(-P,0,-CXo,CY,"MS","E"); }
if (FTYPE == "T11") { B(-P,CYo,-1000,P,"2BR","S"); B(-1000,CYo,7000,P,"1BR","S"); B(7000,CYo,P,P,"2BR","S"); E3(); S4(""); B(-P,-CY,-CXo,CY,"3BR","E"); }
if (FTYPE == "T10") { B(-P,CYo,-1000,P,"3BR","S"); B(-1000,CYo,7000,P,"1BR","S"); B(7000,CYo,P,P,"2BR","S"); E3(); B(7000,-P,P,-CYo,"2BR","N"); B(-7000,-P,7000,-CYo,"1BR","N"); B(-P,-P,-7000,-CYo,"2BR","N"); B(-P,-CY,-CXo,CY,"3BR","E"); }
if (FTYPE == "T9")  { B(-P,CYo,7000,P,"4BR","S"); B(7000,CYo,P,P,"2BR","S"); E3(); B(7000,-P,P,-CYo,"2BR","N"); B(-7000,-P,7000,-CYo,"1BR","N"); B(-P,-P,-7000,-CYo,"2BR","N"); B(-P,-CY,-CXo,CY,"4BR","E"); }
if (FTYPE == "T33") { B(-2000,CYo,7000,P,"1BR","S"); B(7000,CYo,P,P,"2BR","S"); E3(); S4(""); }
if (FTYPE == "T34") { B(-2000,CYo,7000,P,"1BR","S"); B(7000,CYo,P,P,"2BR","S"); E3(); B(7000,-P,P,-CYo,"2BR","N"); }
var FR = new System.Collections.Generic.Dictionary<string, double[]> { {"1BR", new[]{0.55,0.45}}, {"MS", new[]{0.5,0.5}}, {"2BR", new[]{0.40,0.32,0.28}}, {"3BR", new[]{0.34,0.24,0.21,0.21}}, {"4BR", new[]{0.30,0.20,0.17,0.17,0.16}} };
var NM = new System.Collections.Generic.Dictionary<string, string[]> { {"1BR", new[]{"Living/Kitchen","Bedroom"}}, {"MS", new[]{"Living/Kitchen","Master Bedroom"}}, {"2BR", new[]{"Living/Kitchen","Master Bedroom","Bedroom 2"}}, {"3BR", new[]{"Living/Kitchen","Master Bedroom","Bedroom 2","Bedroom 3"}}, {"4BR", new[]{"Living/Kitchen","Master Bedroom","Bedroom 2","Bedroom 3","Bedroom 4"}} };
int walls = 0, rooms = 0, doors = 0, wins = 0, viol = 0; var vlog = new System.Text.StringBuilder();
var allWalls = new System.Collections.Generic.List<Wall>();
foreach (var fname in FLOORS)
{
    if (!levels.ContainsKey(fname)) continue;
    var lv = levels[fname]; int fl = int.Parse(fname.Substring(1));
    // clear what v1 (or an earlier v2 run) put on this level
    var kill = new System.Collections.Generic.List<ElementId>();
    foreach (var bic in new[] { BuiltInCategory.OST_Doors, BuiltInCategory.OST_Windows, BuiltInCategory.OST_Rooms, BuiltInCategory.OST_Walls })
        foreach (var e in new FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType())
            if (e.LevelId == lv.Id) kill.Add(e.Id);
    if (kill.Count > 0) doc.Delete(kill);
    var edges = new System.Collections.Generic.HashSet<string>(); var lvWalls = new System.Collections.Generic.List<Wall>();
    var checks = new System.Collections.Generic.List<object[]>();
    Func<double,double,double,double,double,Wall> W = (x0,y0,x1,y1,h) => {
        var key = string.Join(",", new[]{Math.Min(x0,x1),Math.Min(y0,y1),Math.Max(x0,x1),Math.Max(y0,y1)}.Select(v=>Math.Round(v)));
        if (!edges.Add(key) || (Math.Abs(x0-x1) < 1 && Math.Abs(y0-y1) < 1)) return null;
        var w = Wall.Create(doc, Line.CreateBound(new XYZ(ft(x0),ft(y0),0), new XYZ(ft(x1),ft(y1),0)), wt.Id, lv.Id, ft(h), 0, false, false); walls++; lvWalls.Add(w); return w; };
    Func<double,double,Wall> HostAt = (x,y) => { var p = new XYZ(ft(x), ft(y), 0); double tol = ft(60);
        return lvWalls.FirstOrDefault(w => { var c = (w.Location as LocationCurve).Curve; var pr = c.Project(new XYZ(p.X, p.Y, c.GetEndPoint(0).Z)); return pr != null && pr.Distance < tol; }); };
    Action<double,double,FamilySymbol> Put = (x,y,sym) => { var h = HostAt(x,y); if (h == null) { vlog.Append(fname + " no host @" + Math.Round(x) + "," + Math.Round(y) + "; "); return; }
        var inst = doc.Create.NewFamilyInstance(new XYZ(ft(x), ft(y), lv.Elevation), sym, h, lv, Autodesk.Revit.DB.Structure.StructuralType.NonStructural);
        if (sym == win) { var sp = inst.get_Parameter(BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM); if (sp != null && !sp.IsReadOnly) sp.Set(ft(900)); wins++; } else doors++; };
    Func<double,double,string,string,string,string,Autodesk.Revit.DB.Architecture.Room> R = (x,y,name,num,dept,kind) => {
        var rm = doc.Create.NewRoom(lv, new UV(ft(x), ft(y))); rm.Name = name; rm.Number = num;
        var c = CLS[kind]; string[] pn = {"DA_UniclassSl","DA_OmniClassT11","DA_BrickClasses","DA_HaystackTags"};
        for (int i = 0; i < 4; i++) { var p = rm.LookupParameter(pn[i]); if (p != null && !p.IsReadOnly) p.Set(c[i]); }
        var d = rm.get_Parameter(BuiltInParameter.ROOM_DEPARTMENT); if (d != null) d.Set(dept);
        var cm = rm.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (cm != null) cm.Set("v2 generator (Neufert gate) — typology template scaled from developer floor-plan deck; not surveyed");
        rooms++; return rm; };
    // plate, core, corridor cross-ring
    W(-P,-P,P,-P,H); W(P,-P,P,P,H); W(P,P,-P,P,H); W(-P,P,-P,-P,H);
    W(-CX,-CY,CX,-CY,H); W(CX,-CY,CX,CY,H); W(CX,CY,-CX,CY,H); W(-CX,CY,-CX,-CY,H);
    W(-P,CYo,P,CYo,H); W(-P,-CYo,P,-CYo,H);                                  // N/S strip outer edges (unit band boundaries)
    W(-P,CY,-CXo,CY,H); W(CXo,CY,P,CY,H); W(-P,-CY,-CXo,-CY,H); W(CXo,-CY,P,-CY,H);   // strip inner edges beside the W/E bands
    W(-CXo,-CY,-CXo,CY,H); W(CXo,-CY,CXo,CY,H);                                // W/E strip outer edges
    R(0, CY + 900, "Corridor", fl.ToString("00") + "-COR", "Circulation", "corridor");
    // units
    for (int u = 0; u < bays.Count; u++)
    {
        double x0 = (double)bays[u][0], y0 = (double)bays[u][1], x1 = (double)bays[u][2], y1 = (double)bays[u][3]; string t = (string)bays[u][4], back = (string)bays[u][5];
        int idx = u + 1; if (FTYPE == "T33" || FTYPE == "T34") idx = (u < 6 ? u + 1 : u + 2);
        string unit = (fl * 100 + idx).ToString("0000");
        double Wd = (back == "S" || back == "N") ? (x1 - x0) : (y1 - y0);   // width along the facade
        double D = (back == "S" || back == "N") ? (y1 - y0) : (x1 - x0);    // depth corridor -> facade
        Func<double,double,double[]> Wp = (uu,vv) => back == "S" ? new[]{x0+uu, y0+vv} : back == "N" ? new[]{x1-uu, y1-vv} : back == "W" ? new[]{x0+vv, y1-uu} : new[]{x1-vv, y0+uu};
        Action<double,double,double,double,double> LW = (u0,v0,u1,v1,h) => { var a = Wp(u0,v0); var b = Wp(u1,v1); W(a[0],a[1],b[0],b[1],h); };
        // unit boundary
        LW(0,0,Wd,0,H); LW(Wd,0,Wd,D,H); LW(Wd,D,0,D,H); LW(0,D,0,0,H);
        double hallD = 1200, bathW = 2200, bathD = 2600;
        LW(0,hallD,Wd-bathW,hallD,H);                    // hall / front rooms
        LW(Wd-bathW,0,Wd-bathW,bathD,H);                 // bath block west side
        LW(Wd-bathW,bathD,Wd,bathD,H);                   // bath block front
        var fr = FR[t]; var nm = NM[t]; double pos = 0;
        var mids = new System.Collections.Generic.List<double>();
        for (int k = 0; k < fr.Length; k++) { double w = fr[k]*Wd; if (k < fr.Length-1) LW(pos+w, hallD, pos+w, D, H); mids.Add(pos + w/2); pos += w; }
        // doors: entry from corridor into the hall, hall -> each front room, hall -> bath
        var e = Wp(800, 0); Put(e[0], e[1], dEnt);
        for (int k = 0; k < mids.Count; k++) { var d0 = Wp(Math.Min(mids[k], Wd-bathW-700), hallD); Put(d0[0], d0[1], dInt); }
        var bd = Wp(Wd-bathW, 600); Put(bd[0], bd[1], dBath);
        // facade: balcony for living + master (door), window for every front room
        for (int k = 0; k < mids.Count; k++) {
            double wk = fr[k]*Wd, uk0 = mids[k]-wk/2, uk1 = mids[k]+wk/2;
            if (k <= 1 && wk >= 3000) { LW(uk0+300,D,uk0+300,D+1500,1100); LW(uk0+300,D+1500,uk1-300,D+1500,1100); LW(uk1-300,D+1500,uk1-300,D,1100);
                var bdoor = Wp(mids[k]-700, D); Put(bdoor[0], bdoor[1], dInt); var wpt = Wp(mids[k]+900, D); Put(wpt[0], wpt[1], win);
                var bc = Wp(mids[k], D+750); R(bc[0], bc[1], "Balcony", unit + "-B" + (k+1), "Unit " + unit + " · " + t, "balcony"); }
            else { var wpt = Wp(mids[k], D); Put(wpt[0], wpt[1], win); }
        }
        // rooms + gate checks
        var hc = Wp((Wd-bathW)/2, hallD/2); R(hc[0], hc[1], "Hall", unit + "-H", "Unit " + unit + " · " + t, "hall");
        var bc2 = Wp(Wd-bathW/2, bathD/2); var rb = R(bc2[0], bc2[1], "Bathroom", unit + "-WC", "Unit " + unit + " · " + t, "bath");
        for (int k = 0; k < mids.Count; k++) {
            var rc = Wp(mids[k], D - 1800); var kind = k == 0 ? "living" : "bedroom";
            var rm = R(rc[0], rc[1], nm[k], unit + "-" + (k+1), "Unit " + unit + " · " + t, kind);
            double min = k == 0 ? (fr.Length >= 4 ? 21 : 14) : (k == 1 ? 12 : 7);
            checks.Add(new object[]{rm, min, unit + " " + nm[k]});          // G7 evaluated after ONE regen (Area forces a regen per read)
        }
        checks.Add(new object[]{rb, 3.5, unit + " bath"});
    }
    doc.Regenerate();
    foreach (var c in checks) { var rm = (Autodesk.Revit.DB.Architecture.Room)c[0]; double min = (double)c[1];
        double a = UnitUtils.ConvertFromInternalUnits(rm.Area, UnitTypeId.SquareMeters);
        if (a < min) { viol++; vlog.Append((string)c[2] + " " + Math.Round(a,1) + "<" + min + "; "); } }
    allWalls.AddRange(lvWalls);
}
doc.Regenerate();
return FTYPE + " on " + FLOORS.Length + " floors: walls " + walls + ", rooms " + rooms + ", doors " + doors + ", windows " + wins + " | G7 violations " + viol + (vlog.Length > 0 ? " | " + vlog.ToString().Substring(0, Math.Min(600, vlog.Length)) : "");
