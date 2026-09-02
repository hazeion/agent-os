from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from conversation_planning import (
    MAX_ATTENTION,
    MAX_DEPENDENCY_MAP_EDGES,
    MAX_DEPENDENCY_MAP_EXTERNAL_STUBS,
    MAX_DEPENDENCY_MAP_NODES,
    MAX_PLANNING_SEARCH_PROJECTS,
    MAX_PLANNING_SEARCH_TASKS,
    MAX_TASK_PAGE,
    planning_dependency_map,
    planning_navigation_search,
    planning_overview,
    planning_task_locator,
    planning_task_page,
)
from mentat_db import connect
from task_repository import MAX_TASKS, TaskRepository


TODAY = date(2026, 9, 2)
NOW = "2026-09-02T12:00:00Z"
PROJECT_CAP = 256
PLANNER_RESPONSE_BUDGET_BYTES = 768 * 1024
PLANNER_SEARCH_RESPONSE_BUDGET_BYTES = 64 * 1024


def canonical_density_fixture() -> tuple[list[dict], list[dict]]:
    """Build the exact repository-cap fixture without private test data.

    The first Project intentionally owns the remaining Tasks.  That gives one
    deterministic selected-Project traversal enough nodes, cross-Project
    references, and edges to prove all planner caps while still exercising the
    full 256-Project / 2,048-Task canonical authority limit.
    """

    projects = [
        {
            "id": f"project_density_{index:03d}",
            "name": f"Density Project {index:03d}",
            "status": "active",
        }
        for index in range(PROJECT_CAP)
    ]
    primary_count = MAX_TASKS - (PROJECT_CAP - 1)
    tasks: list[dict] = []
    for index in range(MAX_TASKS):
        project_index = 0 if index < primary_count else index - primary_count + 1
        item = {
            "id": f"task_density_{index:04d}",
            "title": f"Density Task {index:04d}",
            "description": "bounded canonical fixture",
            "project": f"Density Project {project_index:03d}",
            "status": "todo",
            "priority": "medium",
            "assignee": None,
            "due_date": TODAY.isoformat(),
            "source": "test",
            "tags": [],
            "review_required": False,
            "needs_attention": False,
            "created_at": NOW,
            "updated_at": NOW,
            "completed_at": None,
        }
        if 0 < index < primary_count:
            item["depends_on"] = [f"task_density_{index - 1:04d}"]
        elif index >= primary_count:
            # These 255 incident edges supply the external-stub cap without
            # expanding the selected Project's retained node set.
            item["depends_on"] = ["task_density_0000"]
        tasks.append(item)
    return projects, tasks


class PlanningDensityTests(unittest.TestCase):
    def test_repository_cap_fixture_keeps_all_planner_projections_bounded_and_deterministic(self):
        projects, tasks = canonical_density_fixture()
        self.assertEqual((len(projects), len(tasks)), (PROJECT_CAP, MAX_TASKS))

        with TemporaryDirectory() as temporary:
            connection = connect(Path(temporary))
            try:
                TaskRepository(connection).insert_collection(tasks)

                overview = planning_overview(connection, projects, today=TODAY)
                search = planning_navigation_search(
                    connection, projects, query="Density", today=TODAY
                )
                first_page = planning_task_page(
                    connection,
                    projects,
                    project_id="project_density_000",
                    cursor=None,
                    today=TODAY,
                )
                second_page = planning_task_page(
                    connection,
                    projects,
                    project_id="project_density_000",
                    cursor=first_page["next_cursor"],
                    today=TODAY,
                )
                deepest = planning_task_locator(
                    connection,
                    projects,
                    task_id="task_density_2047",
                    today=TODAY,
                )
                graph = planning_dependency_map(
                    connection,
                    projects,
                    project_id="project_density_000",
                    today=TODAY,
                )
                graph_repeat = planning_dependency_map(
                    connection,
                    projects,
                    project_id="project_density_000",
                    today=TODAY,
                )
            finally:
                connection.close()

        self.assertEqual(overview["project_count"], PROJECT_CAP)
        self.assertEqual(graph_repeat, graph)
        for projection in (overview, first_page, second_page, deepest, graph):
            self.assertLess(
                len(json.dumps(projection, separators=(",", ":")).encode("utf-8")),
                PLANNER_RESPONSE_BUDGET_BYTES,
            )
        self.assertLess(
            len(json.dumps(search, separators=(",", ":")).encode("utf-8")),
            PLANNER_SEARCH_RESPONSE_BUDGET_BYTES,
        )
        self.assertEqual((len(overview["attention"]), overview["attention_count"]), (MAX_ATTENTION, MAX_TASKS))
        self.assertTrue(overview["truncated"])
        self.assertEqual(overview["attention"][0]["id"], "task_density_0000")
        self.assertEqual(overview["attention"][-1]["id"], f"task_density_{MAX_ATTENTION - 1:04d}")

        self.assertEqual((search["project_count"], search["task_count"]), (MAX_PLANNING_SEARCH_PROJECTS, MAX_PLANNING_SEARCH_TASKS))
        self.assertTrue(search["truncated"])
        self.assertEqual(search["projects"][0]["id"], "project_density_000")
        self.assertEqual(search["tasks"][0]["id"], "task_density_0000")

        self.assertEqual(first_page["count"], MAX_TASK_PAGE)
        self.assertIsNotNone(first_page["next_cursor"])
        self.assertEqual(first_page["tasks"][0]["id"], "task_density_0000")
        self.assertEqual(second_page["count"], MAX_TASK_PAGE)
        self.assertEqual(second_page["tasks"][0]["id"], f"task_density_{MAX_TASK_PAGE:04d}")
        self.assertEqual(deepest["project"]["id"], "project_density_255")
        self.assertEqual(deepest["task"]["id"], "task_density_2047")

        self.assertEqual((graph["node_count"], graph["node_total"]), (MAX_DEPENDENCY_MAP_NODES, MAX_TASKS - (PROJECT_CAP - 1)))
        self.assertTrue(graph["nodes_truncated"])
        self.assertEqual((graph["external_stub_count"], graph["external_stub_total"]), (MAX_DEPENDENCY_MAP_EXTERNAL_STUBS, PROJECT_CAP - 1))
        self.assertTrue(graph["external_stubs_truncated"])
        # 49 retained internal chain edges, one boundary edge from the next
        # omitted primary Task, and 255 cross-Project dependents are counted
        # before the visible-endpoint cap is applied.
        self.assertEqual((graph["edge_count"], graph["edge_total"]), (99, 305))
        self.assertLessEqual(graph["edge_count"], MAX_DEPENDENCY_MAP_EDGES)
        self.assertTrue(graph["edges_truncated"])
        visible = {item["id"] for item in graph["nodes"] + graph["external_stubs"]}
        self.assertTrue(all(edge["from_task_id"] in visible and edge["to_task_id"] in visible for edge in graph["edges"]))


if __name__ == "__main__":
    unittest.main()
