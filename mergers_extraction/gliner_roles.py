"""Acquirer, target and merger subsidiary as "GLiNER proposes, checks decide".

GLiNER's party spans (any of the three labels, learned windows, gliner_candidates.py) are the candidate names. The
filing's own structure decides which candidate plays which role, using role_rule.py's readers:
  target            a candidate whose shares the conversion clauses convert (several, " | "-separated, when more
                    than one company's shares convert); else the candidate defined as "the Company" / "Target"
  acquirer          the candidate whose shares holders receive in the conversion clauses; else the parent of the
                    merger sub; else the candidate defined as "Parent" / "Buyer" / "Purchaser"
  merger_subsidiary a candidate defined as "Merger Sub" (or named "... Merger Sub ...")
GLiNER's names come first. A legal name from the party definitions is added only when GLiNER did not propose that
company at all, so a missed name can still be found. When no check applies, the role falls back to GLiNER's own best
span for that label. A candidate that is a short name or
defined term ("Willow Lane", "Parent") is reported as its legal name from the party definitions.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

import common
import gliner_candidates
import role_rule as rr


def _legal(value: str, defs: list[dict]) -> str:
    """The legal name for a span: itself, or the defined party it names ("Willow Lane" -> "Willow Lane Acquisition
    Corp.")."""
    v = re.sub(r"\s+", " ", value).strip(" ,.;:")
    low = v.lower()
    for d in defs:
        if d["term"].lower() == low or d["term"].lower() == f"the {low}":
            if rr.LEGAL_NAME.search(d["name"]) and common.norm_name(d["name"]) not in common.GENERIC_ROLES:
                return d["name"]
    return v


def _same(a: str, b: str) -> bool:
    """Same company: equal after removing suffixes and punctuation, or one name contained in the other when the
    shorter has at least two words and neither is a merger sub ("D. Boral ARC Merger Corporation" is not
    "D. Boral Arc Merger Sub Inc")."""
    x, y = common.norm_name(a), common.norm_name(b)
    if not x or not y:
        return False
    if x == y:
        return True
    if re.search(r"merger\s+sub", f"{a} {b}", re.I):
        return False
    short, long_ = sorted((x, y), key=len)
    return len(short.split()) >= 2 and f" {short} " in f" {long_} "


def roles(cands: list[dict], text: str, form: str = "", registrant: str = "") -> dict[str, tuple[str, str]]:
    defs = rr.definitions(text)
    # candidate names with their total GLiNER support, per label and overall
    support: Counter = Counter()
    by_label: dict[str, Counter] = defaultdict(Counter)
    for c in cands:
        if c["field"] not in ("acquirer", "target", "merger_subsidiary"):
            continue
        name = _legal(c["value"], defs)
        canon = next((d["name"] for d in defs if rr.LEGAL_NAME.search(d["name"]) and _same(name, d["name"])
                      and common.norm_name(d["name"]) not in common.GENERIC_ROLES), None)
        name = canon or next((n for n in support if common.norm_name(n) == common.norm_name(name)), name)
        if len(name) < 3 or not common.norm_name(name) or common.norm_name(name) in common.GENERIC_ROLES:
            continue
        support[name] += c["score"]
        by_label[c["field"]][name] += c["score"]
    names = [n for n, _ in support.most_common()]
    # names GLiNER missed: legal names from the party definitions, added after GLiNER's own (they only win a role
    # when no GLiNER name matches what the checks want)
    from_defs = set()
    for d in defs:
        n = d["name"]
        if (rr.LEGAL_NAME.search(n) and common.norm_name(n) and common.norm_name(n) not in common.GENERIC_ROLES
                and not any(_same(n, m) for m in names)):
            names.append(n)
            from_defs.add(n)

    def pick(wanted: list[str]) -> list[str]:
        """Candidates matching the wanted names, in the order of the wanted list (the checks' preference), then by
        GLiNER support."""
        out = []
        for w in wanted:
            for n in names:
                if n not in out and _same(n, w):
                    out.append(n)
        return out

    out = {"acquirer": ("", ""), "target": ("", ""), "merger_subsidiary": ("", "")}
    # merger subsidiary: defined as Merger Sub, or named like one
    subs = [d for d in defs if re.search(r"merger\s*sub", d["term"], re.I) or re.search(r"merger\s+sub", d["name"], re.I)]
    hit = pick([d["name"] for d in subs]) or [n for n in names if re.search(r"merger\s+sub", n, re.I)]
    if hit:
        out["merger_subsidiary"] = (" | ".join(hit[:2]), "GLiNER span; defined as Merger Sub")
    # conversion clauses: whose shares convert (targets) and whose shares holders receive (acquirer)
    conv = rr.conversions(text, defs)
    not_sub = lambda xs: [x for x in xs if not re.search(r"merger\s+sub", x, re.I)]
    targets = not_sub(pick([t for t, _ in Counter(t for t, _, _ in conv).most_common()]))
    receivers = not_sub(pick([a for a, _ in Counter(a for _, a, _ in conv if a).most_common()]))
    if receivers:
        out["acquirer"] = (receivers[0], "GLiNER span; holders receive its shares")
    else:
        parents = []
        for d in subs:
            m = rr.SUB_OF.search(d["desc"])
            if m and rr.resolve(m.group(1), defs):
                parents.append(rr.resolve(m.group(1), defs))
        parents = [p for p, _ in Counter(parents).most_common()]
        parents += [d["name"] for d in defs if d["term"].lower() in rr.ACQ_TERMS]
        hit = not_sub(pick(parents))
        if hit:
            out["acquirer"] = (hit[0], "GLiNER span; parent of the merger sub / defined as Parent")
    taken = {out["acquirer"][0], *out["merger_subsidiary"][0].split(" | ")}
    targets = [t for t in targets if t not in taken]
    if targets:
        out["target"] = (" | ".join(targets[:3]), "GLiNER span; its shares convert")
    else:
        defined = Counter(d["name"] for d in defs if d["term"].lower() in rr.TARGET_TERMS)
        hit = [n for n in pick([n for n, _ in defined.most_common()]) if n not in taken]
        if hit:
            out["target"] = (hit[0], "GLiNER span; defined as the Company / Target")
    for field, (value, why) in list(out.items()):
        if value and any(v in from_defs for v in value.split(" | ")):
            out[field] = (value, why.replace("GLiNER span", "party definitions (GLiNER missed the name)"))
    # SEC practice: a merger proxy is filed by the target, an S-4 by the issuer of the new shares
    if registrant and not out["target"][0] and form in rr.PROXY_FORMS and not _same(registrant, out["acquirer"][0]):
        out["target"] = (registrant, f"filer of a {form}")
    if registrant and not out["acquirer"][0] and form in rr.ISSUER_FORMS and not _same(registrant, out["target"][0]):
        out["acquirer"] = (registrant, f"filer of a {form}")
    # fall back to GLiNER's own best span for the label
    for field in out:
        if not out[field][0]:
            taken = {v for f, (v, _) in out.items() if v}
            best = [n for n, _ in by_label[field].most_common() if n not in taken]
            if best:
                out[field] = (best[0], "GLiNER span (no structural check applied)")
    return out


def predict_all(accs: list[str], model: str) -> dict:
    meta = common.load_ground_truth(common.TRAINING_DATA / "ground_truth_snapshot.csv").drop_duplicates(
        "accession_number").set_index("accession_number")  # filing metadata only: form and filer name
    return {acc: roles(cands, common.filing_text(acc), meta.at[acc, "form"], meta.at[acc, "registrant_name"])
            for acc, cands in gliner_candidates.load(accs, model).items()}
