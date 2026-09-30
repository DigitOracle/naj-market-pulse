"""LAB (register thread, research only): write the production integration as ONE unified diff, never applied.

Reads the current production files (never writes them), applies the edits in memory against exact anchors (each must
occur once, or this stops), and writes data/lab/register/PATCH_register_thread.diff:

  new  scripts/register_thread.py          = data/lab/register/proposed/register_thread.py (smoke-tested on arjan)
  new  scripts/build_register_csv.py       = scripts/lab_register_build_csv.py writing data/ce/<slug>/register.csv
  mod  scripts/pyprt_district.py           prepare(): reg_* attrs; export_glb(): LOD 0 reports pass + node extras
  mod  scripts/ce_batch_v2.py              regTable on all shapes (1 call); extras from the report callback after the merge
  mod  scripts/ce_lod3_datasmith.py        regTable on all shapes (metadata ALL is already set: nothing else)
  mod  najma/scripts/ce_report_v2.py       keep string reports as strings (every one became 0.0)
  (the rule itself: data/lab/register/PATCH_najma_v4_register.diff, from scripts/lab_register_make_rule.py)

  python scripts/lab_register_make_patches.py
"""
import difflib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "lab", "register")
WS = os.path.join(os.path.expanduser("~"), "OneDrive", "Documents", "CityEngine", "Default Workspace", "najma")


def read(p):
    return open(p, "rb").read().decode("utf-8").replace("\r\n", "\n")


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit("anchor for %s found %d times - production file changed, patch not written" % (label, n))
    return src.replace(old, new)


def diff(a_text, b_text, path):
    a = a_text.splitlines(True) if a_text is not None else []
    return "".join(difflib.unified_diff(a, b_text.splitlines(True), "a/" + path if a_text is not None else "/dev/null",
                                        "b/" + path, n=3))


PD_PREPARE_SIG = 'def prepare(slug, lod, name_style="b%d", tall_h=None, tall_lod=3):'
PD_ORIGIN = "    ox, oz = district_origin(feats, tf)\n"
PD_LEVELS = '            a["levels"] = lv\n'
PD_BEFORE_ORIGIN = '    origin = {"slug": slug, "ver": ver, "crs": "EPSG:32640",\n'
PD_BUILT = '"built": time.strftime("%Y-%m-%dT%H:%M:%S"), "builder": "pyprt"}'

CB_LEVELS = '    for lv, lst in by_lv.items(): ce.setAttribute(lst, "levels", lv)\n'
CB_SOURCE = '    for a in ("bHeight", "status", "levels", "fclass", "fvar", "pctComplete"):\n'
CB_SOURCE_BODY = ('        try: ce.setAttributeSource(shapes, "/ce/rule/" + a, "OBJECT")\n'
                  '        except Exception as e: log(f"  attr source {a}: {str(e).splitlines()[0][:80]}")\n')
CB_SIZE = '                size = os.path.getsize(out_glb)\n'

DS_AZ = '    for az, lst in by_az.items(): ce.setAttribute(lst, "streetAz", float(az))\n'
DS_SOURCE_BODY = ('        try: ce.setAttributeSource(sel, "/ce/rule/" + a, "OBJECT")\n'
                  '        except Exception as e: log(f"attr source {a}: {str(e).splitlines()[0][:80]}")\n')
DS_SOURCE = '    for a in ("bHeight", "status", "levels", "fclass", "fvar", "pctComplete", "streetAz"):\n'

RP_NUM = 'def _num(v):\n'
RP_REPORTS = '"reports": {str(k): ([round(_num(x), 3) for x in v] if len(v) <= 8 else {"n": len(v), "sum": round(sum(_num(x) for x in v), 3)}) for k, v in rep.items()},'


def main():
    parts = []

    # ---- new modules
    rt = read(os.path.join(OUT, "proposed", "register_thread.py"))
    parts.append(diff(None, rt, "scripts/register_thread.py"))
    bc = read(os.path.join(HERE, "lab_register_build_csv.py"))
    bc = sub(bc, '"""LAB (register thread, research only): one register row per footprint, keyed by b<i>, for a district.',
             '"""The register thread\'s table: one register row per footprint, keyed by b<i>, for a district.', "csv doc")
    bc = sub(bc, "  python scripts/lab_register_build_csv.py alyufrah1 [alhebiahfifth arjan ...]",
             "  python scripts/build_register_csv.py alyufrah1 [alhebiahfifth arjan ...]", "csv usage")
    bc = sub(bc, "Writes data/lab/register/register_<slug>.csv (UTF-8, RFC 4180 quoting) and register_<slug>.json (coverage).",
             "Writes data/ce/<slug>/register.csv (UTF-8, RFC 4180 quoting) and data/ce/<slug>/register_coverage.json.", "csv writes")
    bc = sub(bc, '        p = os.path.join(OUT, "register_%s.csv" % slug)\n',
             '        p = os.path.join(ROOT, "data", "ce", slug, "register.csv")\n', "csv out")
    bc = sub(bc, '                  open(os.path.join(OUT, "register_%s.json" % slug), "w", encoding="utf-8"), indent=1)',
             '                  open(os.path.join(ROOT, "data", "ce", slug, "register_coverage.json"), "w", encoding="utf-8"), indent=1)', "csv json")
    parts.append(diff(None, bc, "scripts/build_register_csv.py"))

    # ---- pyprt_district.py
    p = os.path.join(HERE, "pyprt_district.py"); a = read(p); b = a
    b = sub(b, PD_PREPARE_SIG, PD_PREPARE_SIG.replace("tall_lod=3):", "tall_lod=3, register=True):"), "prepare sig")
    b = sub(b, PD_ORIGIN, PD_ORIGIN +
            "    # The register thread (lab 30 Sep, data/lab/register): name / developer / project / floors / units / status ride ON\n"
            "    # the model as reg_* attrs; the rule reports them back as reg.* -> Datasmith <MetaData>, glTF node extras.\n"
            "    # A rule without the register block ignores reg_* (measured on najma_v4.rpk), so this is safe before the rule ships.\n"
            "    reg = {}\n"
            "    if register:\n"
            "        from register_thread import rows as reg_rows\n"
            "        try:\n"
            "            reg = reg_rows(slug)\n"
            "        except FileNotFoundError:\n"
            "            reg = {}                   # no data/ce/<slug>/register.csv yet: the model carries ids only\n", "prepare reg load")
    b = sub(b, PD_LEVELS, PD_LEVELS +
            "        if fi in reg:\n"
            "            from register_thread import reg_attrs\n"
            "            a.update(reg_attrs(reg[fi]))\n", "prepare reg attrs")
    b = sub(b, PD_BEFORE_ORIGIN,
            "    # Register thread: the glTF encoder has no metadata option (data/lab/register/encoder_options), so the rule's own\n"
            "    # reg.* reports - a LOD 0 pass, 2.1 s against 249.5 s of geometry on arjan - go into each b<i> node as\n"
            "    # extras.najma_register, which three.js hands to Object3D.userData and glb_pack_v3.mjs keeps.\n"
            "    from register_thread import reports_pass, inject\n"
            "    per = reports_pass(shapes, attrs, idx, rpk)\n"
            "    reg_inj = inject(out, per, {\"slug\": slug, \"ver\": ver, \"rule\": os.path.basename(rpk),\n"
            "                                \"origin_ce_xyz\": [oe, 0.0, -on]}) if per else None\n" + PD_BEFORE_ORIGIN, "export_glb inject")
    b = sub(b, PD_BUILT, PD_BUILT[:-1] + ",\n              \"register_nodes\": reg_inj[\"tagged\"] if reg_inj else 0}", "origin register_nodes")
    parts.append(diff(a, b, "scripts/pyprt_district.py"))

    # ---- ce_batch_v2.py: table mode (ONE bridge call); the rule finds its row by the b<i> shape name
    p = os.path.join(HERE, "ce_batch_v2.py"); a = read(p); b = a
    b = sub(b, CB_SOURCE + CB_SOURCE_BODY, CB_SOURCE + CB_SOURCE_BODY +
            "    # register thread (lab 30 Sep): the rule reads its own row of data/ce/<slug>/register.csv - one bridge call, where\n"
            "    # pushing reg_* per building would cost ~2-3 calls a building (reg_id / duid / name are unique)\n"
            "    if VER == \"v4\":\n"
            "        try:\n"
            "            from register_thread import table_ce\n"
            "            log(f\"  register table {table_ce(ce, shapes, slug)}\")\n"
            "        except FileNotFoundError:\n"
            "            log(\"  no register.csv for this district - the model carries ids only\")\n"
            "        except Exception as e:\n"
            "            log(\"  register table not set:\", str(e)[:120])\n", "ce_batch table")
    b = sub(b, CB_SIZE, CB_SIZE +
            "                # register thread: this export's report callback (patched ce_report_v2 keeps strings) -> node extras\n"
            "                try:\n"
            "                    from register_thread import from_ce_report, inject\n"
            "                    per = from_ce_report(json_p) if os.path.exists(json_p) else {}\n"
            "                    if per:\n"
            "                        ri = inject(out_glb, per, {\"slug\": slug, \"ver\": VER, \"rule\": RULE_WS, \"lod\": lod})\n"
            "                        log(f\"  register extras on {ri['tagged']} of {ri['nodes']} nodes (+{ri['json_bytes_added']} B JSON)\")\n"
            "                        size = os.path.getsize(out_glb)\n"
            "                except Exception as e:\n"
            "                    log(\"  register extras skipped:\", str(e)[:120])\n", "ce_batch inject")
    parts.append(diff(a, b, "scripts/ce_batch_v2.py"))

    # ---- ce_lod3_datasmith.py: table mode; the Datasmith settings already export metadata ALL per initial shape
    p = os.path.join(HERE, "ce_lod3_datasmith.py"); a = read(p); b = a
    b = sub(b, DS_SOURCE + DS_SOURCE_BODY, DS_SOURCE + DS_SOURCE_BODY +
            "    # register thread (lab 30 Sep): one bridge call; setMetadata(ALL) below then carries reg.* onto every actor\n"
            "    try:\n"
            "        from register_thread import table_ce\n"
            "        log(f\"register table {table_ce(ce, sel, SLUG)}\")\n"
            "    except FileNotFoundError:\n"
            "        log(\"no register.csv for this district - actors carry ids only\")\n"
            "    except Exception as e:\n"
            "        log(\"register table not set:\", str(e)[:120])\n", "datasmith table")
    parts.append(diff(a, b, "scripts/ce_lod3_datasmith.py"))

    # ---- ce_report_v2.py (CityEngine-side callback; Jython or CPython, so no py3-only syntax)
    p = os.path.join(WS, "scripts", "ce_report_v2.py"); a = read(p); b = a
    b = sub(b, RP_NUM,
            "def _keep(v):\n"
            "    \"\"\"A string report (reg.name, reg.project ...) stays a string; _num() turned every one of them into 0.0.\"\"\"\n"
            "    if hasattr(v, \"encode\"):\n"
            "        return v\n"
            "    return round(_num(v), 3)\n\n\n" + RP_NUM, "report keep")
    b = sub(b, RP_REPORTS,
            '"reports": {str(k): ([_keep(x) for x in v] if len(v) <= 8 or hasattr(v[0], "encode") else {"n": len(v), "sum": round(sum(_num(x) for x in v), 3)}) for k, v in rep.items()},',
            "report dict")
    parts.append(diff(a, b, "najma/scripts/ce_report_v2.py"))

    head = ("# Register thread - production integration. NOT APPLIED. Research use only.\n"
            "# Rule change: data/lab/register/PATCH_najma_v4_register.diff (najma_v4.cga, +78 lines; tested as\n"
            "#   najma/rules/lab/register/najma_v4_register.cga -> data/lab/register/najma_v4_register.rpk).\n"
            "# Generated by scripts/lab_register_make_patches.py against the files as they were on %s.\n"
            "# Order to apply: rule diff -> export_najma_rpk.py -> this diff -> build_register_csv.py <slug> -> builds.\n\n"
            % __import__("time").strftime("%Y-%m-%d %H:%M"))
    outp = os.path.join(OUT, "PATCH_register_thread.diff")
    open(outp, "w", encoding="utf-8", newline="\n").write(head + "\n".join(parts))
    print("  wrote %s  (%d files, %d lines)" % (os.path.relpath(outp, ROOT), len(parts), (head + "\n".join(parts)).count("\n")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
