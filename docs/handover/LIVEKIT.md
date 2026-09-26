# Connecting a LiveKit voice agent (cascade or speech-to-speech)

```
caller ──SIP──▶ LiveKit ──▶ your LiveKit agent ──MCP (streamable HTTP)──▶ ContextForge ──▶ frontdesk-mcp ──▶ frontdesk-api
                                  │  headers on every MCP request:
                                  │    Authorization: Bearer <ContextForge token>
                                  │    X-Call-Id: <LiveKit room or job id>
                                  └─   X-Caller-Number: <the SIP caller's number, E.164, e.g. +919845012345>
```

The agent gets three tools: `find_availability`, `manage_booking` and `search_knowledge`.
Their descriptions and the server instructions come from the domain pack
(`services/mcp/src/frontdesk_mcp/packs/<pack>.json`).

## Identity comes from the call, never from the model

Set `X-Call-Id` and `X-Caller-Number` from the SIP participant, in code, on the MCP client.
Don't pass them as tool arguments. Without `X-Call-Id`, writes are refused because there
is no idempotency key. Without `X-Caller-Number`, lookups return `IDENTITY_UNAVAILABLE`.
ContextForge must run with `ENABLE_HEADER_PASSTHROUGH=true` (see `CONTEXTFORGE.md`).

## Mode A: cascade (STT → LLM → TTS)

- **STT:** choose one that supports `en-IN`, `hi-IN` and `kn-IN`. Forward the transcript as
  it comes: Kannada or Devanagari script, romanised text, or a mix. The tools normalise all
  of these into one comparison space.
- **LLM:** any tool-calling model. It passes the caller's words into `utterance`,
  `resourceName`, `category`, `needText` and `when.expression`, and sets `language`.
- **TTS:** needs Kannada and Hindi voices. `search_knowledge` returns the approved answer in
  the caller's language (`answer.language`), and TTS reads it as it is.
- **Best when** approved wording matters: the answer text reaches TTS unchanged.

## Mode B: speech-to-speech (e.g. an OpenAI realtime model)

The realtime model hears the caller and calls the tools itself. Its arguments are
sometimes in English ("I need a children's doctor") even when the caller spoke Kannada, and
sometimes in the caller's script. Both work: the demo pack covers English synonyms, and the
pack instructions tell the model to:

- set `language` to the language the caller speaks, and pass the caller's own words untranslated
  (a translation can lose the exact words of an emergency);
- put the date in `when.expression` as the caller said it, never as a date it worked out;
- speak approved answers in the language they come back in, and never translate or paraphrase them.

Two cautions:

1. **Approved wording.** A speech-to-speech model generates its own speech, so an
   instruction is the only thing keeping it verbatim. If a hospital requires exact
   wording (fees, reports), speak `answer.text` through a TTS voice from agent code, or use
   cascade mode for those turns.
2. **Latency.** The model waits for each tool call. Server time is about 5–10 ms per search
   (`Server-Timing` header); ContextForge and the network add the rest. Have the agent say a
   short filler line ("one moment, let me check") before `find_availability`.

LiveKit Agents can load MCP servers as function tools. Check with your LiveKit Agents
version that MCP tools are exposed to a realtime model in the same way as to an LLM.

## Verified in English, Hindi and Kannada

`services/api/tests/unit/test_spoken_input.py` and `tests/integration/test_languages.py`
run these through the real resolver and API:

| Caller says (as STT or the model passes it) | Result |
|---|---|
| "ನಾಳೆ ಸಂಜೆ", "naale sanje", "कल शाम", "kal shaam", "tomorrow ಸಂಜೆ" | tomorrow, evening |
| "ಐದು ತಾರೀಖು", "ಐದನೇ ತಾರೀಖು", "aidu tareekh", "पाँच तारीख", "paanch tareekh", "fifth of October", "twenty first October" | that date |
| "ಡಾಕ್ಟರ್ ಗರಿಮಾ", "doctor garima", "डॉक्टर गरिमा", "Garima madam", "Gareema" | Dr. Garima |
| "ಮಕ್ಕಳ ಡಾಕ್ಟರ್", "bacchon ka doctor", "a children's doctor" | Paediatrics |
| "ಹೊಟ್ಟೆ ನೋವು", "pet mein dard", "पेट में दर्द", "stomach pain", "ತಲೆ ನೋವು", "sir dard", "back pain", "kamar dard" | the approved department |
| "ಎದೆ ನೋವು", "सीने में दर्द", "seene mein dard", "chest pain", "ಅಪ್ಪನಿಗೆ chest pain" | emergency transfer, immediately |
| an everyday complaint with a danger sign: "worst headache", "headache and vomiting", "stomach pain and vomiting blood", "khansi mein khoon", "ಕೆಮ್ಮು ರಕ್ತ", "back pain, cannot move legs", "face drooping" | emergency transfer, never a routine slot |
| severity or a fall: "severe stomach pain", "bahut tez sir dard", "ತುಂಬಾ ತಲೆ ನೋವು", "back pain after a fall", "kamar dard gir gaya" | transfer to the desk, where a person triages |
| a symptom for a child or in pregnancy: "my child has stomach pain", "pet dard pregnant" | the caller is asked which department |
| "अस्पताल कहाँ है", "hospital kahan hai", "ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ" | the approved answer, in that language |

A date that isn't clear gets a question back, never a guessed date. That covers a date that
doesn't exist ("32 tareekh"), two different days ("ek tareekh nahi, das tareekh"), a number that
isn't the day ("October first week", "book me one appointment"), and "May"/"मई"/"ಮೇ", which are
also everyday words. Digits keep their plain meaning.

## Known limits

- **Names across scripts.** A booking made as "Lakshmi Rao" isn't found by "ಲಕ್ಷ್ಮಿ ರಾವ್"
  (policy P1 in `OPEN-QUESTIONS.md`), so the agent transfers.
- **The demo pack's vocabulary is synthetic.** A real hospital's lexicon (departments, symptom
  routes, emergency phrases) must be signed off by its clinicians, with English synonyms for
  speech-to-speech mode (`ONBOARDING.md` step 4).
- **Other languages** (Tamil, Telugu, …) need a locale module first (`ONBOARDING.md` step 1).
- **Not yet tested on a live call.** Everything above is verified against the tools' HTTP and
  MCP interfaces, not through a live LiveKit call.
