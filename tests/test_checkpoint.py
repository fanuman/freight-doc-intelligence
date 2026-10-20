"""Checkpoints in Postgres. Needs the database from docker compose and the real langgraph library."""
import uuid

import psycopg
import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.postgres import PostgresSaver  # noqa: E402

from freight_intel.pipeline.checkpoint import open_pool, setup_checkpoint_tables  # noqa: E402
from freight_intel.pipeline.graph import (  # noqa: E402
    build_graph, pending_review, resume_document, review_thread_id, run_document,
)
from freight_intel.synth.oracle import OracleLLM  # noqa: E402
from freight_intel.synth.scenario import ARITHMETIC_ERROR, build_dataset  # noqa: E402
from freight_intel.synth.writer import write_dataset  # noqa: E402

CASES = build_dataset(45, 42)
WRONG_TOTAL = next(c for c in CASES if c.error_kind == ARITHMETIC_ERROR)
APPROVE = {"action": "approve", "reviewer": "ana@example.com", "note": "the printed total is wrong on the paper"}


@pytest.fixture(scope="module", autouse=True)
def tables():
    setup_checkpoint_tables()


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    out = tmp_path_factory.mktemp("files")
    write_dataset(45, 42, out)
    return out


def new_graph(pool):
    return build_graph(OracleLLM(CASES), checkpointer=PostgresSaver(pool), human_review=True)


def test_a_paused_review_survives_a_restart(files):
    thread = review_thread_id(uuid.uuid4(), uuid.uuid4())
    path = str(files / "cases" / WRONG_TOTAL.case_id / f"invoice.{WRONG_TOTAL.invoice_format}")
    pool = open_pool(max_size=2)
    try:
        run_document(new_graph(pool), path, thread_id=thread)  # pauses for a person
    finally:
        pool.close()  # the "server" goes away; nothing stays in memory

    pool = open_pool(max_size=2)  # a brand-new "server": new pool, new saver, new graph
    try:
        graph = new_graph(pool)
        request = pending_review(graph, thread)
        assert request is not None and any(issue["code"] == "TOTAL_MISMATCH" for issue in request["issues"])
        final = resume_document(graph, thread, APPROVE)
        assert final["status"] == "reviewed"
        assert pending_review(graph, thread) is None
    finally:
        PostgresSaver(pool).delete_thread(thread)  # leave the dev database clean
        pool.close()


def test_the_app_role_cannot_create_tables():
    """Setup is the owner's job. If this ever passes without an error, the app role has too many rights."""
    pool = open_pool(max_size=1)
    try:
        with pool.connection() as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("CREATE TABLE should_not_exist (id int)")
    finally:
        pool.close()
