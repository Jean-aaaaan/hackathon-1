"""
Conversation Intelligence — pure computation over Fireflies transcript data.

Everything here is derived from data the Fireflies queries already return
(sentences with speakers + timings, participants, attendees, action items).
No I/O, no LLM calls: deterministic, auditable, free.

Canonical per-transcript entry shape (stored at state["transcripts"], cap 20):
  {id, date, title, transcript_url, participants, attendees[{name,email}],
   duration_minutes, summary, action_items, speaker_stats{name:{talk_time_pct,
   sentences, words}}, talk_ratio_rep, buyer_questions[{speaker,text}],
   buyer_question_count, commitments[{text, owner, owner_name}], stats_version}

Account-level rollup shape (stored at state["conversation_intel"]):
  {calls_last_30d, last_call_date, avg_talk_ratio_rep, eb_attendance,
   open_buyer_commitments, open_our_commitments, computed_at}
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
import structlog

log = structlog.get_logger()

# Seller-side email domains — mirrors the buyer-participant filter in
# nightly_worker (internal_domains). Keep in sync.
REP_DOMAINS: set[str] = set()

STATS_VERSION = 1
MAX_BUYER_QUESTIONS = 10


def identify_rep_speakers(transcript: dict, rep_domains: set[str] = REP_DOMAINS) -> set[str]:
    """
    Speaker display-names on OUR side of the table.
    Sources: organizer_email + meeting_attendees whose email is a rep domain,
    matched to attendee displayName (Fireflies speaker_name follows displayName).
    Falls back to first-token matching on the local part of the email address.
    """
    rep_names: set[str] = set()
    rep_emails: set[str] = set()

    organizer = (transcript.get("organizer_email") or "").lower()
    if organizer and organizer.split("@")[-1] in rep_domains:
        rep_emails.add(organizer)

    for att in transcript.get("meeting_attendees") or []:
        email = (att.get("email") or "").lower()
        name = (att.get("displayName") or "").strip()
        if email and email.split("@")[-1] in rep_domains:
            rep_emails.add(email)
            if name:
                rep_names.add(name.casefold())

    # No attendee names? Derive from the email local part ("vishnu.saran@…" → "vishnu")
    for email in rep_emails:
        local = email.split("@")[0]
        for token in local.replace(".", " ").replace("_", " ").split():
            if len(token) > 2:
                rep_names.add(token.casefold())

    return rep_names


def _is_rep_speaker(speaker_name: str, rep_names: set[str]) -> bool:
    s = (speaker_name or "").casefold().strip()
    if not s:
        return False
    if s in rep_names:
        return True
    # First-name match: "Vishnu Saran" vs rep name "vishnu"
    first = s.split()[0] if s.split() else ""
    return first in rep_names


def compute_speaker_stats(sentences: list[dict], rep_names: set[str]) -> tuple[dict, Optional[float]]:
    """
    Per-speaker talk time from sentence timings.

    talk_time_pct is each speaker's share of total SPOKEN time (Σ end−start),
    not of meeting duration — silence and screen-share gaps would skew that.
    Returns ({name: {talk_time_pct, sentences, words}}, talk_ratio_rep | None).
    """
    if not sentences:
        return {}, None

    per_speaker: dict[str, dict] = {}
    total_time = 0.0
    for s in sentences:
        name = (s.get("speaker_name") or "Unknown").strip() or "Unknown"
        start, end = s.get("start_time"), s.get("end_time")
        try:
            dur = max(0.0, float(end) - float(start)) if (start is not None and end is not None) else 0.0
        except (TypeError, ValueError):
            dur = 0.0
        rec = per_speaker.setdefault(name, {"time": 0.0, "sentences": 0, "words": 0})
        rec["time"] += dur
        rec["sentences"] += 1
        rec["words"] += len((s.get("text") or "").split())
        total_time += dur

    if total_time <= 0:
        # Timing data absent (e.g. list query without end_time) — fall back to
        # word share so the ratio is still meaningful.
        total_words = sum(r["words"] for r in per_speaker.values())
        if total_words <= 0:
            return {}, None
        stats = {
            name: {
                "talk_time_pct": round(100.0 * r["words"] / total_words, 1),
                "sentences": r["sentences"],
                "words": r["words"],
            }
            for name, r in per_speaker.items()
        }
    else:
        stats = {
            name: {
                "talk_time_pct": round(100.0 * r["time"] / total_time, 1),
                "sentences": r["sentences"],
                "words": r["words"],
            }
            for name, r in per_speaker.items()
        }

    rep_pct = sum(v["talk_time_pct"] for name, v in stats.items() if _is_rep_speaker(name, rep_names))
    talk_ratio_rep = round(rep_pct / 100.0, 2) if rep_names else None
    return stats, talk_ratio_rep


# Call-mechanics noise — not buyer intent
_NOISE_QUESTIONS = (
    "can you hear me", "can you see my screen", "can you see me",
    "are you there", "is that better", "can everyone hear",
    "shall we start", "shall we begin", "should we wait",
    "is my audio", "is my mic", "am i audible",
)


def extract_buyer_questions(sentences: list[dict], rep_names: set[str]) -> list[dict]:
    """Questions the BUYER asked — the clearest record of intent and objections."""
    questions = []
    for s in sentences or []:
        text = (s.get("text") or "").strip()
        speaker = (s.get("speaker_name") or "").strip()
        if not text.endswith("?") or len(text) < 12:
            continue
        if _is_rep_speaker(speaker, rep_names):
            continue
        lowered = text.casefold()
        if any(n in lowered for n in _NOISE_QUESTIONS):
            continue
        questions.append({"speaker": speaker or "Buyer", "text": text[:300]})
        if len(questions) >= MAX_BUYER_QUESTIONS:
            break
    return questions


def attribute_commitments(
    action_items: list[str],
    rep_names: set[str],
    attendees: list[dict],
) -> list[dict]:
    """
    Tag each Fireflies action item with the owning side.

    Fireflies' dominant format is name HEADERS followed by that person's tasks:
        "**Vishnu Saran**",
        "Send the proposal (12:03)",
        "**Kenneth Edwards**",
        "Review the platform (27:40)",
    A header sets the owner context for the items after it and is NOT itself a
    commitment. The older inline format ("**Vishnu** Send proposal") is kept as
    a fallback. Deterministic heuristics; "unknown" when no confident match.
    """
    buyer_names: set[str] = set()
    for att in attendees or []:
        name = (att.get("name") or att.get("displayName") or "").strip()
        if name and not _is_rep_speaker(name, rep_names):
            buyer_names.add(name.casefold())
            first = name.casefold().split()[0]
            if len(first) > 2:
                buyer_names.add(first)

    def _side_of(name_cf: str) -> Optional[str]:
        if name_cf in rep_names or (name_cf.split() and name_cf.split()[0] in rep_names):
            return "us"
        if name_cf in buyer_names or (name_cf.split() and name_cf.split()[0] in buyer_names):
            return "buyer"
        return None

    def _looks_like_name_header(text: str) -> bool:
        """A line that is ONLY a person's name (≤4 words, no digits/timestamps)."""
        words = text.split()
        if not words or len(words) > 4:
            return False
        if any(ch.isdigit() for ch in text) or "(" in text or ":" in text:
            return False
        if _side_of(text.casefold()):
            return True
        # Unknown attendee but clearly name-shaped: every word capitalized
        return all(w[0].isupper() for w in words if w)

    commitments = []
    current_owner: Optional[str] = None
    current_owner_name: Optional[str] = None

    for raw in action_items or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        text = raw.strip().lstrip("•- ").replace("**", "").strip()

        # Owner header line — sets context, emits nothing
        if _looks_like_name_header(text):
            current_owner = _side_of(text.casefold()) or "unknown"
            current_owner_name = text
            continue

        # Inline-name fallback ("Vishnu Send the proposal …")
        owner, owner_name = "unknown", None
        tokens = [t.strip("*:()").casefold() for t in text.split()[:2]]
        for i in (2, 1):
            candidate = " ".join(tokens[:i])
            if candidate and _side_of(candidate):
                owner = _side_of(candidate) or "unknown"
                owner_name = text.split()[0].strip("*:()")
                break

        # Header context wins when the inline scan found nothing
        if owner == "unknown" and current_owner:
            owner, owner_name = current_owner, current_owner_name

        commitments.append({"text": text[:300], "owner": owner, "owner_name": owner_name})
    return commitments


def build_transcript_entry(transcript: dict, rep_domains: set[str] = REP_DOMAINS) -> dict:
    """Canonical stored shape for one call — computed once at ingest."""
    summary = transcript.get("summary") or {}
    sentences = transcript.get("sentences") or []
    attendees = [
        {"name": (a.get("displayName") or "").strip(), "email": (a.get("email") or "").lower()}
        for a in (transcript.get("meeting_attendees") or [])
        if a.get("displayName") or a.get("email")
    ]

    rep_names = identify_rep_speakers(transcript, rep_domains)
    speaker_stats, talk_ratio_rep = compute_speaker_stats(sentences, rep_names)
    buyer_questions = extract_buyer_questions(sentences, rep_names)

    action_items = summary.get("action_items") or []
    if isinstance(action_items, str):
        action_items = [line.strip() for line in action_items.split("\n") if line.strip()]
    # Anyone who SPOKE on the call is attributable too — meeting_attendees is
    # often missing people who clearly attended (their words are in the
    # transcript), and Fireflies headers use the same display names
    speaker_attendees = attendees + [
        {"name": n, "email": ""} for n in speaker_stats.keys()
        if n and n != "Unknown"
    ]
    commitments = attribute_commitments(action_items, rep_names, speaker_attendees)

    duration = transcript.get("duration")
    return {
        "id": transcript.get("id"),
        "date": transcript.get("date"),
        "title": transcript.get("title"),
        "transcript_url": transcript.get("transcript_url") or transcript.get("meeting_link"),
        "participants": transcript.get("participants") or [],
        "attendees": attendees,
        "duration_minutes": round(duration / 60) if isinstance(duration, (int, float)) and duration > 120 else duration,
        "summary": summary.get("overview") or summary.get("bullet_gist") or "",
        "keywords": (summary.get("keywords") or [])[:10],
        "action_items": action_items[:10],
        "speaker_stats": speaker_stats,
        "talk_ratio_rep": talk_ratio_rep,
        "buyer_questions": buyer_questions,
        "buyer_question_count": len(buyer_questions),
        "commitments": commitments,
        "stats_version": STATS_VERSION,
    }


def merge_transcript_entries(existing: list[dict], new_entries: list[dict], cap: int = 20) -> list[dict]:
    """Dedup by id, newest first, capped — shared by webhook and nightly paths."""
    seen = {t.get("id") for t in new_entries if t.get("id")}
    kept = [t for t in (existing or []) if t.get("id") not in seen]
    merged = list(new_entries) + kept
    merged.sort(key=lambda t: t.get("date") or 0, reverse=True)
    return merged[:cap]


def conversation_intel_line(state: dict) -> str:
    """One-line summary of the rollup for agent deal-context blocks."""
    ci = (state or {}).get("conversation_intel") or {}
    if not ci or not ci.get("calls_total"):
        return "no recorded calls"
    parts = [f"{ci.get('calls_total', 0)} recorded calls ({ci.get('calls_last_30d', 0)} in last 30d)"]
    if ci.get("avg_talk_ratio_rep") is not None:
        parts.append(f"rep talk share {round(ci['avg_talk_ratio_rep'] * 100)}%")
    if ci.get("eb_identified"):
        parts.append(
            "economic buyer HAS attended a recorded call"
            if ci.get("eb_attendance")
            else "economic buyer has NEVER attended a recorded call"
        )
    n_buyer = len(ci.get("open_buyer_commitments") or [])
    n_ours = len(ci.get("open_our_commitments") or [])
    if n_buyer or n_ours:
        parts.append(f"open commitments: buyer {n_buyer}, us {n_ours}")
    return " | ".join(parts)


def compute_conversation_rollup(entries: list[dict], stakeholders: list[dict]) -> dict:
    """
    Account-level conversation rollup, recomputed whenever transcripts change.
    days_since_last_call is intentionally NOT stored — derive on read from
    last_call_date so it never goes stale.
    """
    now = datetime.now(timezone.utc)
    cutoff_30d_ms = (now - timedelta(days=30)).timestamp() * 1000

    dates = [t.get("date") for t in entries or [] if t.get("date")]
    ratios = [t.get("talk_ratio_rep") for t in entries or [] if t.get("talk_ratio_rep") is not None]

    # Did anyone tagged economic buyer ever attend a recorded call?
    eb_idents: set[str] = set()
    for s in stakeholders or []:
        if "economic" in (s.get("role") or "").lower():
            if s.get("email"):
                eb_idents.add(s["email"].lower())
            if s.get("name"):
                eb_idents.add(s["name"].casefold())
    eb_attended = False
    if eb_idents:
        for t in entries or []:
            for att in t.get("attendees") or []:
                if (att.get("email") or "").lower() in eb_idents or (att.get("name") or "").casefold() in eb_idents:
                    eb_attended = True
                    break
            for p in t.get("participants") or []:
                if (p or "").lower() in eb_idents:
                    eb_attended = True
                    break
            if eb_attended:
                break

    open_buyer = []
    open_ours = []
    for t in entries or []:
        for c in t.get("commitments") or []:
            item = {**c, "call_title": t.get("title"), "call_date": t.get("date")}
            if c.get("owner") == "buyer":
                open_buyer.append(item)
            elif c.get("owner") == "us":
                open_ours.append(item)

    return {
        "calls_total": len(entries or []),
        "calls_last_30d": sum(1 for d in dates if d and d >= cutoff_30d_ms),
        "last_call_date": max(dates) if dates else None,
        "avg_talk_ratio_rep": round(sum(ratios) / len(ratios), 2) if ratios else None,
        "eb_identified": bool(eb_idents),
        "eb_attendance": eb_attended,
        "open_buyer_commitments": open_buyer[:10],
        "open_our_commitments": open_ours[:10],
        "computed_at": now.isoformat(),
    }
