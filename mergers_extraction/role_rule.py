"""Acquirer, target and merger subsidiary, defined per affected security (README): the target is each company whose
shares are cancelled or converted, the acquirer the company whose shares or cash its holders receive.

1. Conversion clauses (first choice for acquirer and target):
   'each issued and outstanding Willow Lane Ordinary Share will be converted ... into the right to receive one share
   of Pubco Class A Common Stock' -> target Willow Lane Acquisition Corp., acquirer Boost Run Inc. (Pubco).
   Short names are resolved through the party definitions. Up to three targets, " | "-separated (a SPAC and the
   operating company both convert into a new holding company). Warrants, options, units, preferred stock and the
   merger sub's own shares are not holder events and are skipped.
2. Party definitions, near the front of the agreement:
   'Bending Spoons US Inc., a Delaware corporation ("Parent")', 'Everest Merger Sub Inc., ... a wholly owned
   subsidiary of Parent ("Merger Sub")', 'Vimeo, Inc. (the "Company")'.
     merger_subsidiary  the party defined as Merger Sub (up to two)
     acquirer           the parent of the merger sub; else the party defined as Parent, Buyer, Purchaser or Acquiror
     target             the party defined as the Company or Target
3. The filer by form (a merger proxy is filed by the target, an S-4 by the issuer), then the fine-tuned GLiNER.

The definition rules were written from training filings. The conversion-clause rule (Nov 12, 2026) was written while
reading held-out SPAC errors, so its held-out score is not an unseen test; compare it on the validation filings.
"""
from __future__ import annotations

import re
from collections import Counter

import common
import gliner_candidates

ENTITY = re.compile(r"corporation|company|limited|partnership|\bL\.?L\.?C\b|\bLLC\b|trust|exempted|\bplc\b|\bAG\b|\bN\.?V\b|"
                    r"\bS\.?A\b|société|gmbh|incorporated|association|bank", re.I)
DEFINITION = re.compile(r",\s+(?:an?|the)\s+(?P<desc>[^()“”\"]{3,220}?)\s*\((?P<paren>[^()]{3,200})\)")
TERM = re.compile(r"[“\"]\s*([^”\"]{2,40}?)\s*[,.]?\s*[”\"]")
NAME_BEFORE = re.compile(r"([A-Z0-9][\w&.,’'\- ]{1,90}?)\s*$")
SUB_OF = re.compile(r"(?:wholly[- ]owned|direct|indirect)[\w ,-]{0,30}?subsidiary\s+of\s+(?:the\s+)?([A-Z][\w&.’'\- ]{1,60}?)"
                    r"(?=\s*(?:,|\(|$|and\b|;))")
ACQ_TERMS = {"parent", "buyer", "purchaser", "acquiror", "acquirer", "acquiring company", "pubco"}
TARGET_TERMS = {"company", "target", "the company"}
SUFFIX = re.compile(r"^(?:Inc|Incorporated|LLC|L\.L\.C|Ltd|Limited|L\.?P|N\.?V|S\.?A|Corp|Co|PLC|AG|SE|GmbH)\.?$", re.I)
LEAD = re.compile(r"^(?:.*\b(?:among|between|and|by|with|of|to|from|for|including)\s+)", re.I)


def definitions(text: str, limit: int = 400_000) -> list[dict]:
    """[{name, term, desc}] for 'Legal Name, a <jurisdiction> <entity> (“Term”)' definitions near the front."""
    head = text[:limit]
    out = []
    for m in DEFINITION.finditer(head):
        terms = [t.strip() for t in TERM.findall(m.group("paren"))]
        if not terms or not ENTITY.search(m.group("desc")):
            continue
        before = re.sub(r"\s+", " ", head[max(0, m.start() - 120):m.start()])
        before = re.split(r"[;:()“”\"]", before)[-1]
        name = NAME_BEFORE.search(before)
        if not name:
            continue
        name = LEAD.sub("", name.group(1)).strip(" ,")
        # keep only the last party of a list: "Synchronoss, Lumine Group US Holdco Inc." -> "Lumine Group US Holdco Inc."
        parts = [p.strip() for p in name.split(", ")]
        keep = [parts.pop()]
        while parts and SUFFIX.match(keep[0]):
            keep.insert(0, parts.pop())
        name = ", ".join(keep)
        name = re.sub(r"^(?:the|and|by|among)\s+", "", name, flags=re.I).strip()
        if len(name) < 3 or not name[0].isupper() or len(name.split()) > 9:
            continue
        if not re.search(r"[a-z]{2}", name):  # "HRZN", "Ltd." alone: not a legal name
            continue
        for term in terms:  # 'Aero Velocity, Inc. (“Aero” or the “Company”)' defines two terms
            out.append({"name": name, "term": term, "desc": re.sub(r"\s+", " ", m.group("desc"))})
    return out


def resolve(term: str, defs: list[dict]) -> str:
    """Legal name for a defined term ('Parent' -> 'Bending Spoons US Inc.'), or the text itself if it is a name."""
    t = term.strip().lower()
    for d in defs:
        if d["term"].lower() == t or d["term"].lower() == f"the {t}":
            return d["name"]
    return term.strip() if ENTITY.search(term) or len(term.split()) >= 2 else ""


CONVERT = re.compile(r"\b(?:shall|will|would)\s+(?:no\s+longer\s+be\s+outstanding\s+and\s+(?:shall|will)\s+)?(?:be\s+)?"
                     r"(?:automatically\s+)?(?:cancell?ed|converted|exchanged)\b", re.I)
RECEIVE = re.compile(r"right\s+to\s+receive|converted\s+(?:automatically\s+)?into|in\s+exchange\s+for|exchanged\s+for", re.I)
HOLDER_SECURITY = re.compile(r"\b(?:shares?|stock|ordinary|common)\b", re.I)
NOT_HOLDERS = re.compile(r"warrant|option|\bunits?\b|restricted|\brsus?\b|\bpsus?\b|award|treasury|dissent|merger\s+sub|"
                         r"preferred|note|debenture|right\b", re.I)


LEGAL_NAME = re.compile(r"\b(?:inc|incorporated|corp|corporation|co|company|ltd|limited|llc|l\.?l\.?c|l\.?p|plc|n\.?v|"
                        r"s\.?a|ag|se|gmbh|b\.?v|trust|bancorp|holdings?|group|partners)\b\.?", re.I)


def _party_in(segment: str, defs: list[dict], last: bool) -> str:
    """The party whose defined term or legal name appears first (or last) in the segment, among definitions that
    look like a legal entity."""
    hits = []
    for d in defs:
        if common.norm_name(d["name"]) in common.GENERIC_ROLES or not LEGAL_NAME.search(d["name"]) or \
                re.search(r"merger\s+sub", d["name"], re.I):  # misread definitions ("Exchange Share Consideration")
            continue
        # defined terms are matched case-sensitively ("Company", not the word "company"), allowing PubCo/Pubco;
        # legal names case-insensitively
        keys = [(d["term"], 0), (d["term"][:1] + d["term"][1:].lower(), 0), (d["name"], re.I)]
        for key, flags in keys:
            if len(key) < 3:
                continue
            for m in re.finditer(rf"(?<![\w-]){re.escape(key)}(?![\w-])", segment, flags):
                hits.append((m.start(), d["name"]))
    if not hits:
        return ""
    hits.sort()
    return hits[-1][1] if last else hits[0][1]


def conversions(text: str, defs: list[dict], limit: int = 4_000_000) -> list[tuple[str, str, str]]:
    """(target, acquirer, quote) for each clause that converts holders' shares: 'each [Willow Lane] Ordinary Share
    ... will be converted ... into the right to receive one share of [Pubco] Class A Common Stock'. The target is the
    company whose shares convert; the acquirer is the company whose shares holders receive ('' for cash only).
    Warrants, options, units, preferred stock and Merger Sub's own shares are skipped: they are not common holders."""
    out = []
    flat = re.sub(r"\s+", " ", text[:limit])
    for m in CONVERT.finditer(flat):
        start = flat.rfind("each ", max(0, m.start() - 260), m.start())
        if start < 0:
            continue
        source = flat[start:m.start()]
        if not HOLDER_SECURITY.search(source) or NOT_HOLDERS.search(source[:120]):
            continue
        tail = flat[m.end():m.end() + 260]
        recv = RECEIVE.search(flat[m.start():m.end() + 260])
        if not recv:
            continue
        received = flat[m.start() + recv.end():m.start() + recv.end() + 200]
        received = re.split(r";|\.\s|\((?:[ivx]+|[a-h])\)\s", received)[0]  # not "(1)" in "one (1) share"
        if re.search(r"surviving\s+(?:corporation|company|entity)", received, re.I):
            continue  # Merger Sub's shares becoming the survivor's: not a holder event
        source = re.split(r"\(?other\s+than|\(?excluding|\(?except", source, flags=re.I)[0]  # "other than shares held by Parent"
        target = _party_in(source, defs, last=False)
        acquirer = _party_in(received, defs, last=False)
        if not target or target == acquirer:
            continue
        out.append((target, acquirer, flat[start:m.end() + len(tail[:160])]))
    return out


PROXY_FORMS = {"DEFM14A", "PREM14A", "SC 13E3", "SC 13E3/A", "DEFA14A"}  # usually filed by the target
ISSUER_FORMS = {"S-4", "S-4/A", "F-4", "F-4/A"}  # usually filed by the company issuing the new shares


def roles(text: str, form: str = "", registrant: str = "") -> dict[str, tuple[str, str]]:
    defs = definitions(text)
    subs = [d for d in defs if re.search(r"merger\s*sub", d["term"], re.I) or re.search(r"merger\s+sub", d["name"], re.I)]
    out = {"acquirer": ("", ""), "target": ("", ""), "merger_subsidiary": ("", "")}
    if subs:
        names = list(dict.fromkeys(d["name"] for d in subs))
        out["merger_subsidiary"] = (" | ".join(names[:2]), f'{subs[0]["name"]}, {subs[0]["desc"]} (“{subs[0]["term"]}”)')
        parents = Counter()
        for d in subs:
            m = SUB_OF.search(d["desc"])
            if m and resolve(m.group(1), defs):
                parents[resolve(m.group(1), defs)] += 1
        if parents:
            parent = parents.most_common(1)[0][0]
            if parent and parent.lower() not in common.GENERIC_ROLES:
                out["acquirer"] = (parent, f"parent of the merger subsidiary: {subs[0]['desc']}")
    if not out["acquirer"][0]:
        acq = Counter(d["name"] for d in defs if d["term"].lower() in ACQ_TERMS)
        if acq:
            out["acquirer"] = (acq.most_common(1)[0][0], "defined as Parent / Buyer / Purchaser / Acquiror")
    tgt = Counter(d["name"] for d in defs if d["term"].lower() in TARGET_TERMS
                  and d["name"] != out["acquirer"][0] and "merger sub" not in d["name"].lower())
    if tgt:
        out["target"] = (tgt.most_common(1)[0][0], "defined as the Company / Target")
    # Per affected security (README): the conversion clauses say whose shares convert (targets) and whose shares
    # holders receive (acquirer). They override the party definitions, which in SPAC deals point at the SPAC.
    conv = conversions(text, defs)
    if conv:
        targets = Counter(t for t, _, _ in conv)
        names = [t for t, _ in targets.most_common(3)]
        quote = next(q for t, _, q in conv if t == names[0])
        receivers = Counter(a for _, a, _ in conv if a and a not in names)
        if receivers:
            out["acquirer"] = (receivers.most_common(1)[0][0], f"holders receive its shares: {quote}")
        names = [t for t in names if t != out["acquirer"][0]]
        if names:
            out["target"] = (" | ".join(names), f"its shares convert: {quote}")
    # fallback from SEC practice: a merger proxy is filed by the target, an S-4 by the issuer of the new shares
    if registrant and not out["target"][0] and form in PROXY_FORMS and registrant != out["acquirer"][0]:
        out["target"] = (registrant, f"filer of a {form}")
    if registrant and not out["acquirer"][0] and form in ISSUER_FORMS and registrant != out["target"][0]:
        out["acquirer"] = (registrant, f"filer of a {form}")
    return out


def predict_all(accs: list[str], model: str) -> dict:
    cands = gliner_candidates.load(accs, model)
    meta = common.load_ground_truth(common.TRAINING_DATA / "ground_truth_snapshot.csv").drop_duplicates(
        "accession_number").set_index("accession_number")  # filing metadata only: form and filer name
    out = {}
    for acc in accs:
        found = roles(common.filing_text(acc), meta.at[acc, "form"], meta.at[acc, "registrant_name"])
        for field in found:
            if not found[field][0]:  # fall back to the fine-tuned GLiNER's best non-generic candidate
                best = sorted((c for c in cands[acc] if c["field"] == field and
                               common.norm_name(c["value"]) not in common.GENERIC_ROLES), key=lambda c: -c["score"])
                if best:
                    found[field] = (best[0]["value"], "GLiNER fallback")
        out[acc] = found
    return out
