"""本项目的固定评价权重；模型只输出等级与依据，不决定权重。"""

RESUME_WEIGHTS = {
    "experience_quality": 35,
    "skills_evidence": 20,
    "education_growth": 20,
    "positioning": 10,
    "expression": 10,
    "completeness": 5,
}

DEFAULT_EXPERIENCE_WEIGHTS = {
    "background": 10, "contribution": 25, "implementation": 30,
    "validation": 25, "expression": 10,
}

EXPERIENCE_WEIGHTS = {
    "technical_project": {
        "background": 10, "contribution": 15, "implementation": 20,
        "decision": 20, "validation": 25, "expression": 10,
    },
    "research": {
        "background": 15, "contribution": 20, "implementation": 20,
        "decision": 15, "validation": 20, "expression": 10,
    },
    "internship": {
        "background": 10, "contribution": 25, "implementation": 35,
        "validation": 20, "expression": 10,
    },
    "coursework": {
        "background": 15, "contribution": 25, "implementation": 30,
        "validation": 20, "expression": 10,
    },
    "volunteering": {
        "background": 10, "contribution": 30, "implementation": 30,
        "validation": 20, "expression": 10,
    },
}


def experience_weights(experience_type: str) -> dict[str, int]:
    return EXPERIENCE_WEIGHTS.get(experience_type, DEFAULT_EXPERIENCE_WEIGHTS)
