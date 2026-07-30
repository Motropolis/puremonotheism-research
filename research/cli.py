"""
One CLI, two triggers. Run it locally to iterate; GitHub Actions runs the
same commands on a schedule. What you test is what ships.

  python -m research.cli plan   "does the Quran define salat?"
  python -m research.cli write  "does the Quran define salat?" --roots s6-l-w
  python -m research.cli next   --count 1
  python -m research.cli publish articles/2026-07-29-does-the-quran.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from . import generate, retrieve

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles"
FINDINGS = ROOT / "findings" / "observations.json"
QUEUE = ROOT / "questions.json"
DEFAULT_TRANSLATIONS = ["pickthall", "yusufali"]


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:60].rstrip("-")


def cmd_plan(args):
    cands = retrieve.candidate_roots(args.question)
    if not cands:
        print("No roots matched. Pass --roots explicitly, or rephrase using "
              "words that appear in translations.")
        return 1
    print(f"Candidate roots for: {args.question}\n")
    for c in cands:
        print(f"  {c['root']:<14} {c['occurrences']:>5} occ   matched: {', '.join(c['matched'])}")
    print("\nRun `write` with the roots you want:")
    print(f"  python -m research.cli write {args.question!r} "
          f"--roots {' '.join(c['root'] for c in cands[:3])}")
    return 0


def cmd_write(args):
    roots = args.roots or [c["root"] for c in
                           retrieve.candidate_roots(args.question)[:3]]
    if not roots:
        print("No roots resolved; pass --roots.", file=sys.stderr)
        return 1

    print(f"roots: {', '.join(roots)}", file=sys.stderr)
    packet = retrieve.build(args.question, roots, args.translations)
    packet.prior_findings = retrieve.load_findings(FINDINGS, roots)
    pj = packet.to_json()
    print(f"packet: {len(packet.verses)} verses, {len(packet.lexicon)} lexicon "
          f"entries, {len(packet.prior_findings)} prior observations",
          file=sys.stderr)

    report = {"question": args.question, "roots": roots,
              "translations": args.translations,
              "packet_verses": len(packet.verses), "attempts": []}

    article = None
    for attempt in range(1, args.retries + 2):
        art = generate.draft(pj, args.question, packet.prior_findings)

        mech = generate.mechanical_check(art, packet.citable_verses())
        model = generate.verify(pj, art)
        failed = bool(mech) or model.get("verdict") == "fail"

        report["attempts"].append({
            "n": attempt, "mechanical": mech,
            "critical": model.get("critical", []),
            "warnings": model.get("warnings", []),
            "checked_claims": model.get("checked_claims", 0),
            "passed": not failed,
        })
        print(f"attempt {attempt}: mechanical={len(mech)} "
              f"critical={len(model.get('critical', []))} "
              f"warnings={len(model.get('warnings', []))}", file=sys.stderr)

        if not failed:
            article = art
            break
        article = art  # keep the last one even if it failed

    slug = slugify(args.question)
    today = dt.date.today().isoformat()
    ARTICLES.mkdir(exist_ok=True)
    out = ARTICLES / f"{today}-{slug}.md"

    last = report["attempts"][-1]
    status = "passed" if last["passed"] else "FAILED VERIFICATION"
    front = {
        "title": args.question,
        "date": today,
        "roots": roots,
        "translations": args.translations,
        "verification": status,
        "corpus": retrieve.BASE.rsplit("@", 1)[-1],
    }
    body = (
        "---\n" + json.dumps(front, ensure_ascii=False, indent=1) + "\n---\n\n"
        + article + "\n"
    )
    out.write_text(body, encoding="utf-8")
    (ARTICLES / f"{today}-{slug}.report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nwrote {out}")
    print(f"status: {status}")
    return 0 if last["passed"] else 2


def cmd_next(args):
    if not QUEUE.exists():
        print("questions.json not found", file=sys.stderr)
        return 1
    q = json.loads(QUEUE.read_text(encoding="utf-8"))
    pending = [x for x in q["questions"] if x.get("status") == "pending"]
    if not pending:
        print("queue empty")
        return 0
    rc = 0
    for item in pending[: args.count]:
        a = argparse.Namespace(
            question=item["question"], roots=item.get("roots"),
            translations=item.get("translations", DEFAULT_TRANSLATIONS),
            retries=args.retries)
        rc |= cmd_write(a)
        item["status"] = "drafted"
        item["drafted"] = dt.date.today().isoformat()
    QUEUE.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    return rc


def cmd_publish(args):
    """Run after merge. Extracts observations into the findings store."""
    text = Path(args.path).read_text(encoding="utf-8")
    body = text.split("---", 2)[-1]
    data = generate.extract(body)

    FINDINGS.parent.mkdir(exist_ok=True)
    store = (json.loads(FINDINGS.read_text(encoding="utf-8"))
             if FINDINGS.exists() else {"findings": [], "open_questions": []})
    stamp = dt.date.today().isoformat()
    for o in data.get("observations", []):
        o["source"] = Path(args.path).name
        o["date"] = stamp
        store["findings"].append(o)
    for q in data.get("open_questions", []):
        if q not in store["open_questions"]:
            store["open_questions"].append(q)
    FINDINGS.write_text(json.dumps(store, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"added {len(data.get('observations', []))} observations, "
          f"{len(data.get('open_questions', []))} open questions")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="research")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("plan", help="show candidate roots for a question")
    a.add_argument("question")
    a.set_defaults(fn=cmd_plan)

    b = sub.add_parser("write", help="draft and verify one article")
    b.add_argument("question")
    b.add_argument("--roots", nargs="*")
    b.add_argument("--translations", nargs="*", default=DEFAULT_TRANSLATIONS)
    b.add_argument("--retries", type=int, default=1)
    b.set_defaults(fn=cmd_write)

    c = sub.add_parser("next", help="draft the next pending questions")
    c.add_argument("--count", type=int, default=1)
    c.add_argument("--retries", type=int, default=1)
    c.set_defaults(fn=cmd_next)

    d = sub.add_parser("publish", help="extract observations from a merged article")
    d.add_argument("path")
    d.set_defaults(fn=cmd_publish)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
