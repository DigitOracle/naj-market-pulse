// Golden Building card exports v4 (send via revit-mcp send_code_to_revit after revit_v2_apply.cs).
// Reads data/revit/cards_spec.txt (key|unit|floor|x0|y0|x1|y1|highlight numbers, mm) and for each card exports two VECTOR PDFs
// into data/revit/cards/: floor_<key>.pdf (whole plate, this unit filled crimson, everything else grey) and unit_<key>.pdf
// (1:50 crop of the unit: colour fill by room, room tags with area, overall dimension strings). build_unit_cards_v4.py rasterises them.
var d=document;string DIR=@"C:\Dev\naj-market-pulse\data\revit\";string OUT=DIR+"cards";System.IO.Directory.CreateDirectory(OUT);
Func<double,double> ft=m=>UnitUtils.ConvertToInternalUnits(m,UnitTypeId.Millimeters);var LOG=new System.Text.StringBuilder();
var solid=new FilteredElementCollector(d).OfClass(typeof(FillPatternElement)).Cast<FillPatternElement>().First(f=>f.GetFillPattern().IsSolidFill);
Func<Color,OverrideGraphicSettings> fill=c=>{var o=new OverrideGraphicSettings();o.SetSurfaceForegroundPatternId(solid.Id);o.SetSurfaceForegroundPatternColor(c);o.SetSurfaceForegroundPatternVisible(true);return o;};
var HI=fill(new Color(196,30,58));var DIM=fill(new Color(232,232,232));var NONE=new OverrideGraphicSettings();
var tagTypes=new FilteredElementCollector(d).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_RoomTags).Cast<FamilySymbol>().ToList();
var tagT=tagTypes.FirstOrDefault(t=>t.Name.ToLower().Contains("area"))??tagTypes.FirstOrDefault();
var hideCats=new[]{BuiltInCategory.OST_Elev,BuiltInCategory.OST_Sections,BuiltInCategory.OST_Grids,BuiltInCategory.OST_CLines,BuiltInCategory.OST_Cameras,BuiltInCategory.OST_Callouts,BuiltInCategory.OST_Levels};
var po=new PDFExportOptions();po.Combine=true;po.ColorDepth=ColorDepthType.Color;po.ExportQuality=PDFExportQualityType.DPI600;po.HideCropBoundaries=true;po.HideReferencePlane=true;po.HideScopeBoxes=true;po.HideUnreferencedViewTags=true;po.PaperFormat=ExportPaperFormat.ISO_A3;po.ZoomType=ZoomType.FitToPage;po.AlwaysUseRaster=false;
foreach(var ln in System.IO.File.ReadAllLines(DIR+"cards_spec.txt")){if(ln.Trim().Length==0)continue;try{
 var t=ln.Split('|');string key=t[0],unit=t[1],F=t[2];double x0=double.Parse(t[3]),y0=double.Parse(t[4]),x1=double.Parse(t[5]),y1=double.Parse(t[6]);var hl=t[7].Split(',');
 var fp=new FilteredElementCollector(d).OfClass(typeof(ViewPlan)).Cast<ViewPlan>().First(v=>!v.IsTemplate&&v.ViewType==ViewType.FloorPlan&&v.Name.StartsWith("FLOOR "+F));
 var rooms=new FilteredElementCollector(d,fp.Id).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().Cast<Autodesk.Revit.DB.Architecture.Room>().ToList();
 Func<Autodesk.Revit.DB.Architecture.Room,bool> mine=r=>hl.Any(h=>r.Number.StartsWith(h+"-"));
 // 1) floor plate with the unit highlighted
 foreach(var c in hideCats){try{fp.SetCategoryHidden(new ElementId(c),true);}catch{}}
 foreach(var r in rooms)fp.SetElementOverrides(r.Id,mine(r)?HI:DIM);
 po.FileName="floor_"+key;d.Export(OUT,new System.Collections.Generic.List<ElementId>{fp.Id},po);
 foreach(var r in rooms)fp.SetElementOverrides(r.Id,NONE);
 // 2) unit plan 1:50 (reuse the view if it exists)
 string vn="V4 UNIT "+unit+" "+key;var uv=new FilteredElementCollector(d).OfClass(typeof(ViewPlan)).Cast<ViewPlan>().FirstOrDefault(v=>v.Name==vn);
 if(uv==null){uv=(ViewPlan)d.GetElement(fp.Duplicate(ViewDuplicateOption.Duplicate));uv.Name=vn;}
 uv.Scale=50;uv.DetailLevel=ViewDetailLevel.Fine;var bb=uv.CropBox;bb.Min=new XYZ(ft(x0),ft(y0),bb.Min.Z);bb.Max=new XYZ(ft(x1),ft(y1),bb.Max.Z);uv.CropBox=bb;uv.CropBoxActive=true;uv.CropBoxVisible=false;
 foreach(var c in hideCats){try{uv.SetCategoryHidden(new ElementId(c),true);}catch{}}
 foreach(var r in rooms)uv.SetElementOverrides(r.Id,mine(r)?NONE:DIM);
 // room tags (name + area) for the rooms of this unit
 foreach(var old in new FilteredElementCollector(d,uv.Id).OfCategory(BuiltInCategory.OST_RoomTags).ToElementIds().ToList())d.Delete(old);
 int tags=0;foreach(var r in rooms.Where(mine)){var lp=(r.Location as LocationPoint);if(lp==null||r.Area<0.01)continue;var tg=d.Create.NewRoomTag(new LinkElementId(r.Id),new UV(lp.Point.X,lp.Point.Y),uv.Id);if(tagT!=null)tg.ChangeTypeId(tagT.Id);tags++;}
 // overall dimensions: walls crossing the mid-lines of the crop
 foreach(var old in new FilteredElementCollector(d,uv.Id).OfClass(typeof(Dimension)).ToElementIds().ToList())d.Delete(old);
 var lw=new FilteredElementCollector(d).OfClass(typeof(Wall)).Cast<Wall>().Where(w=>w.LevelId==fp.GenLevel.Id).ToList();
 Func<Wall,XYZ> A=w=>(w.Location as LocationCurve).Curve.GetEndPoint(0);Func<Wall,XYZ> Bp=w=>(w.Location as LocationCurve).Curve.GetEndPoint(1);
 double tol=ft(50),X0=ft(x0+700),X1=ft(x1-700),Y0=ft(y0+700),Y1=ft(y1-700),my=(Y0+Y1)/2,mx=(X0+X1)/2;
 var vert=lw.Where(w=>Math.Abs(A(w).X-Bp(w).X)<tol&&A(w).X>X0-tol&&A(w).X<X1+tol&&Math.Min(A(w).Y,Bp(w).Y)<=my&&Math.Max(A(w).Y,Bp(w).Y)>=my).OrderBy(w=>A(w).X).ToList();
 var horiz=lw.Where(w=>Math.Abs(A(w).Y-Bp(w).Y)<tol&&A(w).Y>Y0-tol&&A(w).Y<Y1+tol&&Math.Min(A(w).X,Bp(w).X)<=mx&&Math.Max(A(w).X,Bp(w).X)>=mx).OrderBy(w=>A(w).Y).ToList();
 int dims=0;if(vert.Count>=2){var ra=new ReferenceArray();foreach(var w in vert)ra.Append(new Reference(w));d.Create.NewDimension(uv,Line.CreateBound(new XYZ(X0,Y1+ft(500),0),new XYZ(X1,Y1+ft(500),0)),ra);dims++;}
 if(horiz.Count>=2){var ra=new ReferenceArray();foreach(var w in horiz)ra.Append(new Reference(w));d.Create.NewDimension(uv,Line.CreateBound(new XYZ(X0-ft(500),Y0,0),new XYZ(X0-ft(500),Y1,0)),ra);dims++;}
 d.Regenerate();po.FileName="unit_"+key;d.Export(OUT,new System.Collections.Generic.List<ElementId>{uv.Id},po);
 LOG.Append(key+": rooms "+rooms.Count(mine)+" tags "+tags+" dims "+dims+" | ");
}catch(Exception ex){LOG.Append(ln.Split('|')[0]+" FAIL "+ex.Message+" | ");}}
return LOG.ToString()+" files: "+string.Join(",",System.IO.Directory.GetFiles(OUT).Select(System.IO.Path.GetFileName));
