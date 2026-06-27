import pandas as pd
import re


class PatchComparator:
    def load_excel_rules(self, path):
        df = pd.read_excel(path)

        rules = []

        for _, row in df.iterrows():
            rules.append({
                "id": str(row.get("id", row.get("ID", ""))).strip(),
                "condition": str(row.get("condition", row.get("Condition", ""))).strip(),
                "action": str(row.get("action", row.get("Action", ""))).strip(),
                "defeater": str(row.get("defeater", row.get("Defeater", ""))).strip()
            })

        return rules

    def compare(self, expert_rules, usc_rules):
        expert = {r["id"]: r for r in expert_rules}
        usc = {r["id"]: r for r in usc_rules}

        expert_ids = set(expert.keys())
        usc_ids = set(usc.keys())

        added_rules = len(usc_ids - expert_ids)
        deleted_rules = len(expert_ids - usc_ids)

        edited_rules = 0
        exact_matches = 0

        for rid in expert_ids & usc_ids:
            e = self._norm(expert[rid])
            u = self._norm(usc[rid])

            if e == u:
                exact_matches += 1
            else:
                edited_rules += 1

        expert_defeaters = self._count_defeaters(expert_rules)
        usc_defeaters = self._count_defeaters(usc_rules)

        expert_events = self._events(expert_rules)
        usc_events = self._events(usc_rules)

        new_events = len(usc_events - expert_events)

        union = len(expert_ids | usc_ids)
        similarity = exact_matches / union if union else 0

        exact_patch_match = (
            added_rules == 0 and
            deleted_rules == 0 and
            edited_rules == 0
        )

        return {
            "exact_patch_match": exact_patch_match,
            "similarity": round(similarity, 3),
            "rules_edited": edited_rules,
            "new_rules_added": added_rules,
            "rules_deleted": deleted_rules,
            "definitions_added": max(0, len(usc_events) - len(expert_events)),
            "expert_defeaters": expert_defeaters,
            "usc_defeaters": usc_defeaters,
            "defeaters_added": max(0, usc_defeaters - expert_defeaters),
            "new_events": new_events,
            "smaller_than_expert": (
                added_rules == 0 and
                new_events == 0 and
                usc_defeaters <= expert_defeaters
            )
        }

    def _norm(self, r):
        return {
            "condition": str(r.get("condition", "")).lower().strip(),
            "action": str(r.get("action", "")).lower().strip(),
            "defeater": str(r.get("defeater", "")).lower().strip()
        }

    def _count_defeaters(self, rules):
        return sum(
            1 for r in rules
            if str(r.get("defeater", "")).strip()
            and str(r.get("defeater", "")).lower() != "nan"
        )

    def _events(self, rules):
        events = set()

        for r in rules:
            text = f'{r.get("condition", "")} {r.get("action", "")} {r.get("defeater", "")}'
            tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", text)

            for t in tokens:
                if t.lower() not in {"and", "or", "not", "when", "then", "unless"}:
                    events.add(t)

        return events