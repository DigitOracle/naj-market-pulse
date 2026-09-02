// Golden Building — whole-tower unit + room map generator (send via revit-mcp send_code_to_revit).
// Source: developer floor-plan deck (data/brochure/floorplan_pages, labels in floorplan_labels.json).
// Plate 40x40 m, core 14x22 m centred, corridor ring to ±8.8/±12.8 m. Units are bays around the
// ring; numbering runs clockwise from the NW corner as the deck numbers them (01..NN).
// Dimensions are SCALED FROM THE RASTER PLATES, not surveyed — every room says so in Comments.
// Set FLOORS and FTYPE at the top, run once per floor group:
//   T13: F10-F22 (13 units)  T11: F23,F25,F27,F29,F31 (11)  T10: F24,F26,F28,F30 (10, 3BR)
//   T9 : F32 (9, 4BR)        T33: F33 others (duplex modelled separately)  T34: F34 others
var doc = document;
var FLOORS = new[] { "F10","F11","F12","F13","F14","F15","F16","F17","F18","F19","F20","F21","F22" };
var FTYPE = "T13";
Func<double, double> ft = mm => UnitUtils.ConvertToInternalUnits(mm, UnitTypeId.Millimeters);
var levels = new System.Collections.Generic.Dictionary<string, Level>();
foreach (Level lv in new FilteredElementCollector(doc).OfClass(typeof(Level))) levels[lv.Name] = lv;
var wt = new FilteredElementCollector(doc).OfClass(typeof(WallType)).Cast<WallType>().First(w => w.Kind == WallKind.Basic);
// bay rectangles: x0,y0,x1,y1 (mm) and unit type
double P = 20000, CX = 8800, CY = 12800;
var rects = new System.Collections.Generic.List<double[]>(); var types = new System.Collections.Generic.List<string>();
Action<double,double,double,double,string> B = (x0,y0,x1,y1,t) => { rects.Add(new[]{x0,y0,x1,y1}); types.Add(t); };
// clockwise from NW: north band L->R, east band top->bottom, south band R->L, west band bottom->top
if (FTYPE == "T13") { B(-P,CY,-9000,P,"MS"); B(-9000,CY,-1000,P,"1BR"); B(-1000,CY,7000,P,"1BR"); B(7000,CY,P,P,"2BR");
  B(CX,4266,P,CY,"1BR"); B(CX,-4266,P,4266,"1BR"); B(CX,-CY,P,-4266,"1BR");
  B(7000,-P,P,-CY,"2BR"); B(0,-P,7000,-CY,"1BR"); B(-7000,-P,0,-CY,"1BR"); B(-P,-P,-7000,-CY,"2BR");
  B(-P,-CY,-CX,0,"MS"); B(-P,0,-CX,CY,"MS"); }
if (FTYPE == "T11") { B(-P,CY,-1000,P,"2BR"); B(-1000,CY,7000,P,"1BR"); B(7000,CY,P,P,"2BR");
  B(CX,4266,P,CY,"1BR"); B(CX,-4266,P,4266,"1BR"); B(CX,-CY,P,-4266,"1BR");
  B(7000,-P,P,-CY,"2BR"); B(0,-P,7000,-CY,"1BR"); B(-7000,-P,0,-CY,"1BR"); B(-P,-P,-7000,-CY,"2BR");
  B(-P,-CY,-CX,CY,"3BR"); }
if (FTYPE == "T10") { B(-P,CY,-1000,P,"3BR"); B(-1000,CY,7000,P,"1BR"); B(7000,CY,P,P,"2BR");
  B(CX,4266,P,CY,"1BR"); B(CX,-4266,P,4266,"1BR"); B(CX,-CY,P,-4266,"1BR");
  B(7000,-P,P,-CY,"2BR"); B(-7000,-P,7000,-CY,"1BR"); B(-P,-P,-7000,-CY,"2BR");
  B(-P,-CY,-CX,CY,"3BR"); }
if (FTYPE == "T9")  { B(-P,CY,7000,P,"4BR"); B(7000,CY,P,P,"2BR");
  B(CX,4266,P,CY,"1BR"); B(CX,-4266,P,4266,"1BR"); B(CX,-CY,P,-4266,"1BR");
  B(7000,-P,P,-CY,"2BR"); B(0,-P,7000,-CY,"1BR"); B(-7000,-P,0,-CY,"1BR"); B(-P,-P,-7000,-CY,"2BR");
  B(-P,-CY,-CX,CY,"4BR"); }
if (FTYPE == "T33") { B(-2000,CY,7000,P,"1BR"); B(7000,CY,P,P,"2BR");
  B(CX,4266,P,CY,"1BR"); B(CX,-4266,P,4266,"1BR"); B(CX,-CY,P,-4266,"1BR");
  B(7000,-P,P,-CY,"2BR"); B(-7000,-P,7000,-CY,"2BR"); B(-P,-P,-7000,-CY,"2BR"); }
if (FTYPE == "T34") { B(-2000,CY,7000,P,"1BR"); B(7000,CY,P,P,"2BR");
  B(CX,4266,P,CY,"1BR"); B(CX,-4266,P,4266,"1BR"); B(CX,-CY,P,-4266,"1BR"); }
// room templates: fractions along the unit's long axis
var TPL = new System.Collections.Generic.Dictionary<string, string[]> {
  {"1BR", new[]{"Living/Kitchen:0.50","Bedroom:0.35","Bathroom:0.15"}},
  {"MS",  new[]{"Living/Kitchen:0.45","Master Bedroom:0.35","Bath & Dressing:0.20"}},
  {"2BR", new[]{"Living/Kitchen:0.40","Master Bedroom:0.25","Bedroom 2:0.20","Bathroom:0.15"}},
  {"3BR", new[]{"Living/Kitchen:0.34","Master Bedroom:0.20","Bedroom 2:0.16","Bedroom 3:0.16","Bathrooms:0.14"}},
  {"4BR", new[]{"Living/Kitchen:0.30","Master Bedroom:0.18","Bedroom 2:0.14","Bedroom 3:0.14","Bedroom 4:0.12","Bathrooms:0.12"}} };
var CLS = new System.Collections.Generic.Dictionary<string, string[]> {  // name-key -> SL, OmniT11, Brick/REC, Haystack
  {"living", new[]{"SL_45_10_45 : Kitchen-dining-living rooms","11-11 11 11 Residential Spaces - Living Room","brick:Living_Room","space room residential"}},
  {"bedroom", new[]{"SL_45_10_09 : Bedrooms","11-11 11 14 Residential Spaces - Bedroom","brick:Bedroom","space room residential sleep"}},
  {"bath", new[]{"SL_45_10 : Living spaces (bathroom)","11-11 11 31 Residential Spaces - Bathroom","rec:Bathroom","space room toilet"}},
  {"corridor", new[]{"SL_90 : Circulation spaces (verify code)","11-11 17 11 Circulation Spaces - Corridor","brick:Hallway","space corridor"}} };
int walls = 0, rooms = 0;
foreach (var fname in FLOORS)
{
    if (!levels.ContainsKey(fname)) continue;
    var lv = levels[fname]; int fl = int.Parse(fname.Substring(1));
    var edges = new System.Collections.Generic.HashSet<string>();
    Action<double,double,double,double> W = (x0,y0,x1,y1) => {
        var key = string.Join(",", new[]{Math.Min(x0,x1),Math.Min(y0,y1),Math.Max(x0,x1),Math.Max(y0,y1)}.Select(v=>Math.Round(v)));
        if (!edges.Add(key)) return;
        Wall.Create(doc, Line.CreateBound(new XYZ(ft(x0),ft(y0),0), new XYZ(ft(x1),ft(y1),0)), wt.Id, lv.Id, ft(3500), 0, false, false); walls++; };
    Action<double[]> Rect = r => { W(r[0],r[1],r[2],r[1]); W(r[2],r[1],r[2],r[3]); W(r[2],r[3],r[0],r[3]); W(r[0],r[3],r[0],r[1]); };
    Rect(new[]{-P,-P,P,P}); Rect(new[]{-7000.0,-11000,7000,11000});
    Action<double,double,string,string,string,string> R = (x,y,name,num,dept,cmt) => {
        var rm = doc.Create.NewRoom(lv, new UV(ft(x), ft(y))); rm.Name = name; rm.Number = num;
        var n = name.ToLower(); var k = n.Contains("bath") ? "bath" : (n.Contains("bed") ? "bedroom" : (n.Contains("corridor") ? "corridor" : "living"));
        var c = CLS[k]; string[] pn = {"DA_UniclassSl","DA_OmniClassT11","DA_BrickClasses","DA_HaystackTags"};
        for (int i = 0; i < 4; i++) { var p = rm.LookupParameter(pn[i]); if (p != null && !p.IsReadOnly) p.Set(c[i]); }
        var d = rm.get_Parameter(BuiltInParameter.ROOM_DEPARTMENT); if (d != null) d.Set(dept);
        var cm = rm.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (cm != null) cm.Set(cmt);
        rooms++; };
    for (int u = 0; u < rects.Count; u++)
    {
        var r = rects[u]; var t = types[u]; Rect(r);
        string unit = (fl * 100 + (u + 1)).ToString("0000");
        bool horiz = (r[2]-r[0]) >= (r[3]-r[1]); double L = horiz ? r[2]-r[0] : r[3]-r[1]; double pos = 0;
        var tpl = TPL[t];
        for (int k = 0; k < tpl.Length; k++)
        {
            var parts = tpl[k].Split(':'); double f = double.Parse(parts[1]); double a = pos, b = (k == tpl.Length-1) ? L : pos + f*L;
            double[] rr = horiz ? new[]{r[0]+a, r[1], r[0]+b, r[3]} : new[]{r[0], r[1]+a, r[2], r[1]+b};
            if (k < tpl.Length-1) { if (horiz) W(rr[2],rr[1],rr[2],rr[3]); else W(rr[0],rr[3],rr[2],rr[3]); }
            R((rr[0]+rr[2])/2, (rr[1]+rr[3])/2, parts[0], unit + "-" + (k+1), "Unit " + unit + " · " + t,
              "Unit " + unit + " (" + t + ") — typology template scaled from developer floor-plan deck; not surveyed");
            pos = b;
        }
    }
    R(-7900, 0, "Corridor", fl.ToString("00") + "-COR", "Circulation", "Corridor ring around core — scaled from deck");
}
doc.Regenerate();
return FTYPE + " on " + FLOORS.Length + " floors: walls " + walls + ", rooms " + rooms;
