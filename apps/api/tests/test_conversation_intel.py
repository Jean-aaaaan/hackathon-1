"""Unit tests for the conversation intelligence helpers — pure functions, no I/O."""
from app.services.conversation_intel import (
    build_transcript_entry,
    compute_speaker_stats,
    identify_rep_speakers,
    attribute_commitments,
    compute_conversation_rollup,
    merge_transcript_entries,
    extract_buyer_questions,
)

SYNTH_TRANSCRIPT = {
    "id": "ff-001",
    "title": "Vantage x Acme — discovery",
    "date": 1760000000000,
    "duration": 1800,  # seconds
    "organizer_email": "rep@acmecorp.com",
    "participants": ["rep@acmecorp.com", "sarah.lee@acme.com", "cfo@acme.com"],
    "meeting_attendees": [
        {"displayName": "Alex Johnson", "email": "rep@acmecorp.com"},
        {"displayName": "Sarah Lee", "email": "sarah.lee@acme.com"},
        {"displayName": "Tom Chen", "email": "cfo@acme.com"},
    ],
    "transcript_url": "https://app.fireflies.ai/view/ff-001",
    "summary": {
        "overview": "Discovery call about the platform.",
        "keywords": ["platform", "integration"],
        "action_items": [
            "**Alex** Send the proposal by Friday (12:03)",
            "**Sarah** Share the security questionnaire (24:10)",
            "Review budget internally",
        ],
    },
    "sentences": [
        {"speaker_name": "Alex Johnson", "text": "Let me walk you through the platform.", "start_time": 0, "end_time": 60},
        {"speaker_name": "Alex Johnson", "text": "It integrates with your existing tools.", "start_time": 60, "end_time": 120},
        {"speaker_name": "Sarah Lee", "text": "How does the data privacy side work exactly?", "start_time": 120, "end_time": 150},
        {"speaker_name": "Tom Chen", "text": "What does this cost at our scale of two hundred seats?", "start_time": 150, "end_time": 180},
        {"speaker_name": "Alex Johnson", "text": "Good questions, let me answer both.", "start_time": 180, "end_time": 200},
    ],
}


def test_rep_speakers_identified():
    reps = identify_rep_speakers(SYNTH_TRANSCRIPT)
    assert "alex johnson" in reps
    assert not any("sarah" in r for r in reps)


def test_speaker_stats_and_ratio():
    reps = identify_rep_speakers(SYNTH_TRANSCRIPT)
    stats, ratio = compute_speaker_stats(SYNTH_TRANSCRIPT["sentences"], reps)
    assert stats["Alex Johnson"]["talk_time_pct"] == 70.0  # 140s of 200s
    assert stats["Sarah Lee"]["talk_time_pct"] == 15.0
    assert ratio == 0.7


def test_speaker_stats_word_fallback_without_timings():
    sentences = [
        {"speaker_name": "A", "text": "one two three four"},
        {"speaker_name": "B", "text": "five six"},
    ]
    stats, _ = compute_speaker_stats(sentences, set())
    assert stats["A"]["talk_time_pct"] > stats["B"]["talk_time_pct"]


def test_buyer_questions_exclude_rep():
    reps = identify_rep_speakers(SYNTH_TRANSCRIPT)
    qs = extract_buyer_questions(SYNTH_TRANSCRIPT["sentences"], reps)
    assert len(qs) == 2
    assert all(q["speaker"] in ("Sarah Lee", "Tom Chen") for q in qs)


def test_commitment_attribution():
    reps = identify_rep_speakers(SYNTH_TRANSCRIPT)
    attendees = [{"name": "Sarah Lee", "email": "sarah.lee@acme.com"}]
    commitments = attribute_commitments(
        SYNTH_TRANSCRIPT["summary"]["action_items"], reps, attendees
    )
    owners = {c["text"][:10]: c["owner"] for c in commitments}
    assert owners["Alex Send "] == "us"
    assert owners["Sarah Shar"] == "buyer"
    assert owners["Review budge"] == "unknown"


def test_commitment_header_format():
    """Fireflies' dominant format: name headers, then that person's tasks."""
    reps = identify_rep_speakers(SYNTH_TRANSCRIPT)
    attendees = [{"name": "Kenneth Edwards", "email": "ken@buyer.com"}]
    items = [
        "**Alex Johnson**",
        "Check with team to confirm sandbox access (27:20)",
        "Provide sandbox environment access (31:30)",
        "**Kenneth Edwards**",
        "Review platform once access is granted (27:40)",
        "**Jonathan Kramer**",
        "Arrange meeting early next week (29:30)",
    ]
    commitments = attribute_commitments(items, reps, attendees)
    # Headers are NOT commitments
    assert len(commitments) == 4
    assert all(c["text"] not in ("Alex Johnson", "Kenneth Edwards", "Jonathan Kramer") for c in commitments)
    assert commitments[0]["owner"] == "us" and "sandbox access" in commitments[0]["text"]
    assert commitments[1]["owner"] == "us"
    assert commitments[2]["owner"] == "buyer" and commitments[2]["owner_name"] == "Kenneth Edwards"
    # Jonathan is not in attendees — unknown side, but context name retained
    assert commitments[3]["owner"] == "unknown"
    assert commitments[3]["owner_name"] == "Jonathan Kramer"


def test_build_entry_full_shape():
    entry = build_transcript_entry(SYNTH_TRANSCRIPT)
    assert entry["id"] == "ff-001"
    assert entry["transcript_url"].endswith("ff-001")
    assert entry["duration_minutes"] == 30
    assert entry["talk_ratio_rep"] == 0.7
    assert entry["buyer_question_count"] == 2
    assert len(entry["commitments"]) == 3
    assert entry["speaker_stats"]["Tom Chen"]["sentences"] == 1


def test_merge_dedup_and_cap():
    older = [{"id": "a", "date": 1}, {"id": "b", "date": 2}]
    newer = [{"id": "b", "date": 2}, {"id": "c", "date": 3}]
    merged = merge_transcript_entries(older, newer, cap=2)
    assert [t["id"] for t in merged] == ["c", "b"]


def test_rollup_eb_attendance_and_commitments():
    entry = build_transcript_entry(SYNTH_TRANSCRIPT)
    stakeholders = [{"name": "Tom Chen", "email": "cfo@acme.com", "role": "economic_buyer"}]
    rollup = compute_conversation_rollup([entry], stakeholders)
    assert rollup["eb_identified"] is True
    assert rollup["eb_attendance"] is True
    assert rollup["calls_total"] == 1
    assert rollup["avg_talk_ratio_rep"] == 0.7
    assert len(rollup["open_buyer_commitments"]) == 1
    assert rollup["open_buyer_commitments"][0]["call_title"] == "Vantage x Acme — discovery"


def test_rollup_eb_never_attended():
    entry = build_transcript_entry(SYNTH_TRANSCRIPT)
    stakeholders = [{"name": "Maria Garcia", "email": "maria@acme.com", "role": "economic_buyer"}]
    rollup = compute_conversation_rollup([entry], stakeholders)
    assert rollup["eb_identified"] is True
    assert rollup["eb_attendance"] is False


def test_empty_transcript_degrades_gracefully():
    entry = build_transcript_entry({"id": "x", "title": "t"})
    assert entry["speaker_stats"] == {}
    assert entry["talk_ratio_rep"] is None
    assert entry["buyer_questions"] == []
    rollup = compute_conversation_rollup([entry], [])
    assert rollup["avg_talk_ratio_rep"] is None
    assert rollup["last_call_date"] is None
