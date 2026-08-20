"""Independent blind review of the 144-item disclosure audit queue.

The reviewer here is Codex (an independent LLM distinct from the DeepSeek
auditor), not a human annotator. Judgments were made against the blind queue
only (fact + owner messages), without the AI or rule labels, using the same
six disclosure rules as the audit prompt. Every disclosed judgment carries an
owner-authored message ID and an exact-substring quote, validated program-
matically before metrics are computed.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from mas_experiment.hiddenbench_blind_review import (
    BlindReviewCase,
    BlindReviewMessage,
    ReviewJudgment,
    compute_weighted_review_metrics,
    make_blind_id,
    validate_review_judgment_evidence,
)
from mas_experiment.hiddenbench_ai_disclosure import DisclosureAudit
from mas_experiment.hiddenbench_stability_domain import StudyRunRecord
from mas_experiment.hiddenbench_stability_reporting import (
    build_fact_comparisons,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
SELECTED_JSONL = (
    ARTIFACTS / "hiddenbench-stability-20260729.blind-review.selected.jsonl"
)
RUNS_PATH = ARTIFACTS / "hiddenbench-stability-20260729.jsonl"
AUDITS_PATH = (
    ARTIFACTS / "hiddenbench-stability-20260729.ai-disclosure.jsonl"
)
QUEUE_CSV = (
    ARTIFACTS / "hiddenbench-stability-20260729.blind-review.queue.csv"
)
JUDGMENTS_JSONL = (
    ARTIFACTS / "hiddenbench-stability-20260729.blind-review.gpt.judgments.jsonl"
)
FILLED_QUEUE_CSV = (
    ARTIFACTS / "hiddenbench-stability-20260729.blind-review.gpt.queue.csv"
)
SUMMARY_JSON = (
    ARTIFACTS / "hiddenbench-stability-20260729.blind-review.gpt.summary.json"
)
REVIEWER_ID = "codex-blind-review-v1"
BLIND_SEED = 20260730


# blind_id -> (evidence_message_id, exact quote, reason). Missing entries are
# judged undisclosed (disclosed=False, no evidence).
DISCLOSED: dict[str, tuple[str, str, str]] = {
    "BR-57C0F4057A03": ("38ff4e8406587e9f", "Station Delta has confirmed safe water, working backup lights, and no contamination", "owner states the exact confirmed-safety content of the private fact"),
    "BR-B3FF21099989": ("12bf9f3aeb2effc5", "the walking trails are closed", "owner states the decision-relevant claim (trails closed)"),
    "BR-A5CF53A986ED": ("6d29654297abfcbb", "repair teams confirm the solar panels are offline and batteries are depleted, leaving it without power", "faithful restatement of the Charlie power-outage fact"),
    "BR-7634F2076923": ("f2535f5e58a3f543", "Bravo has abnormal air sensor readings near the plant", "faithful paraphrase of the Bravo sensor fact"),
    "BR-AD25CA9CF07B": ("f16c632b9b01be16", "Cape Industries meets the most requirements (c, d, e, i, j)", "states Cape Y-values exactly matching the packet"),
    "BR-F36291D91767": ("99f5bef50041e87c", "success in securing a multimillion-dollar federal grant, and proven commitment to increasing faculty diversity", "faithful paraphrase of Roberts' grant and diversity items"),
    "BR-1830E9607F18": ("9adf14a51389f771", "Cape Industries is the best choice as it meets key air vehicle requirements (a, c) and manufacturing capacity (j), while Franklin Enterprises fails critical air vehicle specs (a, c)", "Cape (a,c,j) and Franklin (a,c) values match the packet"),
    "BR-E4430C0F260E": ("142d13373980ef68", "it passed inspection this morning with safe water and working backup lights", "faithful restatement of the Delta inspection fact"),
    "BR-8400FEE34D08": ("fc714214d8da61cd", "Stevens has been observed drinking heavily at university events and discourages new ideas", "faithful paraphrase of Stevens' drinking and idea-discouraging items"),
    "BR-5567E404B727": ("d4414a3c271b2fc3", "the walking trails closed", "owner states the trails-closed claim"),
    "BR-9DB59322C190": ("39df1ef88bf4e0af", "Station Charlie has no power due to windstorm damage", "faithful restatement of the no-power fact"),
    "BR-B00AA3978929": ("72a1972b93d0e227", "the tunnel to East Town is blocked by the supply truck", "states the decision-relevant consequence of the fire fact"),
    "BR-DAD7842D80E0": ("83b087d8b3bd4f76", "North Hill's trails are closed due to fallen trees", "exact restatement of the trails fact"),
    "BR-CF7A3942CE36": ("07a01efc43e23fbf", "Cape Industries is the best choice because it meets the most critical criteria, including air vehicle specs (a, c)", "Cape (a,c) values match the packet"),
    "BR-1AF1DAC51D93": ("329925c67268dde0", "Cape Industries fails on sweep time (b) and weight (f)", "Cape (b),(f) failure values match the packet"),
    "BR-77FB2AD0C855": ("b1dff1844e8f50bd", "Cape Industries meets more criteria overall (a, d, e, i, j) and has no critical failures", "Cape Y-values exactly match the packet"),
    "BR-EB9EE252FD87": ("918c0627b42c427b", "Cape Industries fails on key requirements like (b), (f), (g), and (h)", "Cape failure values (b),(f),(h) match the packet"),
    "BR-14A2E8968939": ("ded2ddf3f28cd6b7", "Stevens has concerning issues like discouraging innovation and heavy drinking", "faithful paraphrase of Stevens' items"),
    "BR-07C4E2EBA2AB": ("d0be0d2aad662daf", "the contamination risk at Station Bravo", "faithful paraphrase of the Bravo fact"),
    "BR-F62904E45F8E": ("424f1a5f6ed84889", "Cape Industries meets all air vehicle specs except (b)", "Cape (a),(c) meet and (b) fail matches the packet"),
    "BR-B5DDDC4D8F8A": ("096ade10bbf78e33", "the power outage at Station Charlie", "states the no-power claim"),
    "BR-4E9B41EA27D0": ("31a9fa63d2927082", "the tunnel to East Town is blocked by the supply truck", "faithful restatement of the truck-in-tunnel fact"),
    "BR-426B46349B26": ("915925f716a0f001", "Starlight Incorporated is the best choice because it meets the critical air vehicle requirement (b) and the key computer requirement (d)", "Starlight (b),(d) Y-values exactly match the packet"),
    "BR-9083974B5FFC": ("7cda9a3d740e3aa3", "Station Alpha is contaminated and unsafe", "faithful paraphrase of the elevated-toxins fact"),
    "BR-4B4D87770A90": ("5d0e70d12736300f", "North Hill is blocked by a mudslide", "faithful restatement of the mudslide fact"),
    "BR-32C7E6FC1CB1": ("b541a40e934e9ca1", "Cape Industries meets more criteria overall (c, d, e, i, j) and satisfies key air vehicle and computer specs, while Franklin Enterprises fails critical air vehicle requirements (a, b)", "Cape (c,d,e,i,j) and Franklin (a,b) values match the packet"),
    "BR-7B8798BD7A69": ("8b272ed925c403be", "it avoids the contamination risk near Bravo", "faithful paraphrase of the Bravo fact"),
    "BR-6E41D1D46BE8": ("4c2db8237ef4b2fe", "Bravo's proximity to the plant poses a contamination risk", "faithful paraphrase of the Bravo fact"),
    "BR-EC1D59B8C6A2": ("fc9786f5c06f98d9", "it was inspected this morning with confirmed safe water, working backup lights, and no contamination", "exact restatement of the Delta inspection fact"),
    "BR-2E78BBB50722": ("cbeadbed5737627a", "the tunnel to East Town is blocked by the supply truck", "faithful restatement of the truck-in-tunnel fact"),
    "BR-1D1A8294554A": ("ab2aa3143d5b9f4f", "Station Charlie's power outage", "states the no-power claim"),
    "BR-C63980DDCD27": ("44cd9610b838e6ae", "despite some leadership tension", "states the Jones-provost tension item"),
    "BR-4ECC47C4E74D": ("91fe8542d47fbca8", "Cape fails on (b), (f), (g), and (h)", "Cape failure values (b),(f),(h) match the packet"),
    "BR-C981B82A780C": ("85dc853af264d43e", "the mudslide blocking North Hill", "faithful restatement of the mudslide fact"),
    "BR-7D3FDEDA86C2": ("a2090300ca1814b1", "influential contacts", "faithful paraphrase of Roberts' senator-contacts item"),
    "BR-E1E971D99DF2": ("bade9050bc56f517", "the noted tension with the provost", "states the Jones-provost tension item"),
    "BR-F20A9426D27C": ("9796d034893ac98b", "the contamination risk at Station Bravo", "faithful paraphrase of the Bravo fact"),
    "BR-B067B8132F06": ("dd8b75689e7cd110", "Bravo's contamination risk", "faithful paraphrase of the Bravo fact"),
    "BR-A1B3119F8BC6": ("d9d4e470192ce88a", "the contamination risk near Bravo", "faithful paraphrase of the Bravo fact"),
    "BR-793C1DF7B6D0": ("48b5e4c1ed6afffb", "the driveway to North Hill is covered by a mudslide", "exact restatement of the mudslide fact"),
    "BR-5C7BAE147E52": ("014d07c1483615c4", "the hotline reported elevated toxin levels inside after the accident", "faithful restatement of the Alpha toxin fact"),
    "BR-4FE678E8F0B2": ("cee64234a68c6e16", "Franklin’s missing vehicle specs", "states Franklin's missing vehicle-spec items"),
    "BR-242324EAB3B3": ("54870cd637b6b4df", "all other routes are blocked by fire, mudslide, or fallen trees", "states the fallen-trees blockage of routes"),
    "BR-3CFA43A4F238": ("a985d1ca11bbc276", "it was just inspected and confirmed safe, with open roads and no contamination", "faithful summary of the Delta inspection fact"),
    "BR-40175D9A7851": ("4aa97a940a17a489", "avoiding contamination risks near Bravo", "faithful paraphrase of the Bravo fact"),
    "BR-E22602159C77": ("c8fec0470b3a68cd", "Cape Industries fails (b), (f), (g), and (h)", "Cape failure values (b),(f) match the packet"),
    "BR-9FF97A750D22": ("60d72c7e84044eb4", "the fire blocking the supply truck", "exact restatement of the fire fact"),
    "BR-72EEFE5659C2": ("573940907afbfe99", "the massive fire blocking all traffic, including the supply truck", "exact restatement of the fire fact"),
    "BR-5DADFA9224C7": ("d10b60970871ea07", "the fire blocking the main roads", "faithful paraphrase of the fire fact"),
    "BR-4CFB5F9B2B04": ("d6b2c867380a0db2", "the closed walking trails", "states the trails-closed claim"),
    "BR-325AD8EB1C2B": ("7d8b7199e785e008", "the solar panels are offline and batteries depleted, Station Charlie has no power", "exact restatement of the Charlie power fact"),
    "BR-796C8B7CAA69": ("34567305ba5a314f", "it was just inspected and confirmed safe, with all roads open", "faithful summary of the Delta inspection fact"),
    "BR-2D4F43CA75F6": ("c89e498b0108f789", "Cape Industries is the best choice as it meets the most critical requirements, including air vehicle criteria (c) and computer specs (d, e)", "Cape (c),(d),(e) values match the packet"),
    "BR-65E98CB83412": ("845425f577593056", "Cape Industries fails on criteria (b), (f), (g), and (h)", "Cape failure values (b),(f),(h) match the packet"),
    "BR-96718587B5CC": ("c461e826dcf3672e", "local presence", "faithful paraphrase of the Jones local-residence item"),
    "BR-5BE0CC70CDB4": ("6195643d849d9020", "strategic thinking", "faithful paraphrase of the Jones strategic-thinker item"),
    "BR-BC65644290B9": ("95b1ec4c932dcddb", "the massive fire blocking the supply truck and all traffic", "exact restatement of the fire fact"),
    "BR-ECFAA2C20FD1": ("9f252568ddf1fd2e", "Cape Industries meets more criteria overall (c, d, e, i, j)", "Cape Y-values (c),(d),(i) match the packet"),
    "BR-A29CC8FA34E4": ("19236c0f95602dec", "the closed walking trails to North Hill", "states the trails-closed claim"),
    "BR-BB88C4441105": ("75c6758c95cc9941", "the critical requirement of sweeping the entire sensor field in 30 minutes or less (criterion b)", "Starlight criterion-b Y-value exactly matches the packet"),
    "BR-92ED2D95F0B0": ("5a22f67b2b81901c", "it uniquely satisfies past performance (i) and manufacturing capacity (j)", "Cape (i),(j) Y-values match the packet"),
    "BR-FD21A4D20BFE": ("721ac85ccb4a241d", "the walking trails to North Hill are closed", "exact restatement of the trails fact"),
    "BR-B33E799C96D9": ("ac2d0840be345a55", "avoiding the contamination risk at Bravo", "faithful paraphrase of the Bravo fact"),
    "BR-F3E8F27C0D17": ("0d4a5c3ce517a9f1", "Cape Industries fails (b), (f), (g), and (h)", "Cape failure values (b),(f),(h) match the packet"),
    "BR-499305D50343": ("b749cbf73c1027a1", "the walking trails to North Hill are closed", "exact restatement of the trails fact"),
    "BR-6D5A49A5DD66": ("b6c333683afbbd1f", "despite some leadership tension", "states the Jones tension item"),
    "BR-045CECBB9DB0": ("ec8183ea738e14ab", "the supply truck is stuck in the tunnel to East Town", "exact restatement of the truck-in-tunnel fact"),
    "BR-75BDD9DF48B9": ("3d3bed787b0d00a0", "air vehicle specs (c), computer specs (d, e), past performance (i), and manufacturing capacity (j)", "Cape Y-values exactly match the packet"),
    "BR-27D616F8C84E": ("0f425cabecdea299", "the confirmed toxin contamination", "faithful paraphrase of the Alpha toxin fact"),
    "BR-F195ADF2B8DB": ("26622b6fe27c2591", "the noted tension with the provost", "states the Jones-provost tension item"),
    "BR-4BFBE4E9BE6D": ("417aa4c1e0303248", "Cape Industries fails on key criteria like sweep time (b) and weight (f)", "Cape (b),(f) failure values match the packet"),
    "BR-6DDBC2892B9A": ("49be8f5b4da1dab8", "Starlight Incorporated is the best choice because it meets the cost and size criteria (e and h) without any critical failures", "Starlight (e),(h) and Franklin (a),(c) values match the packet"),
    "BR-9F12B8B2B83A": ("909c6d9cfc959d9c", "Cape Industries fails on sweep time (b) and weight (f)", "Cape (b),(f) failure values match the packet"),
}


def _build_population() -> tuple[BlindReviewCase, ...]:
    records = tuple(
        StudyRunRecord.model_validate_json(line)
        for line in RUNS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    audits = tuple(
        DisclosureAudit.model_validate_json(line)
        for line in AUDITS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    audit_by_key = {item.study_key.value: item for item in audits}
    population: list[BlindReviewCase] = []
    for record in records:
        audit = audit_by_key[record.key.value]
        comparisons = build_fact_comparisons(record, audit)
        by_fact = {item.fact_id: item for item in comparisons}
        for owner_agent_id, fact in (
            record.run.assignment.private_information.items()
        ):
            fact_id = f"private-fact:{owner_agent_id}"
            comparison = by_fact[fact_id]
            owner_messages = tuple(
                BlindReviewMessage(
                    message_id=message.message_id,
                    turn_index=message.turn_index,
                    content=message.content,
                )
                for message in record.run.discussion_messages
                if message.agent_id == owner_agent_id
            )
            population.append(
                BlindReviewCase(
                    blind_id=make_blind_id(
                        seed=BLIND_SEED,
                        study_key=record.key.value,
                        fact_id=fact_id,
                    ),
                    study_key=record.key.value,
                    task_id=record.key.task_id,
                    condition=record.key.condition,
                    fact_id=fact_id,
                    owner_agent_id=owner_agent_id,
                    fact=fact,
                    owner_messages=owner_messages,
                    ai_disclosed=comparison.ai_disclosed,
                    rule_disclosed=comparison.rule_disclosed,
                )
            )
    if len(population) != 320:
        raise ValueError(f"expected 320 cases, found {len(population)}")
    return tuple(population)


def main() -> None:
    population = _build_population()
    cases = tuple(
        BlindReviewCase.model_validate_json(line)
        for line in SELECTED_JSONL.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    population_by_id = {case.blind_id: case for case in population}
    case_by_id = {case.blind_id: case for case in cases}
    for case in cases:
        population_case = population_by_id[case.blind_id]
        if (
            population_case.fact != case.fact
            or population_case.ai_disclosed != case.ai_disclosed
            or population_case.rule_disclosed != case.rule_disclosed
            or population_case.condition != case.condition
            or population_case.task_id != case.task_id
        ):
            raise ValueError(
                f"selected case {case.blind_id} does not match population"
            )
    unknown = set(DISCLOSED) - set(case_by_id)
    if unknown:
        raise ValueError(f"unknown blind IDs: {sorted(unknown)}")

    judgments = []
    for case in cases:
        entry = DISCLOSED.get(case.blind_id)
        if entry is None:
            judgments.append(
                ReviewJudgment(
                    blind_id=case.blind_id,
                    disclosed=False,
                    reason=(
                        "Owner never states the fact or a faithful paraphrase "
                        "of any decision-relevant claim from the packet; "
                        "messages are generic, weakened, contradictory, or "
                        "assert content not in the packet."
                    ),
                    reviewer_id=REVIEWER_ID,
                )
            )
            continue
        message_id, quote, reason = entry
        judgment = ReviewJudgment(
            blind_id=case.blind_id,
            disclosed=True,
            evidence_message_ids=(message_id,),
            evidence_quote=quote,
            reason=reason,
            reviewer_id=REVIEWER_ID,
        )
        validate_review_judgment_evidence(case, judgment)
        judgments.append(judgment)

    if len(judgments) != len(cases):
        raise ValueError("judgment count mismatch")
    JUDGMENTS_JSONL.write_text(
        "".join(
            judgment.model_dump_json() + "\n"
            for judgment in judgments
        ),
        encoding="utf-8",
    )

    rows = list(csv.DictReader(QUEUE_CSV.open(encoding="utf-8-sig")))
    by_id = {row["blind_id"].strip(): row for row in rows}
    for judgment in judgments:
        row = by_id[judgment.blind_id]
        row["human_disclosed"] = "true" if judgment.disclosed else "false"
        row["human_evidence_message_ids"] = "|".join(
            judgment.evidence_message_ids
        )
        row["human_evidence_quote"] = judgment.evidence_quote
        row["human_reason"] = judgment.reason
        row["human_reviewer_id"] = REVIEWER_ID
    with FILLED_QUEUE_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    metrics = compute_weighted_review_metrics(
        population,
        tuple(judgments),
    )
    agreement_counts = {
        (case.ai_disclosed == judgment.disclosed)
        for case, judgment in zip(cases, judgments, strict=True)
    }
    ai_matches = sum(
        case.ai_disclosed == judgment.disclosed
        for case, judgment in zip(cases, judgments, strict=True)
    )
    summary = {
        "reviewer_id": REVIEWER_ID,
        "status": "independent_llm_review_not_human_ground_truth",
        "population_size": metrics.population_size,
        "reviewed_size": metrics.reviewed_size,
        "reviewed_disclosed": sum(
            judgment.disclosed for judgment in judgments
        ),
        "reviewed_undisclosed": sum(
            not judgment.disclosed for judgment in judgments
        ),
        "unweighted_ai_matches": ai_matches,
        "metrics": metrics.model_dump(mode="json"),
        "human_queue_filled": str(FILLED_QUEUE_CSV),
        "note": (
            "Codex independent blind review. Not human ground truth; the "
            "same filled form can be re-verified by a human annotator."
        ),
    }
    SUMMARY_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(f"cases={len(cases)} judgments={len(judgments)}")
    print(f"reviewed_disclosed={summary['reviewed_disclosed']}")
    print(f"reviewed_undisclosed={summary['reviewed_undisclosed']}")
    print(f"unweighted_ai_matches={ai_matches}/{len(cases)}")
    print(json.dumps(metrics.model_dump(), ensure_ascii=False, indent=1))
    print(JUDGMENTS_JSONL)
    print(SUMMARY_JSON)


if __name__ == "__main__":
    main()
