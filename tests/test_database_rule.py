"""The ready-made rule for a tool that runs one SQL statement: rules.database.

The rule is called as the checkpoint calls it, with the inputs of one action.
Nothing here reaches a database: the rule reads the statement and never runs it.
"""

import pytest

from kettle import rules
from kettle.checkpoint import HELD, RAN, REFUSED, Checkpoint
from kettle.checkpoint.rules import FREE, NEEDS_YES, NEVER, RulesError

FINE = "it is one statement that only reads, and it names nothing you protect"
UNTOLD = "the rule was not told about {} of the inputs of this query"
UNREAD = "the statement cannot be read"
UNSEEN = "the statement holds a character that cannot be seen"
BACKSLASH = "it holds a backslash, which some databases read as part of a quote and some do not"
COMMENT = "it holds a comment, and some databases run what is inside one"
OPEN = "a quote in it is never closed"
PREFIX = "a quote in it has a letter or a number stuck to its front, which can change how it is read"
BACKTICK = "a name in backticks holds more than a plain name"
DOLLAR = "it holds a $ that is not a numbered placeholder such as $1"
BRACKET = "it uses square brackets or braces in a way the rule does not read"
NUMBER = "a number in it runs into a word"
NOT_PLAIN = "it holds a character outside quotes that the rule does not read"
MORE = "it holds more than one statement"
NOT_SELECT = "it does not start with SELECT or WITH, so the rule cannot tell that it only reads"
CHANGES = "it holds {}, which can change the database"
CALL = "it calls {}, and the rule does not know that it only reads"
QUOTED_CALL = "it calls a function whose name is in quotes"
PROTECTED = "it names {}, which you protect"
PASSWORDS = "it names a place where the database keeps its own passwords"
DROPS = "it holds DROP or TRUNCATE, which remove a whole table, column or database"
EVERY_ROW = "it is a DELETE or an UPDATE with no WHERE of its own, so it would reach every row"


def make(**settings):
    settings = {"protect": ["payroll", "api_keys"], "functions": ["monthly_total"], **settings}
    return rules.database(**settings)


def said(reasons):
    """The reasons as why() writes them: the first four, then how many more."""
    return "; ".join(reasons[:4]) + (f"; and {len(reasons) - 4} more" if len(reasons) > 4 else "")


def given(sql, **more):
    return {"sql": sql, **more}


def runs(inputs, rule=None):
    rule = make() if rule is None else rule
    inputs = given(inputs) if type(inputs) is str else inputs
    verdict = rule.explain(inputs)
    assert (verdict.level, list(verdict.reasons)) == (FREE, [])
    assert rule(inputs) == FREE
    assert rule.why(inputs) == "Runs without asking: " + FINE


def asks(inputs, reasons, rule=None):
    rule = make() if rule is None else rule
    inputs = given(inputs) if type(inputs) is str else inputs
    verdict = rule.explain(inputs)
    assert (verdict.level, list(verdict.reasons)) == (NEEDS_YES, reasons)
    assert rule(inputs) == NEEDS_YES
    assert rule.why(inputs) == "Asks because: " + said(reasons)


def never(inputs, reasons, rule=None):
    rule = make(live=True) if rule is None else rule
    inputs = given(inputs) if type(inputs) is str else inputs
    verdict = rule.explain(inputs)
    assert (verdict.level, list(verdict.reasons)) == (NEVER, reasons)
    assert rule(inputs) == NEVER
    assert rule.why(inputs) == "Never allowed: " + said(reasons)


# ---- statements that only read ----


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, name FROM customers WHERE id = ?",
        "select id from customers",
        "SELECT * FROM orders WHERE placed > '2026-11-01' ORDER BY placed DESC LIMIT 20",
        "SELECT c.name, count(*) FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.name ORDER BY 2 DESC LIMIT 10",
        "WITH recent AS (SELECT * FROM orders WHERE placed > date('now', '-7 days')) SELECT count(*) FROM recent",
        "SELECT a FROM t WHERE x IN (SELECT y FROM u) AND NOT EXISTS (SELECT 1 FROM v)",
        "SELECT round(avg(total)::numeric, 2), coalesce(sum(total), 0) FROM orders",
        "SELECT cast(x AS varchar(10)), extract(year FROM d), row_number() OVER (PARTITION BY a ORDER BY b) FROM t",
        "SELECT a FROM t UNION ALL (SELECT a FROM u)",
        "SELECT count(*) FILTER (WHERE paid) FROM orders",
        "SELECT a, sum(b) FROM t GROUP BY ROLLUP (a)",
        "SELECT CASE WHEN a > 1 THEN (a + 1) ELSE (a - 1) END FROM t",
        "SELECT a FROM t WHERE b BETWEEN (1) AND (2)",
        "SELECT a FROM t WHERE b LIKE ('x' || '%')",
        "SELECT data->>'name', tags[1], ARRAY[1, 2] FROM t",
        "SELECT * FROM information_schema.tables",
        "SELECT a FROM t WHERE b <> 1 AND c != 2 AND d <= 3 AND e >= 4 AND f % 2 = 0 AND g | h & i ^ j = ~k",
        "SELECT 1",
        "SELECT 1.5, 10, 0.25 FROM t",
        "SeLeCt A fRoM T wHeRe B = 1",
        "WITH a AS (SELECT 1), b AS (SELECT 2) SELECT * FROM a, b",
    ],
)
def test_a_statement_that_only_reads_runs(sql):
    runs(sql)


def test_one_semicolon_at_the_end_is_fine_and_so_are_empty_statements():
    runs("SELECT 1;")
    runs("SELECT 1 ; ")
    runs("SELECT 1;;")
    runs("; SELECT 1")


def test_tabs_and_line_breaks_are_blanks():
    runs("SELECT a,\n\tb\r\nFROM t\nWHERE a = 1\n")


@pytest.mark.parametrize("holder", ["?", "$1", "$12", ":name", "%s", "%(name)s"])
def test_a_placeholder_for_a_value_is_fine(holder):
    runs(f"SELECT a FROM t WHERE b = {holder}")
    runs(f"SELECT a FROM t WHERE b IN ({holder}, {holder})")


def test_what_is_in_quotes_is_not_read_as_words():
    runs("SELECT * FROM notes WHERE body = 'drop table users; -- delete update insert'")
    runs('SELECT "update", "drop" FROM t')
    runs("SELECT `delete`, `truncate` FROM t")
    runs("SELECT 'it''s; delete from t' FROM t")
    runs('SELECT "a""; drop table t" FROM t')
    runs("SELECT 'a' 'b', '' FROM t")
    runs("SELECT * FROM t WHERE n = 'café' AND m = '<!-- x -->' AND o = '$$ @ { } [ # /* é'")


def test_the_values_passed_beside_the_statement_are_not_judged():
    runs(given("SELECT a FROM t WHERE b = ?", params=["drop table users; --\\ ​"]))
    runs(given("SELECT a FROM t WHERE b = ?", params=None))


# ---- the words that may stand before a bracket ----

BEFORE_A_BRACKET = [
    "select", "from", "where", "and", "or", "not", "in", "exists", "any", "all", "some", "on", "using", "join", "lateral",
    "values", "as", "over", "by", "case", "when", "then", "else", "between", "union", "except", "intersect", "having",
    "limit", "offset", "filter", "distinct", "like", "group", "rollup", "cube", "sets",
]  # fmt: skip

TYPES = ["char", "varchar", "nchar", "nvarchar", "decimal", "numeric", "float", "binary", "varbinary", "bit", "time", "timestamp"]

READS = [
    "count", "sum", "avg", "min", "max", "total", "group_concat", "string_agg", "array_agg", "json_agg", "bool_and", "bool_or", "stddev", "variance",
    "coalesce", "nullif", "ifnull", "isnull", "nvl", "iif", "if", "greatest", "least",
    "abs", "round", "floor", "ceil", "ceiling", "trunc", "mod", "power", "sqrt", "sign",
    "lower", "upper", "length", "char_length", "substr", "substring", "left", "right", "trim", "ltrim", "rtrim", "replace", "concat", "concat_ws", "instr", "position", "strpos",
    "cast", "convert", "try_cast", "to_char", "to_date", "to_timestamp", "to_number",
    "date", "datetime", "julianday", "strftime", "now", "curdate", "getdate", "date_trunc", "date_part", "extract", "date_add", "date_sub", "datediff", "date_format", "dateadd", "age",
    "year", "month", "day", "hour", "minute", "second",
    "row_number", "rank", "dense_rank", "ntile", "lag", "lead", "first_value", "last_value", "nth_value", "percent_rank", "cume_dist",
    "json_extract", "json_object", "json_array", "json_array_length", "json_value",
    "unnest", "array_length", "cardinality", "array", "row",
]  # fmt: skip


@pytest.mark.parametrize("word", BEFORE_A_BRACKET)
def test_a_word_of_the_language_before_a_bracket_is_not_a_call(word):
    runs(f"select 1 x {word} (2)")
    runs(f"select 1 x {word.upper()}(2)")


@pytest.mark.parametrize("name", TYPES)
def test_a_type_with_a_size_is_not_a_call(name):
    runs(f"select cast(a as {name}(10)) from t")
    runs(f"select a::{name.upper()} (10) from t")


@pytest.mark.parametrize("name", READS)
def test_a_function_that_only_reads_runs(name):
    runs(f"select {name}(a) from t")
    runs(f"select {name.upper()} (a) from t")


def test_the_lists_of_known_words_are_the_ones_tested_here():
    assert sorted(rules._SQL_BEFORE_BRACKET) == sorted(BEFORE_A_BRACKET)
    assert sorted(rules._SQL_TYPES) == sorted(TYPES)
    assert sorted(rules._SQL_READS) == sorted(READS)
    assert len(BEFORE_A_BRACKET) == 37 and len(TYPES) == 12 and len(READS) == 100


# ---- functions the rule does not know ----


@pytest.mark.parametrize(
    "name",
    [
        "pg_sleep", "sleep", "benchmark", "load_file", "pg_read_file", "pg_ls_dir", "dblink", "lo_import", "nextval", "setval", "set_config",
        "generate_series", "repeat", "lpad", "version", "random", "xp_cmdshell", "openrowset", "load_extension", "readfile", "writefile",
        "query_to_xml", "get_lock", "pg_terminate_backend", "truncate", "selects", "counts", "my_count", "count2",
    ],
)  # fmt: skip
def test_a_function_the_rule_does_not_know_asks(name):
    asks(f"select {name}(1)", [CALL.format(name)])
    asks(f"SELECT a FROM t WHERE b = {name.upper()} (1)", [CALL.format(name)])
    asks(f"select a from t where b = {name}\n\t(1)", [CALL.format(name)])


def test_every_unknown_function_is_named_once_and_in_order():
    asks("select sleep(1), count(a), sleep(2), benchmark(1, 2) from t where c = pg_sleep(3)", [CALL.format("sleep"), CALL.format("benchmark"), CALL.format("pg_sleep")])


def test_a_function_of_the_owners_own_runs():
    runs("select monthly_total(2026, 10)")
    runs("SELECT Monthly_Total (2026, 10) FROM t")
    asks("select monthly_total(1)", [CALL.format("monthly_total")], rules.database())
    asks("select monthly_totals(1)", [CALL.format("monthly_totals")])
    runs("select Monthly_Total(1)", rules.database(functions=["MONTHLY_TOTAL"]))


def test_a_function_with_a_schema_in_front_is_another_function():
    asks("select pg_catalog.count(1)", [CALL.format("pg_catalog.count")])
    asks("select reports.monthly_total(1)", [CALL.format("reports.monthly_total")])
    asks("select a . b . count (1)", [CALL.format("a.b.count")])
    asks("select x.select(1)", [CALL.format("x.select")])
    rule = rules.database(functions=["reports.monthly_total", "a.b.c"])
    runs("select reports.monthly_total(1)", rule)
    runs("select Reports . Monthly_Total (1), a.b.c(2)", rule)
    asks("select monthly_total(1)", [CALL.format("monthly_total")], rule)
    asks("select b.c(1)", [CALL.format("b.c")], rule)
    asks("select x.a.b.c(1)", [CALL.format("x.a.b.c")], rule)


def test_a_function_whose_name_is_in_quotes_asks():
    asks('select "pg_sleep"(1)', [QUOTED_CALL])
    asks("select `sleep`(1)", [QUOTED_CALL])
    asks('select "count" (a) from t', [QUOTED_CALL])
    asks('select "pg_catalog".count(1)', [QUOTED_CALL])
    asks('select pg_catalog."count"(1)', [QUOTED_CALL])
    asks('select "monthly_total"(1)', [QUOTED_CALL])
    asks('select "a".b.monthly_total(1), sleep(2)', [QUOTED_CALL, CALL.format("sleep")])


def test_a_bracket_after_a_text_a_number_or_a_mark_is_not_a_call():
    runs("select 'sleep' (1)")
    runs("select 1 (2), (3) (4), a = (5)")
    runs("select a.b, (select 1) from t")
    runs('select "a" in (1, 2) from t')
    runs("select sleep, pg_sleep from t")  # a name with no bracket after it calls nothing


def test_a_long_function_name_is_cut_short_in_the_reason():
    long = "a" * 41
    asks(f"select {long}(1)", [CALL.format("a" * 40 + "...")])
    asks(f"select {'b' * 40}(1)", [CALL.format("b" * 40)])
    asks(f"select s.{'c' * 39}(1)", [CALL.format("s." + "c" * 38 + "...")])


def test_the_brackets_of_a_statement_that_changes_are_not_taken_for_calls():
    asks("INSERT INTO t (a, b) VALUES (1, 2)", [NOT_SELECT, CHANGES.format("INSERT"), CHANGES.format("INTO")])
    asks("CREATE TABLE t (a int)", [NOT_SELECT, CHANGES.format("CREATE")])
    asks("EXPLAIN sleep(1)", [NOT_SELECT])
    asks("select sleep(1) into x", [CHANGES.format("INTO")])


# ---- statements that change ----

CHANGE_WORDS = ["insert", "update", "delete", "merge", "into", "alter", "create", "grant", "revoke", "replace"]


@pytest.mark.parametrize("word", CHANGE_WORDS)
def test_a_word_that_changes_asks_wherever_it_stands(word):
    said_word = CHANGES.format(word.upper())
    asks(f"select 1 {word} x", [said_word])
    asks(f"SELECT 1 {word.upper()} x", [said_word])
    asks(f"with a as (select 1) {word.capitalize()} x where 1", [said_word])
    asks(f"select a from t where b = 1\n{word}\nx", [said_word])
    every_row = [EVERY_ROW] if word in ("update", "delete") else []
    asks(f"select ({word}) from t", every_row + [said_word])
    runs(f"select '{word}', \"{word}\", `{word}` from t")
    runs(f"select {word}d, {word}_at, my_{word}, {word}2 from t")


def test_the_change_words_are_the_ones_tested_here():
    assert sorted(rules._SQL_CHANGES) == sorted(CHANGE_WORDS)
    assert sorted(rules._SQL_WHOLE) == ["drop", "truncate"]


def test_replace_is_a_function_when_a_bracket_follows_and_a_change_when_none_does():
    runs("select replace(name, 'a', 'b') from t")
    runs("select REPLACE (name, 'a', 'b') from t")
    asks("REPLACE INTO t VALUES (1)", [NOT_SELECT, CHANGES.format("REPLACE"), CHANGES.format("INTO")])
    asks("select replace from t", [CHANGES.format("REPLACE")])
    asks("select replace", [CHANGES.format("REPLACE")])


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE customers SET name = 'x' WHERE id = 1",
        "DELETE FROM orders WHERE id = 3",
        "DELETE FROM orders WHERE 1 = 1",
        "update t set a = 1 where b in (select c from u)",
    ],
)
def test_a_change_with_a_where_asks_even_on_a_live_database(sql):
    word = sql.split()[0].upper()
    asks(sql, [NOT_SELECT, CHANGES.format(word)])
    asks(sql, [NOT_SELECT, CHANGES.format(word)], make(live=True))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * INTO OUTFILE '/tmp/x' FROM t",
        "SELECT * INTO backup FROM t",
        "SELECT a FROM t INTO DUMPFILE '/tmp/x'",
    ],
)
def test_a_select_that_writes_asks(sql):
    asks(sql, [CHANGES.format("INTO")])


def test_a_select_that_locks_rows_asks():
    asks("SELECT * FROM t WHERE a = 1 FOR UPDATE", [CHANGES.format("UPDATE")])
    asks("SELECT * FROM t WHERE a = 1 FOR UPDATE", [CHANGES.format("UPDATE")], make(live=True))


@pytest.mark.parametrize(
    "sql",
    [
        "EXPLAIN SELECT 1", "SHOW TABLES", "DESCRIBE t", "PRAGMA table_info", "CALL tidy", "EXEC tidy", "EXECUTE tidy", "COPY t TO stdout",
        "SET a = 1", "BEGIN", "COMMIT", "VACUUM", "ATTACH 'x.db' AS x", "LOCK TABLES t", "VALUES (1)", "TABLE t", "DO 1", "USE shop", "ANALYZE t",
        "(SELECT 1)", "1", "'select'", "\"select\" 1", "selects 1", "with_x select 1", ", select 1", "? select 1",
    ],
)  # fmt: skip
def test_a_statement_that_does_not_start_with_select_or_with_asks(sql):
    asks(sql, [NOT_SELECT])


def test_more_than_one_statement_asks():
    asks("SELECT 1; SELECT 2", [MORE])
    asks("SELECT 1;SELECT 2;", [MORE])
    asks("SELECT 1; SELECT 2; SELECT 3", [MORE])
    asks("SELECT 1; UPDATE t SET a = 1 WHERE b = 2", [MORE, NOT_SELECT, CHANGES.format("UPDATE")])
    asks("SHOW a; SHOW b", [MORE, NOT_SELECT])
    asks("UPDATE t SET a = 1 WHERE b = 2; SELECT 1", [MORE, NOT_SELECT, CHANGES.format("UPDATE")])
    asks("SHOW a; SELECT 1", [MORE, NOT_SELECT])
    asks("SELECT 1; SHOW a; SELECT 2", [MORE, NOT_SELECT])
    asks("SELECT pg_sleep(1); SELECT 1", [MORE, CALL.format("pg_sleep")])
    asks("SELECT 1; SELECT pg_sleep(1)", [MORE, CALL.format("pg_sleep")])
    never("DELETE FROM t; SELECT 1", [EVERY_ROW])
    never("SELECT 1; DELETE FROM t", [EVERY_ROW])
    never("SELECT 1; UPDATE t SET a = 1; SELECT 2", [EVERY_ROW])


@pytest.mark.parametrize("word", ["insert", "update", "delete", "merge", "into", "alter", "create", "grant", "revoke"])
def test_a_word_that_changes_with_a_bracket_after_it_is_still_a_change(word):
    asks(f"SELECT {word}(a) FROM t", [CHANGES.format(word.upper())])
    asks(f"SELECT {word} (a) FROM t", [CHANGES.format(word.upper())])


def test_a_call_whose_bracket_is_the_last_thing_is_still_a_call():
    asks("SELECT pg_sleep(", [CALL.format("pg_sleep")])
    asks("SELECT 1, pg_sleep (", [CALL.format("pg_sleep")])
    asks('SELECT "pg_sleep"(', [QUOTED_CALL])
    runs("SELECT count(")
    runs("SELECT 'a; b' FROM t")
    runs('SELECT "a; b" FROM t;')


# ---- the worst kinds ----

WHOLE_TABLES = [
    "DROP TABLE users",
    "drop table users",
    "DROP DATABASE shop",
    "DrOp\n\tTaBlE users",
    "TRUNCATE orders",
    "truncate table orders",
    "DROP INDEX a",
]


@pytest.mark.parametrize("sql", WHOLE_TABLES)
def test_dropping_a_table_asks_and_is_refused_on_a_live_database(sql):
    asks(sql, [NOT_SELECT, DROPS])
    never(sql, [DROPS])


def test_a_drop_is_found_anywhere_outside_quotes():
    never("SELECT 1; DROP TABLE users", [DROPS])
    asks("SELECT 1; DROP TABLE users", [MORE, NOT_SELECT, DROPS])
    never("select 1 drop", [DROPS])
    never("select (drop) from t", [DROPS])
    never("ALTER TABLE t DROP COLUMN c", [DROPS])
    asks("ALTER TABLE t DROP COLUMN c", [NOT_SELECT, CHANGES.format("ALTER"), DROPS])
    never("select [drop] from t", [DROPS])
    never("select 1; truncate t; drop table u", [DROPS])
    live = make(live=True)
    runs("select 'drop table t', \"drop\", `truncate` from t", live)
    runs("select dropped, drop_date, truncated, backdrop from t", live)


def test_truncate_with_a_bracket_after_it_is_a_function_the_rule_does_not_know():
    asks("select truncate(1.234, 1)", [CALL.format("truncate")], make(live=True))
    asks("select TRUNCATE (a, 1) from t", [CALL.format("truncate")])
    never("select 1 drop (a)", [DROPS])
    asks("select 1 drop (a)", [DROPS])


EVERY_ROW_STATEMENTS = [
    "DELETE FROM orders",
    "delete from orders;",
    "UPDATE customers SET name = 'x'",
    "update t set a = (select b from u where u.id = 1)",
    "delete from t returning (select 1 where 2)",
    "WITH x AS (SELECT 1 WHERE 2) DELETE FROM t",
    "with x as (select 1) update t set a = 1",
    "WITH gone AS (DELETE FROM t RETURNING *) SELECT * FROM gone WHERE a = 1",
    "with a as (update t set b = 1 returning *) select 1",
    "SELECT 1; DELETE FROM t",
    ") DELETE FROM t",
    "(DELETE FROM t",
    "delete from t where a = 1; delete from u",
    "update t set a = 1 limit 5",
]


@pytest.mark.parametrize("sql", EVERY_ROW_STATEMENTS)
def test_a_delete_or_an_update_with_no_where_of_its_own_is_refused_on_a_live_database(sql):
    never(sql, [EVERY_ROW])
    verdict = make().explain(given(sql))
    assert verdict.level == NEEDS_YES and EVERY_ROW in verdict.reasons


def test_what_a_delete_with_no_where_says_when_the_database_is_not_live():
    asks("DELETE FROM orders", [NOT_SELECT, EVERY_ROW, CHANGES.format("DELETE")])
    asks("WITH x AS (SELECT 1) UPDATE t SET a = 1", [EVERY_ROW, CHANGES.format("UPDATE")])


@pytest.mark.parametrize(
    "sql, reasons",
    [
        ("DELETE FROM t WHERE id = 1", [NOT_SELECT, CHANGES.format("DELETE")]),
        ("delete from t where id in (select 1)", [NOT_SELECT, CHANGES.format("DELETE")]),
        ("UPDATE t SET a = (b + 1) WHERE c = 2", [NOT_SELECT, CHANGES.format("UPDATE")]),
        ("delete from t where a = (select 1", [NOT_SELECT, CHANGES.format("DELETE")]),
        ("WITH gone AS (DELETE FROM t WHERE a = 1 RETURNING *) SELECT * FROM gone", [CHANGES.format("DELETE")]),
        ("with a as (select 1) delete from t where b = 2", [CHANGES.format("DELETE")]),
        ("SELECT * FROM t FOR UPDATE", [CHANGES.format("UPDATE")]),
        ("select a from t where b = 1 for update", [CHANGES.format("UPDATE")]),
        ("INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = 2", [NOT_SELECT, CHANGES.format("INSERT"), CHANGES.format("INTO"), CHANGES.format("UPDATE")]),
        ("MERGE INTO t USING u ON t.a = u.a WHEN MATCHED THEN DELETE", [NOT_SELECT, CHANGES.format("MERGE"), CHANGES.format("INTO"), CHANGES.format("DELETE")]),
        ("CREATE TABLE t (a int REFERENCES u ON DELETE CASCADE)", [NOT_SELECT, CHANGES.format("CREATE"), CHANGES.format("DELETE")]),
        ("select a from t where b = 1 delete", [CHANGES.format("DELETE")]),
    ],
)
def test_these_ask_and_are_not_refused_on_a_live_database(sql, reasons):
    asks(sql, reasons, make(live=True))
    asks(sql, reasons)


# ---- text that two databases would read in two ways ----


@pytest.mark.parametrize("sql", ["SELECT 'a\\' FROM t", "SELECT 'it\\'s' FROM t", "SELECT a \\ b FROM t", 'SELECT "a\\"" FROM t', "SELECT a FROM t \\g"])
def test_a_backslash_asks(sql):
    verdict = make().explain(given(sql))
    assert verdict.level == NEEDS_YES and verdict.reasons[0] == BACKSLASH


def test_what_a_backslash_says():
    asks("SELECT 'a\\' FROM t", [BACKSLASH])
    asks("SELECT 'it\\'s' FROM t", [BACKSLASH, PREFIX, OPEN])
    asks('SELECT "a\\"" FROM t', [BACKSLASH, OPEN])
    asks("SELECT a \\ b FROM t", [BACKSLASH, NOT_PLAIN])
    asks("SELECT 'a\\' ; DROP TABLE t --'", [BACKSLASH, COMMENT, OPEN, MORE, NOT_SELECT, DROPS])


def test_a_quote_closed_by_a_backslash_in_one_database_hides_nothing_on_a_live_one():
    never("SELECT 'a\\' ; DROP TABLE t --'", [DROPS])


@pytest.mark.parametrize("sql", ["SELECT 1 -- note", "SELECT 1 --", "SELECT 1 /* note */", "SELECT /*+ fast */ 1", "SELECT 1 # note", "SELECT a #>> b FROM t", "SELECT 5--3", "SELECT 1 /*"])
def test_a_comment_asks(sql):
    asks(sql, [COMMENT])


def test_what_is_inside_a_comment_is_read_like_the_rest():
    asks("SELECT 1 -- drop table t", [COMMENT, DROPS])
    never("SELECT 1 -- drop table t", [DROPS])
    never("SELECT 1 /*! DROP TABLE t */", [DROPS])
    never("SELECT 1 /*!50000 ; DELETE FROM t */", [EVERY_ROW])
    never("SELECT 1 # truncate t", [DROPS])
    asks("SELECT 1 /* update */", [COMMENT, CHANGES.format("UPDATE")])
    asks("SELECT 1 /* sleep(1) */", [COMMENT, CALL.format("sleep")])
    asks("SELECT 1 -- ; select 2", [COMMENT, MORE])
    asks("SELECT 1 /* payroll */", [COMMENT, PROTECTED.format("payroll")])
    runs("SELECT '-- /* # */' FROM t")
    runs("SELECT a - b, a / b, a * b, a -b, a /b FROM t")


@pytest.mark.parametrize("sql", ["SELECT 'abc", "SELECT a FROM t WHERE b = 'x''", 'SELECT "abc', "SELECT 'a' 'b"])
def test_a_quote_that_is_never_closed_asks(sql):
    asks(sql, [OPEN])


def test_nothing_after_a_quote_that_is_never_closed_is_read():
    asks("SELECT 'a; drop table t", [OPEN], make(live=True))
    asks("SELECT `a; drop table t", [OPEN, BACKTICK], make(live=True))
    asks("SELECT `abc", [OPEN])


@pytest.mark.parametrize("sql", ["SELECT E'abc'", "SELECT N'abc'", "SELECT x'41'", "SELECT _utf8'abc'", 'SELECT U&"abc"', "SELECT 1'abc'", 'SELECT a"b" FROM t', "SELECT a`b` FROM t", "SELECT q'[abc]'", "SELECTé'a'"])
def test_a_quote_with_something_stuck_to_its_front_asks(sql):
    verdict = make().explain(given(sql))
    assert verdict.level == NEEDS_YES and PREFIX in verdict.reasons


def test_what_may_stand_right_before_a_quote():
    asks("SELECT E'abc'", [PREFIX])
    asks("SELECT 1'abc'", [PREFIX])
    asks('SELECT U&"abc"', [PREFIX])
    asks("SELECT a_'abc'", [PREFIX])
    runs("SELECT a FROM t WHERE b IN('x','y') AND c='z' AND d = 'p'||'q' AND e =\"f\"")
    runs("'a' 'b'".join(["SELECT ", " FROM t"]))
    runs("SELECT 'a'\"b\"`c` FROM t")


@pytest.mark.parametrize("sql", ["SELECT `a b` FROM t", "SELECT `a'b` FROM t", "SELECT `a;b` FROM t", "SELECT `` FROM t", "SELECT `1a` FROM t", "SELECT `a``b` FROM t", "SELECT `a.b` FROM t", "SELECT `café` FROM t"])
def test_a_name_in_backticks_that_is_not_a_plain_name_asks(sql):
    asks(sql, [BACKTICK])


def test_a_plain_name_in_backticks_runs():
    runs("SELECT `a`, `Order_2`, `_x` FROM `t`")


@pytest.mark.parametrize("sql", ["SELECT $$abc$$", "SELECT $tag$abc$tag$", "SELECT $a", "SELECT $1a", "SELECT $", "SELECT $1$", "SELECT a$b FROM t", "SELECT $1_ FROM t", "SELECT $ 1"])
def test_a_dollar_that_is_not_a_numbered_placeholder_asks(sql):
    verdict = make().explain(given(sql))
    assert verdict.level == NEEDS_YES and verdict.reasons[0] == DOLLAR


def test_what_a_dollar_says():
    asks("SELECT $$abc$$", [DOLLAR])
    asks("SELECT $a", [DOLLAR])
    asks("SELECT $", [DOLLAR])
    asks("SELECT $1$", [DOLLAR])
    asks("SELECT $ 1", [DOLLAR])
    asks("SELECT $1a", [DOLLAR, NUMBER])
    runs("SELECT $1, $2 FROM t WHERE a=$3")


def test_what_is_between_dollars_is_read_like_the_rest():
    never("SELECT $$ ; DROP TABLE t $$", [DROPS])
    asks("SELECT $x$ update $x$", [DOLLAR, CHANGES.format("UPDATE")])


@pytest.mark.parametrize("sql", ["SELECT [a'b] FROM t", "SELECT [a;b] FROM t", "SELECT [a FROM t", "SELECT [a(b)] FROM t", "SELECT [a[b]] FROM t", "SELECT {fn now()}", "SELECT a } FROM t", "SELECT { a FROM t", 'SELECT [a"b"] FROM t'])
def test_brackets_and_braces_the_rule_does_not_read_ask(sql):
    verdict = make().explain(given(sql))
    assert verdict.level == NEEDS_YES and BRACKET in verdict.reasons


def test_what_a_bracket_may_hold():
    asks("SELECT [a;b] FROM t", [BRACKET, MORE, NOT_SELECT])
    asks("SELECT { a FROM t", [BRACKET])
    asks("SELECT a } FROM t", [BRACKET])
    asks("SELECT [a FROM t", [BRACKET])
    asks("SELECT [a(b)] FROM t", [BRACKET, CALL.format("a")])
    runs("SELECT [a], [Order Details], [a.b], tags[1:2], m[1, 2], n[i+1], o[-1] FROM [t]")
    runs("SELECT a] FROM t")
    asks("SELECT [payroll] FROM t", [PROTECTED.format("payroll")])
    asks("SELECT [update] FROM t", [CHANGES.format("UPDATE")])


@pytest.mark.parametrize("sql", ["SELECT 1e5", "SELECT 0x1F", "SELECT 1.", "SELECT 1.5.2", "SELECT 1abc", "SELECT 1_000", "SELECT 1.e1", "SELECT 2é"])
def test_a_number_that_runs_into_a_word_asks(sql):
    verdict = make().explain(given(sql))
    assert verdict.level == NEEDS_YES and NUMBER in verdict.reasons


def test_a_number_cannot_swallow_a_word():
    asks("SELECT 1e5", [NUMBER])
    asks("SELECT 1.", [NUMBER])
    asks("SELECT 1_000", [NUMBER])
    asks("SELECT 1update", [NUMBER, CHANGES.format("UPDATE")])
    never("SELECT 1drop", [DROPS])
    asks("SELECT 1.5sleep(2)", [NUMBER, CALL.format("sleep")])
    runs("SELECT 1, 22, 3.25, 0.5, t1.a, a1, (1), 1+2, 3-4, 5*6, 7/8, 9;")


@pytest.mark.parametrize("character", ["@", "é", " ", "Е", "　", "１", "×"])
def test_a_character_outside_quotes_that_the_rule_does_not_read_asks(character):
    asks(f"SELECT a {character} FROM t", [NOT_PLAIN])
    runs(f"SELECT '{character}', \"{character}\" FROM t")


def test_a_word_with_a_letter_from_another_alphabet_is_not_the_word():
    asks("SЕLECT 1", [NOT_PLAIN, NOT_SELECT])
    asks("SELECT @@version", [NOT_PLAIN])
    asks("SELECT @a := 1", [NOT_PLAIN])
    asks("SELECT a FROM t WHERE b = café", [NOT_PLAIN])


@pytest.mark.parametrize("character", ["\x00", "\x0b", "\x0c", "\x1b", "\x7f", "\x85", "​", "‮", "⁠", "﻿", "\U000e0041"])
def test_a_character_that_cannot_be_seen_asks(character):
    asks(f"SELECT a FROM t WHERE b = 'x{character}y'", [UNSEEN])
    asks(f"SELECT a {character} FROM t", [UNSEEN, NOT_PLAIN])


# ---- what the owner protects ----


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM payroll",
        "SELECT * FROM PAYROLL",
        'SELECT * FROM "PayRoll" p',
        "SELECT * FROM `payroll`",
        "SELECT * FROM [payroll]",
        "SELECT * FROM hr.payroll",
        "SELECT * FROM hr . payroll p",
        "SELECT payroll.amount FROM t",
        "SELECT a FROM t JOIN payroll ON payroll.id = t.id",
        "SELECT a FROM t WHERE b IN (SELECT c FROM(payroll))",
        "SELECT a FROM t WHERE b = 1 AND payroll=2",
        "SELECT * FROM information_schema.columns WHERE table_name = 'payroll'",
        "SELECT a FROM t UNION SELECT amount FROM payroll;",
        "SELECT a FROM t WHERE b = 'x-payroll-y'",
        "payroll",
    ],
)
def test_a_statement_that_names_something_protected_asks(sql):
    verdict = make().explain(given(sql))
    assert verdict.level == NEEDS_YES and PROTECTED.format("payroll") in verdict.reasons
    assert make(live=True)(given(sql)) == NEEDS_YES


def test_what_naming_something_protected_says():
    asks("SELECT * FROM payroll", [PROTECTED.format("payroll")])
    asks("SELECT key FROM api_keys JOIN payroll USING (id)", [PROTECTED.format("api_keys"), PROTECTED.format("payroll")])
    asks("SELECT * FROM payroll, payroll p2", [PROTECTED.format("payroll")])
    asks("UPDATE payroll SET amount = 1 WHERE id = 2", [PROTECTED.format("payroll"), NOT_SELECT, CHANGES.format("UPDATE")])
    asks("SELECT * FROM Payroll", [PROTECTED.format("payroll")], rules.database(protect=["PayRoll"]))
    never("DROP TABLE payroll", [DROPS])


@pytest.mark.parametrize("name", ["payroll2", "my_payroll", "payrolls", "payroll_old", "xpayroll", "pay_roll", "pay", "roll", "api", "keys", "apikeys"])
def test_a_longer_or_shorter_name_is_another_name(name):
    runs(f"SELECT * FROM {name}")
    runs(f"SELECT a FROM t WHERE b = '{name}'")


def test_with_nothing_protected_any_table_is_read():
    runs("SELECT * FROM payroll", rules.database())
    runs("SELECT * FROM payroll", rules.database(protect=[]))
    runs("SELECT * FROM payroll", rules.database(protect=None, functions=None))


PASSWORD_PLACES = ["pg_shadow", "pg_authid", "pg_user_mapping", "pg_user_mappings", "sql_logins", "dba_users"]


@pytest.mark.parametrize("name", PASSWORD_PLACES)
def test_a_place_where_a_database_keeps_its_passwords_asks(name):
    asks(f"SELECT * FROM {name}", [PASSWORDS])
    asks(f"SELECT * FROM {name.upper()} x", [PASSWORDS])
    asks(f'SELECT * FROM pg_catalog."{name}"', [PASSWORDS])
    asks(f"SELECT a FROM t WHERE b = '{name}'", [PASSWORDS])
    asks(f"SELECT * FROM sys.{name};", [PASSWORDS], rules.database())
    runs(f"SELECT * FROM {name}2")
    runs(f"SELECT * FROM my_{name}")


def test_the_password_places_are_the_ones_tested_here():
    assert list(rules._SQL_SECRETS) == PASSWORD_PLACES


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT user, authentication_string FROM mysql.user",
        "SELECT * FROM MYSQL.db",
        "SELECT * FROM mysql . user",
        "SELECT * FROM mysql\n.user",
        "SELECT * FROM `mysql`.`user`",
        'SELECT * FROM "mysql".user',
        "SELECT * FROM 'mysql'.user",
        "SELECT * FROM 'MySQL' . user",
        'SELECT * FROM "MySQL".user',
        "SELECT mysql.user.password FROM t",
    ],
)
def test_the_tables_mysql_keeps_for_itself_ask(sql):
    asks(sql, [PASSWORDS])
    asks(sql, [PASSWORDS], rules.database(live=True))


@pytest.mark.parametrize("sql", ["SELECT mysql FROM t", "SELECT * FROM mysql_orders", "SELECT t.mysql FROM t", "SELECT * FROM my.sql", "SELECT 'mysql.user' FROM t", "SELECT * FROM xmysql.t", "SELECT * FROM mysql2.t", "SELECT mysql, user FROM t"])
def test_the_word_mysql_alone_is_not_that_place(sql):
    runs(sql)


def test_a_password_place_and_a_protected_name_are_both_said():
    asks("SELECT * FROM pg_shadow, payroll", [PROTECTED.format("payroll"), PASSWORDS])
    asks("SELECT * FROM mysql.user; SELECT * FROM pg_authid", [MORE, PASSWORDS])


# ---- the inputs ----


def test_an_input_the_rule_was_not_told_about_asks():
    asks(given("SELECT 1", database="prod"), [UNTOLD.format(1)])
    asks(given("SELECT 1", database="prod", timeout=5), [UNTOLD.format(2)])
    asks(given("SELECT 1", params=[1], connection="x"), [UNTOLD.format(1)])
    asks(given("DELETE FROM t WHERE a = 1", database="prod"), [UNTOLD.format(1), NOT_SELECT, CHANGES.format("DELETE")])
    never(given("DROP TABLE t", database="prod"), [DROPS])
    runs(given("SELECT 1", params=[1]))


def test_an_input_the_owner_said_to_pass_over_does_not_ask():
    rule = make(ignore=["timeout", "label"])
    runs(given("SELECT 1", timeout=5, label="drop table t", params=[1]), rule)
    asks(given("SELECT 1", timeout=5, database="prod"), [UNTOLD.format(1)], rule)
    runs(given("SELECT 1", timeout=5), make(ignore=("timeout",)))
    runs(given("SELECT 1", timeout=5), make(ignore={"timeout"}))
    runs(given("SELECT 1", timeout=5), make(ignore=frozenset({"timeout"})))


def test_the_inputs_may_have_other_names():
    rule = make(sql="query", params="args")
    runs({"query": "SELECT 1", "args": [1]}, rule)
    asks({"query": "DELETE FROM t WHERE a = 1"}, [NOT_SELECT, CHANGES.format("DELETE")], rule)
    asks({"sql": "SELECT 1"}, [UNTOLD.format(1), UNREAD], rule)
    asks({"query": "SELECT 1", "sql": "SELECT 1"}, [UNTOLD.format(1)], rule)
    asks({"query": "SELECT 1", "params": [1]}, [UNTOLD.format(1)], rule)


@pytest.mark.parametrize("statement", [None, 5, 1.5, True, b"SELECT 1", ["SELECT 1"], ("SELECT 1",), {"sql": "SELECT 1"}, "", "   ", "\n\t", ";", " ; ; ", " "])
def test_a_statement_that_is_not_text_or_holds_nothing_asks(statement):
    verdict = make().explain(given(statement))
    assert verdict.level == NEEDS_YES and UNREAD in verdict.reasons
    assert make(live=True)(given(statement)) == NEEDS_YES


def test_what_a_missing_statement_says():
    asks({}, [UNREAD])
    asks({"params": [1]}, [UNREAD])
    asks({"database": "prod"}, [UNTOLD.format(1), UNREAD])
    asks(given(None), [UNREAD])
    asks(given(""), [UNREAD])
    asks(given(";"), [UNREAD])
    asks(given("\x00"), [UNSEEN, UNREAD])
    asks(given(["SELECT 1"]), [UNREAD])


@pytest.mark.parametrize("inputs", [None, "SELECT 1", ["SELECT 1"], 5, (("sql", "SELECT 1"),)])
def test_inputs_that_are_not_a_set_of_named_values_ask(inputs):
    rule = make()
    verdict = rule.explain(inputs)
    assert (verdict.level, list(verdict.reasons)) == (NEEDS_YES, ["the inputs cannot be read"])
    assert rule.why(inputs) == "Asks because: the inputs cannot be read"


def test_many_reasons_are_cut_short_in_the_line_the_owner_reads():
    sql = "SELECT 'a\\' -- x\n; UPDATE payroll SET a = E'b' WHERE c = $$d$$"
    reasons = [BACKSLASH, COMMENT, PREFIX, DOLLAR, MORE, PROTECTED.format("payroll"), NOT_SELECT, CHANGES.format("UPDATE")]
    rule = make()
    assert list(rule.explain(given(sql)).reasons) == reasons
    assert rule.why(given(sql)) == "Asks because: " + "; ".join(reasons[:4]) + "; and 4 more"


def test_the_strictest_answer_wins_and_only_its_reasons_are_said():
    verdict = make(live=True).explain(given("SELECT 1 -- x\n; DROP TABLE payroll; DELETE FROM t"))
    assert (verdict.level, sorted(verdict.reasons)) == (NEVER, sorted([DROPS, EVERY_ROW]))


# ---- setting the rule up ----


@pytest.mark.parametrize("value", ["payroll", {"payroll": 1}, 5, True, b"payroll"])
def test_a_list_must_be_given_as_a_list(value):
    with pytest.raises(RulesError, match="protect must be a list of names, given as the list itself"):
        rules.database(protect=value)
    with pytest.raises(RulesError, match="functions must be a list of names, given as the list itself"):
        rules.database(functions=value)


@pytest.mark.parametrize("value", [5, None, b"payroll", "", " ", "pay roll", "hr.payroll", "pay;", "1x", "payroll'", '"payroll"', "pay-roll", "payroll\n", "café", "pay$"])
def test_a_protected_name_must_be_a_plain_name(value):
    with pytest.raises(RulesError) as error:
        rules.database(protect=["orders", value])
    assert str(error.value) == f"protect: {value!r} is not a plain name, such as 'payroll'"


@pytest.mark.parametrize("value", [5, None, "", "a b", ".a", "a.", "a..b", "a.1b", "sleep()", "a;b", "a\n", "café"])
def test_a_function_of_the_owners_must_be_a_plain_name(value):
    with pytest.raises(RulesError) as error:
        rules.database(functions=["monthly_total", value])
    assert str(error.value) == f"functions: {value!r} is not a plain name, such as 'monthly_total'"


@pytest.mark.parametrize("value", [1, 0, "yes", None, "True", [True]])
def test_live_must_be_true_or_false(value):
    with pytest.raises(RulesError, match="^live must be True or False$"):
        rules.database(live=value)


@pytest.mark.parametrize("value", ["timeout", 5, None, [5], [""], ["timeout", None], {"timeout": 1}])
def test_the_inputs_to_pass_over_must_be_a_list_of_names(value):
    with pytest.raises(RulesError, match="^ignore must be a list of the names of inputs, each as text$"):
        rules.database(ignore=value)


def test_the_statement_cannot_be_passed_over_and_the_names_must_be_names():
    with pytest.raises(RulesError, match="^the input that holds the statement cannot be ignored$"):
        rules.database(ignore=["sql"])
    with pytest.raises(RulesError, match="^the input that holds the statement cannot be ignored$"):
        rules.database(ignore=["query"], sql="query")
    rules.database(ignore=["sql"], sql="query")
    rules.database(ignore=["params"])
    with pytest.raises(RulesError, match="sql must be the name of an input, as text"):
        rules.database(sql=5)
    with pytest.raises(RulesError, match="sql must be the name of an input, as text"):
        rules.database(sql="")
    with pytest.raises(RulesError, match="params must be the name of an input, as text"):
        rules.database(params=None)
    with pytest.raises(RulesError, match="two of the input names given are the same"):
        rules.database(sql="q", params="q")


def test_the_lists_are_copied_at_setup():
    protect, functions, passed = ["payroll"], ["monthly_total"], ["timeout"]
    rule = rules.database(protect=protect, functions=functions, ignore=passed)
    protect.clear()
    functions.append("sleep")
    passed.append("database")
    asks("SELECT * FROM payroll", [PROTECTED.format("payroll")], rule)
    asks("SELECT sleep(1)", [CALL.format("sleep")], rule)
    asks(given("SELECT 1", database="prod"), [UNTOLD.format(1)], rule)
    runs(given("SELECT monthly_total(1)", timeout=5), rule)


def test_the_lists_may_be_tuples_or_sets():
    rule = rules.database(protect=("payroll",), functions={"monthly_total"})
    asks("SELECT * FROM payroll", [PROTECTED.format("payroll")], rule)
    runs("SELECT monthly_total(1)", rule)
    rule = rules.database(protect=frozenset({"payroll"}), functions=("monthly_total",))
    asks("SELECT * FROM payroll", [PROTECTED.format("payroll")], rule)
    runs("SELECT monthly_total(1)", rule)


# ---- what the rule says about itself ----


def test_the_settings_are_kept_and_named():
    rule = rules.database(protect=["Payroll", "api_keys"], functions=["reports.Total", "monthly_total"], live=True, ignore=["timeout", "label"], sql="query", params="args")
    assert rule.kind == "database"
    assert rule.settings() == {
        "protect": ["api_keys", "payroll"],
        "functions": ["monthly_total", "reports.total"],
        "live": True,
        "ignore": ["label", "timeout"],
        "fields": {"sql": "query", "params": "args"},
    }
    assert rules.database().settings() == {"protect": [], "functions": [], "live": False, "ignore": [], "fields": {"sql": "sql", "params": "params"}}


def test_the_name_of_the_rule_changes_with_any_setting():
    def name(**settings):
        return make(**settings).__qualname__

    assert name().startswith("kettle.rules.database:")
    assert name() == name()
    assert name() == name(protect=["api_keys", "PAYROLL"])
    changed = [
        name(protect=["payroll"]),
        name(functions=[]),
        name(live=True),
        name(ignore=["timeout"]),
        name(sql="query"),
        name(params="args"),
    ]
    assert len(set(changed + [name()])) == 7


def test_the_rule_cannot_be_changed_after_setup():
    rule = make(live=True)
    for name, value in (("_protect", frozenset()), ("_functions", frozenset({"sleep"})), ("_live", False), ("_ignored", frozenset({"database"})), ("kind", "x")):
        with pytest.raises(Exception):
            setattr(rule, name, value)
    asks("SELECT * FROM payroll", [PROTECTED.format("payroll")], rule)
    never("DROP TABLE t", [DROPS], rule)


def test_database_is_one_of_the_rules_the_package_names():
    assert "database" in rules.__all__
    assert rules.__all__.index("database") == rules.__all__.index("calendar") + 1


# ---- with the real checkpoint ----


def test_with_the_checkpoint_a_read_runs_a_change_is_held_and_a_drop_is_refused(tmp_path):
    ran = []

    def run_sql(sql, params=None):
        ran.append(sql)
        return "done"

    rule = make(live=True)
    checkpoint = Checkpoint(str(tmp_path / "kettle.db"))
    try:
        checkpoint.tool("run_sql", run_sql, level=rule, describe=rule.why, watch=["sql"])
        assert checkpoint.gate.request("run_sql", {"sql": "SELECT name FROM customers WHERE id = ?", "params": [7]}).status == RAN
        assert checkpoint.gate.request("run_sql", {"sql": "SELECT count(*) FROM orders"}).status == RAN
        assert ran == ["SELECT name FROM customers WHERE id = ?", "SELECT count(*) FROM orders"]
        assert checkpoint.gate.request("run_sql", {"sql": "UPDATE customers SET name = 'x' WHERE id = 7"}).status == HELD
        assert checkpoint.gate.request("run_sql", {"sql": "SELECT * FROM payroll"}).status == HELD
        assert checkpoint.gate.request("run_sql", {"sql": "SELECT pg_sleep(60)"}).status == HELD
        assert checkpoint.gate.request("run_sql", {"sql": "DROP TABLE customers"}).status == REFUSED
        assert checkpoint.gate.request("run_sql", {"sql": "DELETE FROM customers"}).status == REFUSED
        assert len(ran) == 2
    finally:
        checkpoint.close()
