from __future__ import annotations

import hashlib
import re
from collections import Counter

from mas_experiment.hiddenbench_data import HiddenBenchTask
from mas_experiment.hiddenbench_domain import (
    AGENT_IDS,
    HiddenBenchAssignment,
    HiddenBenchMessage,
)
from mas_experiment.hiddenbench_dynamic_domain import (
    DynamicSelectorConfig,
    InformationAtom,
    SelectorCandidateScore,
)
from mas_experiment.hiddenbench_metrics import lexical_fact_match


def atomize_private_text(
    owner_agent_id: str,
    text: str,
) -> tuple[InformationAtom, ...]:
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    has_bullets = any(line.startswith(("-", "*")) for line in raw_lines)
    if not has_bullets:
        atom_texts = (text.strip(),)
    else:
        heading: str | None = None
        values: list[str] = []
        for line in raw_lines:
            if not line.startswith(("-", "*")):
                heading = line.rstrip(":").strip()
                continue
            value = line.lstrip("-*").strip()
            values.append(f"{heading}: {value}" if heading else value)
        atom_texts = tuple(values)

    return tuple(
        InformationAtom(
            atom_id=hashlib.sha256(
                f"{owner_agent_id}|{index}|{atom_text}".encode("utf-8")
            ).hexdigest()[:16],
            owner_agent_id=owner_agent_id,
            index=index,
            text=atom_text,
        )
        for index, atom_text in enumerate(atom_texts)
        if atom_text
    )


def atomize_private_information(
    assignment: HiddenBenchAssignment,
) -> dict[str, tuple[InformationAtom, ...]]:
    return {
        owner: atomize_private_text(owner, text)
        for owner, text in assignment.private_information.items()
    }


def _phrase_present(text: str, phrase: str) -> bool:
    return phrase.casefold() in text.casefold()


def extract_stance(
    task: HiddenBenchTask,
    text: str,
    previous: str | None,
) -> str | None:
    mentions = tuple(
        answer
        for answer in task.possible_answers
        if _phrase_present(text, answer)
    )
    return mentions[0] if len(mentions) == 1 else previous


def _atom_disclosed(atom: InformationAtom, message: HiddenBenchMessage) -> bool:
    if lexical_fact_match(atom.text, message.content):
        return True
    criterion = re.fullmatch(
        r"(.+?):\s*\(([a-z])\)\s*([ny])",
        atom.text,
        flags=re.IGNORECASE,
    )
    if criterion is None:
        return False
    entity, label, value = criterion.groups()
    content = message.content.casefold()
    entity_names = {
        entity.casefold(),
        entity.split()[0].casefold(),
    }
    if not any(name in content for name in entity_names):
        return False
    if not re.search(rf"(?:\({label}\)|\b{label}\b)", content):
        return False
    positive = bool(re.search(r"\b(?:meet|meets|satisfy|satisfies|pass)\b", content))
    negative = bool(re.search(r"\b(?:fail|fails|not meet|doesn't meet)\b", content))
    return (value.casefold() == "y" and positive) or (
        value.casefold() == "n" and negative
    )


def _latest_stances(
    task: HiddenBenchTask,
    pre_stances: dict[str, str],
    messages: tuple[HiddenBenchMessage, ...],
) -> dict[str, str | None]:
    latest: dict[str, str | None] = {
        agent_id: pre_stances.get(agent_id) for agent_id in AGENT_IDS
    }
    for message in messages:
        latest[message.agent_id] = extract_stance(
            task,
            message.content,
            latest[message.agent_id],
        )
    return latest


def _plurality(stances: dict[str, str | None]) -> str | None:
    counts = Counter(value for value in stances.values() if value is not None)
    if not counts:
        return None
    top = max(counts.values())
    winners = [value for value, count in counts.items() if count == top]
    return winners[0] if len(winners) == 1 else None


def score_dynamic_candidates(
    *,
    task: HiddenBenchTask,
    assignment: HiddenBenchAssignment,
    pre_stances: dict[str, str],
    public_messages: tuple[HiddenBenchMessage, ...],
    remaining_quotas: dict[str, int],
    last_spoken_turns: dict[str, int],
    config: DynamicSelectorConfig,
    turn_index: int,
) -> tuple[SelectorCandidateScore, ...]:
    atoms_by_owner = atomize_private_information(assignment)
    latest = _latest_stances(task, pre_stances, public_messages)
    plurality = _plurality(latest)
    eligible = tuple(
        agent_id
        for agent_id in AGENT_IDS
        if remaining_quotas.get(agent_id, 0) > 0
    )
    raw_waits = {
        agent_id: max(0, turn_index - last_spoken_turns.get(agent_id, -1))
        for agent_id in eligible
    }
    maximum_wait = max(raw_waits.values(), default=1) or 1
    results: list[SelectorCandidateScore] = []

    for agent_id in eligible:
        stance = latest.get(agent_id)
        if plurality is None:
            disagreement = 0.5
        else:
            disagreement = float(stance != plurality)

        owned_atoms = atoms_by_owner.get(agent_id, ())
        disclosed_ids = {
            atom.atom_id
            for atom in owned_atoms
            if any(
                message.agent_id == agent_id
                and _atom_disclosed(atom, message)
                for message in public_messages
            )
        }
        undisclosed_atoms = tuple(
            atom for atom in owned_atoms if atom.atom_id not in disclosed_ids
        )
        undisclosed = (
            len(undisclosed_atoms) / len(owned_atoms) if owned_atoms else 0.0
        )

        last_spoken = last_spoken_turns.get(agent_id, -1)
        new_other_messages = tuple(
            message
            for message in public_messages
            if message.turn_index > last_spoken
            and message.agent_id != agent_id
        )
        related_atoms = tuple(
            atom
            for atom in undisclosed_atoms
            if any(
                _phrase_present(atom.text, answer)
                and any(
                    _phrase_present(message.content, answer)
                    for message in new_other_messages
                )
                for answer in task.possible_answers
            )
        )
        related_discussion = float(bool(related_atoms))

        new_cross_atoms = tuple(
            atom
            for owner, atoms in atoms_by_owner.items()
            if owner != agent_id
            for atom in atoms
            if any(
                message.agent_id == owner
                and message.turn_index > last_spoken
                and _atom_disclosed(atom, message)
                for message in public_messages
            )
        )
        response_due = float(bool(new_cross_atoms))
        waiting = raw_waits[agent_id] / maximum_wait
        weighted_total = (
            config.disagreement * disagreement
            + config.undisclosed * undisclosed
            + config.related_discussion * related_discussion
            + config.response_due * response_due
            + config.waiting * waiting
        )
        evidence_ids = tuple(
            dict.fromkeys(
                atom.atom_id
                for atom in (*undisclosed_atoms, *related_atoms, *new_cross_atoms)
            )
        )
        results.append(
            SelectorCandidateScore(
                agent_id=agent_id,
                disagreement=disagreement,
                undisclosed=undisclosed,
                related_discussion=related_discussion,
                response_due=response_due,
                waiting=waiting,
                weighted_total=weighted_total,
                remaining_quota=remaining_quotas[agent_id],
                raw_waiting=raw_waits[agent_id],
                latest_stance=stance,
                evidence_atom_ids=evidence_ids,
            )
        )
    return tuple(results)


def select_dynamic_speaker(
    **kwargs: object,
) -> tuple[str, tuple[SelectorCandidateScore, ...]]:
    scores = score_dynamic_candidates(**kwargs)  # type: ignore[arg-type]
    if not scores:
        raise ValueError("at least one eligible speaker is required")
    ordered = sorted(
        scores,
        key=lambda item: (
            -item.weighted_total,
            -item.remaining_quota,
            -item.raw_waiting,
            item.agent_id,
        ),
    )
    winner = ordered[0]
    score_ties = [
        item for item in ordered if item.weighted_total == winner.weighted_total
    ]
    if len(score_ties) == 1:
        reason = "highest_score"
    else:
        quota_ties = [
            item
            for item in score_ties
            if item.remaining_quota
            == max(candidate.remaining_quota for candidate in score_ties)
        ]
        if len(quota_ties) == 1:
            reason = "remaining_quota"
        else:
            wait_ties = [
                item
                for item in quota_ties
                if item.raw_waiting
                == max(candidate.raw_waiting for candidate in quota_ties)
            ]
            reason = "raw_waiting" if len(wait_ties) == 1 else "agent_id"
    selected = tuple(
        item.model_copy(
            update={
                "selected": item.agent_id == winner.agent_id,
                "tie_break_reason": (
                    reason if item.agent_id == winner.agent_id else None
                ),
            }
        )
        for item in scores
    )
    return winner.agent_id, selected
