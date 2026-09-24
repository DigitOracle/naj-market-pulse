"""STAGE 3 of Business Bay in Unreal: render the sequences stage 2 built. Renders, but publishes nothing.

Run inside Unreal's Python console (Output Log, entry box switched from Cmd to Python):

    exec(open(r"C:\\Dev\\naj-market-pulse\\scripts\\ue_businessbay_stage3.py").read())

Defaults to the same 3 that stage 2 built, because nobody has watched one of these clips yet. Rendering 189 before
seeing one is the same mistake as building 189 cameras before knowing the actors existed, just later in the pipeline
and more expensive. When the first three look right:

    import ue_businessbay_stage3 as s3; s3.main(limit=None)

PUBLISHING IS A SEPARATE SCRIPT AND RUNS OUTSIDE UNREAL. scripts/publish_unreal_clips.py checks each file on disk -
that it exists, that it is not a few hundred bytes of nothing, that it starts with a real MP4 header - and only then
calls push_unreal_clip.py. A render that fails halfway still leaves a file, and Unreal is the wrong place to decide
whether that file is worth putting in front of a user.

WHAT I COULD NOT VERIFY WHEN WRITING THIS. I have no Unreal to run, so the Movie Render Queue calls here are written
defensively: the encoder setting is looked up by name and the script says which path it took rather than assuming one.
If MRQ reports no command-line encoder, it falls back to a PNG sequence and says so - publish_unreal_clips.py can turn
those into an mp4 with ffmpeg. Better a named fallback than a confident call into an API that moved.

OUTPUT. data/video/unreal_businessbay_<i>.mp4 (or a PNG folder of the same stem), 1080x1350 - 4:5 vertical, matching
the 18x22.5 filmback stage 2 set, so the frame is the shape the camera was aimed for.
"""
import json
import os
import unreal

ROOT = r"C:\Dev\naj-market-pulse"
STAGE2 = os.path.join(ROOT, "data", "board", "unreal_stage2_businessbay.json")
OUTDIR = os.path.join(ROOT, "data", "video")
MANIFEST = os.path.join(ROOT, "data", "board", "unreal_stage3_businessbay.json")

LIMIT = 3
RES_X, RES_Y = 1080, 1350          # 4:5, the filmback stage 2 set
FPS = 24


def log(m):
    unreal.log("[azimuth] " + str(m))


def cls(name):
    """Look a MoviePipeline setting up by name. These classes have moved between releases; absence is reported, not assumed."""
    return getattr(unreal, name, None)


def configure(job, stem):
    """Output settings for one job. Returns the kind of output it will produce."""
    cfg = job.get_configuration()

    out = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    out.output_directory = unreal.DirectoryPath(OUTDIR)
    out.file_name_format = stem
    out.output_resolution = unreal.IntPoint(RES_X, RES_Y)
    out.use_custom_frame_rate = True
    out.output_frame_rate = unreal.FrameRate(FPS, 1)
    out.override_existing_output = True

    # deferred renderer, or nothing draws
    rend = cls("MoviePipelineDeferredPassBase")
    if rend:
        cfg.find_or_add_setting_by_class(rend)

    enc = cls("MoviePipelineCommandLineEncoder")
    if enc:
        cfg.find_or_add_setting_by_class(enc)
        # the encoder consumes an image sequence, so one still has to be produced
        png = cls("MoviePipelineImageSequenceOutput_PNG")
        if png:
            cfg.find_or_add_setting_by_class(png)
        return "mp4"
    png = cls("MoviePipelineImageSequenceOutput_PNG")
    if png:
        cfg.find_or_add_setting_by_class(png)
        return "png_sequence"
    return "unknown"


def main(limit=LIMIT):
    if not os.path.isdir(OUTDIR):
        os.makedirs(OUTDIR)
    st2 = json.load(open(STAGE2, encoding="utf-8"))
    rows = st2["made"]
    if limit:
        rows = rows[:limit]
    log("stage 3: rendering %d of %d built sequences%s"
        % (len(rows), len(st2["made"]), "" if not limit else " (trial - main(limit=None) for the rest)"))

    sub = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
    queue = sub.get_queue()
    for j in list(queue.get_jobs()):
        queue.delete_job(j)

    level = unreal.EditorLevelLibrary.get_editor_world().get_path_name()
    planned, kinds = [], set()
    for r in rows:
        seq = r["sequence"]
        if not unreal.EditorAssetLibrary.does_asset_exist(seq):
            log("   b%-5d MISSING sequence %s" % (r["i"], seq))
            continue
        job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
        job.job_name = "b%d_%s" % (r["i"], r["name"][:40])
        job.sequence = unreal.SoftObjectPath(seq)
        job.map = unreal.SoftObjectPath(level)
        stem = "unreal_businessbay_%d" % r["i"]
        kinds.add(configure(job, stem))
        planned.append({"i": r["i"], "name": r["name"], "sequence": seq, "stem": stem,
                        "expect_mp4": os.path.join(OUTDIR, stem + ".mp4")})
        log("   queued b%-5d %s" % (r["i"], r["name"][:40]))

    json.dump({"district": "businessbay", "queued": len(planned), "output_kind": sorted(kinds),
               "resolution": [RES_X, RES_Y], "fps": FPS, "outdir": OUTDIR,
               "note": "queued for Movie Render Queue. Nothing is published from Unreal; run "
                       "scripts/publish_unreal_clips.py afterwards, which checks each file before it goes anywhere.",
               "clips": planned},
              open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    log("output kind: %s" % (", ".join(sorted(kinds)) or "none"))
    if "unknown" in kinds:
        log("NO OUTPUT SETTING FOUND - Movie Render Queue's output classes are not where this expected them.")
        log("Stopping rather than rendering to nowhere. Edit > Plugins: 'Movie Render Queue' must be enabled.")
        return
    log("manifest -> " + MANIFEST)
    log("starting render of %d jobs - the editor will be busy" % len(planned))
    sub.render_queue_with_executor_instance(unreal.MoviePipelinePIEExecutor(unreal.MoviePipelinePIEExecutor))
    log("render started. When it finishes: python scripts/publish_unreal_clips.py businessbay")


main()
