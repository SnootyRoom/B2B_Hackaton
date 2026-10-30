import json
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import make_client


def _notice(reg_number: str = "0365000000000000001", **extra: Any) -> dict[str, Any]:
    return {
        "reg_number": reg_number,
        "law": "44",
        "subject": "Сопровождение программного обеспечения",
        "nmck": 4200000,
        "method": "auction",
        "customer_inn": "7017000019",
        "region": "Томская область",
        **extra,
    }


def _upload(client: TestClient, *files: tuple[str, bytes]) -> dict[str, Any]:
    r = client.post(
        "/api/procurements/upload",
        files=[("files", (name, content, "application/octet-stream")) for name, content in files],
    )
    assert r.status_code == 202, r.text
    task = client.get(f"/api/tasks/{r.json()['task_id']}")
    assert task.status_code == 200
    result: dict[str, Any] = task.json()
    return result


def test_upload_json_end_to_end(client: TestClient) -> None:
    task = _upload(client, ("a.json", json.dumps(_notice()).encode()))
    assert task["status"] == "done"
    assert task["processed"] == task["total"] == 1
    f = task["files"][0]
    assert f["status"] == "ok"
    assert f["warnings"][0]["code"] == "EGRUL_UNAVAILABLE"

    rows = client.get("/api/results").json()
    assert len(rows) == 1
    assert rows[0]["nmck"] == 4200000
    assert rows[0]["recommendation"] in {"participate", "consider", "skip"}

    detail = client.get(f"/api/procurements/{f['procurement_ids'][0]}").json()
    assert detail["data"]["subject"] == "Сопровождение программного обеспечения"
    assert detail["score"] is not None
    assert detail["customer_error"] == "EGRUL_UNAVAILABLE"


def test_bad_file_does_not_break_batch(client: TestClient) -> None:
    task = _upload(
        client,
        ("good.json", json.dumps(_notice()).encode()),
        ("broken.json", b"{not json"),
        ("no_nmck.json", json.dumps({"reg_number": "1", "subject": "x"}).encode()),
    )
    assert task["status"] == "partial"
    codes = [f["error"]["code"] if f["error"] else None for f in task["files"]]
    assert codes == [None, "UNSUPPORTED_FORMAT", "MISSING_REQUIRED_FIELD"]
    assert task["files"][2]["error"]["message"] == "В файле не найдено: НМЦК"


def test_all_files_failed(client: TestClient) -> None:
    assert _upload(client, ("x.json", b"[]1"))["status"] == "failed"


def test_unsupported_extension_rejected(client: TestClient) -> None:
    r = client.post("/api/procurements/upload", files=[("files", ("a.pdf", b"%PDF", "x"))])
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "UNSUPPORTED_FORMAT"


def test_duplicate_reg_number_updates_record(client: TestClient) -> None:
    _upload(client, ("a.json", json.dumps(_notice(subject="Старый предмет")).encode()))
    _upload(client, ("a.json", json.dumps(_notice(subject="Новый предмет")).encode()))
    items = client.get("/api/procurements").json()
    assert [p["subject"] for p in items] == ["Новый предмет"]


def test_multi_lot_json(client: TestClient) -> None:
    lots = [_notice("32600000001-1", lot_number=1), _notice("32600000001-2", lot_number=2)]
    task = _upload(client, ("lots.json", json.dumps(lots).encode()))
    assert len(task["files"][0]["procurement_ids"]) == 2


def test_user_isolation(client: TestClient) -> None:
    task = _upload(client, ("a.json", json.dumps(_notice()).encode()))
    pid = task["files"][0]["procurement_ids"][0]

    other = make_client("other@example.com")
    assert other.get(f"/api/procurements/{pid}").status_code == 404
    assert other.get(f"/api/tasks/{task['id']}").status_code == 404
    assert other.get("/api/procurements").json() == []
    assert other.get("/api/results").json() == []
    other_task = other.post("/api/score", json={}).json()["task_id"]
    assert other.get(f"/api/tasks/{other_task}").json()["total"] == 0


def test_rescore_after_profile_change(client: TestClient) -> None:
    _upload(client, ("a.json", json.dumps(_notice()).encode()))
    profile = client.get("/api/scoring-profiles/active").json()
    assert len(profile["rules"]) == 5  # правила по умолчанию
    profile["rules"].append(
        {
            "id": "r_nmck",
            "group": "procurement",
            "kind": "weighted",
            "field": "nmck",
            "operator": "between",
            "value": [1000000, 10000000],
            "weight": 3,
            "label": "НМЦК от 1 до 10 млн ₽",
        }
    )
    r = client.put("/api/scoring-profiles/active", json={**profile, "rescore": True})
    assert r.status_code == 200, r.text
    task = client.get(f"/api/tasks/{r.json()['task_id']}").json()
    assert task["kind"] == "rescore"
    assert task["status"] == "done"
    assert task["total"] == 1


def test_invalid_rule_rejected(client: TestClient) -> None:
    profile = client.get("/api/scoring-profiles/active").json()
    profile["rules"].append(
        {
            "id": "bad",
            "group": "procurement",
            "kind": "weighted",
            "field": "nmck",
            "operator": "between",
            "value": [10, 1],
            "weight": 2,
            "label": "x",
        }
    )
    r = client.put("/api/scoring-profiles/active", json=profile)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_parse_without_llm_key(client: TestClient) -> None:
    r = client.post("/api/scoring-profiles/parse", json={"text": "Интересны аукционы"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "LLM_UNAVAILABLE"
    assert client.get("/api/scoring-profiles/catalog").json()["llm_enabled"] is False


def test_organization_lookup_goes_to_queue(client: TestClient) -> None:
    r = client.get("/api/organizations/7017000019")
    assert r.status_code == 202
    task = client.get(f"/api/tasks/{r.json()['task_id']}").json()
    assert task["kind"] == "egrul_lookup"
    assert task["error"]["code"] == "EGRUL_UNAVAILABLE"


def test_engine_bridge_scores_with_real_engine() -> None:
    from datetime import date, timedelta
    from decimal import Decimal

    from app.models import utcnow
    from app.schemas.customer import CustomerData, CustomerStatus
    from app.schemas.procurement import ProcurementData
    from app.schemas.scoring import ScoringProfileData, ScoringRule
    from app.scoring.defaults import default_profile
    from app.tasks.pipeline import run_engine

    profile = ScoringProfileData.model_validate(
        default_profile().model_dump(mode="json", exclude_none=True)
    )
    profile.rules.append(
        ScoringRule.model_validate(
            {"id": "r_nmck", "group": "procurement", "kind": "weighted", "field": "nmck",
             "operator": "between", "value": [1000000, 10000000], "weight": 3, "label": "НМЦК"}
        )
    )  # fmt: skip
    data = ProcurementData(
        reg_number="1",
        subject="Ремонт",
        nmck=Decimal(4200000),
        application_deadline=utcnow() + timedelta(days=10),
        parsed_by="json",
    )
    ok = CustomerData(
        inn="7017000019",
        name="ОК",
        status=CustomerStatus.active,
        registration_date=date(2010, 1, 1),
    )
    r = run_engine(data, ok, profile, None)
    assert r.total == 100 and r.recommendation == "participate"
    assert {x.rule_id: x.field for x in r.rules}["r_nmck"] == "nmck"

    bad = ok.model_copy(update={"status": CustomerStatus.liquidating})
    r = run_engine(data, bad, profile, None)
    assert r.total == 0 and r.recommendation == "skip"
    assert r.stop_factors == ["stop_customer_status"]


def test_list_upload_tasks(client: TestClient) -> None:
    first = _upload(client, ("a.json", json.dumps(_notice()).encode()))
    second = _upload(client, ("b.json", json.dumps(_notice("2")).encode()))
    client.post("/api/score", json={})

    tasks = client.get("/api/tasks", params={"kind": "upload"}).json()
    assert [t["id"] for t in tasks] == [second["id"], first["id"]]
    assert tasks[0]["files"][0]["filename"] == "b.json"

    other = make_client("other@example.com")
    assert other.get("/api/tasks").json() == []


def test_string_lists_of_digits_stay_strings(client: TestClient) -> None:
    _upload(client, ("a.json", json.dumps(_notice()).encode()))
    profile = client.get("/api/scoring-profiles/active").json()
    profile["rules"] += [
        {
            "id": "r_law",
            "group": "procurement",
            "kind": "weighted",
            "field": "law",
            "operator": "in",
            "value": ["44", "223"],
            "weight": 2,
            "label": "Закон",
        },
        {
            "id": "r_okpd",
            "group": "fit",
            "kind": "weighted",
            "field": "okpd2_codes",
            "operator": "prefix_in",
            "value": ["62", "63.11"],
            "weight": 2,
            "label": "ОКПД2",
        },
    ]
    r = client.put("/api/scoring-profiles/active", json={**profile, "rescore": True})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/tasks/{r.json()['task_id']}").json()["status"] == "done"
    saved = {x["id"]: x["value"] for x in r.json()["profile"]["rules"]}
    assert saved["r_law"] == ["44", "223"]
    assert saved["r_okpd"] == ["62", "63.11"]


def test_redelivered_task_restarts_progress(client: TestClient) -> None:
    from app.tasks.jobs import run_task

    first = _upload(client, ("a.json", json.dumps(_notice()).encode()), ("b.json", b"{bad"))
    run_task(first["id"])

    task = client.get(f"/api/tasks/{first['id']}").json()
    assert task["processed"] == task["total"] == 2
    assert task["status"] == "partial"
    assert [f["status"] for f in task["files"]] == ["ok", "error"]
