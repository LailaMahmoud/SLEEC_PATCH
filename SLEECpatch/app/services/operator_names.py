"""Read compatibility for historical experiments; new outputs use canonical names."""
import json

ALIASES = {
    'capability_refinement': 'response_refinement',
    'purpose_capability_refinement': 'response_refinement',
    'purpose_response_refinement': 'response_refinement',
    'conflict_event_specialization': 'event_specialization',
    'redundancy_event_specialization': 'event_specialization',
    'conflict_measure_specialization': 'measure_specialization',
    'redundancy_measure_specialization': 'measure_specialization',
    'concern_new_rule_generation': 'new_rule_generation',
}


def normalize_operators(value):
    if isinstance(value, list): return [normalize_operators(v) for v in value]
    if isinstance(value, dict):
        result = {}
        for key, val in value.items():
            if key.endswith('_json') and isinstance(val, str):
                try: val = json.dumps(normalize_operators(json.loads(val)))
                except (ValueError, TypeError): pass
            result[ALIASES.get(key, key)] = normalize_operators(val)
        if result.get('operation_label') in {'Refine capability', 'Capability refinement'}:
            result['operation_label'] = 'Response refinement'
        return result
    if isinstance(value, str): return ALIASES.get(value, value)
    return value
