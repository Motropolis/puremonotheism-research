"""
Draft, verify, extract.

Three separate model calls with deliberately separate jobs. The verifier is
not the drafter reviewing itself — it receives the packet and the article and
is instructed to find fault. Self-review by the same call in the same context
reliably rubber-stamps.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request

API = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("RESEARCH_MODEL", "claude-sonnet-4-6")


def call(system: str, user: str, max_tokens: int = 8000) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY is not set")
    body = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(API, data=body, headers={
        "content-type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    })
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.loads(r.read().decode())
    return "".join(b.get("text", "") for b in data.get("content", []))


DRAFT_SYSTEM = """You write research articles for a Quran-alone study site.

THE ONE RULE: every factual claim must be traceable to the evidence packet in
the user message. The packet is your only source. You have extensive training
data about the Quran, including classical tafsir, hadith, asbab al-nuzul, and
scholarly consensus. None of it may enter this article. That material is
exactly what this site exists to set aside, and a reader cannot audit what
you do not cite.

Specifically forbidden, because none of it can be sourced from the packet:
- Occasions of revelation ("this was revealed when...")
- Anything attributed to the Prophet, companions, or any commentator
- Meccan/Medinan classification
- Claims about scholarly agreement or disagreement
- Historical background not stated in the cited verses themselves
- Verse references not present in the packet
- Occurrence counts you did not read from a `total_occurrences` field

If the packet cannot answer the question, say so plainly and describe what
evidence would be needed. A short honest article beats a padded one.

METHOD. Argue from usage. The packet gives every occurrence of the relevant
roots; the Quran-alone approach establishes meaning by how the text itself
deploys a term across contexts. Show the pattern, quote the verses, let the
reader check you. Where occurrences pull in different directions, say so —
do not resolve tension you cannot resolve from the text.

Lane's Lexicon entries in the packet are linguistic evidence about classical
Arabic usage, not doctrinal authority. Cite them as "Lane records..." and
name the authorities where given. Never present a Lane gloss as settling a
question of meaning in the Quran.

FORMAT. Markdown. No H1 (the title is frontmatter). Open with the question
and what the evidence permits. Cite as (Surah Name 2:255). Quote translations
sparingly and name which translation. End with an "Open questions" section
listing what this article could not settle — that section is required and
must not be empty."""


VERIFY_SYSTEM = """You are an adversarial fact-checker. Your job is to find
claims the article cannot support. Assume the writer has smuggled in outside
knowledge, because that is the common failure.

You receive an evidence packet and an article. For each factual sentence, ask:
which specific packet item supports this? If none does, it is a violation.

Flag as CRITICAL:
- Any verse reference not in the packet
- Occurrence counts or statistics not in the packet
- Occasions of revelation, hadith, named commentators, companions
- Meccan/Medinan claims
- Claims about scholarly consensus
- A translation quoted with wording that differs from the packet
- Lane content attributed to a root with no lexicon entry in the packet

Flag as WARNING:
- Confident interpretation where the packet shows genuine ambiguity
- A Lane gloss presented as settling Quranic meaning
- Generalisations about "the Quran says" from a handful of verses
- Missing or empty "Open questions" section

Do not flag style, tone, or structure. Only sourcing.

Return ONLY valid JSON, no prose, no code fences:
{"verdict":"pass"|"fail","critical":[{"quote":"...","why":"..."}],
 "warnings":[{"quote":"...","why":"..."}],"checked_claims":<int>}

verdict is "fail" if there is one or more critical finding."""


EXTRACT_SYSTEM = """Extract structured observations from a published article
for a findings store that will be fed back into future research.

Record only what the article actually demonstrated from cited evidence. Do not
add, infer, or improve. If the article was inconclusive, record that.

Never label anything a "discovery" or a "finding of fact". These are
observations about textual usage, and future runs must treat them as such.

Return ONLY valid JSON, no prose, no code fences:
{"observations":[{"text":"...","roots":["..."],"verses":["2:255"]}],
 "open_questions":["..."],
 "cross_references":[{"from":"2:255","to":"3:2","why":"..."}]}"""


def draft(packet_json: str, question: str, prior: list) -> str:
    prior_block = ""
    if prior:
        prior_block = (
            "\n\nPRIOR OBSERVATIONS from earlier articles on these roots. "
            "Treat as leads to verify against the packet, not as established "
            "fact. If the packet contradicts one, say so.\n"
            + json.dumps(prior, ensure_ascii=False, indent=1)
        )
    return call(
        DRAFT_SYSTEM,
        f"QUESTION\n{question}\n\nEVIDENCE PACKET\n{packet_json}{prior_block}",
        max_tokens=8000,
    )


def _json_only(text: str) -> dict:
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return {"verdict": "fail", "critical": [
            {"quote": "", "why": "verifier returned unparseable output"}],
            "warnings": [], "checked_claims": 0}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"verdict": "fail", "critical": [
            {"quote": "", "why": "verifier returned malformed JSON"}],
            "warnings": [], "checked_claims": 0}


def verify(packet_json: str, article: str) -> dict:
    raw = call(VERIFY_SYSTEM,
               f"EVIDENCE PACKET\n{packet_json}\n\nARTICLE\n{article}",
               max_tokens=4000)
    return _json_only(raw)


def mechanical_check(article: str, allowed_refs: set) -> list:
    """Catch bad citations without spending a model call.

    Cheap, deterministic, and it never hallucinates — run it before the
    model verifier so obviously broken drafts fail fast.
    """
    problems = []
    for ref in set(re.findall(r"\b(\d{1,3}:\d{1,3})\b", article)):
        s, a = (int(x) for x in ref.split(":"))
        if not (1 <= s <= 114):
            problems.append(f"{ref} is not a valid surah number")
        elif ref not in allowed_refs:
            problems.append(f"{ref} is cited but is not in the evidence packet")
    banned = [
        (r"\bhadith\b", "hadith reference"),
        (r"\bibn kathir\b|\bal-tabari\b|\btabari\b|\bqurtubi\b", "named commentator"),
        (r"\brevealed (?:when|after|concerning|about)\b", "occasion of revelation"),
        (r"\b(?:meccan|medinan)\b", "Meccan/Medinan classification"),
        (r"\bscholars (?:agree|say|hold)\b|\bconsensus\b", "appeal to scholarly consensus"),
        (r"\bthe prophet (?:said|taught)\b|\bcompanions\b", "prophetic or companion report"),
    ]
    low = article.lower()
    for pat, label in banned:
        if re.search(pat, low):
            problems.append(f"contains {label}")
    if "open questions" not in low:
        problems.append("missing required 'Open questions' section")
    return problems


def extract(article: str) -> dict:
    return _json_only(call(EXTRACT_SYSTEM, article, max_tokens=3000))
