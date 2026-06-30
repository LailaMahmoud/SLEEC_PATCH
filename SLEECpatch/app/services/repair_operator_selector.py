class RepairOperatorSelector:

    DETERMINISTIC_OPERATORS = {
        "conflicts": [
            "trigger_refinement",
            "defeater_introduction",
            "rule_merging",
            "trigger_strengthening",
            "rule_decomposition"
        ],
        "situational_conflicts": [
            "trigger_refinement",
            "defeater_introduction",
            "rule_merging",
            "trigger_strengthening",
            "rule_decomposition"
        ],
        "redundancies": [
            "rule_removal",
            "defeater_propagation",
            "rule_merging"
        ],
        "concerns": [
            "defeater_introduction",
            "trigger_strengthening",
            "rule_decomposition"
        ],
        "purpose_blocking": [
            "purpose_defeater",
            "trigger_refinement",
            "trigger_strengthening",
            "rule_decomposition"
        ]
    }

    LLM_OPERATORS = {
        "conflicts": [
            "event_specialization",
            "measure_specialization",
            "capability_refinement"
        ],
        "situational_conflicts": [
            "event_specialization",
            "measure_specialization",
            "capability_refinement"
        ],
        "redundancies": [
            "event_specialization",
            "measure_specialization",
            "capability_refinement"
        ],
        "concerns": [
            "new_rule_generation",
            "capability_refinement"
        ],
        "purpose_blocking": [
            "capability_refinement",
            "new_rule_generation"
        ]
    }

    def select(self, issue_type):
        return {
            "deterministic": self.DETERMINISTIC_OPERATORS.get(issue_type, []),
            "llm": self.LLM_OPERATORS.get(issue_type, [])
        }

    def needs_llm(self, issue_type):
        return len(self.LLM_OPERATORS.get(issue_type, [])) > 0
