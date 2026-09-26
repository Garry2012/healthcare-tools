"""Synthetic approved answers for the demo hospital. Invented facts: a real deployment
loads the hospital's own signed-off answers through `POST /knowledge`.

Questions are how callers ask, in any script; the resolver-grade normaliser (NFC,
transliteration, honorifics) is applied to both sides, so "ಪಾರ್ಕಿಂಗ್" and "parking" meet.
"""

from __future__ import annotations

from .. import KnowledgeSeed

KNOWLEDGE: tuple[KnowledgeSeed, ...] = (
    KnowledgeSeed(
        "kb_opd_hours", "hours",
        ("opd timings", "what time does the hospital open", "hospital timings", "opd kab khulta hai",
         "ಆಸ್ಪತ್ರೆ ಎಷ್ಟು ಗಂಟೆಗೆ ತೆರೆಯುತ್ತದೆ", "aspatre timing", "अस्पताल कितने बजे खुलता है"),
        {"en": "The outpatient department is open every day, 9 AM to 8 PM. Emergency is open all day, "
               "every day.",
         "kn": "ಹೊರರೋಗಿ ವಿಭಾಗ ಪ್ರತಿದಿನ ಬೆಳಿಗ್ಗೆ 9 ರಿಂದ ರಾತ್ರಿ 8 ರವರೆಗೆ ತೆರೆದಿರುತ್ತದೆ. ತುರ್ತು ವಿಭಾಗ ದಿನದ 24 ಗಂಟೆಯೂ "
               "ತೆರೆದಿರುತ್ತದೆ.",
         "hi": "ओपीडी हर दिन सुबह 9 बजे से रात 8 बजे तक खुली रहती है। इमरजेंसी चौबीसों घंटे खुली रहती है।"},
    ),
    KnowledgeSeed(
        "kb_visiting_hours", "visiting",
        ("visiting hours", "visiting time", "when can i visit a patient", "patient se milne ka time",
         "ರೋಗಿಯನ್ನು ನೋಡಲು ಸಮಯ", "मरीज़ से मिलने का समय"),
        {"en": "Ward visiting hours are 11 AM to 12 noon and 5 PM to 7 PM. One visitor per patient at a time.",
         "kn": "ವಾರ್ಡ್ ಭೇಟಿ ಸಮಯ ಬೆಳಿಗ್ಗೆ 11 ರಿಂದ 12 ಮತ್ತು ಸಂಜೆ 5 ರಿಂದ 7. ಒಂದು ಬಾರಿಗೆ ಒಬ್ಬ ರೋಗಿಗೆ ಒಬ್ಬರು ಮಾತ್ರ.",
         "hi": "वार्ड में मिलने का समय सुबह 11 से 12 और शाम 5 से 7 बजे है। एक समय में एक मरीज़ के पास एक ही व्यक्ति।"},
    ),
    KnowledgeSeed(
        "kb_parking", "parking",
        ("parking", "is there parking", "where do i park", "gaadi kahan park karein", "ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ",
         "पार्किंग है क्या"),
        {"en": "Yes. Free parking is in the basement; enter from the side road next to the main gate.",
         "kn": "ಹೌದು. ನೆಲಮಾಳಿಗೆಯಲ್ಲಿ ಉಚಿತ ಪಾರ್ಕಿಂಗ್ ಇದೆ; ಮುಖ್ಯ ದ್ವಾರದ ಪಕ್ಕದ ರಸ್ತೆಯಿಂದ ಒಳಗೆ ಬನ್ನಿ.",
         "hi": "हाँ। बेसमेंट में मुफ़्त पार्किंग है; मुख्य गेट के बगल वाली सड़क से अंदर आइए।"},
    ),
    KnowledgeSeed(
        "kb_what_to_bring", "first_visit",
        ("what should i bring", "documents to bring", "first visit", "kya lekar aana hai",
         "ಏನು ತರಬೇಕು", "क्या लेकर आना है"),
        {"en": "Please bring any old prescriptions and reports, a photo ID, and arrive 15 minutes early to register.",
         "kn": "ಹಳೆಯ ಚೀಟಿಗಳು ಮತ್ತು ವರದಿಗಳು, ಒಂದು ಗುರುತಿನ ಚೀಟಿ ತನ್ನಿ; ನೋಂದಣಿಗೆ 15 ನಿಮಿಷ ಮುಂಚೆ ಬನ್ನಿ.",
         "hi": "पुरानी पर्चियाँ और रिपोर्ट, एक फ़ोटो पहचान पत्र लेकर आइए, और रजिस्ट्रेशन के लिए 15 मिनट पहले पहुँचिए।"},
    ),
    KnowledgeSeed(
        "kb_payment", "payment",
        ("payment methods", "do you accept upi", "can i pay by card", "card chalega", "upi chalega",
         "ಕಾರ್ಡ್ ತೆಗೆದುಕೊಳ್ಳುತ್ತೀರಾ", "कार्ड से पेमेंट"),
        {"en": "We accept cash, UPI, and debit or credit cards at the billing counter.",
         "kn": "ಬಿಲ್ಲಿಂಗ್ ಕೌಂಟರ್‌ನಲ್ಲಿ ನಗದು, ಯುಪಿಐ ಮತ್ತು ಡೆಬಿಟ್ ಅಥವಾ ಕ್ರೆಡಿಟ್ ಕಾರ್ಡ್ ತೆಗೆದುಕೊಳ್ಳುತ್ತೇವೆ.",
         "hi": "बिलिंग काउंटर पर नकद, यूपीआई और डेबिट या क्रेडिट कार्ड लिए जाते हैं।"},
    ),
    KnowledgeSeed(
        "kb_lab_reports", "lab",
        ("when will my report come", "report collection", "lab report time", "report kab milega",
         "blood test report", "when will my blood report come",
         "ವರದಿ ಯಾವಾಗ ಸಿಗುತ್ತದೆ", "रिपोर्ट कब मिलेगी"),
        {"en": "Most blood test reports are ready the same evening after 6 PM, and are also sent by SMS. "
               "For a specific report I will connect you to the laboratory.",
         "kn": "ಹೆಚ್ಚಿನ ರಕ್ತ ಪರೀಕ್ಷೆ ವರದಿಗಳು ಅದೇ ದಿನ ಸಂಜೆ 6 ರ ನಂತರ ಸಿಗುತ್ತವೆ, ಎಸ್‌ಎಂಎಸ್ ಮೂಲಕವೂ ಬರುತ್ತವೆ.",
         "hi": "ज़्यादातर ब्लड टेस्ट रिपोर्ट उसी दिन शाम 6 बजे के बाद मिल जाती हैं और एसएमएस पर भी आती हैं।"},
    ),
    KnowledgeSeed(
        "kb_pharmacy_hours", "pharmacy",
        ("is the pharmacy open", "pharmacy timings", "medical shop open", "medical store khula hai",
         "pharmacy open at night", "medical shop open at night",
         "ಔಷಧಿ ಅಂಗಡಿ ತೆರೆದಿದೆಯಾ", "दवाई की दुकान खुली है"),
        {"en": "The hospital pharmacy is open 24 hours, every day, on the ground floor.",
         "kn": "ಆಸ್ಪತ್ರೆಯ ಔಷಧಿ ಅಂಗಡಿ ನೆಲಮಹಡಿಯಲ್ಲಿ ದಿನದ 24 ಗಂಟೆಯೂ ತೆರೆದಿರುತ್ತದೆ.",
         "hi": "अस्पताल की दवाई की दुकान ग्राउंड फ्लोर पर चौबीसों घंटे खुली रहती है।"},
    ),
    KnowledgeSeed(
        "kb_location", "location",
        ("where is the hospital", "address", "how to reach", "hospital kahan hai", "ಆಸ್ಪತ್ರೆ ಎಲ್ಲಿದೆ",
         "अस्पताल कहाँ है"),
        {"en": "We are at 12 Example Road, next to the City Bus Stand. I can send the location by SMS if you like.",
         "kn": "ನಾವು 12 ಎಕ್ಸಾಂಪಲ್ ರಸ್ತೆ, ನಗರ ಬಸ್ ನಿಲ್ದಾಣದ ಪಕ್ಕದಲ್ಲಿದ್ದೇವೆ.",
         "hi": "हम 12 एग्ज़ाम्पल रोड पर, सिटी बस स्टैंड के बगल में हैं।"},
    ),
    KnowledgeSeed(
        "kb_insurance", "insurance",
        ("do you take insurance", "cashless", "is my insurance accepted", "insurance chalega",
         "ವಿಮೆ ತೆಗೆದುಕೊಳ್ಳುತ್ತೀರಾ", "बीमा चलेगा"),
        {"en": "Cashless insurance depends on your insurer and policy. I will connect you to the insurance desk.",
         "kn": "ಕ್ಯಾಶ್‌ಲೆಸ್ ವಿಮೆ ನಿಮ್ಮ ವಿಮಾ ಕಂಪನಿಯ ಮೇಲೆ ಅವಲಂಬಿತವಾಗಿದೆ. ನಾನು ನಿಮ್ಮನ್ನು ವಿಮಾ ವಿಭಾಗಕ್ಕೆ ಸಂಪರ್ಕಿಸುತ್ತೇನೆ.",
         "hi": "कैशलेस बीमा आपकी बीमा कंपनी और पॉलिसी पर निर्भर है। मैं आपको इंश्योरेंस डेस्क से जोड़ता हूँ।"},
        action="TRANSFER_DESK", destination="insurance",
    ),
    KnowledgeSeed(
        "kb_cancel_policy", "booking_policy",
        ("is there a cancellation fee", "cancel charges", "cancel karne ka charge", "ರದ್ದು ಮಾಡಿದರೆ ಶುಲ್ಕ ಇದೆಯಾ",
         "कैंसल करने का चार्ज"),
        {"en": "There is no charge to cancel or move an appointment. Please let us know as early as you can.",
         "kn": "ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ರದ್ದು ಮಾಡಲು ಅಥವಾ ಬದಲಿಸಲು ಯಾವುದೇ ಶುಲ್ಕ ಇಲ್ಲ.",
         "hi": "अपॉइंटमेंट कैंसल करने या बदलने का कोई चार्ज नहीं है। कृपया जितनी जल्दी हो सके बताइए।"},
    ),
    KnowledgeSeed(
        "kb_consultation_fee", "fees",
        ("consultation fee", "how much is the consultation fee", "doctor fee", "how much does it cost",
         "fees kitna hai", "ಫೀಸ್ ಎಷ್ಟು", "फीस कितनी है"),
        {"en": "The consultation fee depends on the doctor. Tell me which doctor or department, and I will check it.",
         "kn": "ಸಮಾಲೋಚನಾ ಶುಲ್ಕ ವೈದ್ಯರನ್ನು ಅವಲಂಬಿಸಿದೆ. ಯಾವ ವೈದ್ಯರು ಅಥವಾ ವಿಭಾಗ ಎಂದು ಹೇಳಿ, ನಾನು ನೋಡುತ್ತೇನೆ.",
         "hi": "परामर्श शुल्क डॉक्टर पर निर्भर करता है। बताइए कौन से डॉक्टर या विभाग, मैं देख लेता हूँ।"},
    ),
)
