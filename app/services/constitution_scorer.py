"""
九体质辨识评分算法
参考：中华中医药学会《中医体质分类与判定》标准
"""
from dataclasses import dataclass, field

from app.models.enums import BodyType


# 每种体质的中文名称
BODY_TYPE_NAMES = {
    BodyType.BALANCED: "平和质",
    BodyType.QI_DEFICIENCY: "气虚质",
    BodyType.YANG_DEFICIENCY: "阳虚质",
    BodyType.YIN_DEFICIENCY: "阴虚质",
    BodyType.PHLEGM_DAMPNESS: "痰湿质",
    BodyType.DAMP_HEAT: "湿热质",
    BodyType.BLOOD_STASIS: "血瘀质",
    BodyType.QI_STAGNATION: "气郁质",
    BodyType.SPECIAL_DIATHESIS: "特禀质",
}

BODY_TYPE_DESCRIPTIONS = {
    BodyType.BALANCED: "平和质是最健康的体质，阴阳气血调和，以体态适中、面色红润、精力充沛为主要特征。",
    BodyType.QI_DEFICIENCY: "气虚质以疲乏、气短、自汗等气虚表现为主要特征，体形偏胖，常感乏力，易感冒。",
    BodyType.YANG_DEFICIENCY: "阳虚质以畏冷、手足不温等虚寒表现为主要特征，平素怕冷，冬季易患寒病。",
    BodyType.YIN_DEFICIENCY: "阴虚质以手足心热、口燥咽干、鼻微干、喜冷饮等虚热表现为主要特征。",
    BodyType.PHLEGM_DAMPNESS: "痰湿质以体形肥胖、腹部肥满、口黏苔腻等痰湿表现为主要特征。",
    BodyType.DAMP_HEAT: "湿热质以面垢油光、易生痤疮、口苦口干等湿热表现为主要特征。",
    BodyType.BLOOD_STASIS: "血瘀质以肤色晦暗、色素沉着、容易出现瘀斑等血瘀表现为主要特征。",
    BodyType.QI_STAGNATION: "气郁质以神情抑郁、忧虑脆弱等气郁表现为主要特征，性格多愁善感。",
    BodyType.SPECIAL_DIATHESIS: "特禀质以过敏反应等为主要特征，常鼻塞、打喷嚏，易对药物、食物、气味过敏。",
}


@dataclass
class BodyTypeScore:
    body_type: BodyType
    raw_score: float
    converted_score: float
    level: str  # "yes" | "tendency" | "no"
    name: str = ""
    description: str = ""

    def __post_init__(self):
        self.name = BODY_TYPE_NAMES.get(self.body_type, "")
        self.description = BODY_TYPE_DESCRIPTIONS.get(self.body_type, "")


@dataclass
class AssessmentResult:
    main_type: BodyType
    secondary_types: list[BodyType]
    scores: dict[str, BodyTypeScore]
    is_pure_balanced: bool


def _converted_score(raw: float, n_items: int) -> float:
    """转换分公式：(原始分 - 条目数) / (条目数 × 4) × 100"""
    if n_items == 0:
        return 0.0
    return (raw - n_items) / (n_items * 4) * 100


def _level(converted: float, body_type: BodyType, all_scores: dict[BodyType, float]) -> str:
    if body_type == BodyType.BALANCED:
        # 平和质判定：转换分≥60 且其余8种均<40（宽松版）/ 或均<30（严格版）
        others_all_no = all(
            s < 40 for bt, s in all_scores.items() if bt != BodyType.BALANCED
        )
        if converted >= 60 and others_all_no:
            return "yes"
        elif converted >= 60 or (converted >= 30 and others_all_no):
            return "tendency"
        else:
            return "no"
    else:
        if converted >= 40:
            return "yes"
        elif converted >= 30:
            return "tendency"
        else:
            return "no"


def score_assessment(
    answers: list[dict],  # [{question_id: str, answer_value: int, body_type: str, is_reverse: bool}]
) -> AssessmentResult:
    """
    计算九体质评分。
    answers 每项需包含：question_id, answer_value(1-5), body_type(BodyType str), is_reverse(bool)
    """
    # 分组统计
    raw_scores: dict[BodyType, float] = {bt: 0.0 for bt in BodyType}
    counts: dict[BodyType, int] = {bt: 0 for bt in BodyType}

    for ans in answers:
        bt = BodyType(ans["body_type"])
        value = int(ans["answer_value"])
        is_reverse = ans.get("is_reverse", False)
        if is_reverse:
            value = 6 - value  # 反向计分：1→5, 2→4, 3→3, 4→2, 5→1
        raw_scores[bt] += value
        counts[bt] += 1

    # 计算转换分（first pass，用于平和质判定）
    converted: dict[BodyType, float] = {}
    for bt in BodyType:
        n = counts[bt]
        converted[bt] = _converted_score(raw_scores[bt], n) if n > 0 else 0.0

    # 计算等级
    scores: dict[str, BodyTypeScore] = {}
    for bt in BodyType:
        n = counts[bt]
        c = converted[bt]
        lv = _level(c, bt, converted)
        scores[bt.value] = BodyTypeScore(
            body_type=bt,
            raw_score=raw_scores[bt],
            converted_score=round(c, 1),
            level=lv,
        )

    # 确定主体质和兼夹体质
    # 平和质判定
    balanced_score = scores[BodyType.BALANCED.value]
    if balanced_score.level == "yes":
        main_type = BodyType.BALANCED
        secondary_types = []
    else:
        # 偏颇体质中转换分最高的为主体质
        biased = {
            bt: converted[bt]
            for bt in BodyType
            if bt != BodyType.BALANCED and counts[bt] > 0
        }
        if biased:
            main_type = max(biased, key=lambda bt: biased[bt])
        else:
            main_type = BodyType.BALANCED

        secondary_types = [
            bt for bt, s in scores.items()
            if s.level in ("yes", "tendency")
            and BodyType(bt) != main_type
            and BodyType(bt) != BodyType.BALANCED
        ]

    return AssessmentResult(
        main_type=main_type,
        secondary_types=[BodyType(bt) for bt in secondary_types],
        scores=scores,
        is_pure_balanced=(main_type == BodyType.BALANCED and not secondary_types),
    )
