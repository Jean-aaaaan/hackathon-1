"""
Fireflies.ai Integration — Call transcript ingestion for episodic memory.
Uses Fireflies GraphQL API to fetch recent transcripts and action items.

Auth: API key (Authorization: Bearer <key>)
Webhook: POST /webhooks/fireflies — new transcript ready event

Transcripts are chunked into Interaction records so the agent can
reference call content and action items in future pipeline runs.
"""
import hashlib
import hmac
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx
import structlog

log = structlog.get_logger()

FIREFLIES_GRAPHQL_URL = "https://api.fireflies.ai/graphql"


class FirefliesClient:
    """Async Fireflies.ai GraphQL client."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def _query(self, query: str, variables: Optional[dict] = None) -> dict:
        """Execute a GraphQL query against Fireflies API."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                FIREFLIES_GRAPHQL_URL,
                headers=self.headers,
                json={"query": query, "variables": variables or {}},
            )
            if resp.status_code == 401:
                log.error("fireflies_auth_failed")
                return {}
            if resp.status_code != 200:
                log.warning("fireflies_request_failed", status=resp.status_code)
                return {}
            return resp.json()

    async def get_transcripts(
        self,
        limit: int = 20,
        since_date: Optional[datetime] = None,
    ) -> list[dict]:
        """
        Fetch recent transcripts. Fireflies caps each page at 50 — paginates automatically.
        Returns list of transcript objects with id, title, date, participants, summary.
        """
        PAGE_SIZE = 50  # Fireflies hard limit per request

        query_template = """
        query GetTranscripts($limit: Int, $skip: Int) {{
          transcripts(limit: $limit, skip: $skip) {{
            id
            title
            date
            duration
            organizer_email
            participants{extra}
            summary {{
              keywords
              action_items
              overview
              shorthand_bullet
              bullet_gist
            }}
            sentences {{
              index
              speaker_name
              speaker_id
              text
              start_time
              end_time
            }}
          }}
        }}
        """
        extended_fields = """
            transcript_url
            meeting_attendees {
              displayName
              email
            }"""
        query = query_template.format(extra=extended_fields)
        # Extended fields may not exist on every Fireflies plan/schema version.
        # GraphQL fails the WHOLE query on an unknown field — fall back to the
        # legacy field set rather than silently losing all transcripts.
        legacy_query = query_template.format(extra="")

        all_transcripts: list[dict] = []
        skip = 0
        active_query = query

        while len(all_transcripts) < limit:
            page_limit = min(PAGE_SIZE, limit - len(all_transcripts))
            data = await self._query(active_query, {"limit": page_limit, "skip": skip})
            if data.get("errors") and active_query is query and not all_transcripts:
                log.warning(
                    "fireflies_extended_fields_unsupported",
                    errors=str(data["errors"])[:200],
                )
                active_query = legacy_query
                continue
            page = (data.get("data") or {}).get("transcripts") or []
            all_transcripts.extend(page)
            if len(page) < page_limit:
                break  # no more pages
            skip += page_limit

        # Filter by since_date client-side
        if since_date:
            since_ms = int(since_date.timestamp() * 1000)
            all_transcripts = [t for t in all_transcripts if (t.get("date") or 0) >= since_ms]

        log.info("fireflies_transcripts_fetched", count=len(all_transcripts))
        return all_transcripts

    async def get_transcript_by_id(self, transcript_id: str) -> Optional[dict]:
        """Fetch full transcript detail by ID."""
        query_template = """
        query GetTranscript($transcriptId: String!) {{
          transcript(id: $transcriptId) {{
            id
            title
            date
            duration
            organizer_email
            participants{extra}
            summary {{
              keywords
              action_items
              overview
              shorthand_bullet
              bullet_gist
            }}
            sentences {{
              index
              speaker_name
              speaker_id
              text
              start_time
              end_time
            }}
          }}
        }}
        """
        extended_fields = """
            transcript_url
            meeting_attendees {
              displayName
              email
            }"""
        data = await self._query(
            query_template.format(extra=extended_fields), {"transcriptId": transcript_id}
        )
        if data.get("errors"):
            # Extended fields unsupported on this plan — retry with legacy set
            log.warning("fireflies_detail_extended_unsupported", errors=str(data["errors"])[:200])
            data = await self._query(
                query_template.format(extra=""), {"transcriptId": transcript_id}
            )
        return data.get("data", {}).get("transcript")

    async def search_transcripts_by_keyword(
        self, keyword: str, limit: int = 10
    ) -> list[dict]:
        """Search transcripts by keyword (company name, deal name)."""
        query = """
        query SearchTranscripts($keyword: String!, $limit: Int) {
          transcripts(limit: $limit, title: $keyword) {
            id
            title
            date
            organizer_email
            participants
            summary {
              overview
              action_items
            }
          }
        }
        """
        data = await self._query(query, {"keyword": keyword, "limit": limit})
        return data.get("data", {}).get("transcripts", []) or []


def verify_fireflies_webhook(
    body: bytes,
    signature: str,
    secret: str,
) -> bool:
    """Verify Fireflies webhook HMAC-SHA256 signature."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


def transcript_to_interaction(transcript: dict, max_chars: int = 3000) -> dict:
    """
    Convert a Fireflies transcript to a Vantage Interaction record.

    Notes field: structured summary with overview + key moments
    Outcome field: action items extracted by Fireflies AI
    """
    summary = transcript.get("summary") or {}
    sentences = transcript.get("sentences") or []
    title = transcript.get("title", "Meeting")
    date_ms = transcript.get("date", 0)
    occurred_at = datetime.fromtimestamp(date_ms / 1000, tz=timezone.utc) if date_ms else None

    # Build notes: overview + speaker excerpts
    notes_parts = []
    overview = summary.get("overview") or summary.get("bullet_gist") or ""
    if overview:
        notes_parts.append(f"Overview: {overview[:500]}")

    keywords = summary.get("keywords", [])
    if keywords:
        notes_parts.append(f"Topics: {', '.join(keywords[:10])}")

    # Include top 20 speaker turns
    for s in sentences[:20]:
        speaker = s.get("speaker_name", "Unknown")
        text = s.get("text", "")
        if text:
            notes_parts.append(f"{speaker}: {text}")

    # Conversation stats line — reaches the researcher's transcript context
    # with zero prompt changes. Computed from the same sentence data.
    try:
        from app.services.conversation_intel import build_transcript_entry
        entry = build_transcript_entry(transcript)
        if entry.get("talk_ratio_rep") is not None or entry.get("buyer_question_count"):
            us = sum(1 for c in entry.get("commitments", []) if c.get("owner") == "us")
            buyer = sum(1 for c in entry.get("commitments", []) if c.get("owner") == "buyer")
            ratio = entry.get("talk_ratio_rep")
            notes_parts.insert(0, (
                "[Call stats] "
                + (f"rep talk {round(ratio * 100)}% | " if ratio is not None else "")
                + f"{entry.get('buyer_question_count', 0)} buyer questions | "
                + f"commitments: us {us}, buyer {buyer}"
            ))
    except Exception:  # stats are additive — never block the interaction
        pass

    notes = "\n".join(notes_parts)
    if len(notes) > max_chars:
        notes = notes[:max_chars] + "…"

    # Outcome = action items
    action_items = summary.get("action_items", [])
    if isinstance(action_items, list):
        outcome = "\n".join(f"• {a}" for a in action_items[:10]) if action_items else None
    else:
        outcome = str(action_items)[:500] if action_items else None

    return {
        "type": "call",
        "notes": notes or f"Fireflies transcript: {title}",
        "outcome": outcome,
        "source": "fireflies",
        "occurred_at": occurred_at.isoformat() if occurred_at else None,
        "fireflies_transcript_id": transcript.get("id"),
        "is_training_signal": False,
    }


def _extract_search_terms(account_name: str) -> list[str]:
    """
    Extract search terms from a deal name.
    Strips common HubSpot suffixes and returns candidate keywords.

    "Royal Canadian Mint - New Deal" → ["Royal Canadian Mint", "Royal Canadian"]
    "Sulzer" → ["Sulzer"]
    "Singapore Polytechnic (Global Foundaries)" → ["Singapore Polytechnic"]
    """
    import re
    # Strip common deal suffixes
    cleaned = re.sub(
        r"\s*[-–]\s*(New Deal|Pilot|Phase \d+|POC|Demo|Renewal|Expansion|Follow.?up).*$",
        "",
        account_name,
        flags=re.IGNORECASE,
    ).strip()
    # Strip parenthetical qualifiers
    cleaned = re.sub(r"\s*\(.*?\)", "", cleaned).strip()

    terms = [cleaned]
    # Also try first two words as a shorter form
    words = cleaned.split()
    if len(words) >= 3:
        terms.append(" ".join(words[:2]))
    return [t for t in terms if len(t) >= 3]


async def ingest_fireflies_for_account(
    client: FirefliesClient,
    account_name: str,
    since: Optional[datetime] = None,
) -> list[dict]:
    """
    Search Fireflies for transcripts related to an account.
    Strategy:
      1. Search by cleaned account name (strips "- New Deal" etc.)
      2. If nothing found: fetch all recent transcripts (30d) and fuzzy-match
         against the title using any key term from the account name.
    """
    if not client.api_key:
        return []

    search_terms = _extract_search_terms(account_name)
    transcripts: list[dict] = []

    # Try each search term until we get a hit
    for term in search_terms:
        results = await client.search_transcripts_by_keyword(term, limit=5)
        if results:
            transcripts = results
            break

    # Fallback: fetch recent transcripts and fuzzy-match titles client-side
    if not transcripts:
        cutoff_ms = int((since or (datetime.now(timezone.utc) - timedelta(days=60))).timestamp() * 1000)
        all_recent = await client.get_transcripts(limit=50)
        # Filter by date client-side (Fireflies API dateFilters not supported)
        all_recent = [t for t in all_recent if (t.get("date") or 0) >= cutoff_ms]

        account_words = set(w.lower() for w in account_name.split() if len(w) >= 4)
        for t in all_recent:
            title = t.get("title") or ""
            title_lower = title.lower()
            # Handle "Company ~ Invigilo AI" and "Invigilo AI ~ Company" formats
            # Strip known noise and check if any account word appears
            stripped = title_lower.replace("invigilo ai", "").replace("invigilo", "").replace("vishnu", "")
            if any(w in stripped for w in account_words):
                transcripts.append(t)
        transcripts = transcripts[:5]

    interactions = [transcript_to_interaction(t) for t in transcripts]
    log.info("fireflies_ingested", account=account_name, count=len(interactions))
    return interactions


# ── Matching constants ─────────────────────────────────────────────────────────

# Words stripped from transcript titles before name-matching
_TITLE_NOISE = {"invigilo", "invigilo ai", "vishnu", "saran", "anand", "kumar", "selma"}

# Seller-side email domains — never use these as a company identifier
_SELLER_DOMAINS = {"invigilo", "gmail", "hotmail", "outlook", "yahoo"}

# Generic subdomain prefixes that appear before the real company name in institutional
# email addresses (e.g. partner.nus.edu.sg → skip "partner", use "nus" instead)
# Also includes "tech" because tech.gov.sg → GovTech, not a company called "tech"
_GENERIC_SUBDOMAIN_PREFIXES = {
    "partner", "partners", "mail", "email", "info", "contact", "support",
    "portal", "app", "api", "help", "sales", "marketing", "hr", "admin",
    "noreply", "no-reply", "service", "services", "staff", "corp", "tech",
}

# Institutional domain markers — when encountered, stop walking labels.
# Anything before these is a department/agency name, not a commercial company.
_INSTITUTIONAL_MARKERS = {"gov", "edu", "ac", "mil", "sch"}

# Generic words too common to use as the sole identifier for an account
_GENERIC_WORDS = {
    # geographies
    "india", "china", "japan", "korea", "singapore", "malaysia", "australia",
    "thailand", "vietnam", "indonesia", "philippines", "global", "asia", "apac",
    "mena", "emea", "europe", "america", "americas",
    # org descriptors — also covers common deal name noise
    "demo", "group", "corp", "corporation", "limited", "holdings", "services",
    "solutions", "technologies", "technology", "systems", "international",
    "national", "digital", "capital", "ventures", "partners", "partner",
    "consulting", "management", "resources", "enterprises", "safety",
    "company", "companies", "business", "industrial", "industries",
    "tech", "northern", "southern", "eastern", "western", "central",
    # common words that appear in transcript titles but don't identify a company
    "from", "with", "about", "update", "meeting", "follow", "review",
    "discussion", "weekly", "monthly", "standup", "status", "project",
    "proposal", "pilot", "trial", "draft", "final", "round",
}

# Calendar bucket size: 15 minutes — transcripts starting within this window of a
# calendar event are considered the same meeting
_CAL_BUCKET_SECS = 900


def _domain_root(email: str) -> Optional[str]:
    """Extract the most-specific real company label from an email address.

    Skips generic subdomain prefixes and stops at institutional markers:
      'tomo@partner.nus.edu.sg'    → None  (edu = institutional, skip)
      'dawn@tech.gov.sg'           → None  (gov = institutional, skip)
      'nathan@westgold.com.au'     → 'westgold'
      'vishnu@invigilo.sg'         → 'invigilo'
      'info@aramco.com'            → 'aramco'
      'user@subsidiary.bigcorp.com'→ 'bigcorp' (skips generic subdomain)
    """
    parts = email.lower().split("@")
    if len(parts) != 2:
        return None
    labels = parts[1].split(".")
    # Walk labels left-to-right
    for label in labels:
        if len(label) < 3:
            continue
        # Institutional marker → emails from government/edu are not company-identifiable
        if label in _INSTITUTIONAL_MARKERS:
            return None
        # Stop at country-code / generic TLD segments
        if label in {"com", "org", "net", "int", "co", "sg", "au", "jp",
                     "uk", "ae", "sa", "in", "my", "id", "th", "vn", "ph"}:
            break
        if label not in _GENERIC_SUBDOMAIN_PREFIXES:
            return label
    return None


def _account_specific_words(account: dict) -> set[str]:
    """Specific (non-generic, ≥5 char) words from an account name."""
    import re
    name = (account.get("name") or "").lower()
    clean = re.sub(
        r"\s*[-–]\s*(new deal|pilot|phase \d+|poc|demo|renewal|expansion|follow.?up).*$",
        "", name, flags=re.IGNORECASE,
    ).strip()
    clean = re.sub(r"\s*\(.*?\)", "", clean).strip()
    return {w for w in clean.split() if len(w) >= 5} - _GENERIC_WORDS


def _score_transcript_against_account(
    title_lower: str,
    participants: list[str],
    t_date: Optional[datetime],
    account: dict,
    calendar_account_id: Optional[str] = None,
    ambiguous_words: Optional[set] = None,
) -> int:
    """
    Score a Fireflies transcript against one account.

      +4  calendar time match  — transcript time ±15 min matches an Outlook
                                 calendar event already linked to this account.
                                 Definitive: no other signal needed.
      +2  email domain match   — a non-seller participant's email domain root
                                 matches a specific word in the account name.
      +2  title word match     — transcript title contains a specific
                                 (non-generic) word from the account name.
      +1  date proximity       — transcript date falls inside the deal's active
                                 window (tiebreaker only; requires base ≥ 1).

    Match threshold: ≥ 2.
    Accounts whose names consist only of generic words score 0 on name/domain
    matching to prevent false positives (e.g. "Coca Cola India" → "india" alone
    won't match a transcript about the Indian market).
    """
    import re

    # ── Calendar match (definitive) ──────────────────────────────────────────
    if calendar_account_id and calendar_account_id == str(account.get("id")):
        return 4

    # ── Build specific word set from account name ────────────────────────────
    name = (account.get("name") or "").lower()
    clean = re.sub(
        r"\s*[-–]\s*(new deal|pilot|phase \d+|poc|demo|renewal|expansion|follow.?up).*$",
        "", name, flags=re.IGNORECASE,
    ).strip()
    clean = re.sub(r"\s*\(.*?\)", "", clean).strip()
    specific_words = _account_specific_words(account)
    # Portfolio-ambiguous words (e.g. "shell" across 4 Shell deals) can't
    # discriminate — a "Shell aviation" call once attached to ALL Shell deals.
    # Only the words unique to THIS account count as evidence.
    if ambiguous_words:
        specific_words = specific_words - ambiguous_words

    if not specific_words:
        return 0  # nothing specific enough to match against

    score = 0

    # ── Email domain match (+2) ──────────────────────────────────────────────
    for email in participants:
        root = _domain_root(email)
        if not root or root in _SELLER_DOMAINS:
            continue
        if any(root == w or root in w or w in root for w in specific_words):
            score += 2
            break

    # ── Title word match (+2) ────────────────────────────────────────────────
    stripped_title = title_lower
    for noise in _TITLE_NOISE:
        stripped_title = stripped_title.replace(noise, "")
    if clean in stripped_title or any(w in stripped_title for w in specific_words):
        score += 2

    # ── Date proximity (+1 tiebreaker) ───────────────────────────────────────
    if t_date and score >= 1:
        created_at = account.get("created_at")
        close_date = account.get("close_date")
        if close_date and not isinstance(close_date, datetime):
            close_date = datetime(close_date.year, close_date.month, close_date.day, tzinfo=timezone.utc)
        window_start = (created_at - timedelta(days=90)) if created_at else None
        window_end = (
            close_date + timedelta(days=180) if close_date
            else datetime.now(timezone.utc) + timedelta(days=30)
        )
        if (window_start is None or t_date >= window_start) and t_date <= window_end:
            score += 1

    return score


async def backfill_all_transcripts(
    client: FirefliesClient,
    accounts: list[dict],
    limit: int = 200,
    calendar_events: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Fetch up to `limit` Fireflies transcripts and match each one to accounts.

    Matching hierarchy (highest → lowest confidence):
      1. Calendar time match  — transcript time ±15 min matches an Outlook meeting
                                already linked to an account (requires Outlook sync).
      2. Email domain match   — participant email domain root matches a specific
                                word in the account name (non-seller, non-generic).
      3. Title word match     — specific account name words appear in transcript title.
      4. Date proximity       — tiebreaker only.

    `accounts` dicts need: id, workspace_id, name, created_at, close_date.
    `calendar_events` dicts (optional): account_id (str), occurred_at (datetime).
      Pass Interaction records with source='outlook', type='meeting'.
    """
    if not client.api_key or not accounts:
        return []

    # ── Build calendar time index: bucket → account_id ───────────────────────
    # Each bucket covers _CAL_BUCKET_SECS seconds; check ±1 adjacent bucket too.
    cal_index: dict[int, str] = {}
    for ev in (calendar_events or []):
        ev_time = ev.get("occurred_at")
        if ev_time and ev.get("account_id"):
            bucket = int(ev_time.timestamp() // _CAL_BUCKET_SECS)
            cal_index[bucket] = str(ev["account_id"])

    transcripts = await client.get_transcripts(limit=limit)
    log.info("fireflies_backfill_fetched", total=len(transcripts))

    # Words appearing in MULTIPLE account names ("shell" across 4 Shell deals)
    # cannot discriminate between them — exclude from name/domain evidence
    word_owners: dict[str, set] = {}
    for acc in accounts:
        for w in _account_specific_words(acc):
            word_owners.setdefault(w, set()).add(str(acc.get("id")))
    ambiguous_words = {w for w, owners in word_owners.items() if len(owners) > 1}
    if ambiguous_words:
        log.info("fireflies_ambiguous_words", words=sorted(ambiguous_words)[:15])

    results: list[dict] = []
    skipped_ambiguous = 0
    for t in transcripts:
        t_date_ms = t.get("date", 0)
        t_date = datetime.fromtimestamp(t_date_ms / 1000, tz=timezone.utc) if t_date_ms else None
        title_lower = (t.get("title") or "").lower()
        participants = [p.lower() for p in (t.get("participants") or [])]

        # Calendar lookup: check transcript's time bucket and neighbours
        calendar_account_id: Optional[str] = None
        if t_date and cal_index:
            t_bucket = int(t_date.timestamp() // _CAL_BUCKET_SECS)
            for b in (t_bucket - 1, t_bucket, t_bucket + 1):
                if b in cal_index:
                    calendar_account_id = cal_index[b]
                    break

        scored = [
            (acc, _score_transcript_against_account(
                title_lower, participants, t_date, acc,
                calendar_account_id=calendar_account_id,
                ambiguous_words=ambiguous_words,
            ))
            for acc in accounts
        ]
        matched = [(acc, s) for acc, s in scored if s >= 2]

        if matched:
            best_score = max(s for _, s in matched)
            best = [(acc, s) for acc, s in matched if s >= best_score]
            # A weak-evidence tie across multiple accounts means we don't
            # actually know whose call this is. Attaching it everywhere put
            # Shell Crux calls on Shell Seletar — no data beats wrong data.
            # Calendar matches (4) are definitive and never tie.
            if len(best) > 1 and best_score < 4:
                skipped_ambiguous += 1
                log.info(
                    "fireflies_match_ambiguous_skipped",
                    title=(t.get("title") or "")[:60],
                    tied_accounts=len(best),
                    score=best_score,
                )
                continue
            for acc, s in best:
                from app.services.conversation_intel import build_transcript_entry
                results.append({
                    "account_id": str(acc["id"]),
                    "workspace_id": str(acc["workspace_id"]),
                    "interaction": transcript_to_interaction(t),
                    # Full transcript-shaped entry — the nightly worker reads
                    # action_items/participants/etc. from this (the interaction
                    # dict has none of those fields; reading them from it was
                    # the hollow-transcript bug)
                    "entry": build_transcript_entry(t),
                })

    log.info(
        "fireflies_backfill_matched",
        matches=len(results),
        transcripts=len(transcripts),
        skipped_ambiguous=skipped_ambiguous,
    )
    return results
