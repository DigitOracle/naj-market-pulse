// Golden Building — card-grade unit exports (send via revit-mcp send_code_to_revit, two passes).
// PASS 1 (styling + dimensions): for every "UT-*" plan view — drop the colour fill, hide elevation/section
// markers, grids, ref planes, cameras; scale 1:50; add three dimension strings from wall centrelines
// (top: vertical walls crossing mid-height; left: horizontal walls; bottom: room splits at 1/4 height);
// widen the crop so the strings sit inside the export.
// PASS 2 (export): every "UT-*" plan + 3D view → PNG 2400 px @ 300 dpi into
//   Client_Engagements\Imtiaz\02_Execution\04_Golden_Building_Symphony\02_Revit\unit_cards\
// then rename to card_<Type>_plan.png / card_<Type>_3d.png (PowerShell map in the session log).
// Views themselves are created by revit_unit_map.cs' companion view block (UT-… PLAN/3D, FLOOR …, TOWER …).
// ---------------------------------------------------------------- PASS 1
var doc = document;
Func<double, double> ft = mm => UnitUtils.ConvertToInternalUnits(mm, UnitTypeId.Millimeters);
var uts = new FilteredElementCollector(doc).OfClass(typeof(ViewPlan)).Cast<ViewPlan>().Where(v => !v.IsTemplate && v.Name.StartsWith("UT-")).ToList();
var hideCats = new[] { BuiltInCategory.OST_Elev, BuiltInCategory.OST_Sections, BuiltInCategory.OST_Grids, BuiltInCategory.OST_CLines, BuiltInCategory.OST_Cameras, BuiltInCategory.OST_Callouts };
var walls = new FilteredElementCollector(doc).OfClass(typeof(Wall)).Cast<Wall>().ToList();
int dims = 0;
foreach (var v in uts)
{
    try { v.SetColorFillSchemeId(new ElementId(BuiltInCategory.OST_Rooms), ElementId.InvalidElementId); } catch {}
    foreach (var c in hideCats) { try { v.SetCategoryHidden(new ElementId(c), true); } catch {} }
    v.Scale = 50; v.DetailLevel = ViewDetailLevel.Fine; v.CropBoxVisible = false;
    var bb = v.CropBox; var lvId = v.GenLevel.Id;
    var lw = walls.Where(w => w.LevelId == lvId).ToList();
    Func<Wall, XYZ> A = w => (w.Location as LocationCurve).Curve.GetEndPoint(0);
    Func<Wall, XYZ> Bp = w => (w.Location as LocationCurve).Curve.GetEndPoint(1);
    double tol = ft(50);
    double x0 = bb.Min.X + ft(1500), x1 = bb.Max.X - ft(1500), y0 = bb.Min.Y + ft(1500), y1 = bb.Max.Y - ft(1500);
    var vert = lw.Where(w => Math.Abs(A(w).X - Bp(w).X) < tol && A(w).X > x0 - tol && A(w).X < x1 + tol && Math.Min(A(w).Y, Bp(w).Y) <= (y0 + y1) / 2 && Math.Max(A(w).Y, Bp(w).Y) >= (y0 + y1) / 2).OrderBy(w => A(w).X).ToList();
    var horiz = lw.Where(w => Math.Abs(A(w).Y - Bp(w).Y) < tol && A(w).Y > y0 - tol && A(w).Y < y1 + tol && Math.Min(A(w).X, Bp(w).X) <= (x0 + x1) / 2 && Math.Max(A(w).X, Bp(w).X) >= (x0 + x1) / 2).OrderBy(w => A(w).Y).ToList();
    if (vert.Count >= 2) { var ra = new ReferenceArray(); foreach (var w in vert) ra.Append(new Reference(w)); doc.Create.NewDimension(v, Line.CreateBound(new XYZ(x0, y1 + ft(900), 0), new XYZ(x1, y1 + ft(900), 0)), ra); dims++; }
    if (horiz.Count >= 2) { var ra = new ReferenceArray(); foreach (var w in horiz) ra.Append(new Reference(w)); doc.Create.NewDimension(v, Line.CreateBound(new XYZ(x0 - ft(900), y0, 0), new XYZ(x0 - ft(900), y1, 0)), ra); dims++; }
    var vert2 = lw.Where(w => Math.Abs(A(w).X - Bp(w).X) < tol && A(w).X > x0 - tol && A(w).X < x1 + tol && Math.Min(A(w).Y, Bp(w).Y) <= y0 + (y1 - y0) * 0.25 && Math.Max(A(w).Y, Bp(w).Y) >= y0 + (y1 - y0) * 0.25).OrderBy(w => A(w).X).ToList();
    if (vert2.Count >= 2 && vert2.Count != vert.Count) { var ra = new ReferenceArray(); foreach (var w in vert2) ra.Append(new Reference(w)); doc.Create.NewDimension(v, Line.CreateBound(new XYZ(x0, y0 - ft(900), 0), new XYZ(x1, y0 - ft(900), 0)), ra); dims++; }
    var nb = v.CropBox; nb.Min = new XYZ(bb.Min.X - ft(800), bb.Min.Y - ft(800), nb.Min.Z); nb.Max = new XYZ(bb.Max.X + ft(300), bb.Max.Y + ft(800), nb.Max.Z); v.CropBox = nb;
}
doc.Regenerate();
// ---------------------------------------------------------------- PASS 2 (separate send — keeps each command light)
string dir = @"C:\Users\kwils\OneDrive\Desktop\DigitAlchemy_31MAY2026\Client_Engagements\Imtiaz\02_Execution\04_Golden_Building_Symphony\02_Revit\unit_cards";
System.IO.Directory.CreateDirectory(dir);
var views = new FilteredElementCollector(doc).OfClass(typeof(View)).Cast<View>().Where(v => !v.IsTemplate && v.Name.StartsWith("UT-") && (v.ViewType == ViewType.FloorPlan || v.ViewType == ViewType.ThreeD)).ToList();
foreach (var v in views)
{
    var o = new ImageExportOptions(); o.ExportRange = ExportRange.SetOfViews; o.SetViewsAndSheets(new System.Collections.Generic.List<ElementId> { v.Id });
    o.FilePath = System.IO.Path.Combine(dir, v.Name.Replace("—", "-")); o.HLRandWFViewsFileType = ImageFileType.PNG; o.ShadowViewsFileType = ImageFileType.PNG;
    o.ImageResolution = ImageResolution.DPI_300; o.ZoomType = ZoomFitType.FitToPage; o.PixelSize = 2400; o.FitDirection = FitDirectionType.Horizontal;
    doc.ExportImage(o);
}
return "dimension strings " + dims + ", exported " + views.Count;
