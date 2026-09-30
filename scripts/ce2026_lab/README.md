# CityEngine 2026.1 beta - unattended lab lane

Record copies of the files that live in `C:\Dev\ce2026_lab`, the lab workspace. Never point 2026.1 at the production
workspace: opening it can upgrade 2025.1 projects so 2025.1 can no longer read them.

- `make_lab_copy.py` - writes `ce2026_batch.py`: production `ce_batch_v2.py` with lab-only paths
- `run_lab.py` - the `-DpythonStartupScript`: runs one district's v3 build, then `CE().exit(False)`
- `test_2026.py` - the first smoke test (alyufrah1, 63 buildings)

Driver: `scripts/ce2026_run.py <slug> ...` - one CityEngine process per district, with a per-building parity check
against the production tile.

Environment: `C:\Dev\ce2026_lab\venv311` is built from CE's bundled Python 3.11, with the `cityengine` 1.2.0 and `py4j`
wheels from the pythonbridge plugin's `api_pkg_cache`, plus `pyproj`.

30 Sep 2026: burjkhalifa v3 built with exact parity (298/298 buildings, every building's triangle count equal).
