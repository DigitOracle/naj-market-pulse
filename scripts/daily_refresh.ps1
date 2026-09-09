# Najma daily refresh â€” runs the full pipeline on this PC (the DLD gateway blocks cloud IPs,
# so this cannot run in GitHub Actions; a Windows scheduled task drives it instead).
# fetch fresh DLD -> build pulse.json -> ingest to Worker -> render + push heat map.
$ErrorActionPreference = "Continue"
Set-Location "C:\Dev\naj-market-pulse"
$log = "C:\Dev\naj-market-pulse\daily_refresh.log"
function Log($m) { Add-Content $log ("[{0}] {1}" -f (Get-Date -Format s), $m) }
Log "=== refresh start ==="

$env:DLD_TX_DAYS = "56"; $env:DLD_RENT_DAYS = "28"
python scripts\fetch_dld.py  *>> $log
python scripts\build_pulse.py *>> $log

# secrets from the listener .env (INGEST_TOKEN) â€” never hard-coded
$tok = (Get-Content "C:\Dev\azimuth-listener-naj\.env" | Where-Object { $_ -like "INGEST_TOKEN=*" }) -replace "INGEST_TOKEN=",""
$tok = $tok.Trim()
$env:AZIMUTH_URL = "https://azimuth-2.digitalchemy.workers.dev"
$env:INGEST_TOKEN = $tok

# ingest pulse.json
try {
  $r = Invoke-RestMethod -Method Post -Uri "$($env:AZIMUTH_URL)/ingest_market" `
    -Headers @{ "X-Azimuth-Ingest" = $tok; "Content-Type" = "application/json"; "User-Agent" = "najma-market-pulse/1.0" } `
    -InFile "public\pulse.json"
  Log ("ingest ok: " + ($r | ConvertTo-Json -Compress))
} catch { Log ("ingest FAILED: " + $_.Exception.Message) }

# render + push heat map
python scripts\push_heatmap.py *>> $log

# --- developer availability lifecycle (2 Sep 2026) ---------------------------------------
# group PDFs (listener capture + manual inbox) -> JSON -> board strip + drill claimed -> unit cards -> KV
Log "--- availability: was the listener alive since yesterday? ---"
python scripts\listener_health.py --hours 24 *>> $log
if ($LASTEXITCODE -eq 3) { Log "LISTENER DOWN - starting DA_Azimuth_Listener_Naj now; sheets posted while it was down were NOT captured"; Start-ScheduledTask -TaskName "DA_Azimuth_Listener_Naj" }
elseif ($LASTEXITCODE -eq 2) { Log "LISTENER GAP - it restarted overnight; check listener_health.json for the hours lost" }
Log "--- availability: extract new sheets ---"
python scripts\extract_avail.py --scan *>> $log
Log "--- availability: drill (registered mix + claimed) + board index ---"
python scripts\build_avail_drill.py *>> $log
python scripts\build_avail_index.py *>> $log
# 6 Sep 2026: what is left to sell (launched - sold vs the developer sheet) and the FIND index, straight after the sheets
python scripts\remaining_inventory.py *>> $log
python scripts\build_search_index.py *>> $log
Log "--- DNA chain: sheets + DLD -> developer DNA -> board cards -> project facts -> compare (added 3 Sep 2026: without it, captured sheets never reached the DNA) ---"
python scripts\build_developer_dna.py *>> $log
python scripts\build_board.py *>> $log
python scripts\build_projfacts.py *>> $log
python scripts\build_compare.py *>> $log
Log "--- cards: rebuild + push ---"
python scripts\build_unit_cards_v4.py *>> $log
python scripts\push_cards.py *>> $log
Log "--- knowledge graph: building meta ---"
python scripts\build_building_meta.py goldensymphony *>> $log
Log "=== refresh done ==="

# 8 Sep 2026 - the truth store: nodes, edges and the evidence ledger, rebuilt after the register (data/graph/najma.duckdb)
python scripts\graph_build.py *>> $log
