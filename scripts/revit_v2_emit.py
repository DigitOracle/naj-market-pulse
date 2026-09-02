"""Golden Building generator v2 (Neufert gate G1-G8) - Python side.
Computes every wall / opening / room for a floor and emits three compact C# snippets for revit-mcp send_code_to_revit
(the plugin reads ONE 8 KB socket buffer, so each snippet stays well under that): 1 walls, 2 openings, 3 rooms (+G7 report).
Also writes data/revit/v2_<floor>.json (the same geometry) for the cards and the Pro import.
Usage: python scripts/revit_v2_emit.py F32            -> data/revit/sends/F32_1.cs, _2.cs, _3.cs
       python scripts/revit_v2_emit.py F32 --print 1  -> print snippet 1 to stdout
Plate: 40 x 40 m, core 14 x 22 centred, corridor ring 1.8 m. Per unit: hall strip 1.2 m along the corridor wall, bath
2.2 x 2.6 m at the hall end, front rooms by fraction, window per habitable room, balcony 1.5 m on living + master.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
P, CX, CY, CXo, CYo, H = 20000, 7000, 11000, 8800, 12800, 3500   # P = half plate WIDTH (x)
PY = 21700          # half plate DEPTH (y): calibrated 2 Sep 2026 so N/S-band unit areas meet the Imtiaz sheet (band depth 7.2 -> 8.9 m)
WB1 = 4500          # west-band single 3BR / duplex: top of the bay (15.5 m tall = 173 m2 per the sheet); pocket above it joins the corridor
FR = {"1BR": [.55, .45], "MS": [.5, .5], "2BR": [.40, .32, .28], "3BR": [.34, .24, .21, .21], "4BR": [.30, .20, .17, .17, .16]}
NM = {"1BR": ["Living/Kitchen", "Bedroom"], "MS": ["Living/Kitchen", "Master Bedroom"], "2BR": ["Living/Kitchen", "Master Bedroom", "Bedroom 2"],
      "3BR": ["Living/Kitchen", "Master Bedroom", "Bedroom 2", "Bedroom 3"], "4BR": ["Living/Kitchen", "Master Bedroom", "Bedroom 2", "Bedroom 3", "Bedroom 4"]}
KINDS = ["living", "bedroom", "bath", "hall", "balcony", "corridor"]
CLS = {"living": ["SL_45_10_45 : Kitchen-dining-living rooms", "11-11 11 11 Residential Spaces - Living Room", "brick:Living_Room", "space room residential"],
       "bedroom": ["SL_45_10_09 : Bedrooms", "11-11 11 14 Residential Spaces - Bedroom", "brick:Bedroom", "space room residential sleep"],
       "bath": ["SL_45_10 : Living spaces (bathroom)", "11-11 11 31 Residential Spaces - Bathroom", "rec:Bathroom", "space room toilet"],
       "hall": ["SL_90 : Circulation spaces (entrance hall)", "11-11 17 11 Circulation Spaces - Corridor", "brick:Hallway", "space corridor entrance"],
       "balcony": ["SL_45 : Residential spaces (balcony)", "11-11 11 11 Residential Spaces - Living Room", "brick:Outdoor_Area", "space outdoor balcony"],
       "corridor": ["SL_90 : Circulation spaces (verify code)", "11-11 17 11 Circulation Spaces - Corridor", "brick:Hallway", "space corridor"]}
SYM = {"dEnt": 0, "dInt": 1, "dBath": 2, "win": 3}   # 1010 / 910 / 810 doors, 1810x1210 window


def floor_type(fl):
    if 10 <= fl <= 22: return "T13"
    if fl in (23, 25, 27, 29, 31): return "T11"
    if fl in (24, 26, 28, 30): return "T10"
    return {32: "T9", 33: "T33", 34: "T34"}[fl]


def bays_for(ft):
    b = []
    B = lambda x0, y0, x1, y1, t, back: b.append((x0, y0, x1, y1, t, back))
    S4 = lambda: (B(7000, -PY, P, -CYo, "2BR", "N"), B(0, -PY, 7000, -CYo, "1BR", "N"), B(-7000, -PY, 0, -CYo, "1BR", "N"), B(-P, -PY, -7000, -CYo, "2BR", "N"))
    E3 = lambda: (B(CXo, 3667, P, CY, "1BR", "W"), B(CXo, -3667, P, 3667, "1BR", "W"), B(CXo, -CY, P, -3667, "1BR", "W"))
    if ft == "T13": B(-P, CYo, -9000, PY, "MS", "S"); B(-9000, CYo, -1000, PY, "1BR", "S"); B(-1000, CYo, 7000, PY, "1BR", "S"); B(7000, CYo, P, PY, "2BR", "S"); E3(); S4(); B(-P, -CY, -CXo, 0, "MS", "E"); B(-P, 0, -CXo, CY, "MS", "E")
    if ft == "T11": B(-P, CYo, -1000, PY, "2BR", "S"); B(-1000, CYo, 7000, PY, "1BR", "S"); B(7000, CYo, P, PY, "2BR", "S"); E3(); S4(); B(-P, -CY, -CXo, WB1, "3BR", "E")
    if ft == "T10": B(-P, CYo, -1000, PY, "3BR", "S"); B(-1000, CYo, 7000, PY, "1BR", "S"); B(7000, CYo, P, PY, "2BR", "S"); E3(); B(7000, -PY, P, -CYo, "2BR", "N"); B(-7000, -PY, 7000, -CYo, "1BR", "N"); B(-P, -PY, -7000, -CYo, "2BR", "N"); B(-P, -CY, -CXo, WB1, "3BR", "E")
    if ft == "T9": B(-P, CYo, 7000, PY, "4BR", "S"); B(7000, CYo, P, PY, "2BR", "S"); E3(); B(7000, -PY, P, -CYo, "2BR", "N"); B(-7000, -PY, 7000, -CYo, "1BR", "N"); B(-P, -PY, -7000, -CYo, "2BR", "N"); B(-P, -CY, -CXo, CY, "4BR", "E")
    # T33/T34: unit 3307 = the 4BR duplex on the west wing (both levels) + the NW terrace; the deck skips 07 for the others
    if ft == "T33": B(-2000, CYo, 7000, PY, "1BR", "S"); B(7000, CYo, P, PY, "2BR", "S"); E3(); S4(); B(-P, -CY, -CXo, WB1, "4BR", "E")
    if ft == "T34": B(-2000, CYo, 7000, PY, "1BR", "S"); B(7000, CYo, P, PY, "2BR", "S"); E3(); B(7000, -PY, P, -CYo, "2BR", "N"); B(-P, -CY, -CXo, WB1, "4BR", "E")
    return b


def build(fl):
    ft = floor_type(fl)
    walls, edges, opens, rooms = [], set(), [], []

    def W(x0, y0, x1, y1, h=H):
        key = (round(min(x0, x1)), round(min(y0, y1)), round(max(x0, x1)), round(max(y0, y1)))
        if key in edges or (abs(x0 - x1) < 1 and abs(y0 - y1) < 1):
            return
        edges.add(key)
        walls.append((round(x0), round(y0), round(x1), round(y1), h))

    def R(x, y, name, num, dept, kind, mn=0):
        rooms.append((round(x), round(y), name, num, dept, kind, mn))

    # core + 4 corner stubs (close the dead-end corridor legs); units tile the bands with their own boundary walls -> no collinear overlaps
    W(-CX, -CY, CX, -CY); W(CX, -CY, CX, CY); W(CX, CY, -CX, CY); W(-CX, CY, -CX, -CY)
    W(P, CY, P, CYo); W(P, -CY, P, -CYo); W(-P, CY, -P, CYo); W(-P, -CY, -P, -CYo)
    if ft in ("T10", "T11", "T33", "T34"):
        W(-P, WB1, -P, CY)                      # west perimeter above the shortened west-band unit (pocket = corridor/lift lobby)
    if ft == "T34":
        W(-P, -CYo, 7000, -CYo)                 # south edge of the corridor where the 34th has no south-band units
    units = []
    for u, (x0, y0, x1, y1, t, back) in enumerate(bays_for(ft)):
        idx = u + 1 if ft not in ("T33", "T34") else (7 if t == "4BR" else (u + 1 if u < 6 else u + 2))
        unit = "%04d" % (fl * 100 + idx)
        Wd = (x1 - x0) if back in "SN" else (y1 - y0)
        D = (y1 - y0) if back in "SN" else (x1 - x0)
        Wp = {"S": lambda uu, vv: (x0 + uu, y0 + vv), "N": lambda uu, vv: (x1 - uu, y1 - vv),
              "W": lambda uu, vv: (x0 + vv, y1 - uu), "E": lambda uu, vv: (x1 - vv, y0 + uu)}[back]

        def LW(u0, v0, u1, v1, h=H):
            a = Wp(u0, v0); b = Wp(u1, v1); W(a[0], a[1], b[0], b[1], h)

        LW(0, 0, Wd, 0); LW(Wd, 0, Wd, D); LW(Wd, D, 0, D); LW(0, D, 0, 0)
        hallD, bathW, bathD, CLR = 1200, 2200, 2600, 605   # CLR = half door (455) + 150 mm clear of any wall join (no Revit warning)
        # bath block at the ENTRY end of the hall (wet room against the corridor, G8); hall runs from the bath to the far party wall
        LW(bathW, hallD, Wd, hallD); LW(bathW, 0, bathW, bathD); LW(0, bathD, bathW, bathD)
        fr, nm, pos, mids, spans = FR[t], NM[t], 0, [], []
        for k, f in enumerate(fr):
            w = f * Wd
            if k < len(fr) - 1:
                LW(pos + w, hallD, pos + w, D)
            mids.append(pos + w / 2); spans.append((pos, pos + w)); pos += w
        opens.append((*Wp(bathW + CLR + 100, 0), SYM["dEnt"]))                     # entry from the corridor, clear of the bath block
        for k, m in enumerate(mids):                                              # room door on the hall wall, inside the room's real hall frontage
            lo, hi = max(spans[k][0], bathW) + CLR, spans[k][1] - CLR
            opens.append((*Wp(min(max(m, lo), hi) if lo <= hi else (lo + hi) / 2, hallD), SYM["dInt"]))
        opens.append((*Wp(bathW, 600), SYM["dBath"]))                             # bath door from the hall (600 clear of corridor wall and hall-wall join)
        dept = "Unit %s - %s" % (unit, t)
        for k, m in enumerate(mids):
            wk = fr[k] * Wd; uk0, uk1 = m - wk / 2, m + wk / 2
            if k <= 1 and wk >= 3000:
                LW(uk0 + 300, D, uk0 + 300, D + 1500, 1100); LW(uk0 + 300, D + 1500, uk1 - 300, D + 1500, 1100); LW(uk1 - 300, D + 1500, uk1 - 300, D, 1100)
                # glazed balcony door (910) sits 150 mm clear of the balcony side-wall join; add a window only when both fit (>= 4.0 m room)
                opens.append((*Wp(uk0 + 300 + 250 + 455, D), SYM["dInt"]))
                if wk >= 4000:
                    opens.append((*Wp(uk1 - 300 - 250 - 905, D), SYM["win"]))
                R(*Wp(m, D + 750), "Balcony", unit + "-B%d" % (k + 1), dept, "balcony")
            else:
                opens.append((*Wp(m, D), SYM["win"]))
        R(*Wp((bathW + Wd) / 2, hallD / 2), "Hall", unit + "-H", dept, "hall", 1.0)
        R(*Wp(bathW / 2, bathD / 2), "Bathroom", unit + "-WC", dept, "bath", 3.5)
        for k, m in enumerate(mids):
            mn = (21 if len(fr) >= 4 else 14) if k == 0 else (12 if k == 1 else 7)
            R(*Wp(m, D - 1800), nm[k], unit + "-%d" % (k + 1), dept, "living" if k == 0 else "bedroom", mn)
        units.append({"unit": unit, "type": t, "bay": [x0, y0, x1, y1], "back": back, "width_mm": Wd, "depth_mm": D})
    if ft in ("T33", "T34"):
        # NW terrace of the duplex (pool terrace on 33, planted terrace on 34): close it and the corridor dead-end, door from the corridor leg
        W(-P, CYo, -2000, CYo); W(-P, CYo, -P, PY); W(-P, PY, -2000, PY)
        opens.append((-11000, CYo, SYM["dEnt"]))
        R(-11000, (CYo + PY) // 2, "Pool terrace" if ft == "T33" else "Planted terrace", "%d07-T" % fl, "Unit %d07 - 4BR" % fl, "balcony")
    R(0, CY + 900, "Corridor", "%02d-COR" % fl, "Circulation", "corridor")
    return ft, walls, [(round(x), round(y), s) for x, y, s in opens], rooms, units


def emit(fl):
    F = "F%02d" % fl
    ft, walls, opens, rooms, units = build(fl)
    head = ('var d=document;Func<double,double> ft=m=>UnitUtils.ConvertToInternalUnits(m,UnitTypeId.Millimeters);'
            'var lv=new FilteredElementCollector(d).OfClass(typeof(Level)).Cast<Level>().First(l=>l.Name=="%s");' % F)
    s1 = head + ('var k=new System.Collections.Generic.List<ElementId>();foreach(var b in new[]{BuiltInCategory.OST_Doors,BuiltInCategory.OST_Windows,BuiltInCategory.OST_Rooms,BuiltInCategory.OST_Walls})'
                 'foreach(var e in new FilteredElementCollector(d).OfCategory(b).WhereElementIsNotElementType())if(e.LevelId==lv.Id)k.Add(e.Id);if(k.Count>0)d.Delete(k);'
                 'var wt=new FilteredElementCollector(d).OfClass(typeof(WallType)).Cast<WallType>().First(w=>w.Kind==WallKind.Basic);'
                 'int[] A={%s};int n=0;for(int i=0;i<A.Length;i+=5){Wall.Create(d,Line.CreateBound(new XYZ(ft(A[i]),ft(A[i+1]),0),new XYZ(ft(A[i+2]),ft(A[i+3]),0)),wt.Id,lv.Id,ft(A[i+4]),0,false,false);n++;}'
                 'return "%s: deleted "+k.Count+", walls "+n;' % (",".join(",".join(str(v) for v in w) for w in walls), F))
    s2 = head + ('var sy=new FilteredElementCollector(d).OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>().ToList();'
                 'Func<string,string,FamilySymbol> S=(f,q)=>{var s=sy.First(x=>x.FamilyName==f&&x.Name.StartsWith(q));if(!s.IsActive)s.Activate();return s;};'
                 'var Y=new[]{S("Doors_IntSgl","1010"),S("Doors_IntSgl","910"),S("Doors_IntSgl","810"),S("Windows_Sgl_Plain","1810x1210")};'
                 'var k=new System.Collections.Generic.List<ElementId>();foreach(var b in new[]{BuiltInCategory.OST_Doors,BuiltInCategory.OST_Windows})foreach(var e in new FilteredElementCollector(d).OfCategory(b).WhereElementIsNotElementType())if(e.LevelId==lv.Id)k.Add(e.Id);if(k.Count>0)d.Delete(k);'
                 'var ws=new FilteredElementCollector(d).OfClass(typeof(Wall)).Cast<Wall>().Where(w=>w.LevelId==lv.Id).ToList();'
                 'int[] O={%s};int n=0,miss=0;double tol=ft(60);for(int i=0;i<O.Length;i+=3){var p=new XYZ(ft(O[i]),ft(O[i+1]),0);'
                 'var h=ws.FirstOrDefault(w=>{var c=(w.Location as LocationCurve).Curve;var r=c.Project(new XYZ(p.X,p.Y,c.GetEndPoint(0).Z));return r!=null&&r.Distance<tol;});if(h==null){miss++;continue;}'
                 'var f=d.Create.NewFamilyInstance(new XYZ(p.X,p.Y,lv.Elevation),Y[O[i+2]],h,lv,Autodesk.Revit.DB.Structure.StructuralType.NonStructural);'
                 'if(O[i+2]==3){var sp=f.get_Parameter(BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM);if(sp!=null&&!sp.IsReadOnly)sp.Set(ft(900));}n++;}'
                 'return "%s: openings "+n+", no host "+miss+", cleared "+k.Count;' % (",".join(",".join(str(v) for v in o) for o in opens), F))
    rows = ";".join("%d|%d|%s|%s|%s|%d|%g" % (x, y, nm, num, dept, KINDS.index(kind), mn) for x, y, nm, num, dept, kind, mn in rooms)
    cls = ",".join('new[]{%s}' % ",".join('"%s"' % c for c in CLS[k]) for k in KINDS)
    s3 = head + ('var C=new[]{%s};string[] pn={"DA_UniclassSl","DA_OmniClassT11","DA_BrickClasses","DA_HaystackTags"};'
                 "var rows=\"%s\".Split(';');var chk=new System.Collections.Generic.List<object[]>();int n=0;"
                 "foreach(var r in rows){var t=r.Split('|');var rm=d.Create.NewRoom(lv,new UV(ft(int.Parse(t[0])),ft(int.Parse(t[1]))));rm.Name=t[2];rm.Number=t[3];"
                 'var c=C[int.Parse(t[5])];for(int i=0;i<4;i++){var p=rm.LookupParameter(pn[i]);if(p!=null&&!p.IsReadOnly)p.Set(c[i]);}'
                 'var dp=rm.get_Parameter(BuiltInParameter.ROOM_DEPARTMENT);if(dp!=null)dp.Set(t[4]);'
                 'var cm=rm.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);if(cm!=null)cm.Set("v2 generator (Neufert gate) - typology template scaled from developer floor-plan deck; not surveyed");'
                 'n++;double mn=double.Parse(t[6]);if(mn>0)chk.Add(new object[]{rm,mn,t[3]+" "+t[2]});}'
                 'd.Regenerate();int v=0;var log=new System.Text.StringBuilder();foreach(var q in chk){var rm=(Autodesk.Revit.DB.Architecture.Room)q[0];double a=UnitUtils.ConvertFromInternalUnits(rm.Area,UnitTypeId.SquareMeters);'
                 'if(a<(double)q[1]){v++;log.Append(q[2]+" "+Math.Round(a,1)+"<"+q[1]+"; ");}}'
                 'return "%s: rooms "+n+" | G7 violations "+v+" | "+log.ToString();' % (cls, rows, F))
    out = os.path.join(ROOT, "data", "revit"); os.makedirs(out, exist_ok=True)
    # plain-text twin for the in-Revit loader (revit_v2_apply.cs reads it with File.ReadAllLines): W x0 y0 x1 y1 h / O x y sym / R x|y|name|num|dept|kind|min
    with open(os.path.join(out, "v2_%s.txt" % F), "w", encoding="utf-8") as fh:
        for w in walls: fh.write("W %d %d %d %d %d\n" % w)
        for o in opens: fh.write("O %d %d %d\n" % o)
        for x, y, nm, num, dept, kind, mn in rooms: fh.write("R %d|%d|%s|%s|%s|%d|%g\n" % (x, y, nm, num, dept, KINDS.index(kind), mn))
    json.dump({"floor": F, "ftype": ft, "walls": walls, "openings": opens, "rooms": rooms, "units": units, "kinds": KINDS, "sym": SYM},
              open(os.path.join(out, "v2_%s.json" % F), "w"), indent=0)
    sends = os.path.join(out, "sends"); os.makedirs(sends, exist_ok=True)
    for i, s in enumerate((s1, s2, s3), 1):
        open(os.path.join(sends, "%s_%d.cs" % (F, i)), "w", encoding="utf-8").write(s)
    return F, ft, (s1, s2, s3), (len(walls), len(opens), len(rooms))


def combined(floors):
    """One C# body doing walls -> openings -> rooms for several floors (needs the patched plugin: no 8 KB limit).
    Each phase is wrapped so a failure on one floor is reported, not fatal; returns one line per floor."""
    parts = []
    for fl in floors:
        F, ft, (s1, s2, s3), counts = emit(fl)
        body = []
        for s in (s1, s2, s3):
            core = s[len('var d=document;'):]            # strip the shared prologue
            i = core.rfind('return ')                    # only the final return -> LOG.Append(...); lambdas keep theirs
            core = core[:i] + 'LOG.Append(' + core[i + len('return '):]
            # every snippet ends with 'return "<...>"+...;' -> becomes log.Append("...").Append("; ")
            assert core.rstrip().endswith(';')
            core = core.rstrip()[:-1] + ').Append(" | ");'
            body.append('{' + core + '}')
        parts.append('try{' + ''.join(body) + 'LOG.Append("\\n");}catch(Exception ex){LOG.Append("%s FAIL "+ex.Message+"\\n");}' % F)
    return 'var d=document;var LOG=new System.Text.StringBuilder();' + ''.join(parts) + 'return LOG.ToString();'


if __name__ == "__main__":
    if sys.argv[1] == "--combined":
        floors = [int(x.lstrip("Ff")) for x in sys.argv[2].split(",")]
        code = combined(floors)
        out = os.path.join(ROOT, "data", "revit", "sends", "combined_%s.cs" % "_".join("F%02d" % f for f in floors))
        open(out, "w", encoding="utf-8").write(code)
        print(out, len(code.encode()), "bytes")
        sys.exit()
    fl = int(sys.argv[1].lstrip("Ff"))
    F, ft, snips, counts = emit(fl)
    if "--print" in sys.argv:
        print(snips[int(sys.argv[sys.argv.index("--print") + 1]) - 1])
    else:
        print(F, ft, "walls/openings/rooms", counts, "bytes", [len(s.encode()) for s in snips])
