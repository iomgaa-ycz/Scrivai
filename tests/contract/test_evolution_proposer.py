"""Proposer 合约测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from scrivai.models.evolution import EvolutionProposal, FailureSample


def _mk_failure(i: int) -> FailureSample:
    return FailureSample(
        feedback_id=i,
        run_id=f"r-{i}",
        task_prompt=f"task-{i}",
        question=f"q-{i}",
        draft_output_str='{"x":"draft"}',
        ground_truth_str='{"x":"final"}',
        baseline_score=0.3,
        confidence=0.9,
        trajectory_summary={"plan": "p", "execute": "e", "summarize": "s"},
    )


def _fake_llm_response(n: int) -> str:
    proposals = []
    for i in range(n):
        proposals.append(
            {
                "change_summary": f"proposal {i}",
                "reasoning": f"reason {i}",
                "new_content": {"SKILL.md": f"# new {i}"},
            }
        )
    return json.dumps({"proposals": proposals}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_propose_parses_n_proposals():
    from scrivai.evolution.proposer import Proposer

    mock_client = MagicMock()
    mock_client.simple_query = AsyncMock(return_value=_fake_llm_response(3))
    p = Proposer(mock_client)
    out = await p.propose(
        current_skill_snapshot={"SKILL.md": "# current"},
        failures=[_mk_failure(1), _mk_failure(2)],
        rejected_proposals=[],
        n=3,
    )
    assert len(out) == 3
    assert all(isinstance(x, EvolutionProposal) for x in out)
    assert out[0].new_content_snapshot["SKILL.md"] == "# new 0"


@pytest.mark.asyncio
async def test_propose_prompt_contains_required_elements():
    from scrivai.evolution.proposer import Proposer

    captured = {}

    async def capture(prompt, **kw):
        captured["prompt"] = prompt
        return _fake_llm_response(1)

    mock_client = MagicMock()
    mock_client.simple_query = capture
    p = Proposer(mock_client)
    await p.propose(
        current_skill_snapshot={"SKILL.md": "# current baseline"},
        failures=[_mk_failure(1)],
        rejected_proposals=[
            EvolutionProposal(
                new_content_snapshot={},
                change_summary="rejected direction",
                reasoning="x",
            )
        ],
        n=1,
    )
    prompt = captured["prompt"]
    assert "current baseline" in prompt
    assert "q-1" in prompt
    assert "rejected direction" in prompt
    assert "proposals" in prompt


@pytest.mark.asyncio
async def test_propose_budget_consumed():
    from scrivai.evolution.budget import LLMCallBudget
    from scrivai.evolution.proposer import Proposer

    mock_client = MagicMock()
    mock_client.simple_query = AsyncMock(return_value=_fake_llm_response(1))
    b = LLMCallBudget(limit=5)
    p = Proposer(mock_client)
    await p.propose(
        current_skill_snapshot={"SKILL.md": "# x"},
        failures=[],
        rejected_proposals=[],
        n=1,
        budget=b,
    )
    assert b.used == 1


@pytest.mark.asyncio
async def test_propose_invalid_json_raises():
    from scrivai.evolution.proposer import Proposer, ProposerError

    mock_client = MagicMock()
    mock_client.simple_query = AsyncMock(return_value="not json at all")
    p = Proposer(mock_client)
    with pytest.raises(ProposerError):
        await p.propose(
            current_skill_snapshot={},
            failures=[],
            rejected_proposals=[],
            n=1,
        )
