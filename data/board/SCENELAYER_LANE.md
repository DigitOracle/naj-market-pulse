# Scene layer lane — CityEngine → SLPK → ArcGIS Online → SceneView

*Najma twin, DigitAlchemy. Written 3 Sep 2026. Status: working end to end for six districts,
**private and owner-only**.*

> **Decision, 3 Sep 2026 (owner): this lane is INTERNAL ONLY.** It stays on the current ArcGIS
> subscription, the six scene layers stay private to the owner, and nothing from it is shared,
> embedded or shown to a client. The client-facing twin is the three.js skyline page. Reach for this
> lane for measurement, analysis and ArcGIS Pro work; do not spend further effort making it a
> deliverable unless that decision is revisited.

This is the second 3D lane. The one we ship today is the three.js skyline page
(`renderSkyline` in the Azimuth worker, GLB out of KV). This lane publishes the same
CityEngine massing as a hosted **I3S scene layer** on ArcGIS Online and views it through the
ArcGIS Maps SDK for JavaScript. It is not a replacement — see *Honest comparison* at the end.

---

## 1. Adding a new district — the exact commands

Prerequisites: CityEngine 2025.1 running with the external Python bridge on `127.0.0.1:25333`,
a `/najma/scenes/<slug>.cej` scene with a buildings shape layer, `data/ce/<slug>/buildings.geojson`,
and `data/board/preview/img/anchors_<slug>` for the labels.

```bat
:: 1. export the package  (system python, the one with the `cityengine` module)
python scripts\ce_export_slpk.py <slug>
::    several at once:   python scripts\ce_export_slpk.py businessbay palmdeira
::    the six v3 ones:   python scripts\ce_export_slpk.py --all
::    -> data\ce\_slpk\<slug>.slpk  +  data\ce\_slpk\_export_summary.json

:: 2. publish it, private  (ArcGIS Pro's python, so the signed-in Pro user is reused)
"%LOCALAPPDATA%\Programs\ArcGIS\Pro\bin\Python\Scripts\propy.bat" scripts\agol_publish_scene.py ^
    data\ce\_slpk\<slug>.slpk ^
    --title "Najma - <District> massing" ^
    --tags "najma,digitalchemy"
::    add --replace to overwrite an item with the same title
::    -> data\ce\_slpk\<slug>.slpk.agol.json  (item ids, service url, field list)

:: 3. refresh the manifest the viewer reads
python scripts\agol_manifest.py
::    -> data\board\scenelayers.json
::    --check also re-reads each item's live access level (needs propy)

:: 4. view it
::    data\board\preview\sceneview.html?d=<slug>
```

**The CityEngine lock.** `ce_export_slpk.py` takes `data\ce\.ce_lock` once for the whole batch,
polls every 20 s for up to 30 minutes if another agent holds it, and releases it in a `finally`.
It never calls `gateway.shutdown()` — the CityEngine session is shared, and shutting the bridge
down would kill whatever else is mid-run. Anything else that drives CE must observe the same lock.

**Shape names are not ours to rewrite.** The massing batch names shapes
`b<i>_<facadeclass>_s<status>` (v3) or `b<i>_<facadeclass>` (v2); `<i>` is the footprint index and
the key of `anchors_<slug>`. The exporter checks whether the names already parse to `b<i>` and, if
they do, **leaves them alone and does not save the scene** — rewriting them to a bare `b<i>` would
clobber the facade agent's work. Only when names carry no index does it rename, using the verified
`shape_map_v3.json` mapping, and only then save. On the 3 Sep run four districts were left untouched
and two (dubaimarina, jumeirahvillagecircle, palmdeira) were renamed.

**Re-publishing the same district.** ArcGIS Online enforces unique *file names* per owner
(error 409 / `CONT_0027`), independently of the item title. A second upload of `<slug>.slpk` —
a re-export, or a district that already went up as a proof — is refused. `agol_publish_scene.py`
catches that and retries once from a timestamped copy (`<slug>_<yyyymmddhhmmss>.slpk`); the title
is unchanged. This bit dubaimarina on 3 Sep because the proof had already uploaded that filename.
It is a housekeeping rule, not an account limit. Old package/layer pairs are not deleted for you:
use `--replace` to remove same-titled items first, or tidy them in the ArcGIS Online content page.

**The join.** Nothing is joined server-side. The viewer builds Arcade `Dictionary()` expressions from
`anchors_<slug>` and matches on `b<i>`, taken from the first `_`-token of the package's `name` field
(`?join=oid` falls back to `OBJECTID − 1`). Status comes from the `_s<status>` name suffix when it is
there, else the CGA `buildings.*` report flags.

---

## 2. What the account decision changes

`GIS("pro")` is signed in as **kwilson376@my.ggu.edu**, org **X5OoNWyMULMQeWqf**
("DigitAlchemy Research Platform", `DigitAlchemy.maps.arcgis.com`). The subscription is
type **Personal Use**, subType **Student Use**, `maxUsers: 1`, expiring **12 June 2027**.
The user is org_admin at level 2 with `portal:publisher:publishScenes`, so publishing works —
that is not the constraint. Three things are:

1. **"Share with the organisation" means nothing here.** The org has one seat and no groups.
   Org-level sharing would widen access to an audience of exactly one person. The only real
   choices on this account are *private* or *public (everyone, no sign-in)*.
2. **No API keys.** The subscription carries the `NoApiKeys` option. A keyed, unattended web app
   is not available. A page that reads a private layer therefore needs either an interactive
   OAuth sign-in (`?appid=`) or a short-lived user token (`--print-token`, `?token=`) — neither
   of which suits a public client board.
3. **It is a student/personal licence.** Esri's Student Use and Personal Use plans are
   non-commercial. Hosting client-facing DigitAlchemy deliverables on this subscription is a
   licensing question for the owner, not a technical one. **Do not resolve it by making the
   items public** — that is the same licence problem with wider blast radius.

So the fork is:

| | Stay on this account | Move to a DigitAlchemy organisational subscription |
|---|---|---|
| Sharing that is actually useful | public only | private → group → org → public, with named members |
| Unattended web app | no (no API keys) | yes (API keys / app credentials) |
| Commercial client use | not what the licence is for | yes |
| Cost | already paid, expires Jun 2027 | new ArcGIS Online subscription + credits |
| What to do meanwhile | keep items private, view signed in | — |

Everything published by this lane is **private, owner only**. `agol_publish_scene.py` never calls
`item.share()`, and `agol_manifest.py` only *reports* the access level. Changing sharing is the
owner's decision and should stay a deliberate, manual act.

---

## 3. The photoreal layer — cost and attribution

The photoreal toggle is Google Photorealistic 3D Tiles, loaded as an
`IntegratedMesh3DTilesLayer` from `tile.googleapis.com/v1/3dtiles/root.json`.

- **The key is never in the file.** It is passed as `?gkey=...` at view time. Do not commit one,
  and do not put one in a page that goes on the public board — a key in client-side JavaScript is
  readable by anyone who opens the page, and Google Maps Platform bills per session/tile request.
  If this ever ships publicly the key must be HTTP-referrer-restricted and scoped to the Map Tiles
  API only, with a budget cap and alerts.
- **Billing is per tile session**, under Google Maps Platform's Map Tiles API. Cost scales with
  how much people pan and zoom, not with what we publish. It is the only metered thing in this lane.
- **Attribution is mandatory and cannot be moved off-screen.** Google's terms require the Google
  logo and the per-tile data attributions to be visible while the tiles are displayed. The page
  shows the Google wordmark bottom-left whenever the layer is on, and the SDK's attribution bar
  carries the data credits. Do not restyle either away, and do not screenshot the photoreal view
  into a client deck with the attribution cropped out.
- Our massing and the Google mesh are **different sources of truth**. With photoreal on, the page
  hides *existing* massing (renderer swap, not a filter, so labels and developer colours survive)
  and leaves construction/pipeline volumes solid — the model then reads as "what is not there yet",
  which is the honest way to combine them. Developer-tagged existing buildings get a 35 % tint.
- The subscription reports `availableG3dTilesSessions: 0`, i.e. Esri's own 3D tiles service is not
  on this account. Google is the only photoreal option here.

---

## 4. Honest comparison: this lane vs the three.js viewer we ship

The three.js skyline page (`skyline_<slug>.html`, `renderSkyline` in the Azimuth worker) loads a
packed GLB from KV, drapes Esri World Imagery under it, and draws labels as HTML DOM overlays.

### What the three.js viewer does better

- **No sign-in, no account.** It is on the public board today. This lane's items are private, and
  on this subscription the only alternative is fully public. That single fact is why the three.js
  viewer is still the one we ship.
- **It shows the textured v3 facades.** Verified on the 3 Sep packages: the SLPKs contain
  geometry and attributes only — **zero texture resources**. Colour in the SceneView comes from
  our renderer, so it is flat developer/status massing. The GLB carries the facade classes,
  materials and images the v3 rule generates. For anything where the buildings should look like
  buildings, three.js wins outright.
- **Real ground.** Esri World Imagery is draped under the massing from `ground_<slug>`, so roads
  and parks are photographed, not drawn.
- **We own the whole stack.** Our Worker, our KV, our CSS, our labels. No third-party quota, no
  credits, no licence question, no service that can be retired under us.
- **Labels are interactive DOM.** They take house typography exactly, they are clickable through
  to project cards, they filter by developer, and they drive focus/zoom.
- **It is fast and small.** 0.5–1 MB per district, one fetch, instant.

### What the SceneView lane does better

- **Native 3D labels.** `LabelClass` + `LineCallout3D` gives real leader lines that are
  depth-correct and declutter automatically. The three.js page does that by hand in
  `updateLabels()` and its labels are 2D overlays that do not occlude behind geometry properly.
- **It streams.** I3S is level-of-detail: the browser pulls only what is in view. The GLB lane
  loads a whole district at once. That is fine at 0.5–1 MB and 2,500 buildings; it is not fine at
  city scale. Palm Jumeirah's 2,482 buildings published to a 0.94 MB package that streams.
- **Attributes live on the service.** Popups, renderers and filters read fields server-side
  instead of everything being baked into the GLB before it is pushed.
- **Terrain, basemap and photoreal underneath.** World elevation, a real basemap, and the Google
  mesh — none of which the three.js page has.
- **It leaves the browser.** The same hosted layer opens in ArcGIS Pro, in Web Scenes, and in
  other ArcGIS apps. The GLB only ever works in our page.

### When to reach for the SceneView

Reach for it when the audience is **internal or a signed-in counterparty**, and when the point being
made is **spatial context or scale** — a district in its real terrain, tens of thousands of
buildings, or our pipeline volumes standing in a photoreal city. Reach for it when someone wants
the data in ArcGIS rather than in a web page.

Keep shipping the three.js viewer for **the public board, and for anything where the buildings need
to look like buildings** — client-facing pages, screenshots and decks.

Two blockers before this lane could carry client-facing work: the **account/licence decision**
in §2, and **textures**, which do not survive `SPKMeshExportModelSettings` as currently configured.
Until both are answered, treat this as an internal capability, not a deliverable.

---

## 5. Verified 3 Sep 2026

Served `data/board` on a local static server and opened `preview/sceneview.html?d=businessbay`
and `?d=dubaimarina`. In both cases the page resolved the manifest (`../scenelayers.json`), showed
the district line (features, item id, *private*), built the six-district picker, and then the
ArcGIS Online built-in sign-in dialog appeared when the private layer was requested. That is the
expected behaviour for owner-only items, not a fault; the dialog was dismissed rather than signed
into, and the page reported `scene layer: failed · ABORTED` correctly. Rendering of the massing,
labels and popups therefore stands on the Dubai Marina proof (`sceneview_dubaimarina.html`, same
code path) until someone signs in as the owner. No credentials were entered by automation.

Published on this run (all private, owner `kwilson376@my.ggu.edu`, tags `najma,digitalchemy`):

| slug | features | SLPK | scene layer item | service |
|---|---|---|---|---|
| businessbay | 654 | 0.64 MB | `f1f2b325b61846699468cdb646a8df10` | `.../Najma_Business_Bay_massing/SceneServer` |
| dubaimarina | 589 | 0.26 MB | `58a94d03d5324e2680a82cfa731e1446` | `.../Najma_Dubai_Marina_massing/SceneServer` |
| burjkhalifa | 298 | 0.64 MB | `f5548a0871694861bbfe61dbb5c1e841` | `.../Najma_Burj_Khalifa_massing/SceneServer` |
| palmjumeirah | 2482 | 0.94 MB | `fcde00d2cbe64233aefe754e8cee0958` | `.../Najma_Palm_Jumeirah_massing/SceneServer` |
| jumeirahvillagecircle | 1524 | 0.45 MB | `66019b08b23245c695113fddf3aa252d` | `.../Najma_Jumeirah_Village_Circle_massing/SceneServer` |
| palmdeira | 278 | 0.10 MB | `20014669b29248699310b43501f62275` | `.../Najma_Palm_Deira_massing/SceneServer` |

Service root: `https://tiles.arcgis.com/tiles/X5OoNWyMULMQeWqf/arcgis/rest/services/`. The original
proof pair (`c6b79f939462410aa425f2068c1acea0` package, `7d36620fd6fd4dea8f955912426cf8b2` layer,
"… (proof)") is still there and still private; `sceneview_dubaimarina.html` points at it.

## 6. Files

| Path | What |
|---|---|
| `scripts/ce_export_slpk.py` | CE scene → SLPK, takes the CE lock, preserves shape names |
| `scripts/agol_publish_scene.py` | SLPK → hosted scene layer, private, writes a sidecar |
| `scripts/agol_manifest.py` | sidecars + export summary → `data/board/scenelayers.json` |
| `data/board/scenelayers.json` | the manifest the viewer reads |
| `data/board/preview/sceneview.html` | one page, every district (`?d=<slug>`) |
| `data/board/preview/sceneview_dubaimarina.html` | the original single-district proof, kept |
| `data/ce/_slpk/` | packages, CE export logs, `_export_summary.json`, sidecars |
