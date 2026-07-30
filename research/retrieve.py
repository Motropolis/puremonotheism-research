"""
Build the evidence packet.

This module is the containment boundary of the whole pipeline. The drafting
model sees the packet and nothing else — no question-driven recall, no
free-text search of its own memory. If a fact is not in here, it must not
appear in the article, and the verifier will catch it if it does.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path

BASE = os.environ.get(
    "CORPUS_BASE",
    "https://cdn.jsdelivr.net/gh/Motropolis/puremonotheism-data@v1.8.0",
)
CACHE = Path(os.environ.get("CORPUS_CACHE", ".corpus-cache"))

STOP = set(
    """what does the a an and or of to in on for with is are was were be by that
this it its his her their them they he she we you your i as at from not no but
if then than so all who whom which when where how why do did does have has had
will would shall should may might can could there here about say says said mean
means meaning quran say about""".split()
)


def fetch(path: str) -> dict:
    """Fetch a corpus file, caching locally. The CDN is the source of truth."""
    local = CACHE / path
    if local.exists():
        return json.loads(local.read_text(encoding="utf-8"))
    local.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(f"{BASE}/{path}", timeout=90) as r:
        raw = r.read().decode("utf-8")
    local.write_text(raw, encoding="utf-8")
    return json.loads(raw)


@dataclass
class Packet:
    question: str
    roots: list = field(default_factory=list)
    verses: list = field(default_factory=list)
    lexicon: list = field(default_factory=list)
    prior_findings: list = field(default_factory=list)
    translations_used: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1)

    def citable_verses(self) -> set:
        return {v["ref"] for v in self.verses}


def _stem(w: str) -> str:
    for s in ("iest", "ies", "ing", "edly", "ed", "es", "s", "ly"):
        if w.endswith(s) and len(w) - len(s) >= 3:
            return w[: -len(s)]
    return w


def candidate_roots(question: str, limit: int = 6) -> list:
    """Match question terms against each root's derived English terms.

    Uses the statistically derived `en` field, which came from translation
    co-occurrence rather than from a lexicographer's assertion. Roots whose
    terms were suppressed for being too frequent are correctly skipped —
    they carry no discriminating signal.
    """
    idx = fetch("meta/roots-index.json")["roots"]
    terms = {_stem(w) for w in re.findall(r"[a-z]+", question.lower())
             if w not in STOP and len(w) > 2}
    if not terms:
        return []

    scored = []
    for entry in idx:
        try:
            root = fetch(f"root/{entry['r']}.json")
        except Exception:
            continue
        en = set(root.get("en") or [])
        overlap = terms & en
        if overlap:
            scored.append((len(overlap), entry["n"], entry["r"], sorted(overlap)))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [{"root": r, "matched": m, "occurrences": n} for _, n, r, m in scored[:limit]]


def build(question: str, root_keys: list, translations: list,
          max_occurrences: int = 60) -> Packet:
    """Assemble the packet for a question from an explicit list of roots."""
    p = Packet(question=question, translations_used=list(translations))

    tr = {}
    for slug in translations:
        tr[slug] = fetch(f"translation/{slug}/all.json")["verses"]

    surah_names = {s["id"]: s["translit"] for s in fetch("meta/surahs.json")["surahs"]}
    seen_verses = {}

    for rk in root_keys:
        root = fetch(f"root/{rk}.json")
        occ = root["occ"]
        if len(occ) > max_occurrences:
            p.notes.append(
                f"Root {rk} has {len(occ)} occurrences; packet includes the "
                f"first {max_occurrences}. Any claim about totals must use "
                f"the count field, not the listed occurrences."
            )
            occ = occ[:max_occurrences]

        p.roots.append({
            "key": rk,
            "arabic": root["root_ar"],
            "total_occurrences": root["count"],
            "forms": [{"lemma": f["lem"], "pos": f["pos"], "count": f["count"]}
                      for f in root["forms"]],
        })

        for o in occ:
            ref = o["v"]
            if ref in seen_verses:
                continue
            seen_verses[ref] = True
            s, a = ref.split(":")
            p.verses.append({
                "ref": ref,
                "name": f"{surah_names.get(int(s), s)} {ref}",
                "arabic": root["verses"].get(ref, ""),
                "translations": {
                    slug: " ".join(seg["t"] for seg in tr[slug].get(ref, [])
                                   if not seg.get("i"))
                    for slug in translations
                },
                "via_root": rk,
            })

        try:
            lex = fetch(f"lexicon/{rk}.json")
            heads = [h for h in lex.get("headwords", []) if h.get("gloss")][:4]
            if heads:
                p.lexicon.append({
                    "root": rk,
                    "entries": [{"headword": h["hw"], "gloss": h["gloss"],
                                 "authorities": h.get("auth", [])} for h in heads],
                    "source": "Lane, Arabic-English Lexicon (1863-93), public domain",
                })
        except Exception:
            pass

    p.notes.append(
        "Translations here have translator additions REMOVED. Bracketed "
        "material is absent by design. Do not describe it as missing from "
        "the Arabic without saying so explicitly."
    )
    return p


def load_findings(path: Path, root_keys: list, limit: int = 12) -> list:
    """Prior observations touching the same roots. This is the compounding part."""
    if not path.exists():
        return []
    all_f = json.loads(path.read_text(encoding="utf-8")).get("findings", [])
    rel = [f for f in all_f if set(f.get("roots", [])) & set(root_keys)]
    return rel[-limit:]
