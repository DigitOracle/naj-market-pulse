"""build_ev_rpk.py -- compile EVCharger.cga into a PRT-loadable rule package, headlessly.

CityEngine's GUI is not needed for any of this. Three steps, all scriptable:

  1. COMPILE   CityEngine ships an Eclipse headless application, com.esri.cgac.application, which is
               the CGA compiler. It runs with no window and no licence prompt:
                 CityEngine.exe -application com.esri.cgac.application -nosplash -consoleLog \\
                   -prj <projectDir> -out <outDir|out.rpk> <cgaFiles...>
  2. STAGE     Lay the output out the way PRT expects (see below).
  3. PACK      7-Zip, with archive parameters PRT's bundled reader accepts (see below).

THREE THINGS THAT EACH LOOK LIKE A DIFFERENT BUG:

  * `-prj` must point at a MINIMAL project directory -- one holding just rules/<file>.cga. Pointed at
    the repo root, cgac tried to pack every Datasmith mesh and geodatabase under data/ into the rule
    package and ran for minutes. The compiler also walks UP from the .cga looking for a folder named
    `rules`, and throws a bare NullPointerException in findRulesFolder if it reaches the drive root
    without finding one -- so the .cga must sit inside rules/.

  * cgac's own -out <file>.rpk is NOT loadable by PRT. Its resolve map names only the .cga, which it
    does not even pack, and it puts the .cgb under rules/. A PRT-ready package keeps the source under
    rules/, the BYTECODE under bin/, and lists the .cgb in the resolve map. So we compile to a
    DIRECTORY, take the loose .cgb, and build the package ourselves.

  * PRT's bundled 7z reader predates modern 7-Zip defaults. An archive written with LZMA2, or solid,
    is rejected with "error while reading 7zip archive: unsupported file feature" -- which reads like
    a corrupt file rather than a format mismatch. A known-good Esri .rpk reports `Method = LZMA:22`
    and `Solid = -`, so we pass -m0=lzma -md=4m -ms=off. py7zr cannot write an accepted archive at
    any setting; 7-Zip can. PRT also refuses an unpacked directory and a loose .cgb.

Verified 17 Sep 2026: the package loads, PRT reports the rule's three attributes, and
ev_cityengine.py --rpk generates all 351 stations.

    python scripts/build_ev_rpk.py                 # compile + pack + verify
    python scripts/build_ev_rpk.py --keep-work      # leave the staging dir for inspection
"""
import argparse, os, shutil, subprocess, sys, tempfile

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE_DIR = os.path.join(ROOT, "data", "ev", "cityengine")
CGA = os.path.join(ROOT, "rules", "EVCharger.cga")          # house convention: .cga lives in rules/
RPK = os.path.join(CE_DIR, "EVCharger.rpk")
NAME = "EVCharger"

CITYENGINE = os.environ.get("CITYENGINE_EXE", r"C:\Program Files\ArcGIS\CityEngine2025.1\CityEngine.exe")
SEVENZIP = os.environ.get("SEVENZIP_EXE", r"C:\Program Files\7-Zip\7z.exe")

RESOLVEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<resolvemap>
  <entry key="/{name}/rules/{name}.cga" value="rules/{name}.cga" />
  <entry key="rules/{name}.cga" value="rules/{name}.cga" />
  <entry key="bin/{name}.cgb" value="bin/{name}.cgb" />
</resolvemap>
"""


def need(path, what):
    if not os.path.exists(path):
        sys.exit(f"{what} not found: {path}\n"
                 f"Set its path with the {'CITYENGINE_EXE' if 'CityEngine' in what else 'SEVENZIP_EXE'} "
                 f"environment variable.")


def compile_cga(work):
    """cgac -> a loose .cgb. Compiles in a minimal project so nothing else is swept in."""
    prj = os.path.join(work, "prj")
    os.makedirs(os.path.join(prj, "rules"))
    shutil.copy2(CGA, os.path.join(prj, "rules", NAME + ".cga"))
    outdir = os.path.join(work, "cgb")
    os.makedirs(outdir)
    cmd = [CITYENGINE, "-application", "com.esri.cgac.application", "-nosplash", "-consoleLog",
           "-prj", prj, "-out", outdir, os.path.join(prj, "rules", NAME + ".cga")]
    print("compiling  :", os.path.relpath(CGA, ROOT))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    body = (r.stdout or "") + (r.stderr or "")
    # cgac exits 0 even when the CGA has errors, so the log is the source of truth.
    errs = [l for l in body.splitlines() if " - ERROR" in l]
    warns = [l for l in body.splitlines() if " - WARNING" in l]
    for l in warns: print("  warning  :", l.strip())
    if errs:
        for l in errs: print("  ERROR    :", l.strip())
        sys.exit(f"{len(errs)} CGA error(s); rule package not built.")
    cgb = None
    for root, _dirs, files in os.walk(outdir):
        for f in files:
            if f.endswith(".cgb"): cgb = os.path.join(root, f)
    if not cgb:
        print(body[-1500:])
        sys.exit("compiler produced no .cgb")
    print(f"compiled   : {os.path.basename(cgb)} ({os.path.getsize(cgb):,} bytes)")
    return cgb


def pack(work, cgb):
    """Stage rules/ + bin/ + .resolvemap.xml, then 7z with the parameters PRT accepts."""
    stage = os.path.join(work, "stage")
    os.makedirs(os.path.join(stage, "rules")); os.makedirs(os.path.join(stage, "bin"))
    shutil.copy2(CGA, os.path.join(stage, "rules", NAME + ".cga"))
    shutil.copy2(cgb, os.path.join(stage, "bin", NAME + ".cgb"))
    with open(os.path.join(stage, ".resolvemap.xml"), "w", encoding="utf-8") as f:
        f.write(RESOLVEMAP.format(name=NAME))
    if os.path.exists(RPK): os.remove(RPK)
    os.makedirs(CE_DIR, exist_ok=True)
    # -m0=lzma -ms=off: PRT's reader rejects LZMA2 and solid archives outright.
    r = subprocess.run([SEVENZIP, "a", "-t7z", RPK, "-m0=lzma", "-md=4m", "-ms=off",
                        ".resolvemap.xml", "rules", "bin"],
                       cwd=stage, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(r.stdout[-800:]); sys.exit(f"7z failed ({r.returncode})")
    print(f"packed     : {os.path.relpath(RPK, ROOT)} ({os.path.getsize(RPK):,} bytes)")


def verify():
    """PRT fails silently on a bad package -- an empty attribute dict is the failure signal."""
    try:
        import pyprt
    except ImportError:
        print("verify     : pyprt not installed; skipped"); return True
    info = pyprt.get_rpk_attributes_info(RPK)
    if not info:
        sys.exit("verify FAILED: PRT read no attributes from the package (see the [PRT] errors above).")
    print(f"verify     : PRT loaded it, attributes {sorted(info)}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-work", action="store_true", help="leave the staging directory in place")
    a = ap.parse_args()
    need(CITYENGINE, "CityEngine"); need(SEVENZIP, "7-Zip"); need(CGA, "EVCharger.cga")
    work = tempfile.mkdtemp(prefix="ev_rpk_")
    try:
        pack(work, compile_cga(work))
        verify()
        print("\nnext: python scripts/ev_cityengine.py build --rpk " +
              os.path.relpath(RPK, ROOT).replace(os.sep, "/"))
    finally:
        if a.keep_work: print("work dir   :", work)
        else: shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
