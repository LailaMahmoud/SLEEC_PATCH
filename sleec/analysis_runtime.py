"""Serialize LEGOS analyses and reset their process-wide state on every exit."""
from functools import wraps
import threading


ANALYSIS_LOCK = threading.RLock()


class AnalysisError(RuntimeError):
    """An analysis failed; its findings cannot be used for verification."""


class IncompleteAnalysisError(AnalysisError):
    """The solver reached a bound or returned an inconclusive result."""


def require_conclusive_result(result, *, with_model=False):
    if type(result) is int and result == 0:
        return
    if with_model:
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], str):
            return
    elif isinstance(result, str):
        return
    raise IncompleteAnalysisError(f"Solver did not complete a conclusive analysis (result={result!r}).")


def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with ANALYSIS_LOCK:
            return function(*args, **kwargs)
    return wrapped


def reset_analysis_state():
    # Lazy imports avoid the parser/normal-form parser import cycle.
    from . import sleecParser, SleecNorm
    from .Analyzer import analyzer, derivation_rule, sleecOp, type_constructor

    sleecParser.reset_parser_state()
    SleecNorm.reset_all()
    analyzer.clear_all([])
    derivation_rule.reset()
    sleecOp.M = None
    type_constructor.attribute_variable_map.clear()
    type_constructor.request_action_map.clear()
    type_constructor.exception_map.clear()
    type_constructor.Delayed_Constraints.clear()
    type_constructor.Timed_dict.clear()


def isolated_analysis(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        # Protect the whole analysis, including shared proof files, rather than
        # only the parse. Other detector requests must not reset active state.
        with ANALYSIS_LOCK:
            reset_analysis_state()
            try:
                return function(*args, **kwargs)
            finally:
                reset_analysis_state()
    return wrapped
