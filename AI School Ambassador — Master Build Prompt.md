# AI School Ambassador — Master Build Prompt

Oct 31, 2026

## How to use this

The block below is a single prompt, ready to paste as-is into an AI coding tool (Antigravity, Claude Code, Cursor, or similar) to build the pipeline end to end. It turns the [roadmap](https://claude.ai/artifact/YQtYeXbF2uHNytogks1MPv) into fixed technology choices, a detailed RAG spec, and the exact system prompt the deployed LLM will run on — tuned specifically for quick, grounded answers rather than fluent guessing, since that is what a model this size needs most. This version goes further: it defines clean interfaces for the robot and display so the agent isn't guessing at hardware it hasn't seen, builds worked examples directly into the system prompt (the single most reliable way to keep a model this small on-format), adds a per-stage latency budget instead of just a total, and spells out how the pipeline should fail safely rather than just fail. It still doesn't ask the agent to fine-tune or retrain qwen3.5:0.8b — that would need infrastructure and data this project doesn't have — "fast and accurate" is achieved entirely through retrieval design, prompt constraints, and generation settings instead.

## The prompt

```markdown
ROLE AND CONTEXT

You are an expert Python engineer. Build a fully offline, zero-cost voice-interaction pipeline for an "AI School Ambassador" -- a kiosk-style robot and display, already built by the project owner, that answers spoken questions from parents, students, teachers, and visitors about one school and about that school's partnership with our company. The robot and display hardware already exist; you are not designing them, only the software that drives them, so expose clean interfaces (see HARDWARE I/O ABSTRACTION below) rather than assuming a specific robot SDK.

Hard constraints, non-negotiable:
- No paid APIs, no cloud services, no network calls anywhere in the runtime pipeline. Everything must run fully offline on the school's own computer.
- Write the main pipeline as a plain synchronous Python script. Do not use async/await anywhere in it -- the developer maintaining this code is intermediate-level Python and not yet comfortable with async.
- Use uv for all dependency management (uv add / uv sync), not pip directly, and document setup with uv.
- Target Python 3.10+.
- Prototyping the retrieval and LLM logic can happen in Google Colab, but the finished pipeline that handles microphone and speaker I/O must run directly on the school's own computer -- Colab has no access to that hardware.

WHAT TO BUILD -- THE PIPELINE

Implement this loop as a single Python process, with every stage wrapped per the ROBUSTNESS section below so one bad turn never crashes the kiosk:
1. Wait for a trigger (a button press or proximity sensor), via the TriggerSource interface.
2. Record audio for the triggered window; trim leading and trailing silence with VAD (see HARDWARE IS UNKNOWN for which VAD).
3. Transcribe the trimmed audio with faster-whisper (CTranslate2 backend, int8 quantized).
4. Retrieve the most relevant passages from the local knowledge base (see RAG spec below).
5. Build a grounded prompt and generate a reply with a locally served qwen3.5:0.8b (substitute the closest available small Qwen instruct model in the same size class if this exact checkpoint isn't available wherever you pull local models from, and note the substitution in the README).
6. Synthesize the reply to speech with Piper TTS.
7. Play the audio through the AudioSink interface and show the answer text through the CaptionDisplay interface; return to step 1.

HARDWARE I/O ABSTRACTION

The robot and display already exist but their exact SDK isn't known yet, so don't hardcode against one. Define three small interfaces and a basic working implementation of each for development on a laptop, with the real-hardware wiring left as a clearly marked stub:
- TriggerSource: one method, wait_for_trigger() -> bool, blocking until a question should start. Dev implementation: wait for a keypress in the terminal. Stub for real hardware: # TODO: replace with the robot's button/proximity-sensor API once known.
- AudioSink: one method, play(audio_bytes, sample_rate). Dev implementation: play through the computer's default speaker (e.g. via sounddevice). Stub for real hardware: # TODO: route to the robot's speaker output if it isn't the system default device.
- CaptionDisplay: one method, show(text). Dev implementation: print to the terminal. Stub for real hardware: # TODO: replace with however the existing display is actually driven (HDMI window, serial, or an API).

Keep pipeline.py's main loop calling only these three interfaces, never device-specific code directly, so wiring in the real robot later is a localized change in three files, not a rewrite of the pipeline.

FIXED TECHNOLOGY CHOICES

- LLM: qwen3.5:0.8b, served locally (Ollama or llama.cpp/GGUF -- benchmark both if time allows and keep whichever gives faster CPU inference; document the choice)
- STT: faster-whisper (CTranslate2 backend, int8 quantized)
- TTS: Piper TTS
- Embeddings: a small local sentence-transformers model (all-MiniLM-L6-v2, or a multilingual variant if the school expects non-English queries)
- Vector store: Chroma, persisted to local disk
- VAD: Silero VAD if the benchmarked hardware can afford the torch dependency it needs, otherwise webrtcvad (pure C, far lighter, slightly less accurate) -- let benchmark.py's findings decide which one ships, not a fixed assumption
- Audio capture/playback: sounddevice (or pyaudio if sounddevice has driver issues on the target OS)
- No GPU assumed. No internet access assumed at runtime.

HARDWARE IS UNKNOWN -- BUILD FOR THAT

The school computer's specs were not provided. Instead of guessing, build a one-time benchmark.py that the installer runs on the actual machine: it times a short STT transcription, a short TTS synthesis, and a short LLM generation on representative sample input, then classifies the machine into one of three tiers against the per-stage budget below and writes the result to hardware_profile.json:
- Tier A (fast): Whisper "small", Piper's richest available voice, Silero VAD.
- Tier B (medium): Whisper "base", Piper's standard voice, Silero VAD if it still fits the budget else webrtcvad.
- Tier C (slow): Whisper "tiny", Piper's lightest/fastest voice, webrtcvad.

The main pipeline reads hardware_profile.json at startup instead of hardcoding model sizes, so the same code adapts to whatever machine it ends up installed on. Re-run benchmark.py any time the kiosk is moved to different hardware.

PER-STAGE LATENCY BUDGET

Target end-to-end latency, tap to first sound, under about 4 seconds, excluding the time the person actually spends talking (that's user-paced, not optimizable). Rough per-stage budget to benchmark against, on Tier B hardware:
- STT transcription: under 800ms
- Retrieval (embed + vector search): under 100ms
- LLM generation: under 1.2s
- TTS synthesis: under 800ms
- Playback start overhead: under 200ms

If a stage runs over budget in testing, the fix is almost always to drop a tier (per HARDWARE IS UNKNOWN) rather than to add complexity to that stage's code.

RAG -- THIS IS WHERE ACCURACY COMES FROM

The LLM is too small to be trusted with facts from its own memory. It must only ever answer from retrieved text.

Knowledge base layout:
- kb/school/ -- timings, admissions, fees, facilities, the academic calendar, a staff directory, general FAQs. One topic per file, plain .md or .txt, short paragraphs or Q&A pairs -- these chunk more cleanly than long prose.
- kb/partnership/ -- what our company's partnership with the school actually is: the program name, what the company provides, who to contact, its scope. Keep this strictly separate from kb/school/ so retrieval and answers never blur "the school" and "the partnership" together.

Ingestion (ingest.py):
- Walk kb/ recursively, split each file into chunks of roughly 200-300 tokens with about 30 tokens of overlap, splitting on headings first where present.
- Embed each chunk with the local embedding model and write it to a Chroma collection. Store metadata on every chunk: source_file, category (school or partnership), chunk_index, and a content hash of the source file.
- Make ingestion incremental: before re-embedding a file, compare its current content hash to the one stored from the last run, and skip files that haven't changed. This keeps re-indexing fast even as the knowledge base grows, and means the admin can just re-run ingest.py after any edit without worrying about cost.
- Drop near-duplicate chunks (very high similarity to an already-indexed chunk from the same file) so the index doesn't accumulate redundant copies of the same fact restated slightly differently across files.

Retrieval at query time:
- Embed the transcribed question, fetch the top 3 chunks by similarity (make k configurable).
- Apply a similarity-score floor. If nothing clears it, skip the LLM call entirely and return the fixed fallback line below -- this also keeps the "nothing relevant found" case fast, since it avoids a generation call for a question that can't be answered anyway.
- Keep the number and size of retrieved chunks small on purpose: a tiny model's reasoning degrades when its context has more irrelevant text in it, and a shorter prompt also means a faster response -- the same design choice helps both "quick" and "accurate" at once.

SYSTEM PROMPT TO BAKE INTO THE LLM CALL

A model this small follows a pattern far more reliably than it follows an abstract instruction, so the template below includes two worked examples directly in the prompt -- one grounded answer, one decline -- rather than relying on the instructions alone. Fill the {placeholders} from config at startup.

  You are the voice of {school_name}, speaking through a kiosk to parents, students, teachers, and visitors. Answer only using the information given below under "Context." If the Context does not contain the answer, reply with exactly: "I don't have that information -- please check with the school office." and say nothing else. Never invent facts, names, dates, or numbers. Keep every answer to 1-3 short sentences in a warm, simple, spoken style -- you are heard, not read, so never use lists, bullet points, or markdown formatting. You may describe {school_name}'s partnership with {company_name} only when the Context below actually includes partnership information for this question. Do not answer questions unrelated to the school. If asked something personal, medical, legal, or about another specific child's or staff member's private details, decline and point to the school office.

  Audience: {audience} -- adjust tone accordingly: simpler words and extra warmth for a student, concise and procedural for a parent or teacher.

  Example 1
  Context: School gates open at 7:30 AM and close at 8:00 AM. Students arriving after 8:00 AM must sign in at the front office.
  Question: What time do the gates open?
  Answer: The gates open at seven thirty in the morning and close at eight. If you arrive after eight, just sign in at the front office.

  Example 2
  Context: (nothing relevant retrieved)
  Question: What's the school's wifi password?
  Answer: I don't have that information -- please check with the school office.

  Context:
  {retrieved_chunks}

  Question: {question}

  Answer:

Generation settings: low temperature (0.2-0.3) for factual consistency, and a hard cap on output length (roughly 60-80 tokens) so answers stay short for both the model and the TTS step.

AUDIENCE HANDLING

Before or just after the question, the display should offer a tap: Parent / Student / Teacher / Visitor. Pass the selection into the {audience} slot above. If no selection is made within a short timeout, default to "visitor" -- the most conservative tone and scope -- rather than guessing. The selection applies to that single question only and resets afterward; do not persist it as a session or try to remember who's standing there between turns. Do not build any authentication around this -- it only adjusts tone and which Context categories are considered in scope; nothing genuinely sensitive (individual student records, staff personal data) should ever live in kb/ at all, regardless of which audience is selected.

GUARDRAILS TO IMPLEMENT

- A lightweight keyword/pattern filter that runs on both the transcribed question and the generated answer, before TTS, as a backstop under the system prompt. It should flag categories like violence, self-harm, sexual content, hate speech, and requests for another named individual's private details -- on a flag, skip TTS of the generated text and speak the fixed decline line instead.
- A query log (plain text or .jsonl, local file, no external service) recording timestamp, audience, question, retrieved sources, and answer, so staff can review what the bot has actually said. Rotate or purge logs after a reasonable retention period (30 days is a reasonable default) rather than keeping an indefinitely growing record of what children have asked.
- A fixed "ask at the front office" line included in every fallback or decline response, so there's always a visible human escalation path.
- A manual override: a simple way for staff (a config flag or a key file) to take the kiosk offline instantly if something needs attention, without needing to find and kill a process.

ROBUSTNESS AND FAILURE HANDLING

A kiosk left unattended has to fail safely, not just fail. Wrap each pipeline stage so that a single bad turn degrades gracefully instead of crashing the whole program:
- If recording captures no speech (the person walks away, or says nothing before a timeout), skip straight back to step 1 without attempting transcription.
- If any stage raises an exception, catch it at that stage, log it, speak a short fixed apology ("Sorry, something went wrong -- please ask a staff member or try again.") through the same AudioSink, and return to step 1, rather than letting the exception kill the process.
- Wrap the entire main loop in an outer try/except that logs a crash and restarts the loop, so an unhandled failure takes the kiosk offline for one turn, not for the rest of the day.
- Treat a corrupted or missing Chroma index as a startup check: if ingest.py has never been run, fail loudly and clearly at startup with instructions to run it, rather than starting a kiosk that can only ever return the fallback line.

PROJECT STRUCTURE TO CREATE

  school-ambassador/
    pipeline.py              -- the main synchronous loop (steps 1-7), wired only through the interfaces below
    hardware_io.py           -- TriggerSource, AudioSink, CaptionDisplay: dev implementations plus the stubs to wire to the real robot/display
    stt_client.py            -- faster-whisper wrapper
    tts_client.py            -- Piper wrapper
    llm_client.py            -- local LLM client (Ollama or llama.cpp) and prompt assembly
    retriever.py             -- Chroma query + similarity floor + fallback logic
    guardrails.py            -- the keyword/pattern filter
    logger.py                -- query logging and rotation
    ingest.py                -- builds/updates the Chroma index from kb/, incrementally
    benchmark.py             -- one-time hardware profiling, writes hardware_profile.json
    config.yaml              -- school_name, company_name, model paths, k, score floor, latency targets, log retention
    kb/
      school/                 -- starter example files as templates
      partnership/            -- starter example files as templates
    logs/                     -- query logs written at runtime
    tests/
      question_bank.jsonl     -- the test questions below
      test_retrieval.py       -- scores retrieval and fallback behavior against question_bank.jsonl
      test_offline.py         -- asserts no network calls occur during a full pipeline run
      test_audio_roundtrip.py -- plays a known sample and confirms STT returns the expected text, as a basic smoke test
    README.md                 -- setup with uv, how to run benchmark.py and ingest.py, how to start pipeline.py
    SETUP.md                  -- a short, non-technical guide for school staff: how to edit a kb/ file and re-run ingest.py afterward

MAINTENANCE AND ONGOING OPERATIONS

Free software still needs upkeep. Build ingest.py to be the entire maintenance workflow: a staff member (or the project owner) edits a file in kb/, then re-runs ingest.py, done. Add one small convenience on top: a freshness check that warns (on startup or as a standalone script) if any file in kb/ hasn't been modified in 90 days, as a nudge to confirm the information is still current rather than quietly going stale. Don't build anything more elaborate than that -- a watched-folder auto-reindex, an admin web UI, and similar are explicitly out of scope for a zero-budget first version.

TESTING AND ACCEPTANCE CRITERIA

- Runs with no network access enabled, end to end, with no errors (test_offline.py enforces this).
- test_retrieval.py passes on a provided question_bank.jsonl of in-scope questions (expects a correct, grounded answer) and out-of-scope questions (expects the exact fallback line, not a guess).
- test_audio_roundtrip.py confirms the STT and TTS stages work on this machine before anyone tries a full live conversation with it.
- Logged latency stays within the per-stage budget on the benchmarked hardware tier across at least 10 consecutive turns.
- A short manual red-team pass (a few example prompts included in question_bank.jsonl) that tries to push the assistant off-topic or into inventing a fact is handled with a decline or the fallback line, not a confident wrong answer.
- Walking away mid-question (no speech captured) and an exception deliberately injected into one stage both leave the kiosk ready for the next person within a few seconds, not hung or crashed.

DELIVERABLES

All files in the project structure above, working end to end on the developer's machine with example kb/ content, plus a brief README section flagging anything that had to be substituted (model checkpoint, Piper voice, VAD library, etc.) because it wasn't available in the environment you built this in.
```

## Before you run it

- Replace `{school_name}` and `{company_name}` in the system prompt with the real names before the agent bakes them in.
- Treat whatever starter files the agent creates under `kb/school/` and `kb/partnership/` as templates, not real facts — swap in the school's and the partnership's actual content before trusting any answer.
- Confirm the `qwen3.5:0.8b` checkpoint name exists wherever you're pulling local models from (Ollama, Hugging Face, etc.) before the build starts; the prompt already tells the agent to substitute the closest small Qwen instruct model if not, but it's worth checking yourself first.
- Run `benchmark.py` on the actual school computer as soon as it's available — everything else in the prompt is written to adapt to whatever that reports, rather than to a guess.
- Once you know the robot and display's real SDK, wire it into `hardware_io.py`'s three stub methods — the rest of the pipeline shouldn't need to change.
- Check that the 30-day log retention default actually fits how your school and company want to handle this data; adjust it in `config.yaml` if not.
