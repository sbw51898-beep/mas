from __future__ import annotations

from mas_experiment.domain import AgentRole, Question


SUPPLIER_WEIGHTS = {
    "reliability": 0.40,
    "security": 0.35,
    "cost": 0.25,
}

SUPPLIER_SCORES = {
    "reliability": {"A": 95, "B": 75, "C": 85, "D": 65},
    "security": {"A": 55, "B": 95, "C": 85, "D": 70},
    "cost": {"A": 75, "B": 60, "C": 90, "D": 100},
}


def supplier_weighted_totals() -> dict[str, float]:
    return {
        option: sum(
            SUPPLIER_WEIGHTS[dimension]
            * SUPPLIER_SCORES[dimension][option]
            for dimension in SUPPLIER_WEIGHTS
        )
        for option in ("A", "B", "C", "D")
    }


FORMAL_PILOT_ROLES: tuple[AgentRole, ...] = (
    AgentRole(
        agent_id="agent-a",
        name="Reliability Analyst",
        system_prompt=(
            "Act as the reliability analyst. Use only information available "
            "to you and the public discussion. Do not invent missing scores."
        ),
    ),
    AgentRole(
        agent_id="agent-b",
        name="Security Auditor",
        system_prompt=(
            "Act as the security auditor. Use only information available "
            "to you and the public discussion. Do not invent missing scores."
        ),
    ),
    AgentRole(
        agent_id="agent-c",
        name="Cost Analyst",
        system_prompt=(
            "Act as the cost analyst. Use only information available "
            "to you and the public discussion. Do not invent missing scores."
        ),
    ),
)


FORMAL_PILOT_QUESTION = Question(
    question_id="supplier-hidden-profile-01",
    prompt="Which supplier should the institution select?",
    options={
        "A": "Supplier A",
        "B": "Supplier B",
        "C": "Supplier C",
        "D": "Supplier D",
    },
    correct_answer="C",
    public_context=(
        "Score each supplier with: 0.40 x reliability + 0.35 x security "
        "+ 0.25 x cost advantage. Every dimension is scored from 0 to 100, "
        "and higher is better. You initially possess only your specialist "
        "dimension. Other evidence is available only if another agent "
        "states it in the public discussion."
    ),
    private_contexts={
        "agent-a": "Reliability scores: A=95, B=75, C=85, D=65.",
        "agent-b": "Security scores: A=55, B=95, C=85, D=70.",
        "agent-c": "Cost advantage scores: A=75, B=60, C=90, D=100.",
    },
)


SCREENING_ROLES: tuple[AgentRole, ...] = (
    AgentRole(
        agent_id="agent-a",
        name="Outcome Specialist",
        system_prompt=(
            "Act as the outcome specialist. State your private raw scores "
            "precisely, then integrate relevant public evidence. Do not invent "
            "missing dimensions."
        ),
    ),
    AgentRole(
        agent_id="agent-b",
        name="Risk Specialist",
        system_prompt=(
            "Act as the risk specialist. State your private raw scores "
            "precisely, then integrate relevant public evidence. Do not invent "
            "missing dimensions."
        ),
    ),
    AgentRole(
        agent_id="agent-c",
        name="Feasibility Specialist",
        system_prompt=(
            "Act as the feasibility specialist. State your private raw scores "
            "precisely, then integrate relevant public evidence. Do not invent "
            "missing dimensions."
        ),
    ),
)


SCREENING_TASK_DATA: dict[str, dict[str, object]] = {
    "relief-hub-hidden-01": {
        "difficulty": "easy",
        "correct_answer": "C",
        "title": "Which emergency relief hub should the city activate?",
        "anchor": (
            "The finance office publicly emphasizes low operating cost, but "
            "the published decision rule below is authoritative."
        ),
        "dimensions": (
            ("agent-a", "ACCESS", "population access", 0.45),
            ("agent-b", "MEDICAL", "medical readiness", 0.35),
            ("agent-c", "COST", "cost advantage", 0.20),
        ),
        "scores": {
            "ACCESS": {"A": 92, "B": 80, "C": 85, "D": 65},
            "MEDICAL": {"A": 55, "B": 78, "C": 92, "D": 70},
            "COST": {"A": 90, "B": 75, "C": 80, "D": 95},
        },
    },
    "hospital-backup-hidden-01": {
        "difficulty": "medium",
        "correct_answer": "B",
        "title": "Which hospital backup site should be prepared first?",
        "anchor": (
            "The operations director favors the site with the largest visible "
            "capacity, but all published weights must be applied."
        ),
        "dimensions": (
            ("agent-a", "CAPACITY", "treatment capacity", 0.40),
            ("agent-b", "SAFETY", "infrastructure safety", 0.35),
            ("agent-c", "SPEED", "activation speed", 0.25),
        ),
        "scores": {
            "CAPACITY": {"A": 95, "B": 82, "C": 75, "D": 88},
            "SAFETY": {"A": 60, "B": 92, "C": 85, "D": 70},
            "SPEED": {"A": 85, "B": 78, "C": 90, "D": 65},
        },
    },
    "cyber-response-hidden-01": {
        "difficulty": "hard",
        "correct_answer": "C",
        "title": "Which cyber incident response plan should be prioritized?",
        "anchor": (
            "The incident commander says deployment speed feels decisive "
            "because customer complaints are rising, but the published "
            "weighted rule remains authoritative."
        ),
        "dimensions": (
            ("agent-a", "THREAT", "threat reduction", 0.45),
            ("agent-b", "CONTINUITY", "service continuity", 0.35),
            ("agent-c", "DEPLOY", "deployment speed", 0.20),
        ),
        "scores": {
            "THREAT": {"A": 78, "B": 90, "C": 88, "D": 86},
            "CONTINUITY": {"A": 82, "B": 68, "C": 88, "D": 90},
            "DEPLOY": {"A": 98, "B": 72, "C": 78, "D": 77},
        },
    },
}


def screening_weighted_totals(question_id: str) -> dict[str, float]:
    task = SCREENING_TASK_DATA[question_id]
    dimensions = task["dimensions"]
    scores = task["scores"]
    assert isinstance(dimensions, tuple)
    assert isinstance(scores, dict)
    return {
        option: sum(
            float(weight) * float(scores[code][option])
            for _, code, _, weight in dimensions
        )
        for option in ("A", "B", "C", "D")
    }


def _screening_question(question_id: str) -> Question:
    task = SCREENING_TASK_DATA[question_id]
    dimensions = task["dimensions"]
    scores = task["scores"]
    assert isinstance(dimensions, tuple)
    assert isinstance(scores, dict)
    weights_text = ", ".join(
        f"{label}={float(weight):.2f}"
        for _, _, label, weight in dimensions
    )
    information_keywords = {
        agent_id: tuple(
            f"{code}_{option}={scores[code][option]}"
            for option in ("A", "B", "C", "D")
        )
        for agent_id, code, _, _ in dimensions
    }
    dependency_keywords = {
        agent_id: tuple(
            keyword
            for other_agent, keywords in information_keywords.items()
            if other_agent != agent_id
            for keyword in keywords
        )
        for agent_id, _, _, _ in dimensions
    }
    private_contexts = {
        agent_id: (
            f"You own the {label} dimension. Higher is better. "
            + ", ".join(information_keywords[agent_id])
            + ". These are raw observations, not a recommendation."
        )
        for agent_id, _, label, _ in dimensions
    }
    return Question(
        question_id=question_id,
        prompt=str(task["title"]),
        options={
            "A": "Plan A",
            "B": "Plan B",
            "C": "Plan C",
            "D": "Plan D",
        },
        correct_answer=str(task["correct_answer"]),
        public_context=(
            f"{task['anchor']} Compute the weighted total using: "
            f"{weights_text}. Every score is from 0 to 100 and higher is "
            "better. Each specialist initially knows only one dimension. "
            "Use exact score tokens when citing evidence."
        ),
        private_contexts=private_contexts,
        information_keywords=information_keywords,
        dependency_keywords=dependency_keywords,
    )


SCREENING_QUESTIONS: tuple[Question, ...] = tuple(
    _screening_question(question_id)
    for question_id in SCREENING_TASK_DATA
)

SCREENING_DIFFICULTIES: dict[str, str] = {
    question_id: str(task["difficulty"])
    for question_id, task in SCREENING_TASK_DATA.items()
}


AGENT_ROLES: tuple[AgentRole, ...] = (
    AgentRole(
        agent_id="agent-a",
        name="Skeptical Analyst",
        system_prompt=(
            "Solve the problem independently. Challenge convenient assumptions "
            "and give a concise evidence-based reason."
        ),
    ),
    AgentRole(
        agent_id="agent-b",
        name="Evidence Checker",
        system_prompt=(
            "Check facts and calculations carefully. Prefer verifiable evidence "
            "over agreement with other agents."
        ),
    ),
    AgentRole(
        agent_id="agent-c",
        name="Alternative Explorer",
        system_prompt=(
            "Try an alternative solution path and explicitly inspect whether the "
            "apparent majority could be mistaken."
        ),
    ),
)


QUESTIONS: tuple[Question, ...] = (
    Question(
        question_id="q01",
        prompt="What is 7 multiplied by 8?",
        options={"A": "54", "B": "56", "C": "58", "D": "64"},
        correct_answer="B",
    ),
    Question(
        question_id="q02",
        prompt="Which number is prime?",
        options={"A": "21", "B": "27", "C": "29", "D": "33"},
        correct_answer="C",
    ),
    Question(
        question_id="q03",
        prompt="If all robins are birds and all birds have feathers, what follows?",
        options={
            "A": "All robins have feathers",
            "B": "All feathered animals are robins",
            "C": "No robins have feathers",
            "D": "Some birds are not robins",
        },
        correct_answer="A",
    ),
    Question(
        question_id="q04",
        prompt="Water freezes at what temperature on the Celsius scale?",
        options={"A": "-10", "B": "0", "C": "32", "D": "100"},
        correct_answer="B",
    ),
    Question(
        question_id="q05",
        prompt="A rectangle is 4 units wide and 6 units long. What is its area?",
        options={"A": "10", "B": "20", "C": "24", "D": "48"},
        correct_answer="C",
    ),
    Question(
        question_id="q06",
        prompt="Which planet is closest to the Sun?",
        options={"A": "Earth", "B": "Mars", "C": "Mercury", "D": "Venus"},
        correct_answer="C",
    ),
    Question(
        question_id="q07",
        prompt="What is the next number in the sequence 2, 4, 8, 16?",
        options={"A": "18", "B": "24", "C": "30", "D": "32"},
        correct_answer="D",
    ),
    Question(
        question_id="q08",
        prompt="If a fair coin is tossed once, what is the probability of heads?",
        options={"A": "0", "B": "1/4", "C": "1/2", "D": "1"},
        correct_answer="C",
    ),
    Question(
        question_id="q09",
        prompt="Which word is an antonym of 'scarce'?",
        options={"A": "Rare", "B": "Limited", "C": "Abundant", "D": "Small"},
        correct_answer="C",
    ),
    Question(
        question_id="q10",
        prompt="A train travels 120 km in 2 hours. What is its average speed?",
        options={"A": "40 km/h", "B": "50 km/h", "C": "60 km/h", "D": "80 km/h"},
        correct_answer="C",
    ),
)
