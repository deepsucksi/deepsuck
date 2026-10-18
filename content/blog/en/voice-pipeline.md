---
title: "Inside Auntie Wang's voice pipeline"
description: A scammer says one sentence in the browser or over the phone. Auntie Wang has to answer within a second or two while quietly noting and masking any card number or URL. This post follows one turn through speech recognition, the language model, speech synthesis, fillers, barge-in and transport, plus the rules for extracting and masking intelligence.
date: 2026-10-19
tags: [engineering, voice, intel]
---

Auntie Wang is one of DeepSuck's voice personas: warm, fond of double-checking, and unwilling to press any button before she understands why. The goal of the voice version is to make her sound like a real person on the other end of the line — a beat slow, but never so slow that the caller thinks the line has dropped.

Every implementation detail here follows the repository, mainly [voice/README.md](https://github.com/deepsucksi/deepsuck/blob/main/voice/README.md), [docs/ARCHITECTURE.md](https://github.com/deepsucksi/deepsuck/blob/main/docs/ARCHITECTURE.md), [docs/VOICE_LATENCY.md](https://github.com/deepsucksi/deepsuck/blob/main/docs/VOICE_LATENCY.md) and [docs/INTEL.md](https://github.com/deepsucksi/deepsuck/blob/main/docs/INTEL.md). Every number cites its source.

## One turn, end to end

A single turn goes like this:

1. The scammer's voice reaches the server over **WebRTC** (web) or a **SIP telephony adapter**;
2. **Cloud streaming speech recognition** produces partial results while listening and a final transcript once it decides the speaker is done;
3. The **intel processor** extracts card numbers, phone numbers, URLs and so on from the transcript, masks them, and lets the rule engine pick this turn's strategy;
4. A system prompt is assembled from persona, scenario and strategy and sent, together with the masked conversation, to the **language model**;
5. The model's output passes an **output guard** and is streamed clause by clause into **speech synthesis**;
6. The audio goes back the same way, while a data channel pushes the masked intelligence to a live dashboard in the browser.

Web and phone share one pipeline (`build_pipeline` in `voice/app.py`) with two sets of latency parameters (`voice/tuning.py`). It is built on Pipecat, an open-source real-time voice pipeline framework, served by FastAPI and Uvicorn; recognition, the language model and synthesis are cloud APIs.

## Speech recognition: when is the caller done?

Recognising words is the easy part. Deciding whether the caller has finished is hard: decide too early and one sentence becomes two turns; too late and Auntie Wang feels sluggish.

Three layers stack up (see "turn detection" in VOICE_LATENCY.md):

- **Voice activity detection (VAD)**: the open-source Silero VAD model decides whether anyone is speaking. On the web, speech must last 0.3 s at confidence 0.75 to count as started, and 0.2 s of silence counts as stopped; the phone profile is more conservative.
- **The recogniser's end-of-sentence silence**: lowered from the service default of about 800 ms to 450 ms (web) and 500 ms (phone), which brings the final transcript about 0.3 s earlier.
- **Smart Turn (v3), an open-source turn-detection model**, judges from the audio whether the utterance is complete. When it says "incomplete", the fallback used to be a full 3-second wait.

On top of that we added a digit-aware rule (`voice/turndigits.py`). Scammers often pause while reading out a card number; treated as ordinary speech, a 19-digit number gets split into three turns. The rule: if the transcript ends with an unfinished number (fewer than 16 digits after "card number", fewer than 11 after "phone number", and so on), wait at least 1800 ms after the caller stops; if the sentence already ends with final punctuation and no number is being read, wait at most 1200 ms instead of 3 s.

In local tests, a 19-digit number read with two pauses went from 3 segments to 1, and an announcement like "let me read you the card number" went from 3200 ms to 1802 ms between stopping and end-of-turn (the before/after table in VOICE_LATENCY.md).

## The language model only sees masked text

Only masked transcripts are sent to the model. Raw values such as card numbers stay in process memory for blocklist checks and are never written to disk or reported (voice/README.md, "Privacy and safety").

`voice/persona.py` builds the system prompt from persona, scenario and the strategy chosen by the rule engine: repeat back and probe when new intel appears, stall when asked for a verification code, steer towards the receiving account when asked to transfer. One easily missed constraint: **only follow up on what the caller has already said**. If the scammer has not mentioned a platform yet, the prompt will not tell Auntie Wang to ask which platform — otherwise she would bring up something they never said and give herself away.

## Output guard: no invented numbers

Before synthesis, each reply goes through a guard that strips stage directions in brackets and Markdown symbols and removes any run of five or more digits, so the model cannot invent a plausible verification code or card number. When a number has to be repeated, it is read digit by digit and the masking asterisks are never spoken.

## Speech synthesis: speak while generating

The first version opened a new connection per sentence and waited for the full sentence before synthesising, so the first audio packet took a long time. Now (the "changes" table in VOICE_LATENCY.md):

- each call keeps one long-lived connection, opened at the start;
- a synthesis task is opened as soon as each model turn begins;
- as the model streams tokens, a clause splitter cuts at final punctuation immediately and at commas once 6 characters have accumulated, never inside unclosed brackets or quotes, so the output guard always sees complete fragments;
- on barge-in, if the service is still synthesising, the connection is cancelled and reopened immediately.

After this round the median time to the first synthesised packet dropped from 2781 ms to 1385 ms (stage table under "results" in VOICE_LATENCY.md; n=6 before, n=9 after). The remaining ~1.2 s is mostly the synthesis service itself; direct measurements show fast and slow modes that do not correlate with model, voice or sample rate, so the client side has done what it can.

## Fillers: acknowledge first

Even so, two to three seconds pass between the caller stopping and the real reply. A real person usually says "mm" in that gap.

So each persona has **short backchannels** (`voice/backchannel.py`): ten pre-synthesised lines such as "mm…", "say that again?" or "hold on…", cached on disk with the 0.34–0.47 s of leading silence trimmed. One plays as soon as the turn ends, without waiting for the model. It is skipped when the caller said fewer than 4 meaningful characters, used a hurry-up phrase, asked a short question of 8 characters or less, or is in the middle of reading out digits.

The system prompt also tells the model "you have already acknowledged once this turn", so the real reply does not open with another filler word. In a local on/off comparison, replies starting with a filler word fell from 9/14 to 3/14 (backchannel comparison table in VOICE_LATENCY.md).

## Barge-in: count characters, not words

When the caller talks over Auntie Wang, she should stop. Pipecat's default counts space-separated words, which does not work for Chinese. We count "meaningful characters" instead (`voice/interrupt.py`): punctuation and acknowledgements like "mm", "right" or "OK" are dropped, while "no" or "that's wrong" count as objections. While she is speaking, 2 meaningful characters (3 on the phone) interrupt her; when she is silent, any text starts a new turn. Backchannels are ordinary output audio and are flushed with the output queue on interruption.

## Transport: web, relay and phone

- **Web**: peer-to-peer WebRTC between browser and server, with aiortc on the server side. The server uses a fixed UDP port range and adds its public address as a candidate in the answer.
- **When UDP is blocked**: corporate and campus networks or some proxies do not forward UDP. Deployments can enable a self-hosted coturn relay over TCP or TLS on port 443: Caddy, with the caddy-l4 plugin, separates TURN traffic from HTTPS by the first bytes of each connection, so no extra port is needed. Temporary credentials are fetched when "start call" is clicked, valid for 600 s by default and never stored. The page shows connecting / connected / failed, and after 20 s without a connection it suggests switching networks or turning off proxies.
- **Phone**: an optional Asterisk PBX connects to the same pipeline through a WebSocket adapter; the transport resamples audio to 8 kHz. Telephony is off by default and only answers, never dials; the deploy script also installs fail2ban to block brute-force registrations.

## Latency: measured numbers

All numbers below come from VOICE_LATENCY.md, measured on the same machine with the same six-sentence synthetic scammer recording. Every run makes real paid calls and samples are small, so P90 is indicative only.

| Metric (client side, scammer stops → bot audible) | P50 | P90 |
|---|---|---|
| Before, reply itself | 5842 ms | 6282 ms |
| After, first audible sound (incl. filler) | 1653 ms | 2803 ms |
| After, reply itself (fillers off, 3 sentences) | 4162 ms | 5827 ms |

Measured before the language model was switched; updated figures are pending.

In one external probe of the live service, the first packet of the real reply arrived at 2469, 2627 and 2484 ms: about 650 ms recognition, 430–680 ms to the model's first token and 1050–1340 ms to the first synthesised packet — synthesis is still the largest share ("TTS first-packet breakdown" in VOICE_LATENCY.md).

## Extracting intelligence

There is a single set of extraction rules in `site/assets/core/extractors.json`. The browser and Python implementations match byte for byte and check each other through shared test fixtures (INTEL.md, "noise robustness and cross-turn stitching"). The voice server reuses the Python implementation.

It recognises bank cards, mobile and landline numbers, messaging and payment accounts, email addresses, URLs, crypto wallet addresses and payee names. Spoken transcripts are messy, so text is normalised first:

- **Disguised digits**: full-width digits, circled numbers, Chinese numerals and spoken variants are converted back to Arabic digits;
- **Variant characters and typos**: traditional and variant forms of key characters are unified, and common homophone typos normalised;
- **Joining fragments**: digits separated by spaces, dashes or punctuation are joined only if the result looks like a valid phone number or bank card (check digit, issuer prefix);
- **Cross-turn stitching**: when a card number is read over two or three sentences, fragments from up to 3 adjacent turns by the same speaker are joined with a confidence score. Corrections ("no, wait…"), numbers with units, and digits next to order numbers or verification codes are excluded.

URLs and wallet addresses are checked against public blocklists and labelled "listed" or "not listed". A hit is only a hint; not being listed does not mean safe.

## Masking rules

Everything displayed, exported, stored or sent to the model is masked first. INTEL.md has the full table ("masking rules by type"); the essentials:

| Type | Rule | Example |
|---|---|---|
| Bank card | 16–19 digits keep first 6 and last 4; 8–15 keep last 4; shorter fully masked | `622202*********3445` |
| Mobile number | keep first 3 and last 4 | `139****2233` |
| ID number | keep first 6 and last 4, exactly 8 asterisks between | `110101********123X` |
| Name | family name only | <code data-i18n-keep="intel-data" lang="zh-CN">王**</code> |
| Messaging / payment account | keep 2 characters at each end | `ke******26` |
| URL | keep scheme and TLD, 2 characters at each end of the domain, hide the path | `https://pa***re.top/***` |
| Crypto wallet | keep first 4 (6 for some formats) and last 4 | `TXyz...5678` |

Masking is deterministic — the same input always yields the same output — so masked values can be used for deduplication. Only recognised fragments are replaced, so the docs recommend a second regex pass before storage, for example removing any run of 7+ digits; the intel library validator also rejects masked entries containing 7+ consecutive digits.

On retention: for web calls the visitor chooses whether to save. If they agree, each turn's masked text and latencies are logged and two audio tracks are recorded; if not, only content-free counters are kept. Phone calls store masked text only, no audio, and the caller number is masked. Traces are kept for 30 days by default, and recording stops automatically when disk space runs low (voice/README.md, "call tracing and feedback").

## Does it hold them?

In offline evaluation, a language model plays the scammer against three personas in 7 scenarios with 6 random seeds, 126 sessions per tier. In the default tier, the suspicious hang-up rate is 13.5% (95% interval 8.6–20.5%), the average stall is 23.6 turns (cap 25), extraction rate is 99.8% (430/431) and the leak rate is 0 (main table in section 1 of [docs/EVAL.md](https://github.com/deepsucksi/deepsuck/blob/main/docs/EVAL.md), result file `eval/results-llm-scammer.json`). This is a simulated opponent, not real scammers, and the document notes that recent persona changes still need re-testing.

## Still open

- The barge-in threshold was tuned on synthetic audio, not calibrated on real calls;
- End-to-end tests have only run on Linux with a desktop browser and a fake microphone; real microphones, echo cancellation and mobile are untested;
- Long sentences with comma pauses are occasionally still split into two turns.

Code, parameters and reproduction commands are all in the repository. Issues and pull requests are welcome.

## Acknowledgements

DeepSuck is built on the open-source projects below. Thanks to their authors and maintainers. The list follows the dependencies and deployment config in the repository (`voice/requirements.txt`, `deploy/`, `scripts/`, `site/assets/core/blocklists.json`).

Voice pipeline:

- [Pipecat](https://github.com/pipecat-ai/pipecat): real-time voice pipeline framework
- [Silero VAD](https://github.com/snakers4/silero-vad): voice activity detection
- [Smart Turn](https://github.com/pipecat-ai/smart-turn): turn-detection model
- [aiortc](https://github.com/aiortc/aiortc): WebRTC for Python
- [FastAPI](https://github.com/fastapi/fastapi), [Uvicorn](https://github.com/encode/uvicorn), [websockets](https://github.com/python-websockets/websockets): server and WebSocket

Deployment and telephony:

- [coturn](https://github.com/coturn/coturn): TURN relay
- [Asterisk](https://github.com/asterisk/asterisk): telephone exchange
- [Caddy](https://github.com/caddyserver/caddy) and [caddy-l4](https://github.com/mholt/caddy-l4): HTTPS and port-443 multiplexing
- [fail2ban](https://github.com/fail2ban/fail2ban): blocking brute-force registrations

Website and data:

- [marked](https://github.com/markedjs/marked): Markdown conversion for this blog
- [destroylist](https://github.com/phishdestroy/destroylist), [Phishing.Database](https://github.com/Phishing-Database/Phishing.Database): public phishing-domain blocklists
