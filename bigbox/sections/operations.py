"""Operations — Achievements, stats, and milestones."""
from __future__ import annotations

from bigbox.sections._icons import load as load_icon, load_background
from bigbox.ui import Action, Section, SectionContext


def _achievements(ctx: SectionContext) -> None:
    ctx.show_achievements()


def _mission_report(ctx: SectionContext) -> None:
    ctx.show_mission_report()


def build() -> Section:
    return Section(
        title="Operations",
        icon="[#]",
        icon_img=load_icon("about"), # Fallback
        background_img=load_background("about"),
        actions=[
            Action("Operational Rank", _achievements, "Stats and unlocked medals"),
            Action("Session Debrief", _mission_report, "Current session summary"),
        ],
    )
