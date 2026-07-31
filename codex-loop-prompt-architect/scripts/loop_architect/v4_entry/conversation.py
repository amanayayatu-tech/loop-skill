"""Session-only guardrails for the conversational v4.1 intake compiler."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping

from loop_architect.v4_alpha.protocol import LoopIntakeInput, canonical_bytes


SLOT_NAMES = frozenset(
    {
        "result",
        "allow_scope",
        "forbidden_scope",
        "budget",
        "completion_evidence",
        "stop_conditions",
        "external_actions",
        "destructive_actions_allowed",
        "source_binding",
        "goals",
        "task_horizon",
    }
)


class ConversationIntakeError(ValueError):
    pass


@dataclass(frozen=True)
class SlotAnswer:
    value: Any
    source_kind: str
    source_digest: str
    source_summary: str
    confirmed_round: int


class ConversationIntakeSession:
    """Ephemeral answer retention; intentionally has no save/load method."""

    def __init__(self) -> None:
        self._slots: dict[str, SlotAnswer] = {}

    @property
    def answers(self) -> Mapping[str, SlotAnswer]:
        return dict(self._slots)

    def apply_candidate(
        self,
        updates: Mapping[str, Any],
        *,
        source_kind: str,
        source_digest: str,
        source_summary: str,
        round_number: int,
        explicitly_revised: tuple[str, ...] = (),
    ) -> None:
        if not updates or not set(updates) <= SLOT_NAMES:
            raise ConversationIntakeError("candidate slot shape drift")
        if isinstance(round_number, bool) or round_number < 1:
            raise ConversationIntakeError("round number must be positive")
        revision_set = set(explicitly_revised)
        if not revision_set <= set(updates):
            raise ConversationIntakeError("revision declaration drift")
        for name, value in updates.items():
            existing = self._slots.get(name)
            if existing is not None:
                if existing.value != value and name not in revision_set:
                    raise ConversationIntakeError(
                        f"confirmed slot conflict requires explicit revision: {name}"
                    )
                if existing.value == value and name not in revision_set:
                    continue
            self._slots[name] = SlotAnswer(
                value=value,
                source_kind=source_kind,
                source_digest=source_digest,
                source_summary=source_summary[:256],
                confirmed_round=round_number,
            )

    def blocking_questions(self) -> tuple[str, ...]:
        """Return at most three true blockers in the frozen safety order."""

        questions: list[str] = []
        if "destructive_actions_allowed" not in self._slots:
            questions.append("是否明确允许删除数据或执行其他不可逆动作？默认是不允许。")
        if "allow_scope" not in self._slots:
            questions.append("我可以修改哪些明确的文件、目录或系统表面？")
        if "completion_evidence" not in self._slots:
            questions.append("哪些可观察证据能够证明整个任务完成？")
        if "result" not in self._slots or "goals" not in self._slots:
            questions.append("最终结果和必须按顺序完成的阶段分别是什么？")
        if "budget" not in self._slots:
            questions.append("这次工作的时间、Host 调用和费用上限是什么？")
        if "source_binding" not in self._slots:
            questions.append("需求来源与目标 workspace 应绑定到哪里？")
        if "stop_conditions" not in self._slots:
            questions.append("遇到哪些情况必须停止并回来询问？")
        return tuple(questions[:3])

    def to_intake_input(self) -> LoopIntakeInput:
        blockers = self.blocking_questions()
        if blockers:
            raise ConversationIntakeError("blocking answers remain")

        def value(name: str, default: Any = None) -> Any:
            answer = self._slots.get(name)
            return default if answer is None else answer.value

        goals = tuple(str(item) for item in value("goals"))
        result = str(value("result"))
        if not goals or goals[0] != result:
            raise ConversationIntakeError("Goal order must start with the result")
        source = value("source_binding")
        if not isinstance(source, Mapping):
            raise ConversationIntakeError("source binding must be a mapping")
        authorization_boundaries = [
            f"forbidden_path:{item}" for item in value("forbidden_scope", ())
        ]
        authorization_boundaries.append(
            "destructive:allowed"
            if value("destructive_actions_allowed") is True
            else "destructive:forbidden"
        )
        budget = value("budget")
        if isinstance(budget, Mapping):
            budget_text = canonical_bytes(dict(budget)).decode("utf-8")
        elif isinstance(budget, str) and budget.strip():
            budget_text = budget.strip()
        else:
            raise ConversationIntakeError("budget must be text or a structured mapping")
        return LoopIntakeInput(
            goal=result,
            goal_plan=goals,
            task_horizon=str(value("task_horizon", "long")),
            write_scope=tuple(str(item) for item in value("allow_scope")),
            budget=budget_text,
            external_actions=tuple(
                str(item) for item in value("external_actions", ())
            ),
            acceptance_criteria=tuple(
                str(item) for item in value("completion_evidence")
            ),
            stop_conditions=tuple(str(item) for item in value("stop_conditions")),
            authorization_boundaries=tuple(authorization_boundaries),
            source_kind=str(source["kind"]),
            source_digest=str(source["source_digest"]),
            source_bytes=int(source["source_bytes"]),
        )


def accepts_conversation_confirmation(
    *, role: str, message: str, independent_message: bool
) -> bool:
    if role != "user" or not independent_message or not isinstance(message, str):
        return False
    normalized = unicodedata.normalize(
        "NFC", message.replace("\r\n", "\n").replace("\r", "\n")
    )
    return normalized == "START THIS LOOP"
