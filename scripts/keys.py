"""Register keys, one implementation (digital thread Q1, 15 Sep 2026).

The registers publish the same number in several spellings: developer, broker and escrow numbers arrive as '2537.00' in one
file and '2537' in another, and a parcel is '6830847', '6830847.00' or '683-847' (community-plot). Joined as raw strings those
spellings never meet - brokers, developer numbers and escrow agents joined at 0% on 15 Sep. Every join on a register number goes
through here: the SQL helpers inside DuckDB queries, the Python helpers in scripts.

  num_sql(col)          '3656.00' / ' 3656' / '3656'   -> 3656 (bigint), NULL when not a number
  parcel_key_sql(col)   '6830847' / '6830847.00' / '683-847' -> 6830847 (community x 10000 + plot)
  name_norm_sql(col)    'DAMAC Lagoons - NICE 1 ' -> 'DAMAC LAGOONS NICE 1'
  norm_number(v)        Python twin of num_sql: returns the canonical digit string ('2537'), or None
  parcel_key(v)         Python twin of parcel_key_sql: returns an int, or None
  name_norm(s)          Python twin of name_norm_sql
"""
import re


def num_sql(col):
    """'3656.00', ' 3656', '3656' -> 3656"""
    return "try_cast(try_cast(trim(cast(%s as varchar)) as double) as bigint)" % col


def parcel_key_sql(col):
    """The spellings of one parcel -> one integer key. Twin of parcel_key() below: change them together.
      '6830847' / '6830847.00'   plain number, or a float artefact (only zeros after the dot)  -> 6830847
      '683-847' / '683.847'      community-plot, hyphen OR dot as the separator                -> 6830847
      '4238153.2'                a sub-parcel: REFUSED here (a different parcel, not a spelling) - see parent_parcel_key_sql
    24 Sep 2026: the old digits.digits branch cast through DOUBLE, so community-plot '0117.645' became 118 (DuckDB
    rounds): 746 of 748 dotted DM-address and building-parcel keys collapsed onto community-sized numbers, 203 of them the
    NEIGHBOURING community's. Read as community-plot, 693 of those 748 match a real DLD parcel; read as a number, 1 did.
    25 Sep 2026: zero is NO parcel, not parcel 0 - '0' and '0.0' keyed to 0 while '0.E-10' (the same 'none' in another
    export) keyed to NULL, so 4,784 parcel-less DM projects joined each other and anything else carrying 0 in one copy and
    nothing in the other. Every spelling of zero is NULL now (graph_load_dm already guarded plot_no <> '0')."""
    x = "trim(cast(%s as varchar))" % col
    return ("nullif((case when regexp_matches({x}, '^[0-9]+$') then try_cast({x} as bigint)"
            " when regexp_matches({x}, '^[0-9]+[.]0*$') then try_cast(split_part({x}, '.', 1) as bigint)"
            " when regexp_matches({x}, '^[0-9]{{1,4}}[-.][0-9]{{1,4}}$') and not regexp_matches({x}, '^0+[-.]')"
            " then try_cast(regexp_extract({x}, '^([0-9]+)', 1) as bigint) * 10000"
            " + try_cast(regexp_extract({x}, '([0-9]+)$', 1) as bigint) end), 0)").format(x=x)


def parent_parcel_key_sql(col):
    """parcel_key_sql, plus: a 5+ digit parcel with a sub-parcel suffix ('4238153.2') -> its PARENT, truncated. NOT a
    spelling of the same parcel - it maps a different parcel onto its parent, so a join on it pulls sub-parcel rows in
    under the parent. Call it only where that is the intended semantics; the canonical key refuses sub-parcels."""
    x = "trim(cast(%s as varchar))" % col
    sub = "case when regexp_matches(%s, '^[0-9]{5,}[.][0-9]+$') then try_cast(split_part(%s, '.', 1) as bigint) end" % (x, x)
    return "nullif(coalesce(%s, %s), 0)" % (parcel_key_sql(col), sub)


def name_norm_sql(col):
    """Upper case, anything but letters and digits to a space, spaces collapsed - identity_match.norm in SQL."""
    return "nullif(trim(regexp_replace(regexp_replace(upper(cast(%s as varchar)), '[^A-Z0-9 ]+', ' ', 'g'), '\\s+', ' ', 'g')), '')" % col


_NUM = re.compile(r"^\s*(\d+)(?:\.0*)?\s*$")


def norm_number(v):
    """'2537.00' -> '2537'; 2537.0 -> '2537'; ' 2537 ' -> '2537'; '' / None / 'n/a' -> None. Non-integral decimals ('12.5') -> None."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v == v and v.is_integer() else None
    m = _NUM.match(str(v))
    return str(int(m.group(1))) if m else None


def parcel_key(v):
    """Twin of parcel_key_sql() above - same four rules, change them together:
      '6830847' / '6830847.00' / 6830847.0 -> 6830847;  '683-847' / '683.847' (community-plot) -> 6830847;
      a sub-parcel like '4238153.2' -> None (see parent_parcel_key);  anything else -> None."""
    if v is None:
        return None
    s = str(v).strip()
    n = norm_number(s)
    if n is not None:
        return int(n) or None                      # zero is no parcel (25 Sep 2026) - twin of the nullif in parcel_key_sql
    m = re.match(r"^(\d{1,4})[-.](\d{1,4})$", s)
    if not m or int(m.group(1)) == 0:              # community 0 is not a community: '0-38' is no key, not parcel 38
        return None
    return int(m.group(1)) * 10000 + int(m.group(2))


def parent_parcel_key(v):
    """parcel_key, plus a sub-parcel ('4238153.2') -> its parent 4238153, truncated. Twin of parent_parcel_key_sql; a
    different parcel mapped onto its parent, so use it only where that is wanted."""
    k = parcel_key(v)
    if k is not None or v is None:
        return k
    m = re.match(r"^(\d{5,})\.\d+$", str(v).strip())
    return (int(m.group(1)) or None) if m else None


def name_norm(s):
    s = re.sub(r"[^A-Z0-9 ]+", " ", (s or "").upper())
    return re.sub(r"\s+", " ", s).strip()


if __name__ == "__main__":
    assert norm_number("2537.00") == "2537" and norm_number(" 2537 ") == "2537" and norm_number(2537.0) == "2537"
    assert norm_number("") is None and norm_number("12.5") is None and norm_number(None) is None
    assert parcel_key("6830847.00") == 6830847 and parcel_key("683-847") == 6830847 and parcel_key("6830847") == 6830847
    assert parcel_key("0117.645") == 1170645 and parcel_key("117-645") == 1170645     # dot is a separator, not a decimal
    assert parcel_key("358.607") == 3580607                                           # never rounded into community 359
    assert parcel_key("1214.0") == 1214 and parcel_key("4238153.2") is None                   # a sub-parcel is not a spelling
    assert parent_parcel_key("4238153.2") == 4238153 and parent_parcel_key("4238153.7") == 4238153  # truncated, never rounded
    assert parent_parcel_key("117-645") == 1170645 and parent_parcel_key("TP01") is None
    assert name_norm(" DAMAC Lagoons - NICE 1 ") == "DAMAC LAGOONS NICE 1"
    # zero is no parcel, in every spelling, in both twins (25 Sep 2026)
    for z in ("0", "0.0", "0.00", "0.E-10", "000", "0-0", "00000.0", 0, 0.0):
        assert parcel_key(z) is None and parent_parcel_key(z) is None, z
    assert parcel_key("10") == 10 and parcel_key("7") == 7                            # a real small number stays a key
    # community 0 is no community (25 Sep 2026): 21 DM addresses spelled '0-38' etc. keyed to 38, joining bare '38' junk
    assert parcel_key("0-7") is None and parcel_key("00-38") is None and parcel_key("0.38") is None
    assert parcel_key("1-7") == 10007 and parcel_key("0-0") is None
    import duckdb
    _c = duckdb.connect()
    for z, want in (("0", None), ("0.0", None), ("0.E-10", None), ("0-0", None), ("00000.3", None),
                    ("6830847.00", 6830847), ("683-847", 6830847), ("0117.645", 1170645), ("4238153.2", None), ("10", 10),
                    ("0-38", None), ("00-38", None), ("1-7", 10007)):
        got = _c.execute("select %s from (select ? as v)" % parcel_key_sql("v"), [z]).fetchone()[0]
        assert got == want and got == parcel_key(z), (z, got, want)
        par = _c.execute("select %s from (select ? as v)" % parent_parcel_key_sql("v"), [z]).fetchone()[0]
        assert par == parent_parcel_key(z), ("parent", z, par, parent_parcel_key(z))
    print("keys.py self-test ok")
