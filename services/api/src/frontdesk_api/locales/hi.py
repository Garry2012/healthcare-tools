"""Hindi: Devanagari and the romanised forms callers and speech-to-text produce."""

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
)
