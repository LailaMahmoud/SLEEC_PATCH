import os
import sqlite3
from datetime import datetime


DB_PATH = os.path.join("instance", "sleec_patch_results.db")


class PhilosopherReviewStore:

    def __init__(self):
        os.makedirs("instance", exist_ok=True)
        self.create_table()

    def connect(self):
        return sqlite3.connect(DB_PATH)

    def create_table(self):
        conn = self.connect()
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS philosopher_patch_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            use_case TEXT,
            issue_id TEXT,
            issue_type TEXT,
            patch_id TEXT,
            operation TEXT,
            original_rule TEXT,
            proposed_rule TEXT,
            explanation TEXT,
            reviewer TEXT,
            decision TEXT,
            comment TEXT,
            timestamp TEXT
        )
        """)

        conn.commit()
        conn.close()

    def save_review(self, row):
        conn = self.connect()
        cur = conn.cursor()

        cur.execute("""
        INSERT INTO philosopher_patch_reviews (
            use_case,
            issue_id,
            issue_type,
            patch_id,
            operation,
            original_rule,
            proposed_rule,
            explanation,
            reviewer,
            decision,
            comment,
            timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row.get("use_case", ""),
            row.get("issue_id", ""),
            row.get("issue_type", ""),
            row.get("patch_id", ""),
            row.get("operation", ""),
            row.get("original_rule", ""),
            row.get("proposed_rule", ""),
            row.get("explanation", ""),
            row.get("reviewer", ""),
            row.get("decision", ""),
            row.get("comment", ""),
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

    def all_reviews(self):
        conn = self.connect()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        rows = cur.execute("""
            SELECT *
            FROM philosopher_patch_reviews
            ORDER BY timestamp DESC
        """).fetchall()

        conn.close()
        return [dict(r) for r in rows]

    def summary(self):
        rows = self.all_reviews()

        total = len(rows)
        accepted = len([r for r in rows if r.get("decision") == "accept"])
        rejected = len([r for r in rows if r.get("decision") == "reject"])

        by_operation = {}

        for r in rows:
            op = r.get("operation", "unknown")
            by_operation.setdefault(op, {
                "total": 0,
                "accepted": 0,
                "rejected": 0,
                "acceptance_rate": 0
            })

            by_operation[op]["total"] += 1

            if r.get("decision") == "accept":
                by_operation[op]["accepted"] += 1

            if r.get("decision") == "reject":
                by_operation[op]["rejected"] += 1

        for op, v in by_operation.items():
            v["acceptance_rate"] = round(
                v["accepted"] / v["total"], 3
            ) if v["total"] else 0

        return {
            "total_reviews": total,
            "accepted": accepted,
            "rejected": rejected,
            "acceptance_rate": round(accepted / total, 3) if total else 0,
            "by_operation": by_operation
        }