"""
System descriptions for all SLEEC-PATCH case studies.

These descriptions are inserted into GPT prompts to provide
domain context for semantic repair operators.
"""

USE_CASE_DESCRIPTIONS = {

    "ALMI": """
ALMI is an assistive living system that supports people with limited mobility.
The system helps users perform daily activities, monitors hazards and falls,
provides reminders and guidance, and can contact caregivers or emergency
services when necessary. Requirements must balance user safety, autonomy,
privacy, dignity, and informed consent.
""",

    "ASPEN": """
ASPEN is an autonomous assistive system that monitors users and their
environment to provide timely support during daily activities. It reasons
about contextual information, user state, and environmental hazards before
performing actions. Requirements emphasize safety, transparency, privacy,
human oversight, and user consent.
""",

    "AutoCAR": """
AutoCAR is an autonomous driving system responsible for monitoring road
conditions, surrounding vehicles, pedestrians, traffic signals, and passenger
requests. The vehicle performs driving decisions while ensuring passenger
safety, legal compliance, explainability, and human control whenever required.
""",

    "BSN": """
BSN (Body Sensor Network) is a healthcare monitoring system composed of
wearable sensors that continuously collect physiological information such as
heart rate, blood pressure, and body temperature. The system detects abnormal
conditions, generates alerts, and supports caregivers while preserving patient
privacy, safety, and autonomy.
""",

    "CSICobot": """
CSICobot is a collaborative robot designed to work safely alongside human
operators in shared environments. The robot performs collaborative tasks,
detects human presence, avoids hazardous situations, and coordinates its
actions with nearby workers. Requirements emphasize safety, predictability,
accountability, and appropriate human supervision.
""",

    "DAISY": """
DAISY is an intelligent assistive companion that supports older adults and
people requiring daily assistance. The system monitors user wellbeing,
provides reminders, responds to emergencies, and communicates with caregivers.
Requirements focus on safety, independence, privacy, dignity, and respecting
user preferences.
""",

    "DPA": """
DPA (Digital Personal Assistant) is an intelligent software assistant that
helps users perform everyday digital tasks such as scheduling, reminders,
information retrieval, and communication. The assistant processes personal
information while ensuring privacy, transparency, user control, and secure
decision making.
""",

    "DressAssist": """
DressAssist is an assistive robotic dressing system that helps users safely
put on clothing. The robot monitors user requests, detects discomfort and risk,
responds to stop commands, and adapts its assistance according to the user's
physical condition. Requirements balance safety, comfort, dignity, autonomy,
and informed consent.
""",

    "SafeSCAD": """
SafeSCAD is a safety-critical autonomous control system that continuously
monitors operational conditions, detects hazardous situations, and performs
protective actions when necessary. Requirements emphasize reliability, safety,
human oversight, accountability, and explainable decision making.
""",

    "Tabiat": """
Tabiat is an autonomous environmental monitoring system that observes natural
conditions, detects environmental risks, and supports sustainable decision
making. The system assists human operators by analysing environmental events,
issuing warnings, and recommending appropriate responses while ensuring
reliable and transparent operation.
""",

    "Casper": """
Casper is an autonomous assistive service robot that interacts with users in
indoor environments. The robot performs assistance tasks, responds to user
requests, navigates safely, and cooperates with caregivers when necessary.
Requirements focus on safety, user trust, privacy, autonomy, and effective
human-robot collaboration.
"""
}


def get_use_case_description(use_case: str) -> str:
    if not use_case:
        return ""

    normalized = str(use_case).strip().lower()

    if normalized.endswith("-corrected"):
        normalized = normalized[:-10]

    for name, description in USE_CASE_DESCRIPTIONS.items():
        if name.lower() == normalized:
            return description.strip()

    return (
        f"{use_case} is a SLEEC autonomous-system use case. "
        "No detailed system description is currently available."
    )