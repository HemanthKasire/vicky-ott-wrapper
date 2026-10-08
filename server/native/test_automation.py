import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("automation", Path(__file__).with_name("automation.py"))
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = a.Store(Path(self.temp.name) / "state.sqlite")
        self.config = {"bridge_path": "/webhook/bridge", "legacy_path": "/webhook/torrent-add",
                       "movie_path": "/webhook/movie-secret", "telegram_path": "/webhook/bot-secret",
                       "portal_token": "test-token", "telegram_secret": "bot-secret", "authorized_user_ids": ["42"],
                       "channels": {k: {"telegram_token": "fake", "chat_id": "42", "discord_url": "https://example.invalid"}
                                    for k in ("ott", "movie", "monitor")}}
        self.calls = []
        self.result = {"connected": True}
        def helper(action, payload=None):
            self.calls.append((action, payload))
            return self.result.copy()
        self.app = a.Automation(self.config, self.store, helper)

    def http(self, path, body, headers=None):
        server = a.Server(("127.0.0.1", 0), a.Handler, self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request("http://127.0.0.1:" + str(server.server_port) + path,
                                             data=json.dumps(body).encode(), headers=headers or {})
            try:
                response = urllib.request.urlopen(request, timeout=3)
            except urllib.error.HTTPError as error:
                response = error
            return response.code, json.load(response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_auth_rejects_before_helper(self):
        self.assertEqual(self.http("/webhook/bridge", {"action": "status"})[0], 401)
        self.assertEqual(self.calls, [])

    def test_legacy_route_requires_auth(self):
        self.assertEqual(self.http("/webhook/torrent-add", {"url": "magnet:whatever"})[0], 401)
        self.assertEqual(self.calls, [])

    def test_unknown_action_cannot_reach_helper(self):
        status, _ = self.http("/webhook/bridge", {"action": "cleanup-old"}, {"x-portal-token": "test-token"})
        self.assertEqual(status, 400)
        self.assertEqual(self.calls, [])

    def test_manual_tv_details_preserved(self):
        body = {"action": "add", "mediaType": "show", "magnet": "magnet:test",
                "manualTV": {"title": "Test Show", "season": 2, "episode": None}}
        self.result = {"queued": True, "infoHash": "A" * 40}
        self.assertEqual(self.app.bridge(body, "family")[0], 200)
        self.assertEqual(self.calls[0][1]["manualTV"], body["manualTV"])
        self.assertEqual(self.calls[0][1]["userId"], "family")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs WHERE kind='duplicate'").fetchone()[0], 1)

    def test_helper_validation_error_is_http_error(self):
        self.result = {"error": "Invalid season", "status": 400}
        status, result = self.app.bridge({"action": "add"})
        self.assertEqual(status, 400)
        self.assertEqual(result["message"], "Invalid season")

    def test_status_cache_and_add_invalidation(self):
        self.app.bridge({"action": "status"})
        self.app.bridge({"action": "status"})
        self.assertEqual(len(self.calls), 1)
        self.app.bridge({"action": "add"})
        self.app.bridge({"action": "status"})
        self.assertEqual(len(self.calls), 3)

    def test_queue_survives_restart_and_deduplicates(self):
        self.assertTrue(self.store.enqueue("test", "notify", {"text": "hello"}))
        reopened = a.Store(self.store.path)
        self.assertFalse(reopened.enqueue("test", "notify", {}))
        self.assertEqual(reopened.due()[0][0], "test")
        reopened.finish("test")
        self.assertFalse(reopened.enqueue("test", "notify", {}))

    def test_only_movie_added_events_notify(self):
        self.app.movie_event({"notificationType": "ItemAdded", "itemType": "Episode", "name": "Test"})
        self.assertEqual(self.store.due(), [])
        event = {"notificationType": "ItemAdded", "itemType": "Movie", "name": "Test", "itemId": "abc"}
        self.app.movie_event(event)
        self.app.movie_event(event)
        self.assertEqual(len(self.store.due()), 1)

    def test_telegram_secret_and_update_deduplication(self):
        body = {"update_id": 7, "message": {"from": {"id": 42}, "chat": {"id": 42}, "text": "/status"}}
        self.assertEqual(self.http("/webhook/bot-secret", body)[0], 401)
        headers = {"X-Telegram-Bot-Api-Secret-Token": "bot-secret"}
        self.assertEqual(self.http("/webhook/bot-secret", body, headers)[0], 200)
        self.assertEqual(self.http("/webhook/bot-secret", body, headers)[0], 200)
        self.assertEqual(len(self.store.due()), 1)

    def test_unauthorized_telegram_user_cannot_execute(self):
        self.app.process_telegram({"message": {"from": {"id": 99}, "chat": {"id": 99}, "text": "/docker"}}, "update")
        self.assertEqual(self.calls, [])
        self.assertIn("not authorized", json.loads(self.store.due()[0][2])["text"])

    def test_telegram_command_injection_becomes_help(self):
        self.result = {"stdout": "Help", "code": 0}
        self.app.process_telegram({"message": {"from": {"id": 42}, "chat": {"id": 42}, "text": "/status;rm /"}}, "update")
        self.assertEqual(self.calls, [("stats", {"command": "help"})])

    def test_delivery_retry_does_not_repeat_successful_destination(self):
        calls = []
        def deliver(channel, destination, text, poster):
            calls.append(destination)
            if destination == "discord" and calls.count("discord") == 1:
                raise TimeoutError()
        payload = {"channel": "ott", "text": "Test"}
        with patch.object(a, "deliver", side_effect=deliver):
            with self.assertRaises(TimeoutError):
                self.app.notify("event", payload)
            self.app.notify("event", payload)
        self.assertEqual(calls, ["telegram", "discord", "discord"])

    def test_duplicate_ack_only_after_both_deliveries(self):
        self.result = {"ready": True, "duplicate": True}
        with patch.object(a, "deliver", side_effect=TimeoutError()):
            with self.assertRaises(TimeoutError):
                self.app.duplicate("duplicate", {"infoHash": "A" * 40}, 0)
        self.assertEqual([x[0] for x in self.calls], ["duplicate-check-one"])

    def test_cpu_only_warning_is_silent(self):
        result = {"code": 0, "stdout": "ALERT: warning\nTime: now\n- CPU usage is 100%\n- CPU steal is 80%\n- I/O wait is 30%"}
        state, text = a.health_transition(result, {}, "docker-n8n")
        self.assertFalse(state["inAlert"])
        self.assertIsNone(text)

    def test_actionable_warning_and_recovery(self):
        warning = {"code": 0, "stdout": "ALERT: warning\nTime: now\n- RAM usage is 95%"}
        state, message = a.health_transition(warning, {}, "docker-n8n")
        self.assertIn("RAM", message)
        warning["stdout"] = warning["stdout"].replace("now", "later")
        self.assertIsNone(a.health_transition(warning, state, "docker-n8n")[1])
        recovered, message = a.health_transition({"code": 0, "stdout": "OK"}, state, "docker-n8n")
        self.assertIn("recovered", message)
        self.assertFalse(recovered["inAlert"])

    def test_failed_health_check_always_alerts(self):
        state, message = a.health_transition({"error": "SSH unavailable"}, {}, "jellyfin")
        self.assertTrue(state["inAlert"])
        self.assertIn("SSH unavailable", message)


if __name__ == "__main__":
    unittest.main()
