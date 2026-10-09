from app.engine.intent import (active_intent_signals, classify_reply, has_negotiation_terms, intent_level,
                               LLMReplyClassifier)
from app.engine.profile import build_profile
from app.engine.scoring import compute_score
from app.engine.types import LeadContext
from helpers import Builder, at


def test_reply_classifier(cfg):
    assert classify_reply("Can you send pricing for 50 seats? We want to decide this quarter.", cfg) == "positive_intent"
    assert classify_reply("Not interested. Please remove me from your list.", cfg) == "negative"
    assert classify_reply("We already use HubSpot for this.", cfg) == "objection"
    assert classify_reply("No budget for this until next year.", cfg) == "objection"
    assert classify_reply("I'm out of office until Monday with limited access.", cfg) == "out_of_office"
    assert classify_reply("Thanks, will take a look.", cfg) == "neutral"
    assert classify_reply(None, cfg) == "neutral"


def test_llm_classifier_falls_back_to_keywords(cfg):
    assert LLMReplyClassifier(cfg).classify("remove me") == "negative"


def test_negotiation_terms(cfg):
    assert has_negotiation_terms("Can we discuss a discount and contract terms?", cfg)
    assert not has_negotiation_terms("Thanks!", cfg)


def test_intent_levels(cfg):
    assert intent_level(0, [], at(0), cfg) == "none"
    assert intent_level(5, [], at(0), cfg) == "low"
    assert intent_level(10, [], at(0), cfg) == "medium"
    assert intent_level(15, [], at(0), cfg) == "high"
    assert intent_level(21, [], at(0), cfg) == "hot"


def test_active_signals(cfg):
    b = Builder()
    b.capture(cfg)
    b.page("pricing", 1)
    b.page("pricing", 10)
    b.page("pricing", 30)
    b.ev("demo_request", 31)
    evs = b.sorted()
    s = compute_score(build_profile(evs, cfg), evs, at(32), LeadContext(), cfg)
    sig = active_intent_signals(s.factors, evs, at(32), cfg)
    assert "pricing_page_x3_48h" in sig and "demo_request" in sig and "intent_burst" in sig
    assert s.active_signals == sig


def test_positive_reply_counts_as_intent(cfg):
    b = Builder()
    b.capture(cfg)
    b.reply("What does pricing look like for our team? Budget is around $40k.", 2)
    evs = b.sorted()
    s = compute_score(build_profile(evs, cfg), evs, at(2), LeadContext(), cfg)
    assert "intent.positive_reply_intent" in s.factors
    assert build_profile(evs, cfg).budget == 40000
