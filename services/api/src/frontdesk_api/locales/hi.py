"""Hindi: Devanagari and the romanised forms callers and speech-to-text produce."""

_NUMBERS = {
    **dict.fromkeys(("ek", "एक"), 1), **dict.fromkeys(("do", "दो"), 2), **dict.fromkeys(("teen", "तीन"), 3),
    **dict.fromkeys(("char", "chaar", "चार"), 4), **dict.fromkeys(("paanch", "panch", "पाँच", "पांच"), 5),
    **dict.fromkeys(("chhah", "chhe", "cheh", "छह", "छः"), 6), **dict.fromkeys(("saat", "सात"), 7),
    **dict.fromkeys(("aath", "आठ"), 8), **dict.fromkeys(("nau", "नौ"), 9), **dict.fromkeys(("das", "दस"), 10),
    **dict.fromkeys(("gyarah", "ग्यारह"), 11), **dict.fromkeys(("barah", "baarah", "बारह"), 12),
    **dict.fromkeys(("terah", "तेरह"), 13), **dict.fromkeys(("chaudah", "चौदह"), 14),
    **dict.fromkeys(("pandrah", "पंद्रह", "पन्द्रह"), 15), **dict.fromkeys(("solah", "सोलह"), 16),
    **dict.fromkeys(("satrah", "सत्रह"), 17), **dict.fromkeys(("atharah", "athaarah", "अठारह"), 18),
    **dict.fromkeys(("unnis", "उन्नीस"), 19), **dict.fromkeys(("bees", "बीस"), 20),
    **dict.fromkeys(("ikkis", "इक्कीस"), 21), **dict.fromkeys(("bais", "baais", "बाईस"), 22),
    **dict.fromkeys(("teis", "तेईस"), 23), **dict.fromkeys(("chaubis", "चौबीस"), 24),
    **dict.fromkeys(("pachchis", "pachis", "पच्चीस"), 25), **dict.fromkeys(("chhabbis", "छब्बीस"), 26),
    **dict.fromkeys(("sattais", "सत्ताईस"), 27), **dict.fromkeys(("atthais", "अट्ठाईस"), 28),
    **dict.fromkeys(("untis", "उनतीस"), 29), **dict.fromkeys(("tees", "तीस"), 30),
    **dict.fromkeys(("ikattis", "ikatis", "इकतीस", "इकत्तीस"), 31),
}

WORDS = dict(
    code="hi",
    script=("ऀ", "ॿ"),
    today=("abhi", "aaj", "आज", "अभी"),
    tomorrow=("kal", "कल"),
    day_after_tomorrow=("parso", "parson", "परसों"),
    next=("agle", "agla", "agli", "अगले", "अगला"),
    this=("is", "इस"),
    week=("hafte", "hafta", "हफ्ते", "सप्ताह"),
    weekdays=(
        ("somvar", "सोमवार"), ("mangalvar", "मंगलवार"), ("budhvar", "बुधवार"),
        ("guruvar", "brihaspativar", "गुरुवार"), ("shukravar", "शुक्रवार"), ("shanivar", "शनिवार"),
        ("ravivar", "रविवार"),
    ),
    months=(
        ("जनवरी",), ("फरवरी", "फ़रवरी"), ("मार्च",), ("अप्रैल",), ("मई",), ("जून",), ("जुलाई",), ("अगस्त",),
        ("सितंबर", "सितम्बर"), ("अक्टूबर",), ("नवंबर", "नवम्बर"), ("दिसंबर", "दिसम्बर"),
    ),
    day_of_month=("tareekh", "tarikh", "taarikh", "tarik", "tareek", "तारीख", "तारीख़"),
    history=("pichle", "pichhle", "pichla", "se"),
    ambiguous_in_speech=(),
    titles=("daktar", "dakter", "ji", "डॉ", "डा", "डॉक्टर", "डाक्टर", "सर", "जी"),
    stopwords=(
        "kya", "hai", "hain", "ka", "ki", "ke", "ko", "se", "mein", "aur",
        "kaise", "koi", "mujhe", "hum", "aap", "ji", "bhi", "tha", "ho",
    ),
    availability=("koi", "milega", "milegi", "milenge", "baithe", "baithi", "कोई", "मिलेगा", "बैठे"),
    cardinals=_NUMBERS,
    ordinals={},
    tens={},
    ambiguous_months=("मई",),  # "mai": also "I" and "in"
    date_fillers=(),
)
