"""Compose the Prestige One dossier from the two pulls: the site (PRESTIGE_ONE_SITE.json + per-project originals) and the registers
(PRESTIGE_ONE_REGISTERS.json: DLD developer vehicles, projects, transactions, units; DM consultant/contractor/project rows).
Output: data/kits/prestigeone/PRESTIGE_ONE_DOSSIER.md and a copy in the catalogue tree under Client_Engagements/RealEstateBroker/02_Execution/Developer_Kits_SEP2026/PrestigeOne/.
Usage: python scripts/prestigeone_dossier.py
"""
import json, os, re, shutil, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
K = os.path.join(ROOT, "data", "kits", "prestigeone")
CAT = r"C:\Users\kwils\OneDrive\Desktop\DigitAlchemy_31MAY2026\Client_Engagements\RealEstateBroker\02_Execution\Developer_Kits_SEP2026\PrestigeOne"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main():
    site = json.load(open(os.path.join(K, "PRESTIGE_ONE_SITE.json"), encoding="utf-8")); reg = json.load(open(os.path.join(K, "PRESTIGE_ONE_REGISTERS.json"), encoding="utf-8"))
    pages = {p: v for p, v in site["pages"].items() if p.startswith("/projects/") and p != "/projects" and "error" not in v}
    tx = reg.get("transactions", {}); units = reg.get("units", {}).get("by_project", {}); dld = reg.get("projects", [])
    def find(d, name):
        n = norm(name.split("|")[0].replace("by Prestige One", ""))
        for k in d:
            if n and (n in norm(k) or norm(k) in n): return k, d[k]
        return None, None
    L = [f"# Prestige One Developments — everything public, pulled {time.strftime('%d %b %Y')}", "",
         f"Site: {site['base']} · {len(pages)} project pages · registers: DLD developers / projects / transactions / units (exports of 4 Sep 2026), DM consultant / contractor / project registers (data.dubai, 9 Sep 2026).", "",
         "## Licensed vehicles (DLD developer register)", "", "| Developer number | Name | Licensed | Expires |", "|---|---|---|---|"]
    for d in sorted(reg.get("developers", []), key=lambda x: str(x.get("developer_number"))):
        L.append(f"| {str(d.get('developer_number','')).split('.')[0]} | {d.get('developer_name_en','')} | {d.get('license_issue_date','')} | {d.get('license_expiry_date','')} |")
    L += ["", "## Projects on the DLD register", "", "| Project (register name) | Master project | Status | % complete | Units | Villas | Escrow agent |", "|---|---|---|---:|---:|---:|---|"]
    for p in dld:
        L.append(f"| {p.get('project_name','')} | {p.get('master_project_en','') or p.get('area_name_en','')} | {p.get('project_status','')} | {str(p.get('percent_completed','0')).rstrip('0').rstrip('.') or '0'} | {p.get('no_of_units','')} | {p.get('no_of_villas','')} | {p.get('escrow_agent_name','')} |")
    L += ["", "## Registered sales by project (DLD transactions, all years to 4 Sep 2026)", "", "| Project | Sales | Median AED | Median AED/m² | Years |", "|---|---:|---:|---:|---|"]
    for k, v in sorted(tx.items(), key=lambda x: -x[1]["n"]):
        yrs = ", ".join(f"{y}: {n}" for y, n in sorted(v["years"].items(), reverse=True) if y >= "2023")
        L.append(f"| {k} | {v['n']} | {v['median_aed'] or ''} | {v['median_aed_per_sqm'] or ''} | {yrs} |")
    L += ["", "## Units on the register", "", "| Project | Units |", "|---|---:|"] + [f"| {k} | {v} |" for k, v in units.items()]
    L += ["", "## The website, project by project", ""]
    for path, v in sorted(pages.items()):
        name = v["title"].split("|")[0].strip(); imgs = [a for a in v["assets"] if "error" not in a and not a["file"].lower().endswith(".pdf")]; pdfs = [a for a in v["assets"] if a["file"].lower().endswith(".pdf")]
        tk, tv = find(tx, name); uk, uv = find(units, name)
        L.append(f"### {name}"); L.append(f"- Page: {v['url']}")
        if v.get("description"): L.append(f"- Says: {v['description']}")
        L.append(f"- Originals saved: {len(imgs)} images, {len(pdfs)} documents → `data/kits/prestigeone/{path.split('/')[-1]}/`")
        if tv: L.append(f"- Register: {tv['n']} sales, median AED {tv['median_aed']:,} ({tv['median_aed_per_sqm']:,} per m²)" + (f"; {uv} units on the register" if uv else ""))
        elif uv: L.append(f"- Register: {uv} units, no sales yet")
        else: L.append("- Register: not found under a Prestige One vehicle (plot-level or unregistered)")
        for f in v.get("faq", [])[:6]: L.append(f"- Q: {f['q']}  A: {f['a'][:300]}")
        L.append("")
    dm = reg.get("dm_projects", [])
    if dm:
        L += ["## Dubai Municipality construction registers mentioning Prestige", "", "| Source | Community | Parcel | Project no | Status | Consultant | Contractor |", "|---|---|---|---|---|---|---|"]
        for r in dm[:40]:
            L.append(f"| {r.get('_src','')} | {r.get('community_name','')} | {r.get('parcel_id','')} | {r.get('project_no','')} | {r.get('project_status') or r.get('project_status_english','')} | {str(r.get('consultant_english',''))[:40]} | {str(r.get('contractor_english',''))[:40]} |")
    L += ["", "## Notes", "- Floor plans: none published on prestigeone.ae (every project page says to ask the sales team). Plans would have to come from the developer directly.",
          "- 'AURA PRESTIGE' and 'Prestige One Residences' appear in the register under different vehicles; check before attributing them to this developer.",
          "- Luxe Villa (Palm Jumeirah) is not on the projects register: a plot-level sale, to be traced through the land registry by frond and plot number.",
          "- Everything here is evidence, not truth: it goes into the truth store through a loader with source rows (dld_project, dld_tx, prestigeone_site) before it reaches a card."]
    md = "\n".join(L); open(os.path.join(K, "PRESTIGE_ONE_DOSSIER.md"), "w", encoding="utf-8").write(md)
    os.makedirs(CAT, exist_ok=True); shutil.copy(os.path.join(K, "PRESTIGE_ONE_DOSSIER.md"), CAT); shutil.copy(os.path.join(K, "PRESTIGE_ONE_REGISTERS.json"), CAT); shutil.copy(os.path.join(K, "PRESTIGE_ONE_SITE.json"), CAT)
    n_img = sum(1 for v in pages.values() for a in v["assets"] if "error" not in a)
    print(f"dossier: {len(pages)} pages · {n_img} originals · {len(dld)} DLD projects · {sum(v['n'] for v in tx.values())} sales -> {CAT}")


if __name__ == "__main__":
    main()
