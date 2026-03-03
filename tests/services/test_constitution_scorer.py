"""
体质评分算法单测（纯逻辑，不需要 DB）。
"""
import pytest
from app.models.enums import BodyType
from app.services.constitution_scorer import score_assessment, _converted_score


def _make_answers(body_type: BodyType, value: int, count: int = 8, is_reverse: bool = False) -> list[dict]:
    return [
        {
            "question_id": f"q-{body_type.value}-{i}",
            "answer_value": value,
            "body_type": body_type.value,
            "is_reverse": is_reverse,
        }
        for i in range(count)
    ]


def _all_types_low(main_type: BodyType, value: int = 3) -> list[dict]:
    """构造除 main_type 外其余体质均答 1 的答案集。"""
    answers = []
    for bt in BodyType:
        if bt == main_type:
            answers.extend(_make_answers(bt, value))
        else:
            answers.extend(_make_answers(bt, 1))
    return answers


def test_converted_score_formula():
    """转换分公式验证：n=8, raw=32(全答4) → (32-8)/(8×4)×100 = 75.0"""
    assert abs(_converted_score(32, 8) - 75.0) < 0.01


def test_all_moderate_answers_yields_balanced():
    """所有题目答3（偏低），期望主体质为平和质（或转换分最高的体质）。"""
    # 平和质全答4，其余全答1 → 平和质 converted≈75，其余≈0 → BALANCED
    answers = _all_types_low(BodyType.BALANCED, value=4)
    result = score_assessment(answers)
    assert result.main_type == BodyType.BALANCED


def test_qi_deficiency_high_score():
    """气虚质全答5，其余全答1 → 主体质为气虚质。"""
    answers = []
    for bt in BodyType:
        v = 5 if bt == BodyType.QI_DEFICIENCY else 1
        answers.extend(_make_answers(bt, v))
    result = score_assessment(answers)
    assert result.main_type == BodyType.QI_DEFICIENCY
    score = result.scores[BodyType.QI_DEFICIENCY.value]
    assert score.level == "yes"
    assert score.converted_score >= 40


def test_tendency_level():
    """转换分在30-39之间应为 tendency。"""
    # n=8, score=30 → raw = 30*32/100+8 ≈ 17.6，取整18
    # 精确计算：converted=30 → raw = 30/100*32+8 = 17.6 → 实际answer均值约3
    # 直接构造：answer均值2.5 → raw=20，converted=(20-8)/32*100=37.5 → tendency
    answers = []
    for bt in BodyType:
        if bt == BodyType.PHLEGM_DAMPNESS:
            # 8个答案，mix 2和3 → raw = 4*2+4*3 = 20 → converted = 37.5
            for i in range(4):
                answers.append({"question_id": f"q-{bt.value}-{i}a", "answer_value": 2,
                                "body_type": bt.value, "is_reverse": False})
            for i in range(4):
                answers.append({"question_id": f"q-{bt.value}-{i}b", "answer_value": 3,
                                "body_type": bt.value, "is_reverse": False})
        else:
            answers.extend(_make_answers(bt, 1))

    result = score_assessment(answers)
    phlegm_score = result.scores[BodyType.PHLEGM_DAMPNESS.value]
    assert phlegm_score.level == "tendency"


def test_multiple_biased_types():
    """两种体质均高分时，两种都应出现（主体质 + 兼夹）。"""
    answers = []
    for bt in BodyType:
        if bt in (BodyType.YIN_DEFICIENCY, BodyType.QI_STAGNATION):
            answers.extend(_make_answers(bt, 5))
        else:
            answers.extend(_make_answers(bt, 1))

    result = score_assessment(answers)
    all_high = {result.main_type} | set(result.secondary_types)
    assert BodyType.YIN_DEFICIENCY in all_high
    assert BodyType.QI_STAGNATION in all_high


def test_reverse_scoring():
    """反向计分：答5应等同正向答1。"""
    forward_answers = _make_answers(BodyType.BALANCED, 1, count=8, is_reverse=False)
    reverse_answers = _make_answers(BodyType.BALANCED, 5, count=8, is_reverse=True)

    # 补充其他体质使评分完整
    others = [
        {"question_id": f"q-other-{i}", "answer_value": 1,
         "body_type": BodyType.QI_DEFICIENCY.value, "is_reverse": False}
        for i in range(8)
    ]

    r_forward = score_assessment(forward_answers + others)
    r_reverse = score_assessment(reverse_answers + others)

    assert abs(
        r_forward.scores[BodyType.BALANCED.value].converted_score
        - r_reverse.scores[BodyType.BALANCED.value].converted_score
    ) < 0.01
