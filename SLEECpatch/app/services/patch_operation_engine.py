import copy
import re


class PatchOperationEngine:
    """Apply selected SLEEC patches to rule dictionaries."""

    def apply_patches(self, rules, patches):
        updated = [self._to_rule_dict(r) for r in copy.deepcopy(rules or [])]

        for patch in patches or []:
            if isinstance(patch, dict):
                updated = self.apply_patch(updated, patch)

        return updated

    def apply_patch(self, rules, patch):
        operation = str(patch.get("operation") or "").strip().lower()
        target_rule_id = str(
            patch.get("target_rule_id")
            or patch.get("rule_id")
            or ""
        ).strip()

        proposed_text = str(
            patch.get("proposed_rule")
            or patch.get("resolution_patch")
            or ""
        ).strip()

        if operation == "rule_removal":
            return [
                r for r in rules
                if self._rule_id(r).lower() != target_rule_id.lower()
            ]

        parsed = self._parse_rule_texts(proposed_text)
        if not parsed:
            return rules

        if operation == "new_rule_generation":
            return self._append_unique(rules, parsed)

        if operation == "rule_decomposition":
            remaining = [
                r for r in rules
                if self._rule_id(r).lower() != target_rule_id.lower()
            ]
            return self._append_unique(remaining, parsed)

        if target_rule_id:
            return self._replace_target(rules, target_rule_id, parsed)

        return self._append_unique(rules, parsed)

    def _replace_target(self, rules, target_rule_id, replacements):
        result = []
        replaced = False

        for rule in rules:
            if self._rule_id(rule).lower() == target_rule_id.lower():
                if not replaced:
                    result.extend(copy.deepcopy(replacements))
                    replaced = True
            else:
                result.append(rule)

        if not replaced:
            result = self._append_unique(result, replacements)

        return result

    def _append_unique(self, rules, additions):
        result = list(rules)
        existing_ids = {
            self._rule_id(r).lower()
            for r in result
            if self._rule_id(r)
        }

        for rule in additions:
            rid = self._rule_id(rule)
            if not rid:
                continue

            if rid.lower() in existing_ids:
                result = [
                    rule if self._rule_id(old).lower() == rid.lower() else old
                    for old in result
                ]
            else:
                result.append(rule)
                existing_ids.add(rid.lower())

        return result

    def _rule_id(self, rule):
        if isinstance(rule, dict):
            return str(rule.get("id") or rule.get("rule_id") or "")
        return str(getattr(rule, "id", "") or "")

    def _to_rule_dict(self, rule):
        if isinstance(rule, dict):
            return {
                "id": rule.get("id") or rule.get("rule_id") or "",
                "condition": rule.get("condition", ""),
                "action": rule.get("action", ""),
                "defeater": rule.get("defeater", ""),
            }

        return {
            "id": getattr(rule, "id", ""),
            "condition": getattr(rule, "condition", ""),
            "action": getattr(rule, "action", ""),
            "defeater": getattr(rule, "defeater", ""),
        }

    def _parse_rule_texts(self, text):
        text = str(text or "").strip()
        if not text:
            return []

        header = re.compile(
            r"(?=^\\s*(?:Rule|R|r)\\d+(?:_\\d+)?\\s+when\\b)",
            flags=re.IGNORECASE | re.MULTILINE,
        )

        chunks = [c.strip() for c in header.split(text) if c.strip()]
        parsed = []

        for chunk in chunks:
            clean = re.sub(r"\\s+", " ", chunk).strip()

            match = re.match(
                r"^((?:Rule|R|r)\\d+(?:_\\d+)?)\\s+when\\s+(.+?)\\s+then\\s+(.+)$",
                clean,
                flags=re.IGNORECASE,
            )
            if not match:
                continue

            rule_id = match.group(1).strip()
            condition = match.group(2).strip()
            remainder = match.group(3).strip()

            parts = re.split(
                r"\\s+unless\\s+",
                remainder,
                maxsplit=1,
                flags=re.IGNORECASE,
            )

            action = parts[0].strip()
            defeater = parts[1].strip() if len(parts) > 1 else ""

            parsed.append({
                "id": rule_id,
                "condition": condition,
                "action": action,
                "defeater": defeater,
            })

        return parsed
