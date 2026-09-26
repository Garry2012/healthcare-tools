"""Kannada: Kannada script and the romanised forms callers and speech-to-text produce."""

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
)
