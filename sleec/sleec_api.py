from flask import jsonify

from . import sleecParser
from . import SleecNorm

from .sleecParser import (
    check_input_red,
    check_input_conflict,
    check_input_concerns,
    check_input_purpose
)

from .SleecNorm import check_situational_conflict

from .Analyzer.analyzer import *
from .analysis_runtime import AnalysisError


# ---------- WRAPPERS WITH ERROR HANDLING ----------

def check_concern(text):
    try:
        return check_input_concerns(text)
    except Exception as e:
        msg = str(e)
        if "Expected" in msg:
            msg = "Syntax  concern error in concern: " + msg
        raise AnalysisError(f"Concern analysis failed: {msg}") from e


def check_conflict(text):
    try:
        return check_input_conflict(text)
    except Exception as e:
        msg = str(e)

        # cleaner message
        if "Expected" in msg:
            msg = "Syntax conflict error in conflict: " + msg
        raise AnalysisError(f"Conflict analysis failed: {msg}") from e

   


def check_redundancy(text):
    try:
        return check_input_red(text)
    except Exception as e:
        msg = str(e)

        # cleaner message
        if "Expected" in msg:
            msg = "Syntax error  red in redundancy: " + msg

        raise AnalysisError(f"Redundancy analysis failed: {msg}") from e

    

def check_situational(text):
    try:
        return check_situational_conflict(text)
    except Exception as e:
        msg = str(e)

        # cleaner message
        if "Expected" in msg:
            msg = "Syntax error in situational : " + msg

        raise AnalysisError(f"Situational-conflict analysis failed: {msg}") from e


def check_purpose(text):
    try:
        return check_input_purpose(text)
    except Exception as e:
        msg = str(e)

        # cleaner message
        if "Expected" in msg:
            msg = "Syntax error in purpose: " + msg

        raise AnalysisError(f"Purpose analysis failed: {msg}") from e

        
