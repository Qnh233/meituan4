"""TSV 数据解析器：将输入文本转为结构化 ProblemData。"""

from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class CandidateAssignment:
    task_ids: tuple[str, ...]
    courier_id: str
    total_score: float
    willingness: float

    @property
    def task_count(self) -> int:
        return len(self.task_ids)

    @property
    def is_combined(self) -> bool:
        return len(self.task_ids) > 1


@dataclass
class ProblemData:
    candidates: list[CandidateAssignment]
    all_tasks: set[str] = field(default_factory=set)
    all_couriers: set[str] = field(default_factory=set)
    task_to_candidates: dict[str, list[int]] = field(default_factory=dict)
    candidate_index: dict[tuple, int] = field(default_factory=dict)

    def __post_init__(self):
        self._build_indices()

    def _build_indices(self):
        self.task_to_candidates = defaultdict(list)
        for i, c in enumerate(self.candidates):
            self.all_tasks.update(c.task_ids)
            self.all_couriers.add(c.courier_id)
            for t in c.task_ids:
                self.task_to_candidates[t].append(i)

    def get_candidate(self, task_ids: tuple[str, ...], courier_id: str) -> CandidateAssignment | None:
        for c in self.candidates:
            if c.task_ids == task_ids and c.courier_id == courier_id:
                return c
        return None

    def unreachable_tasks(self) -> set[str]:
        return {t for t in self.all_tasks if t not in self.task_to_candidates or len(self.task_to_candidates[t]) == 0}


def parse(input_text: str) -> ProblemData:
    lines = input_text.strip().splitlines()
    if not lines:
        return ProblemData(candidates=[])

    start = 1 if lines[0].startswith("task_id_list") else 0
    candidates = []

    for line in lines[start:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue

        task_id_list_str, courier_id, score_str, willingness_str = parts[:4]
        try:
            score = float(score_str)
            willingness = float(willingness_str)
        except ValueError:
            continue

        task_ids = tuple(t.strip() for t in task_id_list_str.split(",") if t.strip())
        if not task_ids:
            continue

        candidates.append(CandidateAssignment(
            task_ids=task_ids,
            courier_id=courier_id.strip(),
            total_score=score,
            willingness=willingness,
        ))

    return ProblemData(candidates=candidates)
