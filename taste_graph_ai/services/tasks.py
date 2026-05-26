import uuid
from datetime import date, datetime, timedelta

from taste_graph_ai.container import get_container
from taste_graph_ai.domain.enums import TaskType, TaskPriority, TaskStatus
from taste_graph_ai.domain.models import Task
from taste_graph_ai.infrastructure.repos.sources import SourceRepository
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.tasks import TaskRepository
from taste_graph_ai.infrastructure.db.event_log import EventLog


class TaskService:
    """Generates daily operational tasks from system state."""

    def __init__(
        self,
        source_repo: SourceRepository,
        pack_repo: PackRepository,
        task_repo: TaskRepository,
        event_log: EventLog,
    ):
        self.source_repo = source_repo
        self.pack_repo = pack_repo
        self.task_repo = task_repo
        self.event_log = event_log

    async def generate_daily_tasks(self) -> list[Task]:
        """Synthesize system state into 1-3 actionable tasks."""
        tasks: list[Task] = []

        # 1. Pending source review
        pending_count = await self.source_repo.count_pending()
        if pending_count >= 1:
            tasks.append(self._make_task(
                TaskType.REVIEW_SOURCES,
                f"{pending_count} 个新源等你审核",
                f"发现引擎找到了 {pending_count} 个新内容源，去审核一下决定是否加入图谱。",
                TaskPriority.HIGH,
                "/api/v1/sources/pending",
            ))

        # 2. Stale deferred sources
        stale = await self.source_repo.count_stale_deferred(days=3)
        if stale > 0:
            tasks.append(self._make_task(
                TaskType.STALE_REVIEW,
                f"{stale} 个源已待定超过 3 天",
                "长时间待定会影响推荐质量，建议今天决定保留还是移除。",
                TaskPriority.MEDIUM,
                "/api/v1/sources/pending?status=deferred",
            ))

        # 3. Top-performing theme from last week
        top = await self.pack_repo.get_top_theme(days=7)
        if top and top["count"] >= 2:
            tasks.append(self._make_task(
                TaskType.THEME_SUGGESTION,
                f"上周「{top['name']}」互动最好（{top['count']} 次发布）",
                f"平均品味分 {top['avg_score']:.0f}，建议本周再做一组变形。",
                TaskPriority.MEDIUM,
                "",
            ))

        # 4. Trend detection from graph
        trend = self._detect_trend()
        if trend:
            tasks.append(self._make_task(
                TaskType.TREND_ALERT,
                f"「{trend['label']}」相关概念热度上升",
                f"最近 7 天出现了 {trend['count']} 次，可以考虑做成系列内容。",
                TaskPriority.LOW,
                "",
            ))

        # 5. Content pillar gap
        gap = await self._detect_pillar_gap()
        if gap:
            tasks.append(self._make_task(
                TaskType.GAP_ALERT,
                f"「{gap}」内容支柱已超过 2 周未更新",
                "保持内容支柱的平衡可以让账号更有层次感。",
                TaskPriority.LOW,
                "",
            ))

        return tasks[:3]  # Cap at 3

    async def persist_daily_tasks(self) -> list[Task]:
        """Generate and save today's tasks, avoiding duplicates."""
        today = date.today().isoformat()
        existing = await self.task_repo.list_today(today)

        # Skip if tasks were already generated today
        if existing:
            return existing

        tasks = await self.generate_daily_tasks()
        for t in tasks:
            await self.task_repo.save(t)
            self.event_log.append("task.generated", {
                "id": t.id, "type": t.task_type.value, "title": t.title,
            })

        return tasks

    # ── Internal helpers ──────────────────────────────────────

    def _make_task(self, task_type: TaskType, title: str, body: str,
                   priority: TaskPriority, action_url: str) -> Task:
        return Task(
            id=uuid.uuid4().hex[:12],
            task_type=task_type,
            title=title,
            body=body,
            priority=priority,
            action_url=action_url,
        )

    def _detect_trend(self) -> dict | None:
        """Detect concepts with increased edge weight in the graph."""
        graph = get_container().taste_graph
        trending = []
        for node_id, data in graph.graph.nodes(data=True):
            if data["type"].value == "concept":
                # Sum incoming edge weights as a proxy for "hotness"
                total = sum(
                    graph.graph.edges.get((s, node_id), {}).get("weight", 0)
                    for s, _ in graph.graph.in_edges(node_id)
                )
                fb_count = data.get("properties", {}).get("feedback_count", 0)
                if total > 5:
                    trending.append({
                        "label": data["label"],
                        "count": int(total),
                        "feedback_count": fb_count,
                    })

        trending.sort(key=lambda x: x["count"], reverse=True)
        return trending[0] if trending else None

    async def _detect_pillar_gap(self) -> str | None:
        """Check if any content pillar hasn't been used in 14+ days."""
        graph = get_container().taste_graph
        two_weeks_ago = (datetime.now() - timedelta(days=14)).isoformat()

        # Get all content pillar nodes
        pillars = []
        for node_id, data in graph.graph.nodes(data=True):
            if data["type"].value == "pillar":
                pillars.append(data["label"])

        if not pillars:
            return None

        # Check which pillars have been used recently
        packs = await self.pack_repo.get_latest_packs(limit=50)
        used_pillars = set()
        for p in packs:
            if p.created_at >= two_weeks_ago:
                for pillar in pillars:
                    if pillar.lower() in p.theme.lower() or pillar.lower() in p.why_today.lower():
                        used_pillars.add(pillar)

        for pillar in pillars:
            if pillar not in used_pillars:
                return pillar

        return None
