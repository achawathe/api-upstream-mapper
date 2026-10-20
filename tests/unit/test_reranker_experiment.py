"""Experimental selection parsing cannot turn invalid or prohibited choices into mappings."""

import json

from experiments.local_reranker.compare import decision
from experiments.local_reranker.dataset import completion_tokens
from experiments.local_reranker.evaluate import parse_choice, summary


def test_reranker_rejects_non_contract_answers():
    payload = {"candidates": [{"candidate_id": "C1"}, {"candidate_id": "C2", "prohibited": True}]}
    assert parse_choice('{"candidate_id":"C1"}', payload) == "C1"
    assert parse_choice('{"candidate_id":"NONE"}', payload) == "NONE"
    for raw in (
        '{"candidate_id":"C2"}',
        '{"candidate_id":"C99"}',
        '{"candidate_id":["C1"]}',
        '{"candidate_id":"C1","reason":"trust me"}',
        "C1",
        '{"candidate_id":true}',
    ):
        assert parse_choice(raw, payload) is None


def test_order_sensitivity_and_invalid_outputs_remain_visible():
    rows = [
        {"case": 1, "order": "original", "actual": "C1", "outcome": "correct", "seconds": 1},
        {"case": 1, "order": "reversed", "actual": None, "outcome": "invalid", "seconds": 2},
    ]
    result = summary(rows)
    assert result["order_changes"] == 1
    assert result["original"]["correct"] == 1
    assert result["reversed"]["invalid"] == 1


def test_training_uses_the_inference_prefix_and_literal_answer():
    class Tokenizer:
        eos_token_id = 99

        def apply_chat_template(self, messages, **options):
            assert options == {"add_generation_prompt": True, "return_dict": False, "enable_thinking": False}
            assert all(message["role"] != "assistant" for message in messages)
            return [1, 2, 3]

        def encode(self, text, **options):
            assert text == '{"candidate_id":"NONE"}'
            assert options == {"add_special_tokens": False}
            return [4, 5]

    row = {
        "messages": [
            {"role": "user", "content": "API details"},
            {"role": "assistant", "content": '{"candidate_id":"NONE"}'},
        ]
    }
    assert completion_tokens(row, Tokenizer()) == ([1, 2, 3, 4, 5, 99], 3)


def test_more_correct_choices_cannot_hide_a_lost_working_origin(tmp_path):
    for dataset in ("heldout", "docs", "public"):
        for model in ("base", "trained"):
            folder = tmp_path / f"{model}-{dataset}"
            folder.mkdir()
            counts = {
                "correct": 5 if model == "trained" else 4,
                "wrong": 0,
                "missed": 1 if model == "trained" else 2,
                "abstained": 2,
                "invalid": 0,
                "cases": 8,
            }
            (folder / "summary.json").write_text(json.dumps({order: counts for order in ("original", "reversed")}))
    folder = tmp_path / "public-inputs"
    folder.mkdir()
    (folder / "focused-manifest.json").write_text(
        json.dumps({"cases": [{"baseline": "source", "expected": ["source"]}]})
    )
    (tmp_path / "trained-public/results.json").write_text(json.dumps([{"case": 0, "outcome": "missed"}]))
    result = decision(tmp_path)
    assert not result["passes_focused_gate"]
    assert "public: an existing correct origin was lost" in result["reasons"]
