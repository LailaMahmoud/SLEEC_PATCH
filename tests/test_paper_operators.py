"""Paper examples and operator boundaries, with real SLEEC parser round trips."""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'SLEECpatch/app'), str(Path(__file__).resolve().parents[1])]
from services.boolean_simplifier import simplify_expression
from services.paper_repairs import plan
from services.evidence_repair import generate_repairs
from services.rule_model import parse_sleec_ast, apply_rule_patch, source, expression_value
from services.structured_semantic_edit import materialize_semantic_edit
from services.patch_ranker import PatchRanker
from services.operator_names import normalize_operators


def spec(rules, concern=''):
    return '''def_start
event SmokeDetectorAlarm
event HumanOnFloor
event CallEmergencyServices
event NotifyUserRisk
measure humanAssents:boolean
measure userPresent:boolean
measure userDisablesAlarm:boolean
measure userUnconscious:boolean
def_end
rule_start
'''+rules+'\nrule_end\n'+('concern_start\nc1 when SmokeDetectorAlarm and (not {userDisablesAlarm}) then not CallEmergencyServices within 3 minutes\nconcern_end\n' if concern else '')


class PaperOperators(unittest.TestCase):
    def roundtrip(self, text, candidate):
        updated = apply_rule_patch(text, candidate)
        return parse_sleec_ast(updated), updated

    def test_boolean_identities_and_precedence(self):
        for expr, expected in [('not (not {humanAssents})','{humanAssents}'),('not not {humanAssents}','{humanAssents}'),
            ('{humanAssents} and true','{humanAssents}'),('{humanAssents} or false','{humanAssents}'),
            ('{humanAssents} and {humanAssents}','{humanAssents}'),('{humanAssents} or {humanAssents}','{humanAssents}')]:
            self.assertEqual(simplify_expression(expr), expected)
        self.assertEqual(simplify_expression('{humanAssents} or {userPresent} and {userDisablesAlarm}'),
                         '({humanAssents} or ({userPresent} and {userDisablesAlarm}))')

    def test_conflict_refinement_simplifies_double_negation(self):
        text=spec('r1 when SmokeDetectorAlarm then CallEmergencyServices within 5 minutes\nr2 when HumanOnFloor and (not {humanAssents}) then not CallEmergencyServices within 500 seconds')
        result=plan(text,'conflicts','r1 conflicts with r2')
        candidate=next(p for p in result['candidates'] if p['operation']=='trigger_refinement' and p['target_rule_id']=='r1')
        self.assertIn('and {humanAssents} then',candidate['proposed_rule'])
        self.roundtrip(text,candidate)
        self.assertNotIn('rule_merging',result['deterministic'])
        self.assertEqual(set(result['llm']),{'event_specialization','measure_specialization','response_refinement'})

    def test_redundancy_alternatives_do_not_remove_support(self):
        text=spec('r3 when SmokeDetectorAlarm then CallEmergencyServices within 7 minutes unless {userPresent} then NotifyUserRisk\nr4 when SmokeDetectorAlarm then NotifyUserRisk within 2 minutes\nr5 when NotifyUserRisk then CallEmergencyServices within 5 minutes')
        result=plan(text,'redundancies','r3 redundant because of r4 and r5','Smoke severity distinguishes direct and indirect response.')
        self.assertEqual(set(result['deterministic']),{'rule_removal','defeater_propagation'})
        self.assertEqual(set(result['llm']),{'event_specialization','measure_specialization','response_refinement'})
        for p in result['candidates']:
            model, updated=self.roundtrip(text,p)
            self.assertIn('r4 when',updated); self.assertIn('r5 when',updated)
        self.assertEqual([p['target_rule_id'] for p in result['candidates']],['r3','r3'])

    def test_trigger_strengthening_is_or_and_preserves_response(self):
        text=spec('r7 when SmokeDetectorAlarm and (not {userPresent}) then CallEmergencyServices within 1 minutes',True)
        candidate=next(p for p in plan(text,'concerns','c1')['candidates'] if p['operation']=='trigger_strengthening')
        model,_=self.roundtrip(text,candidate)
        expr=model.ruleBlock.rules[0].condition
        self.assertTrue(expression_value(expr,{'userPresent':True,'userDisablesAlarm':False}))
        self.assertTrue(expression_value(expr,{'userPresent':False,'userDisablesAlarm':True}))
        self.assertFalse(expression_value(expr,{'userPresent':True,'userDisablesAlarm':True}))
        self.assertIn('within 1 minutes',candidate['proposed_rule'])

    def test_defeater_refinement_does_not_introduce_exception(self):
        text=spec('r8 when SmokeDetectorAlarm then CallEmergencyServices within 1 minutes unless {userPresent}',True)
        result=plan(text,'concerns','c1')
        candidate=next(p for p in result['candidates'] if p['operation']=='defeater_refinement')
        self.assertIn('unless ({userPresent} and {userDisablesAlarm})',candidate['proposed_rule'])
        self.assertEqual(candidate['proposed_rule'].count('unless'),1)
        self.roundtrip(text,candidate)
        self.assertNotIn('defeater_introduction',result['deterministic'])

    def test_decomposition_complementary_contexts_and_original_deadline(self):
        text=spec('r9 when SmokeDetectorAlarm and {userPresent} then not CallEmergencyServices within 3 minutes',True)
        candidate=next(p for p in plan(text,'concerns','c1')['candidates'] if p['operation']=='rule_decomposition')
        model,updated=self.roundtrip(text,candidate)
        first,second=model.ruleBlock.rules
        self.assertFalse(first.response.occ.neg); self.assertTrue(second.response.occ.neg)
        self.assertEqual(source(updated,second.response),'not CallEmergencyServices within 3 minutes')
        for present in (False,True):
            for disables in (False,True):
                vals={'userPresent':present,'userDisablesAlarm':disables}
                a,b=(expression_value(r.condition,vals) for r in [first,second])
                self.assertFalse(a and b);self.assertEqual(a or b,present)

    def test_deadline_changes_only_bound_and_requires_weaker_obligation(self):
        rule='r10 when SmokeDetectorAlarm then CallEmergencyServices within 5 minutes unless {userPresent}'
        text=spec(rule,True)
        candidate=next(p for p in plan(text,'concerns','c1')['candidates'] if p['operation']=='deadline_refinement')
        self.assertEqual(candidate['proposed_rule'],rule.replace('5 minutes','3 minutes'))
        self.roundtrip(text,candidate)
        for variant in [rule.replace('5 minutes','2 minutes'),rule.replace('CallEmergencyServices','NotifyUserRisk'),rule.replace('then Call','then not Call'),rule.replace(' within 5 minutes','')]:
            self.assertNotIn('deadline_refinement',plan(spec(variant,True),'concerns','c1')['deterministic'])

    def test_semantic_operators_preserve_untargeted_elements(self):
        text=spec('r3 when SmokeDetectorAlarm and {userPresent} then CallEmergencyServices within 7 minutes unless {humanAssents} then NotifyUserRisk')
        for op,old,new in [('event_specialization','SmokeDetectorAlarm','SevereSmokeDetected'),('response_refinement','CallEmergencyServices','CallFireDepartment'),('measure_specialization','userPresent','userAvailable')]:
            proposal={'operation':op,'target_rule_id':'r3','change':{'from':old,'to':new,'meaning':'Distinguish the domain situation.','evidence':'System description.'},'natural_language_explanation':'Refine only the selected element.'}
            candidate=materialize_semantic_edit(text,proposal,['r3'])
            self.assertIn('within 7 minutes unless {humanAssents} then NotifyUserRisk',candidate['proposed_rule'])
            self.roundtrip(text,candidate)
        proposal['operation']='response_refinement';proposal['change'].update({'from':'NotifyUserRisk','to':'NotifySevereRisk','response_path':'main.unless[0]'})
        candidate=materialize_semantic_edit(text,proposal,['r3'])
        self.assertIn('then CallEmergencyServices within 7 minutes',candidate['proposed_rule'])
        self.assertIn('then NotifySevereRisk',candidate['proposed_rule'])
        self.roundtrip(text,candidate)

    def test_new_rule_from_source_concern(self):
        text=spec('r1 when HumanOnFloor then NotifyUserRisk',True)
        result=plan(text,'concerns','c1')
        self.assertIn('new_rule_generation',result['llm'])
        p={'operation':'new_rule_generation','target_rule_id':None,'source_requirement_id':'c1','change':{'rule_id':'r6','trigger_event':'SmokeDetectorAlarm','condition':'(not {userDisablesAlarm})','response_event':'CallEmergencyServices','negated':False,'deadline':{'value':1,'unit':'minutes'}},'natural_language_explanation':'Prevent the concern.'}
        candidate=materialize_semantic_edit(text,p,[],result['target_resolution']['addition_scope'])
        self.roundtrip(text,candidate)

    def test_rank_lexicographically_and_never_call_llm(self):
        assessor=Mock(side_effect=AssertionError('LLM ranking is forbidden'))
        ranker=PatchRanker(assessor)
        original='r1 when SmokeDetectorAlarm then CallEmergencyServices within 5 minutes'
        proposals=[('trigger_refinement',original.replace(' then',' and {humanAssents} then'),''),
          ('response_refinement',original.replace('CallEmergencyServices','CallFireDepartment'),'event CallFireDepartment'),
          ('defeater_introduction',original+' unless ({userPresent} and (not {humanAssents}))',''),
          ('measure_specialization',original.replace(' then',' and {userPresent} then')+'\nr2 when HumanOnFloor and (not {userPresent}) then not CallEmergencyServices','measure userPresent:boolean')]
        patches=[{'operation':op,'source':'llm' if op in {'response_refinement','measure_specialization'} else 'deterministic','original_rule':original,'proposed_rule':body,'declaration_text':decl,'verified':True,'syntax_validation':{'valid':True},'target_fixed':True,'regression_report':{'regression_passed':True}} for op,body,decl in proposals]
        patches[-1]['original_rule']+='\nr2 when HumanOnFloor then not CallEmergencyServices'
        ranked=ranker.rank(list(reversed(patches)))
        self.assertEqual([p['operation'] for p in ranked],[p[0] for p in proposals])
        self.assertEqual([p['ranking']['lexicographic_key'][:4] for p in ranked],[[1,0,1,0],[1,1,0,0],[1,1,2,1],[2,1,3,0]])
        assessor.assert_not_called()
        self.assertEqual(ranker.rank([{'verified':False}]),[])

    def test_legacy_names_load_as_response_refinement(self):
        self.assertEqual(normalize_operators({'operation':'capability_refinement'})['operation'],'response_refinement')
        self.assertIn('response_refinement',normalize_operators({'patch_json':'{"operation":"capability_refinement"}'})['patch_json'])

    def test_same_event_rule_merging_preserves_default_and_exception(self):
        text=spec('r1 when SmokeDetectorAlarm then CallEmergencyServices within 5 minutes\nr2 when SmokeDetectorAlarm and (not {humanAssents}) then not CallEmergencyServices within 500 seconds')
        candidate=next(p for p in plan(text,'conflicts','r1 conflicts with r2')['candidates'] if p['operation']=='rule_merging')
        model,updated=self.roundtrip(text,candidate)
        self.assertEqual(len(model.ruleBlock.rules),1)
        self.assertIn('then {not CallEmergencyServices within 500 seconds}',updated)
        score=PatchRanker().score_patch(candidate)
        self.assertEqual((score['rules_edited'],score['rules_removed'],score['rules_affected']),(1,1,2))
        from services.sleec_patch_workbench_engine import SLEECPatchWorkbenchEngine
        engine=SLEECPatchWorkbenchEngine.__new__(SLEECPatchWorkbenchEngine)
        normalized=engine.normalize_patch(candidate,text)
        self.assertEqual(PatchRanker().score_patch(normalized)['rules_affected'],2)

    def test_restrictiveness_introduces_exception_and_offers_response_refinement(self):
        text=spec('r11 when HumanOnFloor and (not {humanAssents}) then not CallEmergencyServices within 500 seconds')
        text+='purpose_start\np1 when HumanOnFloor and {userUnconscious} then CallEmergencyServices within 4 minutes\npurpose_end\n'
        result=plan(text,'purpose_blocking','p1 blocked by r11')
        self.assertEqual(result['deterministic'],['defeater_introduction'])
        self.assertEqual(result['llm'],['response_refinement'])
        p=result['candidates'][0]
        self.assertTrue(p['proposed_rule'].endswith('unless {userUnconscious}'))
        self.roundtrip(text,p)

    def test_measure_partition_edits_both_redundant_paths_as_one_candidate(self):
        text=spec('r3 when SmokeDetectorAlarm then CallEmergencyServices within 7 minutes\nr4 when SmokeDetectorAlarm then NotifyUserRisk within 2 minutes\nr5 when NotifyUserRisk then CallEmergencyServices within 5 minutes')
        p={'operation':'measure_specialization','target_rule_id':'r3','change':{
            'from':'','to':'severeSmoke','meaning':'Smoke severity is high.','evidence':'Description distinguishes smoke severity.',
            'element_path':'trigger','complementary_rule_id':'r4'},'natural_language_explanation':'Partition direct and indirect paths by severity.'}
        candidate=materialize_semantic_edit(text,p,['r3','r4','r5'])
        model,updated=self.roundtrip(text,candidate)
        self.assertIn('r3 when SmokeDetectorAlarm and {severeSmoke}',updated)
        self.assertIn('r4 when SmokeDetectorAlarm and (not {severeSmoke})',updated)
        self.assertIn('r5 when NotifyUserRisk then CallEmergencyServices within 5 minutes',updated)
        score=PatchRanker().score_patch(candidate)
        self.assertEqual(score['rules_affected'],2)
        self.assertEqual(score['new_elements'],1)

    def test_measure_specialization_does_not_change_unselected_defeater(self):
        text=spec('r3 when SmokeDetectorAlarm and {userPresent} then CallEmergencyServices unless {userPresent}')
        p={'operation':'measure_specialization','target_rule_id':'r3','change':{'from':'userPresent','to':'userAvailable','meaning':'Availability.','evidence':'Domain description.','element_path':'trigger'},'natural_language_explanation':'Specialize trigger only.'}
        candidate=materialize_semantic_edit(text,p,['r3'])
        self.assertIn('and {userAvailable} then',candidate['proposed_rule'])
        self.assertTrue(candidate['proposed_rule'].endswith('unless {userPresent}'))
        self.roundtrip(text,candidate)

    def test_no_operators_for_unresolved_diagnosis(self):
        text=spec('r1 when SmokeDetectorAlarm then CallEmergencyServices')
        for kind in ['redundancies','conflicts','concerns','purpose_blocking']:
            result=plan(text,kind,'unknown finding')
            self.assertEqual(result['deterministic'],[])
            self.assertEqual(result['llm'],[])

    def test_alternative_response_defeater_refinement(self):
        text=spec('r8 when SmokeDetectorAlarm then NotifyUserRisk unless {userPresent} then not CallEmergencyServices within 3 minutes',True)
        result=plan(text,'concerns','c1')
        self.assertEqual(result['deterministic'],['defeater_refinement'])
        self.roundtrip(text,result['candidates'][0])

    def test_new_measure_and_defeater_both_count_as_new_elements(self):
        rule='r1 when SmokeDetectorAlarm then CallEmergencyServices'
        score=PatchRanker().score_patch({'original_rule':rule,'proposed_rule':rule+' unless ({isHumanOnFloor} and (not {humanAssents}))','declaration_text':'measure isHumanOnFloor:boolean'})
        self.assertEqual(score['new_elements'],2)
        self.assertEqual(score['boolean_complexity'],2)

    def test_nested_defeater_depth_is_not_parenthesis_depth(self):
        rule='r1 when SmokeDetectorAlarm then CallEmergencyServices unless {userPresent} then {NotifyUserRisk unless (not {humanAssents})}'
        score=PatchRanker().score_patch({'original_rule':'r1 when SmokeDetectorAlarm then CallEmergencyServices','proposed_rule':rule})
        self.assertEqual(score['defeaters'],2)
        self.assertEqual(score['defeater_depth'],2)

    def test_scale_partition_from_paper(self):
        text=spec('r3 when SmokeDetectorAlarm then CallEmergencyServices within 7 minutes\nr4 when SmokeDetectorAlarm then NotifyUserRisk within 2 minutes')
        p={'operation':'measure_specialization','target_rule_id':'r3','change':{'from':'','to':'smokeSeverity',
            'measure_type':'scale','scale_labels':['low','high'],'context':'({smokeSeverity} = high)',
            'complementary_rule_id':'r4','meaning':'Severity of detected smoke.','evidence':'System description distinguishes severity.'},
            'natural_language_explanation':'Partition direct emergency action from notification by severity.'}
        candidate=materialize_semantic_edit(text,p,['r3','r4'])
        _,updated=self.roundtrip(text,candidate)
        self.assertIn('measure smokeSeverity:scale(low,high)',updated)
        self.assertIn('and ({smokeSeverity} = high)',updated)
        self.assertIn('and (not ({smokeSeverity} = high))',updated)

    def test_nested_defeater_simplification_remains_parseable(self):
        from services.boolean_simplifier import simplify_rule
        rule='r1 when SmokeDetectorAlarm then CallEmergencyServices unless {userPresent} then {NotifyUserRisk unless (not (not {humanAssents}))}'
        simplified=simplify_rule(rule)
        self.assertTrue(simplified.endswith('unless {humanAssents}}'))
        parse_sleec_ast(spec(simplified))

    def test_explicit_multiple_redundant_targets_keep_supporting_rule(self):
        text=spec('r1 when SmokeDetectorAlarm then CallEmergencyServices\nr2 when SmokeDetectorAlarm then CallEmergencyServices\nr3 when SmokeDetectorAlarm then CallEmergencyServices')
        patches=generate_repairs(text,'redundancies',{'redundant_rule_ids':['r1','r2'],'affected_rule_ids':['r1','r2','r3']},['rule_removal'])
        self.assertEqual(len(patches),1)
        model,_=self.roundtrip(text,patches[0])
        self.assertEqual([r.name for r in model.ruleBlock.rules],['r3'])
        self.assertEqual(PatchRanker().score_patch(patches[0])['rules_removed'],2)

if __name__=='__main__': unittest.main()
