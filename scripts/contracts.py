"""Shared pieces of the feed contracts (Data Spine Phase 1, 13 Sep 2026): thresholds, the contract table, and a store
connection that waits for the write lock instead of failing.

A contract is a machine-checked promise about a feed: its key is unique, its count reconciles with the source, it has not
shrunk sharply since the last accepted load, and it is fresh enough to post. A feed that breaks its contract is HELD: it
stays in the store for inspection, but v_gov_usable stops naming it, so nothing downstream publishes it.

DuckDB lets one process write the store at a time. graph_build holds that lock for minutes, and on 9 Sep the 08:17 golden
check failed against it. connect_store() retries for a bounded time and says what it waited for.
"""
import os, time

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
STORE = os.path.join(ROOT, "data", "graph", "najma.duckdb")

SHRINK_HOLD = 0.8        # a governed-API dataset loading under 80% of its last accepted count is held
FRESH_DAYS = 10          # the weekly pull plus three days of grace; older than this reads as stale

GOV_CONTRACT_DDL = """
create table if not exists gov_contract (
    run_id        varchar,      -- ISO timestamp of the check, sortable
    mode          varchar,      -- quick (daily) or full (weekly, adds the duplicate scan)
    key           varchar,      -- gov_dataset.key
    table_name    varchar,
    pulled        varchar,
    rows_reported bigint,       -- rows the pull landed, repeats included
    rows_loaded   bigint,       -- rows the loader kept (select distinct)
    rows_in_table bigint,       -- rows the table actually holds now
    rows_distinct bigint,       -- full mode only
    repeats       bigint,       -- rows_reported - rows_loaded: what the source served twice
    status        varchar,      -- ok | ok-deduplicated | stale | held
    reason        varchar,
    held          boolean
)"""

HOLDS_VIEW = """
create or replace view v_gov_contract_holds as
select key, table_name, reason, run_id from gov_contract
where held and run_id = (select max(run_id) from gov_contract)"""


def connect_store(read_only=False, wait_seconds=1200, poll=20):
    """Open the truth store, waiting for another writer to finish rather than failing on the lock."""
    deadline = time.time() + wait_seconds
    waited = False
    while True:
        try:
            con = duckdb.connect(STORE, read_only=read_only)
            if waited:
                print("store lock released - continuing")
            return con
        except duckdb.IOException as e:
            if "lock" not in str(e).lower() or time.time() > deadline:
                raise
            if not waited:
                print("store is locked by another job - waiting up to %d min" % (wait_seconds // 60))
                waited = True
            time.sleep(poll)
