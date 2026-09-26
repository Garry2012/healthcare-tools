"""English, including Indian-English forms and common speech-to-text spellings."""

_ORDINALS = (
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
    "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth",
    "nineteenth", "twentieth",
)

WORDS = dict(
    code="en",
    script=None,
    today=("today", "now", "right now"),
    tomorrow=("tomorrow", "tmrw", "tommorow"),
    day_after_tomorrow=("day after tomorrow",),
    next=("next", "coming"),
    this=("this",),
    week=("week",),
    weekdays=(
        ("monday", "mon"), ("tuesday", "tue", "tues"), ("wednesday", "wed"), ("thursday", "thu", "thurs"),
        ("friday", "fri"), ("saturday", "sat"), ("sunday", "sun"),
    ),
    months=(
        ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",),
        ("june", "jun"), ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"),
        ("october", "oct"), ("november", "nov"), ("december", "dec"),
    ),
    day_of_month=(),
    history=("since", "last", "from"),
    ambiguous_in_speech=(),
    titles=("dr", "doctor", "docter", "doctr", "sir", "madam", "mam"),
    stopwords=(
        "a", "an", "the", "is", "are", "am", "was", "be", "do", "does", "did", "can", "could", "will",
        "would", "i", "me", "my", "you", "your", "we", "our", "it", "its", "to", "of", "in", "on", "at",
        "for", "and", "or", "there", "what", "which", "how", "please", "tell", "want",
        "know", "any", "this", "that", "with", "from", "about", "have", "has", "get", "sir", "madam",
        "near", "nearby", "here", "also", "just", "some", "like",
    ),
    availability=(
        "any", "anyone", "anybody", "someone", "somebody", "available", "availability", "free", "sitting",
        "present", "open", "see", "consult", "consultation", "appointment", "book", "booking", "slot", "token",
        "time", "timing", "currently",
    ),
    cardinals={},
    ordinals={**{w: n for n, w in enumerate(_ORDINALS, 1)}, "thirtieth": 30},
    tens={"twenty": 20, "thirty": 30},
    ambiguous_months=("may",),
    date_fillers=("of", "the"),
)
