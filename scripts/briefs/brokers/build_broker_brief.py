"""The broker brief: what the government registers say about Dubai's real estate brokers (Kendall, 19 Sep 2026).

Brokers are Naj's own trade, so this branch reads the registers from a broker's side, not a buyer's. Pages, in the house
style of the developer brief (same shell, charts, fonts and PDF path):

  1  The broker boom        DLD broker register: licences issued per year, women's share, register and office counts
  2  The market they serve  DSC estimated population by sex and community, 2018-2025
  3  Who's advertising      DLD real estate permits (advertising, open days, launches, exhibitions), 2016 to date

Page still to come as its data lands: where the brokerage offices
are (DET licences with the brokerage activity codes 6820004 / 6820012 / 7020-01, retired 0701002 / 0701012).

Rules: no broker or office is ever named (README hard rule 4) - counts only. Every figure says its source and period.
The broker register is a snapshot published 2 Oct 2025, so it is read for trends, never as "active today": most licences
run a year and the snapshot has not been refreshed since.

Usage: python scripts/briefs/brokers/build_broker_brief.py      -> data/sheets/broker_brief.pdf (+ .html)
"""
import datetime as dt, glob, io, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(SCRIPTS, ".."))
sys.path.insert(0, SCRIPTS)
import build_client_sheet as S  # noqa: E402
import build_developer_brief as B  # noqa: E402

import duckdb  # noqa: E402

NAVY, GOLD, INK, MUTED, RULE = B.NAVY, B.GOLD, B.INK, B.MUTED, B.RULE
BROKERS = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod", "dld__dld_brokers-open-api.json")
PERMITS = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod", "dld__dld_real_estate_permits-open-api.json")
POP_GLOB = os.path.join(ROOT, "data", "registers", "estimated_population_by_sex_and_community", "*.csv")


def columns(pts, w=690, h=200, fmt=lambda v: "{:,}".format(v), notes=None):
    """pts: [(label, value, colour)], value printed on top; notes: {label: small line under the value}."""
    top = max(v for _, v, _ in pts) or 1
    L, Bm, T = 8, 24, 30
    bw = (w - 2 * L) / len(pts)
    g = []
    for i, (lab, v, col) in enumerate(pts):
        bh = (h - Bm - T) * v / top
        x = L + i * bw
        g.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                 '<text x="%.1f" y="%.1f" font-size="10.5" fill="%s" text-anchor="middle">%s</text>'
                 '<text x="%.1f" y="%d" font-size="10" fill="%s" text-anchor="middle">%s</text>'
                 % (x + bw * 0.16, h - Bm - bh, bw * 0.68, bh, col, x + bw / 2, h - Bm - bh - 5, INK, fmt(v),
                    x + bw / 2, h - 8, MUTED, S.esc(lab)))
        if notes and lab in notes:
            g.append('<text x="%.1f" y="%.1f" font-size="9" fill="%s" text-anchor="middle">%s</text>'
                     % (x + bw / 2, h - Bm - bh - 17, MUTED, S.esc(notes[lab])))
    return '<svg width="%d" height="%d" role="img">%s</svg>' % (w, h, "".join(g))


def stacked(pts, w=690, h=210):
    """pts: [(label, men, women)] stacked columns, total printed on top in millions."""
    top = max(m + f for _, m, f in pts) or 1
    L, Bm, T = 8, 24, 18
    bw = (w - 2 * L) / len(pts)
    g = []
    for i, (lab, m, f) in enumerate(pts):
        x = L + i * bw + bw * 0.16
        hm, hf = (h - Bm - T) * m / top, (h - Bm - T) * f / top
        y0 = h - Bm
        g.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>' % (x, y0 - hm, bw * 0.68, hm, NAVY))
        g.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>' % (x, y0 - hm - hf, bw * 0.68, hf, GOLD))
        g.append('<text x="%.1f" y="%.1f" font-size="10.5" fill="%s" text-anchor="middle">%.2f m</text>'
                 % (x + bw * 0.34, y0 - hm - hf - 5, INK, (m + f) / 1e6))
        g.append('<text x="%.1f" y="%d" font-size="10" fill="%s" text-anchor="middle">%s</text>'
                 % (x + bw * 0.34, h - 8, MUTED, S.esc(lab)))
    return '<svg width="%d" height="%d" role="img">%s</svg>' % (w, h, "".join(g))


def hbars(pts, fmt, w=690, row=22, lw=210, tail=150):
    """B.hbar_chart with room after the longest bar for a value-plus-note label."""
    top = max(v for _, v in pts) or 1
    g = []
    for i, (lab, v) in enumerate(pts):
        y, bl = i * row, (w - lw - tail) * v / top
        g.append('<text x="0" y="%d" font-size="12" fill="%s">%s</text><rect x="%d" y="%d" width="%.1f" height="%d" fill="%s"/>'
                 '<text x="%.1f" y="%d" font-size="11" fill="%s">%s</text>'
                 % (y + 16, INK, S.esc(lab), lw, y + 5, bl, row - 10, NAVY, lw + bl + 6, y + 16, MUTED, fmt(v)))
    return '<svg width="%d" height="%d" role="img">%s</svg>' % (w, row * len(pts), "".join(g))


def legend(items):
    return ('<div style="display:flex;gap:16px;font-size:11px;color:%s;">%s</div>'
            % (INK, "".join('<span><span style="color:%s;font-size:13px;">&#9632;</span> %s</span>' % (c, S.esc(t))
                            for c, t in items)))


def source(text):
    return ('<div class="prov" style="margin-top:auto;border-top:1px solid %s;padding-top:8px;">%s</div>' % (RULE, text))


# --------------------------------------------------------------------------- page 1: the broker boom

def broker_page(today):
    con = duckdb.connect()
    con.execute("create view b as select unnest(results, recursive := true) from read_json_auto('%s', maximum_object_size=500000000)"
                % BROKERS.replace("\\", "/"))
    n, offices, snap = con.execute("select count(*), count(distinct real_estate_number), max(load_timestamp) from b").fetchone()
    last_start = con.execute("select max(try_cast(license_start_date as date)) from b").fetchone()[0]
    # gender '0' = man, '1' = woman: checked against names in the register, 19 Sep 2026
    yr = con.execute("""select year(try_cast(license_start_date as date)) y, count(*) n,
                               count(*) filter (where gender = '1') w, count(*) filter (where gender in ('0', '1')) g
                        from b where y between 2015 and 2025 group by 1 order by 1""").fetchall()
    by = {y: (c, w, g) for y, c, w, g in yr}
    part = "Jan-%s" % last_start.strftime("%b")
    pts = [(str(y), c, GOLD if y >= 2024 else NAVY) for y, c, _, _ in yr]
    share = lambda y: 100.0 * by[y][1] / by[y][2]
    recent = by[2024][0] + by[2025][0]
    body = ('<div class="sub" style="max-width:640px;">New broker licences issued each year, from the Dubai Land '
            'Department broker register. New licences more than doubled in 2024, and 2025 passed that total by September.</div>')
    body += '<div style="display:flex;gap:10px;">%s%s%s%s</div>' % (
        B.stat("Brokers in the register", "{:,}".format(n), "every licence it lists"),
        B.stat("Brokerage offices", "{:,}".format(offices), "the offices those brokers are licensed to"),
        B.stat("Licensed 2024-2025", "{:,}".format(recent), "%.0f%% of the whole register" % (100.0 * recent / n)),
        B.stat("Women, 2025", "%.0f%%" % share(2025), "of new licences (%.0f%% in 2022)" % share(2022)))
    body += '<div class="h2 serif" style="margin-top:6px;">New broker licences, by year</div>'
    body += columns(pts, notes={"2025": part, "2024": "x%.1f on 2023" % (by[2024][0] / by[2023][0])})
    body += '<div class="h2 serif" style="margin-top:2px;">Women\'s share of new licences</div>'
    body += columns([(str(y), round(share(y)), GOLD if y == 2025 else NAVY) for y, *_ in yr], h=130,
                    fmt=lambda v: "%d%%" % v)
    body += source('<b>Source</b> - Dubai Land Department Open Data, real estate broker register as published %s. Contains '
                   'information from the Government of Dubai. Counts only: no broker or office is named. The register is a '
                   'snapshot, so %d is licences issued %s; it is read for trends, not as a count of brokers active today.'
                   % (snap.strftime("%d %B %Y"), 2025, part))
    return B.shell("Dubai's Broker Boom", "BROKER BRIEF", body, today)


# --------------------------------------------------------------------------- page 2: the market they serve

def population_page(today):
    con = duckdb.connect()
    files = sorted(glob.glob(POP_GLOB))
    con.execute("create view p as select * from read_csv_auto('%s', header=true)" % files[-1].replace("\\", "/"))
    rows = con.execute("""select "Year", sum("Value") filter (where "Gender" = 'Male'), sum("Value") filter (where "Gender" = 'Female'),
                                 count(distinct "Code") from p group by 1 order by 1""").fetchall()
    first, last = rows[0], rows[-1]
    tot = lambda r: r[1] + r[2]
    grow = lambda a, b: 100.0 * (b - a) / a
    big = con.execute("""select "Sector & Community", sum("Value") v, sum("Value") filter (where "Gender" = 'Male') m
                         from p where "Year" = ? group by 1 order by 2 desc limit 10""", [last[0]]).fetchall()
    body = ('<div class="sub" style="max-width:640px;">The people every Dubai broker sells and leases to: estimated usual '
            'residents by year, men and women, from the Dubai Statistics Centre.</div>')
    body += '<div style="display:flex;gap:10px;">%s%s%s%s</div>' % (
        B.stat("Residents, %d" % last[0], "%.2f m" % (tot(last) / 1e6), "estimated usual residents"),
        B.stat("Growth since %d" % first[0], "+%.0f%%" % grow(tot(first), tot(last)), "+%.2f m people" % ((tot(last) - tot(first)) / 1e6)),
        B.stat("Women", "+%.0f%%" % grow(first[2], last[2]), "since %d; men +%.0f%%" % (first[0], grow(first[1], last[1]))),
        B.stat("Communities", "%d" % last[3], "counted in %d" % last[0]))
    body += '<div class="h2 serif" style="margin-top:6px;">Dubai residents, by year</div>'
    body += legend([(NAVY, "Men"), (GOLD, "Women")])
    body += stacked([(str(y), m, f) for y, m, f, _ in rows])
    body += ('<div class="h2 serif" style="margin-top:2px;">The ten largest communities, %d</div>'
             '<div class="sub" style="margin-top:-8px;">Residents, with the share who are men - the highest are worker '
             'housing, not the family market a broker serves.</div>' % last[0])
    men = {int(v): 100.0 * m / v for c, v, m in big}
    body += hbars([(c.title(), int(v)) for c, v, m in big],
                  fmt=lambda v: "{:,}  ·  {:.0f}% men".format(v, men[v]))
    body += source('<b>Source</b> - Dubai Statistics Centre, estimated population by sex and community, %d-%d, from '
                   'Data.Dubai. Contains information from the Government of Dubai.' % (first[0], last[0]))
    return B.shell("The Market Brokers Serve", "BROKER BRIEF", body, today)

# --------------------------------------------------------------------------- page 3: who's advertising

EVENTS = ("Open Day", "Launching a real estate project", "Real Estate Seminar", "Real Estate Promotional Stand",
          "Real Estate Exhibition", "Promotional Campaign")


def permits_page(today):
    """Every advertisement, open day, launch or exhibition for Dubai property needs a Land Department permit, so the permit
    register is the market's marketing ledger. Participants are companies by trade licence - brokerages and developers
    together until the licence activity codes can separate them."""
    con = duckdb.connect()
    con.execute("set enable_progress_bar=false")
    con.execute("create table p as select *, try_cast(start_date as date) d from (select unnest(results, recursive := true) "
                "from read_json_auto('%s', maximum_object_size=2000000000))" % PERMITS.replace("\\", "/"))
    snap = con.execute("select max(load_timestamp) from p").fetchone()[0]
    cut = snap.date()
    con.execute("delete from p where d is null or d > ?", [cut])              # a handful are dated ahead of the snapshot
    n, cos = con.execute("select count(*), count(distinct license_number) from p").fetchone()
    yr = dict(con.execute("select year(d), count(*) from p group by 1").fetchall())
    firms = dict(con.execute("select year(d), count(distinct license_number) from p group by 1").fetchall())
    ly, ty = cut.year - 1, cut.year
    same = dict(con.execute("select year(d), count(*) from p where year(d) in (?, ?) and dayofyear(d) <= ? group by 1",
                            [ly, ty, cut.timetuple().tm_yday]).fetchall())
    tot_ly, top10, top1, med = con.execute("""with o as (select license_number, count(*) n from p where year(d) = ? group by 1),
        r as (select n, row_number() over (order by n desc) rk, count(*) over () k from o)
        select sum(n), sum(n) filter (where rk <= k * 0.1) / sum(n), sum(n) filter (where rk <= k * 0.01) / sum(n), median(n) from r""",
                                           [ly]).fetchone()
    mix = con.execute("""select case when main_service_en like 'Electronic%%' then 'Online advertisements'
                                      when main_service_en in %s then 'Open days, launches, stands, exhibitions'
                                      else 'Print, outdoor, SMS and vehicles' end, count(*)
                         from p where year(d) = ? group by 1 order by 2 desc""" % (EVENTS,), [ly]).fetchall()
    change = 100.0 * (same[ty] - same[ly]) / same[ly]
    part = "Jan-%s" % cut.strftime("%d %b").lstrip("0")
    years = [y for y in sorted(yr) if y >= 2017]
    body = ('<div class="sub" style="max-width:640px;">Every property advertisement, open day, launch and exhibition in Dubai '
            'needs a Land Department permit - so the permit register is the market&#39;s marketing ledger.</div>')
    body += '<div style="display:flex;gap:10px;">%s%s%s%s</div>' % (
        B.stat("Permits, %d" % ly, "{:,}".format(yr[ly]), "x%.1f on %d" % (yr[ly] / yr[ly - 3], ly - 3)),
        B.stat("Companies advertising", "{:,}".format(firms[ly]), "in %d; %s in 2019" % (ly, "{:,}".format(firms[2019]))),
        B.stat("Busiest 10% of companies", "%.0f%%" % (100 * top10), "of %d permits; the typical one held %d" % (ly, med)),
        B.stat("%d so far" % ty, "%+.0f%%" % change, "%s permits vs %s, %s" % ("{:,}".format(same[ty]), "{:,}".format(same[ly]), part)))
    body += '<div class="h2 serif" style="margin-top:6px;">Permits issued, by year</div>'
    body += columns([(str(y), yr[y], GOLD if y >= ly else NAVY) for y in years], h=180, notes={str(ty): part})
    body += '<div class="h2 serif" style="margin-top:2px;">Companies holding at least one permit</div>'
    body += columns([(str(y), firms[y], GOLD if y >= ly else NAVY) for y in years], h=130)
    body += '<div class="h2 serif" style="margin-top:2px;">How the market advertised, %d</div>' % ly
    body += hbars([(k, v) for k, v in mix], fmt=lambda v: "{:,}  ·  {:.0f}%".format(v, 100.0 * v / tot_ly), row=24, lw=260)
    body += source('<b>Source</b> - Dubai Land Department Open Data, real estate permits register as published %s: %s permits '
                   'held by %s companies, June 2016 to %s. Contains information from the Government of Dubai. Companies are '
                   'counted by trade licence and include developers as well as brokerages; none is named. Permits later '
                   'cancelled are counted - they show intent to advertise.' % (snap.strftime("%d %B %Y"), "{:,}".format(n),
                                                                               "{:,}".format(cos), cut.strftime("%d %B %Y")))
    return B.shell("Who's Advertising Dubai Property", "BROKER BRIEF", body, today)


def main():
    today = dt.date.today().strftime("%d %B %Y")
    pages = [broker_page(today), population_page(today), permits_page(today)]
    out = "".join('<div class="page">%s</div>' % p.replace("__PAGENO__", "Page %d of %d" % (i, len(pages)))
                  for i, p in enumerate(pages, 1))
    hp = os.path.join(S.SHEETS, "broker_brief.html")
    io.open(hp, "w", encoding="utf-8").write(S.DOC % ("Broker brief", S.CSS, out))
    pp = os.path.join(S.SHEETS, "broker_brief.pdf")
    ok = S.to_pdf(hp, pp)
    print("broker_brief - %d pages, %s" % (len(pages), "%.0f KB" % (os.path.getsize(pp) / 1024) if ok else "HTML only"))


if __name__ == "__main__":
    main()
