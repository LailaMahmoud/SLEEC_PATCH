import re


class NLSLEECMapper:
    def parse_nl_rules(self, nl_rules):
        rules = []
        mapping = {}

        for i, text in enumerate(nl_rules, start=1):
            rule_id = f"r{i}"

            pattern = r"when\s+(.+?)\s+then\s+(.+?)(?:\s+unless\s+\{?(.+?)\}?)?$"
            match = re.search(pattern, text, re.IGNORECASE)

            if match:
                condition = match.group(1).strip()
                action = match.group(2).strip()
                defeater = match.group(3).strip() if match.group(3) else ""

                rules.append({
                    "id": rule_id,
                    "nl_text": text,
                    "condition": self.to_formal(condition),
                    "action": self.to_formal(action),
                    "defeater": self.to_formal(defeater) if defeater else ""
                })

                mapping[condition] = self.to_formal(condition)
                mapping[action] = self.to_formal(action)

                if defeater:
                    mapping[defeater] = self.to_formal(defeater)

        return rules, mapping

    def to_formal(self, text):
        text = re.sub(r"[^A-Za-z0-9 ]", "", text).strip()

        if not text:
            return ""

        parts = text.split()

        return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])

    def build_sleec(self, rules):

        events = set()
        measures = set()

        for r in rules:
            condition = r.get("condition", "")
            action = r.get("action", "")
            defeater = r.get("defeater", "")

            if condition:
                events.add(condition)

            if action:
                clean_action = action.replace("not ", "").strip()
                events.add(clean_action)

            if defeater:
                measures.add(defeater)

        lines = []

        lines.append("def_start")

        for e in sorted(events):
            lines.append(f"event {e}")

        for m in sorted(measures):
            lines.append(f"measure {m}:boolean")

        lines.append("def_end")
        lines.append("")

        lines.append("rule_start")

        for r in rules:
            if r.get("defeater"):
                lines.append(
                    f'{r["id"]} when {r["condition"]} then {r["action"]} unless {{{r["defeater"]}}}'
                )
            else:
                lines.append(
                    f'{r["id"]} when {r["condition"]} then {r["action"]}'
                )

        lines.append("rule_end")

        return "\n".join(lines)
        
