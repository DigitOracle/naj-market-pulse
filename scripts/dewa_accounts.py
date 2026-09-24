"""DEWA's account book, kept copy by copy: who is arriving where now, and from the second copy on, who left (14 Sep 2026).

The DEWA customer register on data.dubai (customers_master_data) is the list of active accounts, not a history of moves:
1,156,050 accounts in the 6 Jan 2026 extract, each with its building (Makani number), community ("345-BURJ KHALIFA"),
category, the account holder's nationality and the move-in date. People who moved out are simply absent, so move-in counts
by year overstate recent growth (2025: 301,974 against 2024: 184,094). One copy answers "who arrived where" as shares within
a period; two copies answer "who arrived and who left". The portal says monthly; the newest extract is still 6 Jan 2026.

Kept per extract, stamped with the register's own load_timestamp (re-downloading the same extract adds nothing):
  lk_dewa_extracts               one row per extract: stamp, data through, accounts
  lk_dewa_accounts_building      accounts by Makani number, community, use and move-in date. No nationality and no national /
                                 expatriate split at building level: a villa's Makani number is one household.
  lk_dewa_accounts_nationality   residential accounts by community, nationality and move-in month. Community level only.

Internal views (Naj's targeting and Azimuth's own reading; nothing here is published as it stands):
  v_dewa_new_residents_nationality  newest extract, per community and move-in quarter: each nationality with 20 or more
                                     accounts, smaller groups pooled as "other nationalities"; nothing under 20 shown
  v_dewa_flows_community            consecutive extracts: accounts before and after, arrivals, late additions, departures
  v_dewa_flows_nationality          the same per community and nationality, for groups of 20 or more

Rules for anything that leaves the store: no figure below 20 accounts, never nationality at building level, nationality
framed as where new residents come from - never as who lives somewhere. Raw rows stay on this machine.

Usage: python scripts/dewa_accounts.py [--dry]      exit 0 loaded or already held; 1 error
"""
import os, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lake
from register_joins import register_files, read

MIN_GROUP = 20
COMM = "try_cast(regexp_extract(community, '^ *([0-9]+)-', 1) as bigint)"

DDL = [
    """create table if not exists lk_dewa_extracts (extract_stamp varchar, data_through date, accounts bigint, residential bigint,
       with_nationality bigint, loaded_at timestamp, source_files varchar)""",
    """create table if not exists lk_dewa_accounts_building (extract_stamp varchar, makani varchar, comm_num bigint, account_use varchar,
       move_in_date date, accounts bigint)""",
    """create table if not exists lk_dewa_accounts_nationality (extract_stamp varchar, comm_num bigint, nationality varchar,
       move_in_month date, accounts bigint)""",
]

PAIRS = """pairs as (select extract_stamp, prev_stamp, prev_through from (
               select extract_stamp, lag(extract_stamp) over (order by data_through, extract_stamp) prev_stamp,
                      lag(data_through) over (order by data_through, extract_stamp) prev_through from lk_dewa_extracts)
           where prev_stamp is not null)"""

VIEWS = [
    ("v_dewa_new_residents_nationality", """
        with latest as (select extract_stamp from lk_dewa_extracts order by data_through desc, extract_stamp desc limit 1),
             n as (select comm_num, nationality, cast(year(move_in_month) as varchar) || '-Q' || cast(quarter(move_in_month) as varchar) move_in_quarter,
                          sum(accounts) accounts
                   from lk_dewa_accounts_nationality
                   where extract_stamp = (select extract_stamp from latest) and comm_num is not null and move_in_month is not null
                   group by 1, 2, 3),
             g as (select comm_num, move_in_quarter, case when accounts >= {MIN} then nationality else 'Other nationalities (under {MIN} each)' end nationality_group,
                          sum(accounts) accounts from n group by 1, 2, 3),
             t as (select comm_num, move_in_quarter, sum(accounts) total from g group by 1, 2 having sum(accounts) >= {MIN})
        select g.comm_num, c.name_en community, g.move_in_quarter, g.nationality_group, g.accounts,
               round(100.0 * g.accounts / t.total, 1) share_pct, t.total quarter_accounts
        from g join t using (comm_num, move_in_quarter)
        left join dm_community c on try_cast(c.comm_num as bigint) = g.comm_num
        where g.accounts >= {MIN}"""),
    ("v_dewa_flows_community", """
        with {PAIRS},
             cur as (select p.extract_stamp, p.prev_stamp, p.prev_through, b.makani, b.comm_num, b.account_use, b.move_in_date, b.accounts
                     from pairs p join lk_dewa_accounts_building b on b.extract_stamp = p.extract_stamp),
             old as (select p.extract_stamp, p.prev_stamp, p.prev_through, b.makani, b.comm_num, b.account_use, b.move_in_date, b.accounts
                     from pairs p join lk_dewa_accounts_building b on b.extract_stamp = p.prev_stamp),
             j as (select coalesce(c.extract_stamp, o.extract_stamp) extract_stamp, coalesce(c.prev_stamp, o.prev_stamp) prev_stamp,
                          coalesce(c.prev_through, o.prev_through) prev_through, coalesce(c.comm_num, o.comm_num) comm_num,
                          coalesce(c.account_use, o.account_use) account_use, coalesce(c.move_in_date, o.move_in_date) move_in_date,
                          coalesce(c.accounts, 0) now_n, coalesce(o.accounts, 0) prev_n
                   from cur c full join old o on c.extract_stamp = o.extract_stamp and c.makani is not distinct from o.makani
                        and c.comm_num is not distinct from o.comm_num and c.account_use = o.account_use and c.move_in_date is not distinct from o.move_in_date)
        select j.extract_stamp, j.prev_stamp, j.comm_num, any_value(c.name_en) community, j.account_use,
               sum(prev_n) accounts_before, sum(now_n) accounts_after,
               sum(case when move_in_date > prev_through then now_n else 0 end) arrivals,
               sum(case when move_in_date <= prev_through or move_in_date is null then greatest(now_n - prev_n, 0) else 0 end) late_additions,
               sum(case when move_in_date <= prev_through or move_in_date is null then greatest(prev_n - now_n, 0) else 0 end) departures
        from j left join dm_community c on try_cast(c.comm_num as bigint) = j.comm_num
        group by j.extract_stamp, j.prev_stamp, j.comm_num, j.account_use"""),
    ("v_dewa_flows_nationality", """
        with {PAIRS},
             cur as (select p.extract_stamp, p.prev_stamp, p.prev_through, n.comm_num, n.nationality, n.move_in_month, n.accounts
                     from pairs p join lk_dewa_accounts_nationality n on n.extract_stamp = p.extract_stamp),
             old as (select p.extract_stamp, p.prev_stamp, p.prev_through, n.comm_num, n.nationality, n.move_in_month, n.accounts
                     from pairs p join lk_dewa_accounts_nationality n on n.extract_stamp = p.prev_stamp),
             j as (select coalesce(c.extract_stamp, o.extract_stamp) extract_stamp, coalesce(c.prev_stamp, o.prev_stamp) prev_stamp,
                          cast(date_trunc('month', coalesce(c.prev_through, o.prev_through)) as date) prev_month,
                          coalesce(c.comm_num, o.comm_num) comm_num, coalesce(c.nationality, o.nationality) nationality,
                          coalesce(c.move_in_month, o.move_in_month) move_in_month, coalesce(c.accounts, 0) now_n, coalesce(o.accounts, 0) prev_n
                   from cur c full join old o on c.extract_stamp = o.extract_stamp and c.comm_num is not distinct from o.comm_num
                        and c.nationality = o.nationality and c.move_in_month is not distinct from o.move_in_month),
             f as (select extract_stamp, prev_stamp, comm_num, nationality, sum(prev_n) accounts_before, sum(now_n) accounts_after,
                          sum(case when move_in_month > prev_month then now_n when move_in_month = prev_month then greatest(now_n - prev_n, 0) else 0 end) arrivals,
                          sum(case when move_in_month <= prev_month or move_in_month is null then greatest(prev_n - now_n, 0) else 0 end) departures
                   from j group by 1, 2, 3, 4)
        select f.extract_stamp, f.prev_stamp, f.comm_num, c.name_en community, f.nationality, f.accounts_before, f.accounts_after,
               f.arrivals, f.departures
        from f left join dm_community c on try_cast(c.comm_num as bigint) = f.comm_num
        where greatest(f.accounts_before, f.accounts_after) >= {MIN}"""),
]


def view_sql(sql):
    return sql.replace("{PAIRS}", PAIRS).replace("{MIN}", str(MIN_GROUP))


def stage(con, C):
    """The extract as the three grains the store keeps - temp tables, outside the lake transaction."""
    con.execute("""create or replace temp table s_building as
        select case when regexp_matches(replace(trim(makani_number), ' ', ''), '^[0-9]{10}$') then replace(trim(makani_number), ' ', '') end makani,
               %s comm_num,
               case when customer_category ilike '%%resi%%' then 'residential' when customer_category ilike 'commercial%%' then 'commercial'
                    when customer_category ilike 'industrial%%' then 'industrial' else 'other' end account_use,
               try_cast(date_of_move_in as date) move_in_date, count(*) accounts
        from %s group by all""" % (COMM, C))
    con.execute("""create or replace temp table s_nationality as
        select %s comm_num, coalesce(nullif(trim(nationality), ''), 'Not recorded') nationality,
               cast(date_trunc('month', try_cast(date_of_move_in as date)) as date) move_in_month, count(*) accounts
        from %s where customer_category ilike '%%resi%%' group by all""" % (COMM, C))


def main():
    dry = "--dry" in sys.argv
    files = register_files("customers_master_data", "customers_master_data__*.csv")
    C = read(files)
    con = lake.connect(read_only=dry)
    stamp, through, accounts, residential, with_nat = con.execute("""select max(load_timestamp), max(try_cast(date_of_move_in as date)), count(*),
        count(*) filter (where customer_category ilike '%resi%'),
        count(*) filter (where customer_category ilike '%resi%' and nullif(trim(nationality), '') is not null) from """ + C).fetchone()
    held = con.execute("select count(*) from information_schema.tables where table_name = 'lk_dewa_extracts'").fetchone()[0]
    if held and con.execute("select count(*) from lk_dewa_extracts where extract_stamp = ?", [stamp]).fetchone()[0]:
        print("DEWA extract %s (data through %s) already held - nothing new" % (stamp, through))
        return 0
    stage(con, C)
    b_rows, b_accounts = con.execute("select count(*), sum(accounts) from s_building").fetchone()
    n_rows, n_accounts = con.execute("select count(*), sum(accounts) from s_nationality").fetchone()
    print("DEWA extract %s, data through %s: %s accounts (%s residential, %s of them with a nationality)"
          % (stamp, through, format(accounts, ","), format(residential, ","), format(with_nat, ",")))
    print("  building grain: %s groups holding %s accounts; nationality grain: %s groups holding %s residential accounts"
          % (format(b_rows, ","), format(b_accounts, ","), format(n_rows, ","), format(n_accounts, ",")))
    if b_accounts != accounts or n_accounts != residential:
        print("FAILED: the grains do not add back to the register (%s / %s)" % (b_accounts, n_accounts))
        return 1
    if dry:
        print("dry run: nothing written")
        return 0

    def body():
        for ddl in DDL:
            con.execute(ddl)
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("insert into lk_dewa_extracts values (?, ?, ?, ?, ?, localtimestamp, ?)",
                        [stamp, through, accounts, residential, with_nat, " | ".join(os.path.basename(f) for f in files)])
            con.execute("insert into lk_dewa_accounts_building select ?, * from s_building", [stamp])
            con.execute("insert into lk_dewa_accounts_nationality select ?, * from s_nationality", [stamp])
            for name, sql in VIEWS:
                con.execute("create or replace view %s as %s" % (name, view_sql(sql)))
            con.execute("COMMIT")
        except Exception:
            # 24 Sep 2026: swallow the rollback's own error and let the REAL one propagate, as lake.publish and
            # register_joins (95b20a1) do. A COMMIT that loses to another catalogue writer has already aborted the
            # transaction, so this ROLLBACK raises "no transaction is active" and hides the write-write conflict that
            # lake.retry is waiting for.
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise
    lake.retry(body, "dewa accounts")
    n = con.execute("select count(*) from lk_dewa_extracts").fetchone()[0]
    print("kept extract %s; the store now holds %d DEWA extract%s%s" % (stamp, n, "" if n == 1 else "s",
          "" if n > 1 else " - arrivals and departures start with the next one"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
