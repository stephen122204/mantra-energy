"""AL3 pilot manifest and independent verifier tests."""

from studies.energy_diagnosis.workloads.pilot_tasks import load_pilot_tasks, verify_pilot


def answer_for(task):
    if task.family == "data":
        return {
            "task_id": task.task_id,
            "total_units": task.expected["total_units"],
            "total_revenue": task.expected["total_revenue"],
            "evidence": [task.asset_sha256],
        }
    return {
        "task_id": task.task_id,
        "file_count": len(task.expected["checks"]),
        "checks": task.expected["checks"],
        "evidence": [task.asset_sha256],
    }


def test_manifest_has_two_lineage_separated_families():
    tasks = load_pilot_tasks()

    assert len(tasks) == 4
    assert [task.family for task in tasks].count("data") == 2
    assert [task.family for task in tasks].count("repository") == 2
    assert len({task.lineage for task in tasks}) == 4


def test_all_pilot_answers_are_recomputed_from_assets():
    for task in load_pilot_tasks():
        result = verify_pilot(task, answer_for(task))
        assert result["passed"] is True, (task.task_id, result)


def test_wrong_data_and_repository_answers_fail():
    tasks = load_pilot_tasks()
    data_answer = answer_for(tasks[0])
    data_answer["total_revenue"] = 999
    repo_answer = answer_for(tasks[2])
    repo_answer["checks"] = []

    assert verify_pilot(tasks[0], data_answer)["passed"] is False
    assert verify_pilot(tasks[2], repo_answer)["passed"] is False


def test_identity_and_evidence_are_required():
    task = load_pilot_tasks()[0]
    answer = answer_for(task)
    answer["evidence"] = []

    result = verify_pilot(task, answer)

    assert result["passed"] is False