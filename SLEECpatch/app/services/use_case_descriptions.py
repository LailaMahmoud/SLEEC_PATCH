"""
System descriptions for all SLEEC-PATCH case studies.

These descriptions are inserted into GPT prompts to provide
domain context for semantic repair operators.
"""

USE_CASE_DESCRIPTIONS = {

        "ALMI": """
With a rapidly ageing population, the world is facing a social care crisis (Appleby, 2009). Without
a step change in the provision of social care, especially to the elderly, the increase in the budgets
and resources allocated to social care will soon become unsustainable. Ambient assisted living
(Blackman et al., 2016) (i.e., assisted living support provided in a person’s daily environment,
with the aid of robotic and autonomous systems – RAS, Artificial Intelligence – AI, and other
technologies) is widely envisaged as a key component of such a step change (Lee et al., 2018).
Given this vision, the development of assisted-living RAS and AI solutions has been the focus of
intense research and industrial effort in recent years. Designed to help or even replace carers at
home and in care homes, these solutions aim to support people with motor or cognitive
impairments in a wide range of tasks, increasing their ability to pursue daily living activities
independently. These advances have provided RAS solutions capable of assisting elderly and
disabled users both in a monitoring/advisory role and with physical tasks. However, integrating
the two types of assistance into a combined assistive-care RAS solution that can be used
safely over a long period of time still poses significant challenges (SPARK, 2015).
In the ALMI project, we employ a TIAGo robot that uses both its speech interaction and its object
manipulation capabilities to help a user with mild motor and cognitive impairments in the daily
activity of preparing a meal. Specifically, the TIAGo robot (i) provides step-by-step voice
instructions guiding the user through the meal preparation task; (ii) fetches and hands to the user
some of the food ingredients, kitchen utensils, crockery, etc. required for these steps; (iii) reminds
the user (if needed) where to find other items that are required for the task, and that the robot
cannot reach or handle. Providing such support requires the robot to dynamically create, update
and exploit a “knowledge store” of household item locations (over a long period of time); to track
the user’s progress with the meal preparation task, so that instructions are delivered progressively
and repeated if necessary; to handle disruptions safely, etc.
The safe handling of disruptions requires the robot to react to events such as task interruptions
due to a phone call received by the user, or loss of vision due to the light being switched off
accidentally by the user, or as a result of a power cut. If such unexpected events interrupt the
execution of the task, the robot will mitigate the detrimental effects of interruption (if there are
remedial actions that can be performed), or issue an alert when an unsafe situation cannot be
handled directly by using its capabilities.
TIAGo is a highly customisable mobile robotic platform with 15 degrees of freedom (DoF). The
TIAGo robot comprises a mobile base with a footprint of 54cm, an adjustable height torso
enabling the robot to vary its overall height between 110–140cm, a pan-tilt head, and a 7 DoF
manipulator arm with a reach of 87cm and a payload of 3kg. The mobile base is provided with a
differential drive capable of speeds of up to 1 m/s, and uses a LIDAR laser for indoor navigation.
The TIAGo control software and applications are deployed on an Intel i7 (7th generation)
computer with 16 GB of RAM, 500 GB of disk space, and running Ubuntu LTS 64-bit with the RT
Preempt real-time framework. Multiple ROS LTS controllers running in a real-time control loop
are used to manage robot components including its torso, head and arm positions, with joint
trajectory controllers used from groups of joints and a Head Action Server for controlling the
robot’s gaze. The TIAGo navigation unit supports laser-based mapping and self-location, with
obstacle avoidance and navigation to map point capabilities. The upper-body motion engine
controllers support path planning with self-collision avoidance, and come with a wide range of
pre-programmed motions and facilities for defining customised motions. Particularly relevant for
ALMI, TIAGo supports (i) speech-based interaction with the users through its integrated
ACAPELA text to-speech system and DeepSpeech speech-to-text module; (ii) object and
people detection thanks to its ASUS XTION Pro Live 3D Camera mounted on the robot’s head.
""",

    "ASPEN": """
Forest protection is essential to mitigating climate change, and a major objective of the Forests
and Climate Leaders’ Partnership established at COP27. The ASPEN project aims to develop
an integrated framework for the autonomous detection, diagnosis and treatment of tree pests
and disease. While recent research reveals the potential benefits of forest health monitoring
using remote sensing and drones combined with machine learning, these technologies are
absent from current government forest-protection strategies. Furthermore, the potential for
autonomous systems to fulfil forest-protection roles beyond surveillance and P&D detection
remains underexplored, as are their trustworthiness, safety, legal and ethical implications, and
their societal acceptance. ASPEN will advance the state of the art by: (1) undertaking proof-of-concept research in relation to the technical aspects of these roles of autonomous systems, (2)
exploring their contextual governance (regulation, legal and ethical norms, impact on wildlife,
and stakeholder perspectives), and (3) evaluating the feasibility of their practical use.
Specifically, our project will prototype an integrated multidisciplinary framework for trustworthy
autonomous-system capabilities in tree health that comprehensively describes their broad
functional potential whilst identifying key knowledge gaps, and technological and governance
needs.
The DJI Phantom 4 Multispectral RTK drone will be used in this project. It is equipped with a
RGB camera and multispectral camera. Currently ASPEN, and specifically the drone’s
inclusion, is being considered in two use cases. The first use case is a forest management team
is tasked with inspecting a whole forest area, however it would be ideal if the workload of the
human experts (which is a vastly limited resource) can be minimised. The deployment of drones
can cover a forest and only alert the experts to specific trees of interest. Second use is
acquiring a sample (be it a physical sample, such as soil or branch, or an image of the tree)
which can be dangerous to a human expert. The dangers include uneven terrain, climbing the
tree, and the P&D themselves can be harmful to humans. The project is also planning on
prototyping a sampling tool which will cut a branch off, specifically the DeLeaves Tree Canopy
Sampling Tool.
ASPEN is investigating not just commercial but public forests as well. Therefore great care must
be considered when concerning citizens who may be in the forest during any drone operation.
""",

    "AutoCAR": """
Autonomous cars are automobiles that can move without any human intervention by detecting
the car, traffic flow, and its surrounding environment using its own control system. Although the
state of autonomous cars is still in its early stages, self-driving technologies are becoming
increasingly common. User interaction with the car’s system is expected to be minimal, thus
there is the assumption that the user has little or no knowledge of the system. For example, the
State of California now allows driverless taxi (Robotaxi) services to operate in San Francisco [1],
with Cruise being approved to charge for rides in vehicles that will have no human backup
driver.
This case study is drawn from the AutoCar Project which aims to add emergency vehicle priority
awareness features to autonomous cars. We look at the Software Requirement Specification
(SRS) Report intended for software developers, software architects, testers, project managers,
and documentation writers. An example of a requirement would be “When an object appears in
front of the car, the system shall stop the car until the object is cleared upon which the car will
continue to its destination.” Current autonomous cars have lane detection and following, object
recognition and auto brake, virtual drive assistant, and route planning features. This project
seeks to add a fifth feature: emergency vehicle priority awareness. This SRS report includes
requirements for all five features. This will allow autonomous cars to detect emergency vehicles
as well as their location and direction. A critical assumption in this project is that the system
works well when there are no environmental factors, such as bad weather, and that lane
markings are distinct. For example, Robotaxis in California are not allowed to operate in heavy
rain or fog, and they are currently restricted to being in places and times where there is less
traffic and fewer pedestrians on the streets. This system also assumes that all traffic signs and
the presence of all objects around the vehicle can be clearly seen - thus the autonomous car is
required to have multiple cameras mounted. It also assumes that emergency vehicles, such as
ambulances and fire trucks, can be recognized by the autonomous car’s voice and image
recognition.
The primary assumption in all of this is that the system is operating properly and that there are
no abnormal conditions. When the assumptions are not true, the autonomous car’s system
becomes ineffective and should give the user warning. This project does not fully cover the
uncertainties that may occur in the environment that the system has to deal with, but aims to
implement the basic external interface requirements, and functional, and non-functional
requirements necessary for the emergency vehicle detection feature to be implemented. The
natural language rules were developed from the document’s use case scenarios for functional
requirements.
""",

        "BSN": """
The SA-BSN is an exemplar of a healthcare application implemented in ROS [1]. The goal of
the SA-BSN is to detect emergencies by continuously monitoring the patient’s health status.
Furthermore, the SA-BSN is equipped to adapt itself in order to maintain the desired QoS levels
with minimal human intervention, while accounting for classes of uncertainty.
A range of vital signs is periodically collected from the patient through a set of distributed
sensors: electrocardiograph sensor (ECG) for heart rate and electrocardiogram curve; a pulse
oximeter (SaO2) for measuring blood oxygen saturation; a thermometer (TEMP), that collects
the body temperature in Celsius; a sphygmomanometer for measuring and systolic arterial
blood pressure (ABP); there is also a Glucose sensor for measuring blood glucose levels. The
collected data is then forwarded to the Central Hub: a component in the Managed System to
fuse the vital signs and classify the overall health situation of the patient into low, moderate, or
high risk status. As a self-adaptive system, the BSN has the Managing System module, which is
responsible for continuously assuring the fulfillment of the desired QoS attributes related to the
values of reliability and battery consumption (i.e. cost).
For the evaluation of the quality of the adaptation the BSN uses control theory metrics following
the terminology proposed by Camara et al. [2]. The chosen QoS constraint is attributed to a
setpoint, which is set by the user before the system execution. For example, if the concerned
QoS attribute is the reliability, one could set it to 95%, within an acceptable error range. This is
called setpoint tracking, which can be measured by the steady-state error (SSE) metric.
Moreover, while trying to meet its requirements, the system is prone to a range of uncertainties.
Thus, the controller is activated to mitigate the effects of unexpected events in quality attributes.
Such uncertainties can be depicted in three distinctive scenarios. The first scenario, S1, focuses
on uncertainties related to the overflow of sensed data into the Central Hub queue and also to
the possible data uncertainties in sensors, which are related to the reliability of the system. The
second scenario, S2, focuses on the uncertainty related to the operational frequencies of the
components, which can lead to a battery consumption that exceeds what is needed to satisfy
the requirements. In the third scenario, S3, depending on the patient profile, the operator may
not want to use certain sensors; with fewer components to manage, less uncertainty in the
system is expected and, consequently, a more stable adaptation process.
""",

    "CSICobot": """
The emergence of ‘collaborative robots’ promises to transform the manufacturing sector,
enabling humans and robots to work together in shared spaces and physically interact to
maximise the benefits of both manual and robotic processes. Whereas traditional, non-
collaborative, processes rely on segregation of robots and workers to ensure safety,
collaborative working introduces complex challenges around the monitoring and control of
systems and processes; where people and robots operate in shared environments, and where
physical interaction is a possibility, it becomes much harder to guard against potential hazards.
Additional safety considerations are therefore required before robots can be deployed alongside
people in industrial processes.
The CSI:Cobot project focuses on a complex industrial case study involving a mobile
collaborative manipulator, i.e. iAM-R. These types of robots are generating increasing interest in
industry in areas including machine tending, logistics, drug discovery, social care, and remote
working. Our proposed case study relates to the former, and is supported by platform
manufacturers, systems integrators, distributors, and end-users. The iAM-R is a mobile
collaborative robot built on the MiR200 mobile robot base, and carrying a 3kg, 5kg, or 10kg 6-
axis Universal Robot collaborative manipulator (the 10kg version being the focus of the existing
CSI:Cobot case study). The two are combined with an Iconsys modular interface, which
provides programmable control over the platform. The system has been CE marked, with the
manipulator having 17 adjustable safety functions certified to PLd cat.3. The MiR base complies
with EN1525 safety regulations, SICK safety lasers and PLd cat.3.
To comply with safety regulations, the iAM-R is currently limited to operation of either the mobile
base or collaborative arm at any one time; before moving off the arm and payload are moved
into a stowed position within the footprint of the robot. When the arm is operational, the mobile
base remains parked. Significant benefit to end users would arise from being able to operate
both the arm and mobile base at once, increasing the workspace of the combined robot. This is
an open challenge, and a significant increase in complexity beyond that available in current
collaborative robot safety controllers. A particular application for this is in opening and tending
CNC machines.
""",

    "DAISY": """
This case-study is drawn from a proposed A&E triage AI-enabled system - the Diagnostic AI
System for Robot-Assisted ED Triage (or ‘DAISY’).
DAISY is a semi-autonomous, sociotechnical AI-supported system that directs patients through
an A&E triage pathway. DAISY will capture data by enabling a patient to input subjective
information - about themselves and their condition - and will support the patient in using
wirelessly connected medical devices to capture and record objective data - such as, blood
pressure, pulse rate, temperature, and so on. Following data collection, patients will then be
guided back to a waiting area. DAISY will utilise a complex, rule-based, ‘dAvInci’ (or Diagnostic
Algorithm for Intelligent Clinical Intervention) algorithm developed by acute-care clinicians to link
patient characteristics, demographics, and symptoms, viewed through the patient’s objective
vital signs, to possible clinical states, urgency, and early treatment options. The algorithm will
return a detailed report that contains a set of possible early diagnoses, as well as suggested
continued investigations, based on the objective and subjective data. These preliminary findings
are approved, amended, or rejected by the clinician to facilitate the early stages of triage. An
assessment with appropriate advisory information regarding a preliminary diagnosis and
treatment plan is then produced which the clinician reviews and discusses with the patient.
Once operational, DAISY will expedite and direct the triage process by better facilitating patient
observations and providing clinicians with a preliminary patient report. The DAISY system
identifies potential patient maladies and suggests further investigations and patient referrals.
The system returns possible or suggested output given the patient data. Considering these as
logical statements enables each of the information types (demographic, anatomic, subjective,
and objective) to be considered in parallel for efficient rule checking for maladies, such that the
intersections of the resultant data type rules are possibilities.
While these potential diagnoses are useful for identifying additional tests or providing potential
avenues for additional investigation, the benefit of the DAISY system is in the rapid
categorisation of patients by severity, identification, and escalation of the critically unwell
patients - and the generation of medically approved investigation plans. Clinical personnel can
thereby streamline the early elements of the process to allow for additional treatment time and
more effective resource management in critical cases. DAISY is not intended to triage patients
at the highest tier of triage illness – that is, those considered to be in need of immediate life-
saving intervention.
""",

        "DPA": """
The General Data Protection Regulation (GDPR) regulates the processing of personal data in
Europe through data processing agreements (DPAs). The GDPR imposes obligations onto
organizations as long as they collect, process, or handle in any way the personal data of people
in Europe. Thus, organizations that have software systems that involve processing or sharing
personal data are responsible for conducting audits to ensure their data processing satisfies
GDPR obligations. To achieve software compliance, organizations must verify their software-
relevant legal documents against GDPR regulations. Organizations do this through DPAs that
regulate data processing activities according to GDPR. These are legally binding agreements
and to be deemed GDPR-compliant, DPAs must cover all criteria imposed by GDPR provisions
concerning data processing.
Data processing involves an organization, known as the data controller, which collects and/or
further shares personal data, an additional organization, known as the data processor, which
processes personal data for the controller, and of course a data subject who shares personal
data willingly. A third-party organization, called a sub-processor, may be employed by the data
processor to perform some data processing services on its behalf. This involves further sharing
the personal data. The controller provides data subjects with the terms on which their personal
data is collected and handled. However, further sharing of personal data with processors and
sub-processors is not directly visible to data subjects. The controller and processor share
responsibility of protecting personal data. Thus, a DPA listing privacy-related requirements
should be established between controller and processor(s). A DPA includes setting terms for
how data is used, stored, protected, and accessed. Establishing a DPA also includes the rights
and obligations of the controller and processor. Signing a DPA means that the processor is
obliged to ensure that any software system deployed for processing personal data has to also
comply with GDPR.
The paper which this case study is drawn from uses the “shall” requirements that the authors
extracted from GDPR provisions relevant to DPA compliance, which removes the additional
complexity and potential ambiguity of legal texts. DPAs are an important source of requirements
for software development involving the processing of personal data. SLEEC requirements allow
the controller and processor to be legally-compliant with the GDPR. For instance, we can
specify that upon the end of the provision of services relating to processing, the processor shall
return or delete all personal data, or that the DPA shall contain the duration of the processing,
after which data return/removal occurs.
""",

    "DressAssist": """
A carebot is an assistive and supportive robotic tool used to care for the elderly, children, and
those with disabilities (typically either of a physical or cognitive nature). The carebot is usually
deployed in the user’s home (or at a care home) – either working with human caregivers or on
their own. Its primary role is to aid a user in dressing and in providing routine care and support
functions such as reminding a user to take their medication. It may also be a source of
companionship and comfort to the user and is expected to engage in social interactions with the
user, by communicating, listening, responding, and reacting and to make certain normatively-
relevant decisions and judgements. In our use case the primary role of the agent is to dress the
user, with a secondary function of monitoring the user’s well-being. The instantiation of SLEEC
requirements allows the agent to be, in some part, SLEEC-sensitive and in certain crucial
instances, legally-compliant.
Developments in machine learning and control engineering promise a world in which
autonomous agents can provide care and support for individuals in their daily lives (Zhang et
al., 2019; Cosar et al, 2020). Jevtić et al. describe the development of such a carebot (Jevtić et
al., 2019). It is a personalised robot with a wide range of physical characteristics and abilities
that can perform assistive dressing functions in close physical interaction with users. Although a
human carer may still be required, the autonomous agent could allow increased reach, enhance
existing activities, and enable greater multitasking (Townsend et al., 2022). Robots of this type
also demonstrate a degree of sociability and of emotional perception, such as, engaging in
high-level interactive dialogue, responsiveness, gesturing, and using voice recognition, which
serve to 'lubricate' the human-robot interface (Breazeal, 2003). This will require the agent to
execute decisions, expressed as SLEEC rules, derived from an array of reasoned and
justifiable alternatives.
The agent is equipped with moving actuators enabling it to pick up and manipulate items of
clothing and with multiple cameras that capture video imagery to determine user pose and limb
trajectory. The agent has voice synthesis and emotional recognition system to interpret verbal
and non-verbal commands and communicate with the user. Interaction with the user is also
possible by means of a touch screen. The audio-visual components may also be leveraged to
monitor user well-being through machine-learning components that detect distress in speech
patterns as well as facial expressions. The user wears a smartwatch to provide biometric
information and to enable the detection of user falls.
""",

    "SafeSCAD": """
The Safe-SCAD project developed a proof-of-concept driver attentiveness management system
to support safe shared control of autonomous vehicles. This system comprises a deep neural
network (DNN) responsible for predicting the driver control-takeover behaviour, methods for
verifying this DNN, and a discrete-event controller that issues optical, acoustic and/or haptic
driver alerts based on the predictions of the DNN and the results of its online verification.
Sensors for detecting the state of the human driver include an eye-tracking camera, and
wearable sensors to measure the driver’s heart rate (PPG) and galvanic skin response (GSR)
signals.
Taking this beyond the initial project though it can be observed how SafeSCAD can benefit from
utilising SLEEC requirements. The safety of the passengers and those around the car is
paramount, and laws are in place to ensure this safety. Thus the controller of this autonomous
system needs to be legally compliant, and identify when it can no longer be legally safe. For
simplicity this can be initially thought of as when the system does not have sufficient control, or
can accurately predict future states. It is at this instance that the system will need to alert the
user of the switch over. This of course would not cover all legal nuances of driving, and a full set
of legal requirements will need to be drafted. Further, these legal requirements will need to be in
a manner that can be understood by the system. Providing cues that will accurately convey the
specific situation’s concerns, and magnitude of said concern, is vital and would be encapsulated
by the SLEEC requirements.
Further, to ensure a successful takeover from the human driver when prompted the human
must be attentive. The controller was assumed to have a light source, speakers, and be able to
haptically interact with the driver (vibrations in seat/steering wheel for example). This allows the
car to alert the human driver whenever the driver is observed to be less attentive. DeepDECs is
employed to generate pareto optimal controllers utilising the different objective tradeoffs; risk
due to attentiveness level, and nuisance caused by the alerts.
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