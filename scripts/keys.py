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
      '4238153.2'                a 5+ digit parcel with a sub-parcel suffix -> the parent parcel, TRUNCATED
    24 Sep 2026: the old digits.digits branch cast through DOUBLE, so community-plot '0117.645' became 118 (DuckDB
    rounds): 746 of 748 dotted DM-address and building-parcel keys collapsed onto community-sized numbers, 203 of them the
    NEIGHBOURING community's. Read as community-plot, 693 of those 748 match a real DLD parcel; read as a number, 1 did."""
    x = "trim(cast(%s as varchar))" % col
    return ("(case when regexp_matches({x}, '^[0-9]+$') then try_cast({x} as bigint)"
            " when regexp_matches({x}, '^[0-9]+[.]0*$') then try_cast(split_part({x}, '.', 1) as bigint)"
            " when regexp_matches({x}, '^[0-9]{{1,4}}[-.][0-9]{{1,4}}$')"
            " then try_cast(regexp_extract({x}, '^([0-9]+)', 1) as bigint) * 10000"
            " + try_cast(regexp_extract({x}, '([0-9]+)$', 1) as bigint)"
            " when regexp_matches({x}, '^[0-9]{{5,}}[.][0-9]+$') then try_cast(split_part({x}, '.', 1) as bigint) end)").format(x=x)


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
      '4238153.2' (5+ digit parcel, sub-parcel suffix) -> 4238153, truncated;  anything else -> None."""
    if v is None:
        return None
    s = str(v).strip()
    n = norm_number(s)
    if n is not None:
        return int(n)
    m = re.match(r"^(\d{1,4})[-.](\d{1,4})$", s)
    if m:
        return int(m.group(1)) * 10000 + int(m.group(2))
    m = re.match(r"^(\d{5,})\.\d+$", s)
    return int(m.group(1)) if m else None


def name_norm(s):
    s = re.sub(r"[^A-Z0-9 ]+", " ", (s or "").upper())
    return re.sub(r"\s+", " ", s).strip()


if __name__ == "__main__":
    assert norm_number("2537.00") == "2537" and norm_number(" 2537 ") == "2537" and norm_number(2537.0) == "2537"
    assert norm_number("") is None and norm_number("12.5") is None and norm_number(None) is None
    assert parcel_key("6830847.00") == 6830847 and parcel_key("683-847") == 6830847 and parcel_key("6830847") == 6830847
    assert parcel_key("0117.645") == 1170645 and parcel_key("117-645") == 1170645     # dot is a separator, not a decimal
    assert parcel_key("358.607") == 3580607                                           # never rounded into community 359
    assert parcel_key("1214.0") == 1214 and parcel_key("4238153.2") == 4238153 and parcel_key("4238153.7") == 4238153
    assert name_norm(" DAMAC Lagoons - NICE 1 ") == "DAMAC LAGOONS NICE 1"
    print("keys.py self-test ok")
