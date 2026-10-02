"""The guard for the mistake that took the site down on 2026-10-02.

A column was added to the User model and to the backfill list, but the edit
that adds it to ensure_schema's migration list silently failed. Every test
still passed, because the test database is built by create_all() from the
models -- so SQLite had the column and Postgres never got it. The first query
against a real database after deploy raised UndefinedColumn on every page
that touches a user, which is all of them.

This file closes that hole: for every table ensure_schema manages, every
column declared on the model must also appear in the migration list. A test
suite that builds its schema from the models cannot otherwise see the gap.
"""
import pytest

import app as app_module
from app import EmailAccount, Flipbook, Form, Lead, Note, Site, Task, User

# Columns that shipped in the very first version of each table and therefore
# predate the migration list. ensure_schema only needs to know about columns
# added AFTER a table existed in the wild.
ORIGINAL = {
    "user": {"id", "name", "email", "password_hash", "created_at"},
    "lead": {"id", "name", "phone", "email", "business", "business_type",
             "source", "status", "created_at"},
    "task": {"id", "owner_id", "lead_id", "title", "kind", "due_at", "done",
             "done_at", "created_at"},
    "note": {"id", "lead_id", "body", "created_at"},
    "form": {"id", "owner_id", "name", "slug", "redirect_url", "created_at"},
    "site": {"id", "slug", "business_name", "tagline", "phone", "email",
             "services", "about", "color", "style", "created_at",
             "updated_at"},
    "flipbook": {"id", "owner_id", "slug", "title", "pages", "created_at",
                 "name", "page_count"},
    "flipbook_page": {"id", "flipbook_id", "num", "png", "created_at",
                      "width", "height"},
}

MODELS = {"user": User, "lead": Lead, "task": Task, "note": Note,
          "form": Form, "site": Site}


def _wanted():
    """Re-read the migration list the way ensure_schema builds it."""
    import inspect as pyinspect
    import re
    src = pyinspect.getsource(app_module._ensure_schema_inner)
    start = src.index("wanted = {")
    depth, i = 0, start + len("wanted = ")
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    # strip comments so eval sees a plain literal
    literal = re.sub(r"#.*", "", src[i:end])
    return eval(literal)   # noqa: S307 - our own source, not user input


@pytest.mark.parametrize("table", sorted(MODELS))
def test_every_model_column_is_in_the_migration_list(ctx, table):
    """If this fails, the column exists in tests and will NOT exist in
    production. Add it to the `wanted` dict in ensure_schema."""
    model = MODELS[table]
    wanted = _wanted()
    declared = {c.name for c in model.__table__.columns}
    covered = set(wanted.get(table, {})) | ORIGINAL.get(table, set())
    missing = declared - covered
    assert not missing, (
        f"{table}: {sorted(missing)} are declared on the model but are not in "
        f"ensure_schema's migration list, so a real Postgres database will "
        f"never get them.")


def test_the_backfill_only_names_columns_the_migration_adds(ctx):
    """A backfill for a column that is never added is dead code, and a sign
    the two lists have drifted apart."""
    import inspect as pyinspect
    import re
    src = pyinspect.getsource(app_module._ensure_schema_inner)
    pairs = set(re.findall(r'\("(\w+)",\s*"(\w+)"\):', src))
    wanted = _wanted()
    for table, col in sorted(pairs):
        assert col in wanted.get(table, {}), (
            f'backfill names {table}.{col} but ensure_schema never adds it')


def test_running_the_migration_twice_is_a_no_op(ctx):
    app_module.ensure_schema()
    app_module.ensure_schema()


def test_the_feature_columns_are_all_covered(ctx):
    """The three add-on flags and the tool-visibility column specifically,
    because these are the ones that broke."""
    wanted = _wanted()
    for col in ("feature_multi_user", "feature_dialer", "feature_enrichment",
                "hidden_tools", "account_id", "role", "active", "seat_limit"):
        assert col in wanted["user"], f"user.{col} missing from the migration list"
