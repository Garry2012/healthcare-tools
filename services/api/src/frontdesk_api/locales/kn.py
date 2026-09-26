"""Kannada: Kannada script and the romanised forms callers and speech-to-text produce."""

_CARDINALS = (
    ("ಒಂದು", "ondu"), ("ಎರಡು", "eradu"), ("ಮೂರು", "mooru"), ("ನಾಲ್ಕು", "naalku"), ("ಐದು", "aidu"),
    ("ಆರು", "aaru"), ("ಏಳು", "elu"), ("ಎಂಟು", "entu"), ("ಒಂಬತ್ತು", "ombattu"), ("ಹತ್ತು", "hattu"),
    ("ಹನ್ನೊಂದು", "hannondu"), ("ಹನ್ನೆರಡು", "hanneradu"), ("ಹದಿಮೂರು", "hadimooru"), ("ಹದಿನಾಲ್ಕು", "hadinaalku"),
    ("ಹದಿನೈದು", "hadinaidu"), ("ಹದಿನಾರು", "hadinaaru"), ("ಹದಿನೇಳು", "hadinelu"), ("ಹದಿನೆಂಟು", "hadinentu"),
    ("ಹತ್ತೊಂಬತ್ತು", "hattombattu"), ("ಇಪ್ಪತ್ತು", "ippattu"), ("ಇಪ್ಪತ್ತೊಂದು", "ippattondu"),
    ("ಇಪ್ಪತ್ತೆರಡು", "ippatteradu"), ("ಇಪ್ಪತ್ತಮೂರು", "ippattamooru"), ("ಇಪ್ಪತ್ತನಾಲ್ಕು", "ippattanaalku"),
    ("ಇಪ್ಪತ್ತೈದು", "ippattaidu"), ("ಇಪ್ಪತ್ತಾರು", "ippattaaru"), ("ಇಪ್ಪತ್ತೇಳು", "ippattelu"),
    ("ಇಪ್ಪತ್ತೆಂಟು", "ippattentu"), ("ಇಪ್ಪತ್ತೊಂಬತ್ತು", "ippattombattu"), ("ಮೂವತ್ತು", "moovattu"),
    ("ಮೂವತ್ತೊಂದು", "moovattondu"),
)
# ordinal "ಐದನೇ" (fifth): the cardinal without its final ು, plus ನೇ
_ORDINALS = {forms[0].removesuffix("ು") + "ನೇ": n for n, forms in enumerate(_CARDINALS, 1)}

WORDS = dict(
    code="kn",
    script=("ಀ", "೿"),
    today=("ivattu", "indu", "iga", "ಇಂದು", "ಇವತ್ತು", "ಈಗ", "ಈಗಲೇ"),
    tomorrow=("naale", "nale", "ನಾಳೆ"),
    day_after_tomorrow=("naadiddu", "nadiddu", "ನಾಡಿದ್ದು"),
    next=("mundina", "ಮುಂದಿನ"),
    this=("ee", "ಈ"),
    week=("vaara", "ವಾರ"),
    weekdays=(
        ("somavara", "somavar", "ಸೋಮವಾರ"), ("mangalavara", "mangalavar", "ಮಂಗಳವಾರ"),
        ("budhavara", "budhavar", "ಬುಧವಾರ"), ("guruvara", "ಗುರುವಾರ"), ("shukravara", "ಶುಕ್ರವಾರ"),
        ("shanivara", "ಶನಿವಾರ"), ("bhanuvar", "bhanuvara", "ಭಾನುವಾರ"),
    ),
    months=(
        ("ಜನವರಿ",), ("ಫೆಬ್ರವರಿ",), ("ಮಾರ್ಚ್",), ("ಏಪ್ರಿಲ್",), ("ಮೇ",), ("ಜೂನ್",), ("ಜುಲೈ",), ("ಆಗಸ್ಟ್",),
        ("ಸೆಪ್ಟೆಂಬರ್",), ("ಅಕ್ಟೋಬರ್",), ("ನವೆಂಬರ್",), ("ಡಿಸೆಂಬರ್",),
    ),
    day_of_month=("ತಾರೀಖು", "ತಾರೀಕು"),
    history=(),
    # "indu" is Kannada for today and a common given name: a date only when given as the time.
    ambiguous_in_speech=("indu",),
    titles=("ಡಾ", "ಡಾಕ್ಟರ್", "ಡಾಕ್ಟ್ರು", "ಡಾಕ್ಟರ", "ಸರ್", "ಮೇಡಂ"),
    stopwords=("ide", "idheya", "ideya", "yenu", "enu", "hege", "nanage", "nimma", "beku", "illa", "hauda", "swalpa"),
    availability=(
        "yaradaru", "yaaradaru", "iddara", "iddare", "iddaara", "sigtara", "sigthare", "ಯಾರಾದರೂ", "ಇದ್ದಾರಾ",
        "ಇದ್ದಾರೆ",
    ),
    cardinals={word: n for n, forms in enumerate(_CARDINALS, 1) for word in forms},
    ordinals=_ORDINALS,
    tens={},
    ambiguous_months=("ಮೇ",),  # "me": also the English and Hindi word
    date_fillers=(),
)
