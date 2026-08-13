# -*- coding: utf-8 -*-
import tempfile
import time
from pathlib import Path

from factory.engine import Engine
from factory.store import Store


def test_store_and_mock_run():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp))
        store.update_settings({"backend": "mock"})
        agents = store.list_agents()
        assert len(agents) >= 3
        fac = store.save_factory(
            {
                "name": "Тест",
                "goal": "Собрать короткий план",
                "agent_ids": [agents[0]["id"], agents[1]["id"]],
                "mode": "round_robin",
                "max_rounds": 1,
                "auto_continue": True,
                "max_tokens": 80,
                "temperature": 0.2,
            }
        )
        engine = Engine(store)
        run = engine.start(fac["id"], brief="Коротко.")
        assert run["id"]
        deadline = time.time() + 8
        status = ""
        while time.time() < deadline:
            live = store.get_run(run["id"])
            status = (live or {}).get("status")
            if status in ("done", "error"):
                break
            time.sleep(0.1)
        live = store.get_run(run["id"])
        assert live is not None
        assert status == "done", live
        spoken = [m for m in live["messages"] if m.get("role") == "assistant"]
        assert len(spoken) >= 2, live["messages"]
        assert live.get("summary")
        print("ok", live["id"], "messages", len(live["messages"]))


if __name__ == "__main__":
    test_store_and_mock_run()
