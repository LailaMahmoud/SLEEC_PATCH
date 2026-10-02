"""Connect detector diagnoses to the paper's parser-backed repair operators."""
import re
from services.rule_model import parse_sleec_ast, source, rule_record
from services.evidence_repair import target_resolution, generate_repairs

SEMANTIC = {
    'conflicts': ['event_specialization', 'measure_specialization', 'response_refinement'],
    'situational_conflicts': ['event_specialization', 'measure_specialization', 'response_refinement'],
    'redundancies': ['event_specialization', 'measure_specialization', 'response_refinement'],
    'concerns': ['new_rule_generation'],
    'purpose_blocking': ['response_refinement'],
}


def diagnosis_for(text, kind, finding):
    if isinstance(finding, dict):
        return finding
    model = parse_sleec_ast(text)
    finding = str(finding)
    def mentioned(name):
        return re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', finding)
    ids = [r.name for r in model.ruleBlock.rules if mentioned(r.name)]
    # Source identifier is the diagnosed subject, before supporting proof IDs.
    ids.sort(key=lambda name: mentioned(name).start())
    result = {'affected_rule_ids': ids, 'description': finding, 'trace': []}
    if kind == 'redundancies':
        result['source_id'] = ids[0] if ids else None
    else:
        block = getattr(model, 'concernBlock' if kind == 'concerns' else 'purposeBlock', None)
        nodes = getattr(block, 'concerns' if kind == 'concerns' else 'purposes', [])
        matches = [n for n in nodes if mentioned(n.name) or source(text, n) in finding]
        if len(matches) == 1: result['source_id'] = matches[0].name
    return result


def plan(text, kind, finding, description=''):
    from services.repair_operator_selector import RepairOperatorSelector
    model = parse_sleec_ast(text)
    diagnosis = diagnosis_for(text, kind, finding)
    resolution = target_resolution(text, kind, diagnosis)
    resolution['semantic_rule_ids'] = list(dict.fromkeys(resolution['rule_ids'] + diagnosis.get('affected_rule_ids', [])))
    targets = [r for r in model.ruleBlock.rules if r.name in resolution['semantic_rule_ids']]
    operators = RepairOperatorSelector.BASE_DETERMINISTIC_OPERATORS.get(kind, [])
    candidates = generate_repairs(text, kind, diagnosis, operators)
    deterministic = list(dict.fromkeys(p['operation'] for p in candidates))
    llm = []
    for op in SEMANTIC.get(kind, []):
        if op == 'new_rule_generation':
            applicable = bool(resolution.get('addition_scope'))
        elif op == 'event_specialization':
            applicable = bool(targets and any(r.trigger for r in targets))
        elif op == 'measure_specialization':
            # A new environmental distinction can be supplied by the system
            # description even if no measure is currently present (paper r3/r4).
            applicable = bool(targets and (description or any(r.condition or r.response.defeater for r in targets)))
        else:
            applicable = bool(targets and any(r.response.occ for r in targets))
        if applicable: llm.append(op)
    return {'deterministic': deterministic, 'llm': llm, 'diagnosis': diagnosis,
            'target_resolution': resolution, 'candidates': candidates,
            'applicability': {op: {'is_applicable': op in deterministic+llm,
                'reason': 'Selected from the implicated rule elements and source requirement; semantic distinctions still require evidence and formal verification.'}
                for op in list(operators)+SEMANTIC.get(kind, [])}}
