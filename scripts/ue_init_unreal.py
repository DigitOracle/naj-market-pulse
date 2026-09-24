"""Runs by itself every time AzimuthDubai opens (Unreal loads Content/Python/init_unreal.py when the Python plugin is on).

It runs the Sobha lens (C:/Dev/naj-market-pulse/scripts/ue_sobha_lens.py) ONCE per manifest build: the manifest's
"generated" stamp is remembered in Saved/sobha_lens_done.txt, so reopening the project does nothing until Kendall's
pipeline writes a newer manifest. Nothing to type: open the project, wait for the import (minutes on first run - the
Output Log shows "Sobha lens" lines), the level saves itself.

Progress and errors go to Saved/sobha_lens.log as well as the Output Log.
"""
import json, os, sys, traceback, datetime

import unreal

LENS = "C:/Dev/naj-market-pulse/scripts/ue_sobha_lens.py"
MANIFEST = "C:/Dev/naj-market-pulse/data/ce/_datasmith/sobha_unreal.json"
PROJ = unreal.Paths.project_dir()
DONE = os.path.join(PROJ, "Saved", "sobha_lens_done.txt")
LOG = os.path.join(PROJ, "Saved", "sobha_lens.log")


def note(msg):
    line = "%s %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg)
    unreal.log(line)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        open(LOG, "a", encoding="utf-8").write(line + "\n")
    except Exception:
        pass


def run_once():
    if not os.path.exists(MANIFEST):
        note("Sobha lens: no manifest yet at %s - nothing to do" % MANIFEST); return
    m = json.load(open(MANIFEST, encoding="utf-8")) or {}
    stamp = m.get("generated", "")
    # only the finished build: every Sobha district exported, all of them the full-LOD 3 Sobha subsets. Until the
    # CityEngine chain has written those, opening the project does nothing (no half-import to undo later).
    not_ready = list(m.get("missing") or []) + [s for s, d in (m.get("districts") or {}).items() if not str(d.get("export", "")).endswith("_sobha_lod3")]
    if not_ready:
        note("Sobha lens: manifest %s not ready for Unreal yet (waiting on %s) - open the project again later" % (stamp, ", ".join(sorted(set(not_ready))))); return
    if os.path.exists(DONE) and open(DONE, encoding="utf-8").read().strip() == stamp:
        note("Sobha lens: already applied for manifest %s" % stamp); return
    note("Sobha lens: applying manifest %s" % stamp)
    sys.path.insert(0, os.path.dirname(LENS))
    import importlib
    lens = importlib.import_module("ue_sobha_lens")
    importlib.reload(lens)
    lens.main()
    try:
        unreal.EditorLevelLibrary.save_current_level()
        note("Sobha lens: level saved")
    except Exception as e:
        note("Sobha lens: level not saved (%s) - File > Save Current Level" % e)
    open(DONE, "w", encoding="utf-8").write(stamp)
    note("Sobha lens: done")


# Only the interactive editor runs the lens. Unreal executes Content/Python/init_unreal.py in EVERY process that loads the
# project - the -game Movie Render Queue render and -run=pythonscript commandlets included - and the lens's editor-only
# calls there crash the process (EXCEPTION_ACCESS_VIOLATION in EditorScriptingUtilities, 24 Sep 2026, two renders lost).
_cmd = unreal.SystemLibrary.get_command_line() or ""
_SKIP = any(k in _cmd for k in ("-game", "-run=", "-server", "-MoviePipelineConfig", "-LevelSequence"))
_H = [None, 0]


def _tick(_dt):
    _H[1] += 1
    if _H[1] < 180:          # ~3 s of editor ticks: the level is open and the Outliner populated before we touch it
        return
    unreal.unregister_slate_post_tick_callback(_H[0])
    try:
        run_once()
    except Exception:
        note("Sobha lens FAILED:\n" + traceback.format_exc())


if _SKIP:
    note("Sobha lens: not an interactive editor session (%s) - skipped" % _cmd[:80])
else:
    _H[0] = unreal.register_slate_post_tick_callback(_tick)
