from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
from cash_research.artifacts import archive_artifact
from cash_research.memory import MemoryReadError, apply_lesson, apply_topic, recall_memory
from cash_research.memory import MemoryRequestError
from cash_research.models import Lesson, TopicSummary

ROOT = Path(__file__).parents[2]
PATHS = {n: ROOT/"fixtures"/"scenarios"/n/"cases.json" for n in ("periodic-delta","long-term-thesis","deep-analysis-revision")}
def load(n): return json.loads(PATHS[n].read_text(encoding="utf-8"))
def dt(value): return datetime.fromisoformat(value.replace("Z","+00:00"))
def write_sources(root, payload):
    for name, value in payload.get("sources",{}).items(): (root/name).write_text(json.dumps(value),encoding="utf-8")
def content(root, pub): return json.loads((root/pub.packet.content_ref).read_text(encoding="utf-8"))

def test_seed_candidates_are_valid_reproducible_and_not_symbolic_only():
    periodic, thesis = load("periodic-delta"), load("long-term-thesis")
    candidates = periodic["candidates"] + thesis["candidates"]
    assert all(c["proposal"] and c["known_at"] and c["index_metadata"] for c in candidates)
    duplicate = next(c for c in candidates if c.get("duplicate_of"))
    assert duplicate["duplicate_of"] == "verify-order-to-revenue"
    cross = thesis["candidates"][0]["proposal"]
    assert cross["applies_when"] and cross["counterexamples"] and cross["source_refs"]
    expected = thesis["cases"][0]["expected"]["selected"][0]
    assert expected == "data/lessons/qualification-conversion/versions/1.json"

def seed_candidates(root, payload, monkeypatch):
    import cash_research.memory as m
    write_sources(root,payload)
    for candidate in payload.get("candidates",[]):
        monkeypatch.setattr(m,"_utc_now",lambda s=candidate["known_at"]:dt(s))
        proposal={**candidate["proposal"],**candidate["index_metadata"]}
        if candidate.get("duplicate_of"): proposal["duplicate_of"]=candidate["duplicate_of"]
        (apply_topic if candidate["kind"]=="topic" else apply_lesson)(root=root,proposal=proposal,expected_version=0)

def test_query_only_paraphrase_dedupes_and_excludes_unrelated(tmp_path,monkeypatch):
    payload=load("periodic-delta"); seed_candidates(tmp_path,payload,monkeypatch)
    pub=recall_memory(root=tmp_path,request={"request_id":"search","query":payload["cases"][0]["query"],"context_mode":"current","as_of":"2026-03-01T00:00:00Z","budget":{"max_items":10,"max_chars":12000}})
    refs=set(pub.packet.selected_refs)
    assert refs==set(payload["cases"][0]["expected"]["selected"])
    assert any(item.startswith("duplicate:") for item in pub.packet.exclusions)
    assert any(item=="unrelated:lessons:unrelated-fx" for item in pub.packet.exclusions)

def test_structured_method_recall_crosses_security_and_preserves_conditions(tmp_path,monkeypatch):
    payload=load("long-term-thesis"); seed_candidates(tmp_path,payload,monkeypatch)
    case=payload["cases"][0]
    pub=recall_memory(root=tmp_path,request={"request_id":"cross","query":case["query"],"query_metadata":case["query_metadata"],"context_mode":"current","as_of":"2026-03-01T00:00:00Z","budget":{"max_items":5,"max_chars":5000}})
    item=content(tmp_path,pub)["items"][0]
    assert item["applies_when"] and item["counterexamples"]
    assert pub.packet.selected_refs==(case["expected"]["selected"][0],)

def test_zero_match_real_baseline_is_normal(tmp_path):
    case=load("periodic-delta")["cases"][1]
    pub=recall_memory(root=tmp_path,request={"request_id":"zero","query":case["query"],"context_mode":"current","as_of":"2026-09-21T00:00:00Z","topic_ids":["new-theme"],"lesson_ids":[],"budget":{"max_items":5,"max_chars":5000}})
    assert content(tmp_path,pub)["items"]==[]
    assert "no_history:topics:new-theme" in pub.packet.exclusions

def test_later_formed_summary_of_old_material_is_excluded(tmp_path,monkeypatch):
    import cash_research.memory as m
    payload=load("deep-analysis-revision"); write_sources(tmp_path,payload)
    monkeypatch.setattr(m,"_utc_now",lambda:dt("2026-03-01T00:00:00Z"))
    apply_topic(root=tmp_path,proposal={"topic_id":"revision","current_thesis":"Old source summarized later.","support_refs":["source-old.json"],"opposing_refs":[],"changes":[],"open_questions":["recompute"],"next_checks":["reopen inputs"]},expected_version=0)
    pub=recall_memory(root=tmp_path,request={"request_id":"later","query":"historical","context_mode":"historical","as_of":"2026-02-01T00:00:00Z","topic_ids":["revision"],"lesson_ids":[],"budget":{"max_items":5,"max_chars":5000}})
    assert content(tmp_path,pub)["items"]==[]
    assert "formed_after_cutoff:topics:revision" in pub.packet.exclusions

def test_historical_v1_selected_but_current_superseded_v2_excluded(tmp_path,monkeypatch):
    import cash_research.memory as m
    payload=load("long-term-thesis"); write_sources(tmp_path,payload)
    base={"lesson_id":"demand-proxy","check_or_method":"Check demand proxy.","applies_when":"Demand data lags.","source_refs":["source-qualification.json"],"counterexamples":["Inventory can distort proxy."],"review_condition":"Review after actual demand."}
    monkeypatch.setattr(m,"_utc_now",lambda:dt("2026-02-01T00:00:00Z")); apply_lesson(root=tmp_path,proposal={**base,"validity":"usable"},expected_version=0)
    monkeypatch.setattr(m,"_utc_now",lambda:dt("2026-04-01T00:00:00Z")); apply_lesson(root=tmp_path,proposal={**base,"validity":"superseded"},expected_version=1)
    req={"request_id":"hist","query":"proxy","context_mode":"historical","as_of":"2026-03-01T00:00:00Z","topic_ids":[],"lesson_ids":["demand-proxy"],"budget":{"max_items":5,"max_chars":5000}}
    assert content(tmp_path,recall_memory(root=tmp_path,request=req))["items"][0]["version"]==1
    req.update(request_id="current",context_mode="current",as_of="2026-05-01T00:00:00Z")
    pub=recall_memory(root=tmp_path,request=req); assert content(tmp_path,pub)["items"]==[]
    assert "superseded_at_cutoff:lessons:demand-proxy" in pub.packet.exclusions

def test_later_duplicate_relation_does_not_suppress_historical_version(tmp_path,monkeypatch):
    import cash_research.memory as m
    write_sources(tmp_path,load("periodic-delta"))
    canonical={"lesson_id":"canonical","check_or_method":"Verify acceptance.","applies_when":"Orders precede revenue.","source_refs":["source-baseline.json"],"counterexamples":["Cancelable order."],"validity":"usable","review_condition":"Review shipment.","methods":["order-to-revenue"],"aliases":["订单兑现"]}
    evolving={**canonical,"lesson_id":"evolving"}
    monkeypatch.setattr(m,"_utc_now",lambda:dt("2026-02-01T00:00:00Z")); apply_lesson(root=tmp_path,proposal=canonical,expected_version=0); apply_lesson(root=tmp_path,proposal=evolving,expected_version=0)
    monkeypatch.setattr(m,"_utc_now",lambda:dt("2026-04-01T00:00:00Z")); apply_lesson(root=tmp_path,proposal={**evolving,"duplicate_of":"canonical"},expected_version=1)
    base={"query":"订单兑现","context_mode":"historical","topic_ids":[],"lesson_ids":[],"budget":{"max_items":10,"max_chars":10000}}
    historical=recall_memory(root=tmp_path,request={**base,"request_id":"hist-dedupe","as_of":"2026-03-01T00:00:00Z"})
    assert set(historical.packet.selected_refs)=={"data/lessons/canonical/versions/1.json","data/lessons/evolving/versions/1.json"}
    current=recall_memory(root=tmp_path,request={**base,"request_id":"current-dedupe","as_of":"2026-05-01T00:00:00Z"})
    assert current.packet.selected_refs==("data/lessons/canonical/versions/1.json",)
    assert any(value.startswith("duplicate:data/lessons/evolving/versions/2.json") for value in current.packet.exclusions)

def test_missing_intermediate_version_is_real_read_error(tmp_path,monkeypatch):
    import cash_research.memory as m
    write_sources(tmp_path,load("deep-analysis-revision"))
    proposal={"topic_id":"missing-chain","current_thesis":"v","support_refs":["source-old.json"],"opposing_refs":[],"changes":[],"open_questions":[],"next_checks":["recompute"]}
    for version,stamp in enumerate(("2026-02-01T00:00:00Z","2026-03-01T00:00:00Z","2026-04-01T00:00:00Z")):
        monkeypatch.setattr(m,"_utc_now",lambda s=stamp:dt(s)); apply_topic(root=tmp_path,proposal=proposal,expected_version=version)
    (tmp_path/"data/topics/missing-chain/versions/2.json").unlink()
    with pytest.raises(MemoryReadError,match="incomplete"):
        recall_memory(root=tmp_path,request={"request_id":"missing","query":"history","context_mode":"historical","as_of":"2026-03-15T00:00:00Z","topic_ids":["missing-chain"],"lesson_ids":[],"budget":{"max_items":5,"max_chars":5000}})

def test_review_uses_frozen_original_packet_and_later_partition(tmp_path,monkeypatch):
    import cash_research.memory as m
    write_sources(tmp_path,load("deep-analysis-revision"))
    monkeypatch.setattr(m,"_utc_now",lambda:dt("2026-02-01T00:00:00Z"))
    apply_topic(root=tmp_path,proposal={"topic_id":"review-topic","current_thesis":"original","support_refs":["source-old.json"],"opposing_refs":[],"changes":[],"open_questions":[],"next_checks":["watch"]},expected_version=0)
    original=recall_memory(root=tmp_path,request={"request_id":"original","query":"decision","context_mode":"historical","as_of":"2026-02-01T00:00:00Z","topic_ids":["review-topic"],"lesson_ids":[],"budget":{"max_items":5,"max_chars":5000}})
    draft={"decision_id":"draft","security_or_topic":"synthetic topic","as_of":"2026-02-01T00:00:00Z","label":"watch","reason_refs":[],"price_or_conditions":None,"price_or_conditions_reason":"not applicable","evidence_limited":False,"limitations":[],"horizon":"one quarter","risks":[],"invalidators":[],"previous_id":None,"memory_packet_refs":[original.packet_ref]}
    (tmp_path/"decision.json").write_text(json.dumps(draft),encoding="utf-8")
    decision=archive_artifact(root=tmp_path,draft_ref="decision.json",record_type="Decision")
    monkeypatch.setattr(m,"_utc_now",lambda:dt("2026-04-01T00:00:00Z"))
    apply_topic(root=tmp_path,proposal={"topic_id":"review-topic","current_thesis":"revised","support_refs":["source-later.json"],"opposing_refs":["source-old.json"],"changes":["assumption changed"],"open_questions":["recompute dependency"],"next_checks":["rerun"]},expected_version=1)
    pub=recall_memory(root=tmp_path,request={"request_id":"review","query":"review","context_mode":"review","as_of":"2026-02-01T00:00:00Z","review_at":"2026-05-01T00:00:00Z","decision_id":decision.record_id,"topic_ids":["review-topic"],"lesson_ids":[],"budget":{"max_items":10,"max_chars":12000}})
    value=content(tmp_path,pub); assert value["original_inputs"] and value["later_facts_and_lessons"]
    assert "original" in json.dumps(value["original_inputs"])
    assert value["later_facts_and_lessons"][0]["current_thesis"]=="revised"

def test_budget_real_recall_returns_full_index(tmp_path,monkeypatch):
    import cash_research.memory as m
    write_sources(tmp_path,load("deep-analysis-revision"))
    monkeypatch.setattr(m,"_utc_now",lambda:dt("2026-02-01T00:00:00Z"))
    apply_lesson(root=tmp_path,proposal={"lesson_id":"budget","check_or_method":"x"*1000,"applies_when":"condition retained","source_refs":["source-old.json"],"counterexamples":["counterevidence retained"],"validity":"usable","review_condition":"review"},expected_version=0)
    pub=recall_memory(root=tmp_path,request={"request_id":"budget","query":"budget","context_mode":"historical","as_of":"2026-03-01T00:00:00Z","topic_ids":[],"lesson_ids":["budget"],"budget":{"max_items":1,"max_chars":300}})
    value=content(tmp_path,pub); assert value["items"]==[] and (tmp_path/value["full_index_ref"]).is_file()

def test_no_return_or_exact_wording_proxy():
    text=" ".join(p.read_text(encoding="utf-8").lower() for p in PATHS.values())
    assert all(term not in text for term in ("stock_return","price_return","exact_text_match"))

def test_query_metadata_shape_is_strict_and_old_models_default_empty(tmp_path):
    with pytest.raises(MemoryRequestError):
        recall_memory(root=tmp_path,request={"request_id":"bad","query":"q","query_metadata":{"unknown":[]},"context_mode":"current","as_of":"2026-03-01T00:00:00Z","budget":{"max_items":1,"max_chars":100}})
    with pytest.raises(MemoryRequestError):
        recall_memory(root=tmp_path,request={"request_id":"bad2","query":"q","query_metadata":{"topics":"not-list"},"context_mode":"current","as_of":"2026-03-01T00:00:00Z","budget":{"max_items":1,"max_chars":100}})
    topic=TopicSummary.model_validate({"topic_id":"old","version":1,"known_at":"2026-01-01T00:00:00Z","updated_at":"2026-01-01T00:00:00Z","current_thesis":"x","support_refs":[],"opposing_refs":[],"changes":[],"open_questions":[],"next_checks":[]})
    lesson=Lesson.model_validate({"lesson_id":"old","version":1,"check_or_method":"x","applies_when":"y","source_refs":[],"counterexamples":[],"validity":"usable","review_condition":"z","known_at":"2026-01-01T00:00:00Z","updated_at":"2026-01-01T00:00:00Z"})
    assert topic.aliases==() and lesson.duplicate_of is None

def test_duplicate_cycle_retains_records_with_explicit_exclusion(tmp_path,monkeypatch):
    import cash_research.memory as m
    write_sources(tmp_path,load("periodic-delta")); monkeypatch.setattr(m,"_utc_now",lambda:dt("2026-02-01T00:00:00Z"))
    base={"check_or_method":"check","applies_when":"condition","source_refs":["source-baseline.json"],"counterexamples":["counter"],"validity":"usable","review_condition":"review","methods":["cycle"],"aliases":["循环"]}
    apply_lesson(root=tmp_path,proposal={**base,"lesson_id":"a","duplicate_of":"b"},expected_version=0)
    apply_lesson(root=tmp_path,proposal={**base,"lesson_id":"b","duplicate_of":"a"},expected_version=0)
    pub=recall_memory(root=tmp_path,request={"request_id":"cycle","query":"循环","context_mode":"current","as_of":"2026-03-01T00:00:00Z","budget":{"max_items":5,"max_chars":5000}})
    assert len(pub.packet.selected_refs)==2
    assert sum(value.startswith("duplicate_relation_unresolved:") for value in pub.gaps)==2

def test_query_only_state_supports_expected_version_apply_roundtrip(tmp_path,monkeypatch):
    import cash_research.memory as m
    payload=load("long-term-thesis"); seed_candidates(tmp_path,payload,monkeypatch)
    case=payload["cases"][0]
    pub=recall_memory(root=tmp_path,request={"request_id":"state","query":case["query"],"query_metadata":case["query_metadata"],"context_mode":"current","as_of":"2026-03-01T00:00:00Z","budget":{"max_items":5,"max_chars":5000}})
    state=json.loads((tmp_path/pub.state_ref).read_text(encoding="utf-8"))
    entry=next(item for item in state["entries"] if item["memory_id"]=="qualification-conversion")
    expected=entry["expected_version"]
    proposal={**payload["candidates"][0]["proposal"],**payload["candidates"][0]["index_metadata"],"review_condition":"updated review"}
    monkeypatch.setattr(m,"_utc_now",lambda:dt("2026-03-02T00:00:00Z"))
    assert apply_lesson(root=tmp_path,proposal=proposal,expected_version=expected).version==2
    assert content(tmp_path,pub)["query_metadata"]["methods"]==["qualification-to-revenue"]

def test_common_words_do_not_select_unrelated_memory(tmp_path,monkeypatch):
    import cash_research.memory as m
    write_sources(tmp_path,load("periodic-delta")); monkeypatch.setattr(m,"_utc_now",lambda:dt("2026-02-01T00:00:00Z"))
    apply_lesson(root=tmp_path,proposal={"lesson_id":"common","check_or_method":"the method to check the result","applies_when":"the input is available","source_refs":["source-baseline.json"],"counterexamples":["the other case"],"validity":"usable","review_condition":"review","topics":["unrelated"]},expected_version=0)
    pub=recall_memory(root=tmp_path,request={"request_id":"common","query":"the and to of","context_mode":"current","as_of":"2026-03-01T00:00:00Z","budget":{"max_items":5,"max_chars":5000}})
    assert pub.packet.selected_refs==()

def test_same_market_exchange_different_security_does_not_match(tmp_path,monkeypatch):
    import cash_research.memory as m
    write_sources(tmp_path,load("periodic-delta")); monkeypatch.setattr(m,"_utc_now",lambda:dt("2026-02-01T00:00:00Z"))
    apply_topic(root=tmp_path,proposal={"topic_id":"msft-only","current_thesis":"Issuer-specific operating update","support_refs":["source-baseline.json"],"opposing_refs":[],"changes":[],"open_questions":[],"next_checks":["review operations"],"securities":["US:XNAS:MSFT"]},expected_version=0)
    apply_topic(root=tmp_path,proposal={"topic_id":"aapl-only","current_thesis":"Issuer-specific operating update","support_refs":["source-baseline.json"],"opposing_refs":[],"changes":[],"open_questions":[],"next_checks":["review operations"],"securities":["US:XNAS:AAPL"]},expected_version=0)
    pub=recall_memory(root=tmp_path,request={"request_id":"aapl","query":"Review US:XNAS:AAPL company update","context_mode":"current","as_of":"2026-03-01T00:00:00Z","budget":{"max_items":5,"max_chars":5000}})
    assert pub.packet.selected_refs==("data/topics/aapl-only/versions/1.json",)
    assert "unrelated:topics:msft-only" in pub.packet.exclusions

    structured=recall_memory(root=tmp_path,request={"request_id":"aapl-structured","query":"issuer review","query_metadata":{"securities":["US XNAS AAPL"]},"context_mode":"current","as_of":"2026-03-01T00:00:00Z","budget":{"max_items":5,"max_chars":5000}})
    assert structured.packet.selected_refs==("data/topics/aapl-only/versions/1.json",)
