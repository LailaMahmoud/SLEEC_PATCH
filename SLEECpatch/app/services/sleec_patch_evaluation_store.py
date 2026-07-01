import json
import os
import sqlite3
import threading
import time
from datetime import datetime


REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
DB_PATH = os.environ.get(
    "SLEEC_SQLITE_PATH",
    os.path.join(REPO_ROOT, "instance", "sleec_patch_results.db")
)
DATABASE_URL = os.environ.get("DATABASE_URL", "")
REQUIRE_DATABASE_URL = os.environ.get("SLEEC_REQUIRE_DATABASE_URL", "") == "1"


class SLEECPatchEvaluationStore:

    def __init__(self):
        if REQUIRE_DATABASE_URL and not self.using_postgres():
            raise RuntimeError(
                "SLEEC_REQUIRE_DATABASE_URL=1 but DATABASE_URL is not configured for Postgres."
            )

        if not self.using_postgres():
            os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

        # Schema creation is deferred to the first DB use (see connect()) rather
        # than run here in the constructor. Connecting to Postgres during
        # import/boot made container startup block on the database; a cold or
        # distant DB then exceeded Cloudflare's container start deadline and took
        # the whole site down. Lazy init lets gunicorn bind its port immediately
        # and pay the DB round-trips on the first request instead.
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        self._schema_local = threading.local()

    def using_postgres(self):
        return DATABASE_URL.startswith(("postgres://", "postgresql://"))

    def connect(self):
        # Ensure the schema exists before handing back a connection, unless we
        # are already inside schema creation on this thread (create_tables/
        # ensure_columns call connect() themselves).
        if not self._schema_ready and not getattr(
            self._schema_local, "in_schema", False
        ):
            self._ensure_schema()
        return self._open_connection()

    def _ensure_schema(self):
        with self._schema_lock:
            if self._schema_ready:
                return
            self._schema_local.in_schema = True
            try:
                self._create_schema()
                self._schema_ready = True
            finally:
                self._schema_local.in_schema = False

    def _create_schema(self):
        self.create_tables()
        self.ensure_columns()

    def _open_connection(self):
        if self.using_postgres():
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError(
                    "DATABASE_URL points to Postgres, but psycopg is not installed."
                ) from exc

            last_error = None

            for _ in range(3):
                try:
                    return psycopg.connect(
                        DATABASE_URL,
                        row_factory=dict_row,
                        connect_timeout=10
                    )
                except psycopg.OperationalError as exc:
                    last_error = exc
                    time.sleep(0.35)

            raise last_error

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def placeholder_sql(self, query):
        if self.using_postgres():
            return query.replace("?", "%s")
        return query

    def execute(self, cur, query, params=()):
        return cur.execute(self.placeholder_sql(query), params)

    def id_column(self):
        if self.using_postgres():
            return "SERIAL PRIMARY KEY"
        return "INTEGER PRIMARY KEY AUTOINCREMENT"

    def rows_to_dicts(self, rows):
        return [dict(r) for r in rows]

    def to_json(self, value):
        return json.dumps(value, default=str, ensure_ascii=False)

    def persistence_status(self):
        conn = self.connect()
        cur = conn.cursor()

        total = self.execute(cur, """
            SELECT COUNT(*) AS count
            FROM sleec_patch_results
        """).fetchone()["count"]

        llm_total = self.execute(cur, """
            SELECT COUNT(*) AS count
            FROM sleec_patch_results
            WHERE source = ?
        """, ("llm",)).fetchone()["count"]

        pending_llm = self.execute(cur, """
            SELECT COUNT(*) AS count
            FROM sleec_patch_results
            WHERE source = ?
            AND (philosopher_decision IS NULL OR philosopher_decision = '')
        """, ("llm",)).fetchone()["count"]

        verified_llm = self.execute(cur, """
            SELECT COUNT(*) AS count
            FROM sleec_patch_results
            WHERE source = ?
            AND verified = 1
        """, ("llm",)).fetchone()["count"]

        latest_row = self.execute(cur, """
            SELECT timestamp
            FROM sleec_patch_results
            ORDER BY timestamp DESC
            LIMIT 1
        """).fetchone()

        conn.close()

        return {
            "backend": "postgres" if self.using_postgres() else "sqlite",
            "database_url_configured": bool(DATABASE_URL),
            "database_url_required": REQUIRE_DATABASE_URL,
            "sqlite_path": "" if self.using_postgres() else DB_PATH,
            "total_patch_rows": total,
            "llm_patch_rows": llm_total,
            "pending_llm_review_rows": pending_llm,
            "verified_llm_rows": verified_llm,
            "latest_patch_timestamp": latest_row["timestamp"] if latest_row else ""
        }

    def create_tables(self):
        conn = self.connect()
        cur = conn.cursor()
        id_column = self.id_column()

        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS sleec_patch_results (
            id {id_column},

            use_case TEXT,
            issue_id TEXT,
            issue_type TEXT,
            selected_issue TEXT,

            attempts INTEGER,
            failed_patch_count INTEGER,
            verified_patch_count INTEGER,

            generation_time_seconds REAL,
            validation_time_seconds REAL,
            total_time_seconds REAL,

            patch_id TEXT,
            operation TEXT,
            source TEXT,
            target_rule_id TEXT,
            original_rule TEXT,
            proposed_rule TEXT,
            natural_language_explanation TEXT,
            patched_sleec TEXT,

            rules_modified INTEGER,
            rules_added INTEGER,
            rules_deleted INTEGER,
            defeaters_added INTEGER,
            conditions_refined INTEGER,
            actions_refined INTEGER,
            capabilities_refined INTEGER,

            verified INTEGER,
            expert_similarity REAL,
            expert_match INTEGER,
            requires_social_scientist_review INTEGER,

            philosopher_decision TEXT,
            philosopher_comments TEXT,
            review_timestamp TEXT,

            timestamp TEXT
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS sleec_patch_pipeline_runs (
            run_id TEXT PRIMARY KEY,
            use_case TEXT,
            issue_id TEXT,
            issue_type TEXT,
            selected_issue TEXT,
            max_attempts INTEGER,
            attempts INTEGER,
            successful INTEGER,
            failed_patch_count INTEGER,
            verified_patch_count INTEGER,
            generation_time_seconds REAL,
            validation_time_seconds REAL,
            total_time_seconds REAL,
            repair_operators_json TEXT,
            original_issue_count INTEGER,
            original_structured_json TEXT,
            generated_file_path TEXT,
            timestamp TEXT
        )
        """)

        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS sleec_patch_candidates (
            id {id_column},
            run_id TEXT,
            use_case TEXT,
            issue_id TEXT,
            issue_type TEXT,
            attempt INTEGER,
            patch_id TEXT,
            source TEXT,
            operation TEXT,
            target_rule_id TEXT,
            original_rule TEXT,
            proposed_rule TEXT,
            natural_language_explanation TEXT,
            candidate_signature TEXT,
            patch_json TEXT,
            timestamp TEXT
        )
        """)

        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS sleec_patch_verifications (
            id {id_column},
            run_id TEXT,
            use_case TEXT,
            issue_id TEXT,
            issue_type TEXT,
            attempt INTEGER,
            patch_id TEXT,
            source TEXT,
            operation TEXT,
            target_rule_id TEXT,
            verified INTEGER,
            target_fixed INTEGER,
            regression_passed INTEGER,
            failure_reason TEXT,
            verification_depth INTEGER,
            related_issue_json TEXT,
            regression_report_json TEXT,
            ranking_json TEXT,
            ranking_score REAL,
            patched_sleec TEXT,
            patch_json TEXT,
            timestamp TEXT
        )
        """)

        conn.commit()
        conn.close()

    def table_columns(self, table_name):
        conn = self.connect()
        cur = conn.cursor()

        if self.using_postgres():
            rows = cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = %s
            """, (table_name,)).fetchall()
            columns = [row["column_name"] for row in rows]
        else:
            rows = cur.execute(f"PRAGMA table_info({table_name})").fetchall()
            columns = [row["name"] for row in rows]

        conn.close()
        return columns

    def ensure_columns(self):
        existing_columns = self.table_columns("sleec_patch_results")

        required_columns = {
            "source": "TEXT",
            "target_rule_id": "TEXT",
            "original_rule": "TEXT",
            "proposed_rule": "TEXT",
            "natural_language_explanation": "TEXT",
            "patched_sleec": "TEXT",
            "philosopher_decision": "TEXT",
            "philosopher_comments": "TEXT",
            "review_timestamp": "TEXT"
        }

        conn = self.connect()
        cur = conn.cursor()

        for col, col_type in required_columns.items():
            if col not in existing_columns:
                cur.execute(
                    f"ALTER TABLE sleec_patch_results ADD COLUMN {col} {col_type}"
                )

        conn.commit()
        conn.close()

    def save_result(self, row):
        conn = self.connect()
        cur = conn.cursor()
        timestamp = datetime.now().isoformat()

        values = (
            row.get("use_case", ""),
            row.get("issue_id", ""),
            row.get("issue_type", ""),
            str(row.get("selected_issue", "")),

            row.get("attempts", 0),
            row.get("failed_patch_count", 0),
            row.get("verified_patch_count", 0),

            row.get("generation_time_seconds", 0),
            row.get("validation_time_seconds", 0),
            row.get("total_time_seconds", 0),

            row.get("patch_id", ""),
            row.get("operation", ""),
            row.get("source", ""),

            row.get("target_rule_id", ""),
            row.get("original_rule", ""),
            row.get("proposed_rule", ""),
            row.get("natural_language_explanation", ""),
            row.get("patched_sleec", ""),

            row.get("rules_modified", 0),
            row.get("rules_added", 0),
            row.get("rules_deleted", 0),
            row.get("defeaters_added", 0),
            row.get("conditions_refined", 0),
            row.get("actions_refined", 0),
            row.get("capabilities_refined", 0),

            1 if row.get("verified") else 0,
            row.get("expert_similarity", 0),
            1 if row.get("expert_match") else 0,
            1 if row.get("requires_social_scientist_review") else 0,

            row.get("philosopher_decision", ""),
            row.get("philosopher_comments", ""),
            row.get("review_timestamp", ""),

            timestamp
        )

        result_id = row.get("id") or row.get("result_id")

        if result_id:
            self.execute(cur, """
            UPDATE sleec_patch_results
            SET use_case = ?,
                issue_id = ?,
                issue_type = ?,
                selected_issue = ?,
                attempts = ?,
                failed_patch_count = ?,
                verified_patch_count = ?,
                generation_time_seconds = ?,
                validation_time_seconds = ?,
                total_time_seconds = ?,
                patch_id = ?,
                operation = ?,
                source = ?,
                target_rule_id = ?,
                original_rule = ?,
                proposed_rule = ?,
                natural_language_explanation = ?,
                patched_sleec = ?,
                rules_modified = ?,
                rules_added = ?,
                rules_deleted = ?,
                defeaters_added = ?,
                conditions_refined = ?,
                actions_refined = ?,
                capabilities_refined = ?,
                verified = ?,
                expert_similarity = ?,
                expert_match = ?,
                requires_social_scientist_review = ?,
                philosopher_decision = COALESCE(NULLIF(philosopher_decision, ''), ?),
                philosopher_comments = COALESCE(NULLIF(philosopher_comments, ''), ?),
                review_timestamp = COALESCE(NULLIF(review_timestamp, ''), ?),
                timestamp = ?
            WHERE id = ?
            """, values + (result_id,))

            conn.commit()
            conn.close()
            return result_id

        insert_sql = """
        INSERT INTO sleec_patch_results (
            use_case,
            issue_id,
            issue_type,
            selected_issue,

            attempts,
            failed_patch_count,
            verified_patch_count,

            generation_time_seconds,
            validation_time_seconds,
            total_time_seconds,

            patch_id,
            operation,
            source,
            target_rule_id,
            original_rule,
            proposed_rule,
            natural_language_explanation,
            patched_sleec,

            rules_modified,
            rules_added,
            rules_deleted,
            defeaters_added,
            conditions_refined,
            actions_refined,
            capabilities_refined,

            verified,
            expert_similarity,
            expert_match,
            requires_social_scientist_review,

            philosopher_decision,
            philosopher_comments,
            review_timestamp,

            timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        if self.using_postgres():
            insert_sql += "\n        RETURNING id"

        inserted = self.execute(cur, insert_sql, values)
        inserted_id = None

        if self.using_postgres():
            inserted_id = inserted.fetchone()["id"]
        else:
            inserted_id = cur.lastrowid

        conn.commit()
        conn.close()
        return inserted_id

    def save_pipeline_run(self, row):
        conn = self.connect()
        cur = conn.cursor()

        if self.using_postgres():
            query = """
            INSERT INTO sleec_patch_pipeline_runs (
                run_id,
                use_case,
                issue_id,
                issue_type,
                selected_issue,
                max_attempts,
                attempts,
                successful,
                failed_patch_count,
                verified_patch_count,
                generation_time_seconds,
                validation_time_seconds,
                total_time_seconds,
                repair_operators_json,
                original_issue_count,
                original_structured_json,
                generated_file_path,
                timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (run_id) DO UPDATE SET
                use_case = EXCLUDED.use_case,
                issue_id = EXCLUDED.issue_id,
                issue_type = EXCLUDED.issue_type,
                selected_issue = EXCLUDED.selected_issue,
                max_attempts = EXCLUDED.max_attempts,
                attempts = EXCLUDED.attempts,
                successful = EXCLUDED.successful,
                failed_patch_count = EXCLUDED.failed_patch_count,
                verified_patch_count = EXCLUDED.verified_patch_count,
                generation_time_seconds = EXCLUDED.generation_time_seconds,
                validation_time_seconds = EXCLUDED.validation_time_seconds,
                total_time_seconds = EXCLUDED.total_time_seconds,
                repair_operators_json = EXCLUDED.repair_operators_json,
                original_issue_count = EXCLUDED.original_issue_count,
                original_structured_json = EXCLUDED.original_structured_json,
                generated_file_path = EXCLUDED.generated_file_path,
                timestamp = EXCLUDED.timestamp
            """
        else:
            query = """
            INSERT OR REPLACE INTO sleec_patch_pipeline_runs (
                run_id,
                use_case,
                issue_id,
                issue_type,
                selected_issue,
                max_attempts,
                attempts,
                successful,
                failed_patch_count,
                verified_patch_count,
                generation_time_seconds,
                validation_time_seconds,
                total_time_seconds,
                repair_operators_json,
                original_issue_count,
                original_structured_json,
                generated_file_path,
                timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

        self.execute(cur, query, (
            row.get("run_id", ""),
            row.get("use_case", ""),
            row.get("issue_id", ""),
            row.get("issue_type", ""),
            str(row.get("selected_issue", "")),
            row.get("max_attempts", 0),
            row.get("attempts", 0),
            1 if row.get("successful") else 0,
            row.get("failed_patch_count", 0),
            row.get("verified_patch_count", 0),
            row.get("generation_time_seconds", 0),
            row.get("validation_time_seconds", 0),
            row.get("total_time_seconds", 0),
            self.to_json(row.get("repair_operators", {})),
            row.get("original_issue_count", 0),
            self.to_json(row.get("original_structured", {})),
            row.get("generated_file_path", ""),
            row.get("timestamp", datetime.now().isoformat())
        ))

        conn.commit()
        conn.close()

    def save_patch_candidate(self, row):
        conn = self.connect()
        cur = conn.cursor()
        patch = row.get("patch", {})

        self.execute(cur, """
        INSERT INTO sleec_patch_candidates (
            run_id,
            use_case,
            issue_id,
            issue_type,
            attempt,
            patch_id,
            source,
            operation,
            target_rule_id,
            original_rule,
            proposed_rule,
            natural_language_explanation,
            candidate_signature,
            patch_json,
            timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row.get("run_id", ""),
            row.get("use_case", ""),
            row.get("issue_id", ""),
            row.get("issue_type", ""),
            row.get("attempt", 0),
            patch.get("patch_id", patch.get("id", "")),
            patch.get("source", ""),
            patch.get("operation", ""),
            patch.get("target_rule_id", ""),
            patch.get("original_rule", ""),
            patch.get("proposed_rule", ""),
            patch.get("natural_language_explanation", patch.get("explanation", "")),
            row.get("candidate_signature", ""),
            self.to_json(patch),
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

    def save_patch_verification(self, row):
        conn = self.connect()
        cur = conn.cursor()
        patch = row.get("patch", {})

        self.execute(cur, """
        INSERT INTO sleec_patch_verifications (
            run_id,
            use_case,
            issue_id,
            issue_type,
            attempt,
            patch_id,
            source,
            operation,
            target_rule_id,
            verified,
            target_fixed,
            regression_passed,
            failure_reason,
            verification_depth,
            related_issue_json,
            regression_report_json,
            ranking_json,
            ranking_score,
            patched_sleec,
            patch_json,
            timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row.get("run_id", ""),
            row.get("use_case", ""),
            row.get("issue_id", ""),
            row.get("issue_type", ""),
            row.get("attempt", 0),
            patch.get("patch_id", patch.get("id", "")),
            patch.get("source", ""),
            patch.get("operation", ""),
            patch.get("target_rule_id", ""),
            1 if patch.get("verified") else 0,
            1 if patch.get("target_fixed") else 0,
            1 if patch.get("regression_passed") else 0,
            patch.get("failure_reason", ""),
            patch.get("verification_depth", 0),
            self.to_json(patch.get("related_issue", {})),
            self.to_json(patch.get("regression_report", {})),
            self.to_json(patch.get("ranking", {})),
            patch.get("ranking_score", 0),
            patch.get("patched_sleec", ""),
            self.to_json(patch),
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

    def summary(self):
        conn = self.connect()
        cur = conn.cursor()

        rows = self.execute(cur, """
        SELECT
            use_case,
            COUNT(*) AS total_records,
            SUM(verified) AS verified_patches,
            AVG(attempts) AS avg_attempts,
            AVG(total_time_seconds) AS avg_total_time,
            AVG(generation_time_seconds) AS avg_generation_time,
            AVG(validation_time_seconds) AS avg_validation_time,
            SUM(rules_modified) AS rules_modified,
            SUM(rules_added) AS rules_added,
            SUM(rules_deleted) AS rules_deleted,
            SUM(defeaters_added) AS defeaters_added,
            SUM(conditions_refined) AS conditions_refined,
            SUM(actions_refined) AS actions_refined,
            SUM(capabilities_refined) AS capabilities_refined,
            AVG(expert_similarity) AS avg_expert_similarity,
            SUM(requires_social_scientist_review) AS social_review_needed
        FROM sleec_patch_results
        GROUP BY use_case
        """).fetchall()

        conn.close()
        return self.rows_to_dicts(rows)

    def result_columns(self, include_patched_sleec=True):
        columns = [
            "id",
            "use_case",
            "issue_id",
            "issue_type",
            "attempts",
            "total_time_seconds",
            "patch_id",
            "operation",
            "source",
            "target_rule_id",
            "original_rule",
            "proposed_rule",
            "natural_language_explanation",
            "rules_modified",
            "rules_added",
            "rules_deleted",
            "defeaters_added",
            "conditions_refined",
            "actions_refined",
            "capabilities_refined",
            "verified",
            "expert_similarity",
            "expert_match",
            "requires_social_scientist_review",
            "philosopher_decision",
            "philosopher_comments",
            "review_timestamp",
            "timestamp"
        ]

        if include_patched_sleec:
            columns.insert(13, "patched_sleec")

        return columns

    def fetch_results(
        self,
        where_clause="",
        params=(),
        include_patched_sleec=True,
        order_by="timestamp DESC"
    ):
        conn = self.connect()
        cur = conn.cursor()
        columns = ",\n            ".join(
            self.result_columns(include_patched_sleec)
        )

        query = f"""
        SELECT
            {columns}
        FROM sleec_patch_results
        """

        if where_clause:
            query += f"\n        WHERE {where_clause}"

        query += f"\n        ORDER BY {order_by}"

        rows = self.execute(cur, query, params).fetchall()
        conn.close()
        return self.rows_to_dicts(rows)

    def all_results(self, include_patched_sleec=True):
        return self.fetch_results(
            include_patched_sleec=include_patched_sleec
        )

    def results_for_use_case(self, use_case, include_patched_sleec=True):
        return self.fetch_results(
            where_clause="use_case = ?",
            params=(use_case,),
            include_patched_sleec=include_patched_sleec
        )

    def unreviewed_semantic_patches(self, use_case=""):
        where = """
        source = ?
        AND (philosopher_decision IS NULL OR philosopher_decision = '')
        """
        params = ["llm"]

        if use_case:
            where += "\n        AND use_case = ?"
            params.append(use_case)

        return self.fetch_results(
            where_clause=where,
            params=tuple(params),
            include_patched_sleec=False,
            order_by="use_case ASC, issue_id ASC, id ASC"
        )

    def save_philosopher_decision(self, result_id, decision, comments=""):
        conn = self.connect()
        cur = conn.cursor()
        timestamp = datetime.now().isoformat()

        self.execute(cur, """
        UPDATE sleec_patch_results
        SET philosopher_decision = ?,
            philosopher_comments = ?,
            review_timestamp = ?
        WHERE id = ?
        """, (
            decision,
            comments,
            timestamp,
            result_id
        ))

        conn.commit()
        conn.close()

        return {
            "id": result_id,
            "philosopher_decision": decision,
            "philosopher_comments": comments,
            "review_timestamp": timestamp
        }

    def philosopher_review_queue(self, use_case="", include_reviewed=False):
        if include_reviewed:
            where = """
            source = ?
            """
            params = ["llm"]

            if use_case:
                where += "\n        AND use_case = ?"
                params.append(use_case)

            return self.fetch_results(
                where_clause=where,
                params=tuple(params),
                include_patched_sleec=False,
                order_by="use_case ASC, issue_id ASC, id ASC"
            )

        return self.unreviewed_semantic_patches(use_case)

    def philosopher_review_metrics(self):
        conn = self.connect()
        cur = conn.cursor()

        rows = self.execute(cur, """
        SELECT
            use_case,
            operation,
            philosopher_decision
        FROM sleec_patch_results
        WHERE source = ?
        """, ("llm",)).fetchall()

        conn.close()

        rows = self.rows_to_dicts(rows)

        def empty_bucket():
            return {
                "total": 0,
                "accepted": 0,
                "rejected": 0,
                "pending": 0,
                "acceptance_rate": 0
            }

        overall = empty_bucket()
        by_use_case = {}
        by_operation = {}

        for row in rows:
            decision = str(row.get("philosopher_decision") or "").lower()
            use_case = row.get("use_case") or "Unknown"
            operation = row.get("operation") or "unknown"

            buckets = [
                overall,
                by_use_case.setdefault(use_case, empty_bucket()),
                by_operation.setdefault(operation, empty_bucket())
            ]

            for bucket in buckets:
                bucket["total"] += 1

                if decision == "accepted":
                    bucket["accepted"] += 1
                elif decision == "rejected":
                    bucket["rejected"] += 1
                else:
                    bucket["pending"] += 1

        for bucket in [overall, *by_use_case.values(), *by_operation.values()]:
            reviewed = bucket["accepted"] + bucket["rejected"]
            bucket["acceptance_rate"] = round(
                bucket["accepted"] / reviewed,
                3
            ) if reviewed else 0

        return {
            "overall": overall,
            "by_use_case": by_use_case,
            "by_operation": by_operation
        }

    def pipeline_runs(self, use_case=""):
        conn = self.connect()
        cur = conn.cursor()

        query = """
        SELECT *
        FROM sleec_patch_pipeline_runs
        """
        params = ()

        if use_case:
            query += "\n        WHERE use_case = ?"
            params = (use_case,)

        query += "\n        ORDER BY timestamp DESC"

        rows = self.execute(cur, query, params).fetchall()
        conn.close()
        return self.rows_to_dicts(rows)

    def patch_candidates(self, run_id=""):
        conn = self.connect()
        cur = conn.cursor()

        query = """
        SELECT *
        FROM sleec_patch_candidates
        """
        params = ()

        if run_id:
            query += "\n        WHERE run_id = ?"
            params = (run_id,)

        query += "\n        ORDER BY timestamp DESC, id DESC"

        rows = self.execute(cur, query, params).fetchall()
        conn.close()
        return self.rows_to_dicts(rows)

    def patch_verifications(self, run_id="", include_patched_sleec=False):
        conn = self.connect()
        cur = conn.cursor()
        patched_sleec_column = "patched_sleec," if include_patched_sleec else ""

        query = f"""
        SELECT
            id,
            run_id,
            use_case,
            issue_id,
            issue_type,
            attempt,
            patch_id,
            source,
            operation,
            target_rule_id,
            verified,
            target_fixed,
            regression_passed,
            failure_reason,
            verification_depth,
            related_issue_json,
            regression_report_json,
            ranking_json,
            ranking_score,
            {patched_sleec_column}
            patch_json,
            timestamp
        FROM sleec_patch_verifications
        """
        params = ()

        if run_id:
            query += "\n        WHERE run_id = ?"
            params = (run_id,)

        query += "\n        ORDER BY timestamp DESC, id DESC"

        rows = self.execute(cur, query, params).fetchall()
        conn.close()
        return self.rows_to_dicts(rows)
