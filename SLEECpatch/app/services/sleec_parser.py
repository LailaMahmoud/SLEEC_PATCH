import re


class SLEECParser:
    def parse_file(self, path):
        with open(path, "r", encoding="utf-8-sig") as f:
            return self.parse_text(f.read())

    def parse_text(self, text):
        return {
            "rules": self.parse_rules(text),
            "raw_text": text
        }

    def get_block(self, text, start, end):
        m = re.search(
            rf"{start}(.*?){end}",
            text,
            re.DOTALL | re.IGNORECASE
        )
        return m.group(1) if m else ""

    def parse_rules(self, text):
        block = self.get_block(text, "rule_start", "rule_end")

        chunks = re.split(
            r"(?=^\s*Rule\d+(?:_\d+)?\s+when\s+)",
            block,
            flags=re.MULTILINE
        )

        rules = []

        for c in chunks:
            c = c.strip()
            if not c:
                continue

            rule = self.parse_rule(c)
            if rule:
                rules.append(rule)

        return rules

    def parse_rule(self, text):
        clean = re.sub(r"\s+", " ", text).strip()

        m = re.match(
            r"^(Rule\d+(?:_\d+)?)\s+when\s+(.*?)\s+then\s+(.*)$",
            clean
        )

        if not m:
            return None

        rule_id = m.group(1)
        condition = m.group(2)
        rest = m.group(3)

        action = re.split(
            r"\s+unless\s+",
            rest,
            maxsplit=1
        )[0].strip()

        defeaters = re.findall(
            r"unless\s+(.*?)(?=\s+unless\s+|$)",
            rest
        )

        return {
            "id": rule_id,
            "condition": condition.strip(),
            "action": action.strip(),
            "defeaters": [d.strip() for d in defeaters],
            "raw": text
        }