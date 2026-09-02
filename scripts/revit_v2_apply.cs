// Golden Building v2 loader: rebuilds FLOORS from data/revit/v2_<F>.txt (written by revit_v2_emit.py) - walls, openings, rooms,
// classification and the Neufert G7 area check - in one send. ~4 KB, so it needs no large payload; 2-3 floors per send stay inside
// the 2-minute client window. Send via revit-mcp send_code_to_revit; edit FLOORS only.
var d=document;var FLOORS=new[]{"F12","F13"};string DIR=@"C:\Dev\naj-market-pulse\data\revit\";
var LOG=new System.Text.StringBuilder();Func<double,double> ft=m=>UnitUtils.ConvertToInternalUnits(m,UnitTypeId.Millimeters);
var levels=new FilteredElementCollector(d).OfClass(typeof(Level)).Cast<Level>().ToDictionary(l=>l.Name,l=>l);
var wt=new FilteredElementCollector(d).OfClass(typeof(WallType)).Cast<WallType>().First(w=>w.Kind==WallKind.Basic);
var sy=new FilteredElementCollector(d).OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>().ToList();
Func<string,string,FamilySymbol> S=(f,q)=>{var s=sy.First(x=>x.FamilyName==f&&x.Name.StartsWith(q));if(!s.IsActive)s.Activate();return s;};
var Y=new[]{S("Doors_IntSgl","1010"),S("Doors_IntSgl","910"),S("Doors_IntSgl","810"),S("Windows_Sgl_Plain","1810x1210")};
var C=new[]{new[]{"SL_45_10_45 : Kitchen-dining-living rooms","11-11 11 11 Residential Spaces - Living Room","brick:Living_Room","space room residential"},new[]{"SL_45_10_09 : Bedrooms","11-11 11 14 Residential Spaces - Bedroom","brick:Bedroom","space room residential sleep"},new[]{"SL_45_10 : Living spaces (bathroom)","11-11 11 31 Residential Spaces - Bathroom","rec:Bathroom","space room toilet"},new[]{"SL_90 : Circulation spaces (entrance hall)","11-11 17 11 Circulation Spaces - Corridor","brick:Hallway","space corridor entrance"},new[]{"SL_45 : Residential spaces (balcony)","11-11 11 11 Residential Spaces - Living Room","brick:Outdoor_Area","space outdoor balcony"},new[]{"SL_90 : Circulation spaces (verify code)","11-11 17 11 Circulation Spaces - Corridor","brick:Hallway","space corridor"}};
string[] pn={"DA_UniclassSl","DA_OmniClassT11","DA_BrickClasses","DA_HaystackTags"};
foreach(var F in FLOORS){try{
 var lv=levels[F];var lines=System.IO.File.ReadAllLines(DIR+"v2_"+F+".txt");
 var kill=new System.Collections.Generic.List<ElementId>();
 foreach(var b in new[]{BuiltInCategory.OST_Doors,BuiltInCategory.OST_Windows,BuiltInCategory.OST_Rooms,BuiltInCategory.OST_Walls})foreach(var e in new FilteredElementCollector(d).OfCategory(b).WhereElementIsNotElementType())if(e.LevelId==lv.Id)kill.Add(e.Id);
 if(kill.Count>0)d.Delete(kill);
 var ws=new System.Collections.Generic.List<Wall>();int nw=0,no=0,miss=0,nr=0,viol=0;var chk=new System.Collections.Generic.List<object[]>();var vlog=new System.Text.StringBuilder();
 foreach(var ln in lines){if(!ln.StartsWith("W "))continue;var a=ln.Substring(2).Split(' ').Select(double.Parse).ToArray();
  ws.Add(Wall.Create(d,Line.CreateBound(new XYZ(ft(a[0]),ft(a[1]),0),new XYZ(ft(a[2]),ft(a[3]),0)),wt.Id,lv.Id,ft(a[4]),0,false,false));nw++;}
 double tol=ft(60);
 foreach(var ln in lines){if(!ln.StartsWith("O "))continue;var a=ln.Substring(2).Split(' ').Select(int.Parse).ToArray();var p=new XYZ(ft(a[0]),ft(a[1]),0);
  var h=ws.FirstOrDefault(w=>{var c=(w.Location as LocationCurve).Curve;var r=c.Project(new XYZ(p.X,p.Y,c.GetEndPoint(0).Z));return r!=null&&r.Distance<tol;});if(h==null){miss++;continue;}
  var fi=d.Create.NewFamilyInstance(new XYZ(p.X,p.Y,lv.Elevation),Y[a[2]],h,lv,Autodesk.Revit.DB.Structure.StructuralType.NonStructural);
  if(a[2]==3){var sp=fi.get_Parameter(BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM);if(sp!=null&&!sp.IsReadOnly)sp.Set(ft(900));}no++;}
 foreach(var ln in lines){if(!ln.StartsWith("R "))continue;var t=ln.Substring(2).Split('|');
  var rm=d.Create.NewRoom(lv,new UV(ft(int.Parse(t[0])),ft(int.Parse(t[1]))));rm.Name=t[2];rm.Number=t[3];var c=C[int.Parse(t[5])];
  for(int i=0;i<4;i++){var p=rm.LookupParameter(pn[i]);if(p!=null&&!p.IsReadOnly)p.Set(c[i]);}
  var dp=rm.get_Parameter(BuiltInParameter.ROOM_DEPARTMENT);if(dp!=null)dp.Set(t[4]);
  var cm=rm.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);if(cm!=null)cm.Set("v2 generator (Neufert gate) - typology template scaled from developer floor-plan deck; not surveyed");
  nr++;double mn=double.Parse(t[6]);if(mn>0)chk.Add(new object[]{rm,mn,t[3]+" "+t[2]});}
 d.Regenerate();
 foreach(var q in chk){var rm=(Autodesk.Revit.DB.Architecture.Room)q[0];double ar=UnitUtils.ConvertFromInternalUnits(rm.Area,UnitTypeId.SquareMeters);if(ar<(double)q[1]){viol++;vlog.Append(q[2]+" "+Math.Round(ar,1)+"<"+q[1]+"; ");}}
 LOG.Append(F+": cleared "+kill.Count+", walls "+nw+", openings "+no+" (no host "+miss+"), rooms "+nr+", G7 violations "+viol+" "+vlog+"\n");
}catch(Exception ex){LOG.Append(F+" FAIL "+ex.Message+"\n");}}
return LOG.ToString();
