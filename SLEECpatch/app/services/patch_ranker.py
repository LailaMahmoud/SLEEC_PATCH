"""Paper §3.3: ascending lexicographic modification and syntax costs."""
import re
from services.boolean_simplifier import simplify_rule
from services.candidate_status import formally_verified


class PatchRanker:
    def __init__(self, semantic_assessor=None):
        # Accepted for old callers; qualitative assessment never affects ranking.
        pass

    def rank(self, verified_patches):
        ranked = []
        for patch in verified_patches:
            if not formally_verified(patch):
                continue
            patch['ranking'] = self.score_patch(patch)
            ranked.append(patch)
        ranked.sort(key=lambda p: tuple(p['ranking']['lexicographic_key']))
        for index, patch in enumerate(ranked, 1):
            patch['rank'] = index
            # Retain a numeric persistence field; this is ordinal, not a quality score.
            patch['ranking_score'] = -index
            patch['ranking_rationale'] = ['Prefer fewer affected rules, new elements, Boolean operators, defeaters, then lower defeater nesting depth.']
        return ranked

    def split_proposed_rules(self, text):
        starts = list(re.finditer(r'(?<!\w)[A-Za-z_]\w*\s+when\b', str(text)))
        return [str(text)[m.start():(starts[i+1].start() if i+1 < len(starts) else len(str(text)))].strip() for i,m in enumerate(starts)]

    def score_patch(self, patch):
        before = simplify_rule(str(patch.get('original_rule', '')))
        after = simplify_rule(str(patch.get('proposed_rule', '')))
        # Derive affected source rules from the original AST: legacy UI
        # normalization may retain only the primary rule's original text.
        addition = patch.get('operation') in {'new_rule_generation', 'add', 'add_rule'}
        if addition:
            before = ''
        if not addition and patch.get('original_sleec') and patch.get('target_rule_id'):
            from services.rule_model import rules_from_text
            baseline = {r['id']:r['raw'] for r in rules_from_text(patch['original_sleec'])}
            ids = list(dict.fromkeys([patch['target_rule_id']] + patch.get('removed_rule_ids', [])
                                    + list(patch.get('additional_rule_edits', {}))))
            before = '\n'.join(baseline[rid] for rid in ids)
        if patch.get('additional_rule_edits'):
            after += '\n' + '\n'.join(patch['additional_rule_edits'].values())
        before, after = simplify_rule(before), simplify_rule(after)
        old = {r.split()[0]: r for r in self.split_proposed_rules(before)}
        new = {r.split()[0]: r for r in self.split_proposed_rules(after)}
        added = len(new.keys()-old.keys())
        removed = len(old.keys()-new.keys())
        edited = sum(old[k] != new[k] for k in old.keys() & new.keys())
        affected = added+removed+edited
        declarations = patch.get('declaration_text', '')
        new_events = len(set(re.findall(r'\bevent\s+(\w+)', declarations)))
        new_measures = len(set(re.findall(r'\bmeasure\s+(\w+)', declarations)))
        if not declarations and patch.get('missing_element'):
            new_events = int(patch.get('operation') in {'event_specialization','response_refinement'})
            new_measures = int(patch.get('operation') == 'measure_specialization')
        count_defeaters = lambda s: len(re.findall(r'\bunless\b', s))
        defeaters = count_defeaters(after)
        introduced_defeaters = max(0, defeaters-count_defeaters(before))
        # Only trigger and exception conditions, never negative responses.
        def bool_count(text):
            conditions = re.findall(r'\bwhen\s+(.*?)\s+then\b', text, re.S)
            conditions += re.findall(r'\bunless\s+(.*?)(?=\s+then\b|\s+unless\b|\n|$)', text)
            return sum(len(re.findall(r'\b(?:and|or|not)\b', c)) for c in conditions)
        complexity = max(0, bool_count(after)-bool_count(before))
        # InnerResponse braces define nesting; measure braces do not.
        depth = maximum = 0
        for token in re.findall(r'\{[^{}]*\}|\{|\}|\bunless\b', re.sub(r'\{\s*\w+\s*\}', '', after)):
            if token == '{': depth += 1
            elif token == '}': depth = max(0,depth-1)
            elif token == 'unless': maximum=max(maximum,depth+1)
            elif token.startswith('{') and 'unless' in token: maximum=max(maximum,depth+2)
        elements = new_events+new_measures+introduced_defeaters
        return {'rules_affected': affected, 'rules_edited': edited, 'rules_added': added,
                'rules_removed': removed, 'new_elements': elements, 'new_events': new_events,
                'new_measures': new_measures, 'new_defeaters': introduced_defeaters,
                'boolean_complexity': complexity, 'defeaters': defeaters, 'defeater_depth': maximum,
                'lexicographic_key': [affected,elements,complexity,defeaters,maximum],
                'method': 'lexicographic', 'total_score': 0}
