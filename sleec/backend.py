from sleec_api import *

# ---------- CORE LOGIC ----------
def process_text(text, mode):

    result= None
    
    if mode == "concern":
        return check_concern(text)
    elif mode == "conflict":
        return check_conflict(text)
    elif mode == "redundancy":
        return check_redundancy(text)
    elif mode == "purpose":
        return check_purpose(text)
    elif mode == "situational":
        return check_situational(text)
    else:
        return False, "Invalid mode", []
    return result

