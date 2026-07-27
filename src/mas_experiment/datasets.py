from __future__ import annotations

from mas_experiment.domain import AgentRole, Question


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
