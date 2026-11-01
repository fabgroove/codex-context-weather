import concurrent.futures
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/contexte-reprise-projet/scripts"))
import context_weather as w
import inline_weather
spec = importlib.util.spec_from_file_location("weather_install", ROOT / "install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class WeatherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / "sessions").mkdir()
        self.path = self.home / "sessions/rollout-test.jsonl"
        self.session = "test-session"
        self.path.write_text(json.dumps({"type": "session_meta", "payload": {"id": self.session}}) + "\n")
        self.payload = {"session_id": self.session, "transcript_path": str(self.path), "hook_event_name": "PostToolUse",
                        "tool_input": {"secret_fixture": "DO_NOT_RETAIN"}, "tool_response": "DO_NOT_RETAIN"}

    def tearDown(self):
        self.tmp.cleanup()

    def token(self, tokens, window=1000, cumulative=999999):
        d = {"type": "event_msg", "timestamp": "2026-01-01T00:00:00Z", "payload": {"type": "token_count", "info": {
             "last_token_usage": {"total_tokens": tokens}, "total_token_usage": {"total_tokens": cumulative}, "model_context_window": window}}}
        with self.path.open("a") as f:
            f.write(json.dumps(d) + "\n")

    def test_exact_threshold_and_dedup(self):
        self.token(599)
        self.assertEqual(w.run_hook(self.payload, self.home), {})
        self.token(600)
        self.assertIn("60 %", w.run_hook(self.payload, self.home)["systemMessage"])
        self.token(630)
        self.assertEqual(w.run_hook(self.payload, self.home), {})

    def test_configurable_threshold(self):
        (self.home / "context-weather.json").write_text('{"threshold_percent":75,"action":"notify"}')
        self.token(700)
        self.assertEqual(w.run_hook(self.payload, self.home), {})
        self.token(750)
        self.assertIn("75 %", w.run_hook(self.payload, self.home)["systemMessage"])

    def test_english_alert_and_language_validation(self):
        (self.home / "context-weather.json").write_text('{"language":"en"}')
        self.token(600)
        out = w.run_hook(self.payload, self.home)
        self.assertIn("Context weather: 60%", out["systemMessage"])
        self.assertIn("Respond in English", out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(w.run_hook(self.payload, self.home), {})
        (self.home / "context-weather.json").write_text('{"language":"xx"}')
        with self.assertRaises(ValueError):
            w.read_settings(self.home)

    def test_install_language_and_update_preserves_it(self):
        installer.install(self.home, 60, "prepare", language="en")
        self.assertEqual(w.read_settings(self.home)["language"], "en")
        installer.install(self.home, 70, "notify", replace=True)
        self.assertEqual(w.read_settings(self.home)["language"], "en")
        self.assertEqual(w.read_settings(self.home)["threshold_percent"], 70)

    def test_cumulative_usage_is_not_context(self):
        self.token(140, cumulative=999999999)
        r = w.run_hook(self.payload, self.home, True)
        self.assertEqual(r["measurement"]["percent"], 14)

    def test_unknown_not_zero(self):
        self.assertEqual(w.run_hook(self.payload, self.home, True)["status"], "unavailable")
        self.token(610, window=0)
        self.assertEqual(w.run_hook(self.payload, self.home, True)["status"], "unavailable")

    def test_no_alert_from_old_counter_after_compaction_hook(self):
        self.token(800)
        self.assertTrue(w.run_hook(self.payload, self.home))
        p = dict(self.payload, hook_event_name="PostCompact")
        self.assertEqual(w.run_hook(p, self.home), {})
        self.assertEqual(w.run_hook(self.payload, self.home), {})
        self.token(100)
        self.assertEqual(w.run_hook(self.payload, self.home), {})
        self.token(700)
        self.assertTrue(w.run_hook(self.payload, self.home))

    def test_compaction_marker_also_resets(self):
        self.token(800)
        self.assertTrue(w.run_hook(self.payload, self.home))
        with self.path.open("a") as f:
            f.write('{"type":"compacted","payload":{"message":"not retained"}}\n')
        self.assertEqual(w.run_hook(self.payload, self.home), {})
        self.token(700)
        self.assertTrue(w.run_hook(self.payload, self.home))

    def test_tool_content_never_retained(self):
        self.token(800)
        out = w.run_hook(self.payload, self.home)
        state = list((self.home / "context-weather-state").glob("*.json"))[0].read_text()
        for s in [state, json.dumps(out)]:
            self.assertNotIn("DO_NOT_RETAIN", s)
            self.assertNotIn(str(self.path), s)

    def test_unsafe_path_and_session_refused(self):
        self.token(800)
        with self.assertRaises(ValueError):
            w.measure(str(self.path), "other-session", self.home)
        outside = self.home / "outside.jsonl"
        outside.write_bytes(self.path.read_bytes())
        with self.assertRaises(ValueError):
            w.measure(str(outside), self.session, self.home)
        linked = self.home / "sessions/link.jsonl"
        linked.symlink_to(outside)
        with self.assertRaises(ValueError):
            w.measure(str(linked), self.session, self.home)

    def test_parallel_hooks_alert_once(self):
        self.token(800)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: w.run_hook(self.payload, self.home), range(12)))
        self.assertEqual(sum(bool(r) for r in results), 1)

    def test_inline_snapshot_escapes_labels_and_never_changes_alert_state(self):
        self.token(610)
        out = self.home / "inline.html"
        receipt = inline_weather.create_fragment(self.session, str(self.path), '</script><script>bad()</script>', out, self.home)
        content = out.read_text()
        self.assertNotIn('</script><script>bad()', content)
        self.assertIn('\\u003c/script>', content)
        self.assertNotIn('fetch(', content)
        self.assertNotIn('@@SAMPLE@@', content)
        self.assertEqual(receipt["percent"], 61)
        self.assertFalse(receipt["live_polling"])
        self.assertFalse((self.home / "context-weather-state").exists())
        with self.assertRaises(FileExistsError):
            inline_weather.create_fragment(self.session, str(self.path), "Other", out, self.home)

    def test_inline_snapshot_refuses_unknown_measurement(self):
        out = self.home / "inline.html"
        with self.assertRaises(ValueError):
            inline_weather.create_fragment(self.session, str(self.path), "Fixture", out, self.home)
        self.assertFalse(out.exists())

    def test_native_event_adapter(self):
        session, sample = w.app_server_sample({"method":"thread/tokenUsage/updated","params":{
            "threadId":"fictional", "tokenUsage":{"last":{"totalTokens":610},"total":{"totalTokens":999999},"modelContextWindow":1000}}})
        self.assertEqual(session, "fictional")
        self.assertEqual(sample["percent"], 61)

    def test_partial_tail_never_creates_measurement(self):
        with self.path.open("ab") as f:
            f.write(b'{"type":"event_msg","payload":{"type":"token_count"')
        self.assertEqual(w.run_hook(self.payload, self.home, True)["status"], "unavailable")

    def test_install_preserves_hooks_and_trust(self):
        original = {"hooks":{"PostToolUse":[{"hooks":[{"type":"command","command":"existing-command"}]}]}}
        (self.home / "hooks.json").write_text(json.dumps(original))
        trust = b'[hooks.state.example]\ntrusted_hash = "fixture-do-not-change"\n'
        (self.home / "config.toml").write_bytes(trust)
        receipt = installer.install(self.home, 60, "prepare")
        self.assertEqual((self.home / "config.toml").read_bytes(), trust)
        after = json.loads((self.home / "hooks.json").read_text())
        self.assertEqual(after["hooks"]["PostToolUse"][0], original["hooks"]["PostToolUse"][0])
        self.assertEqual(receipt["status"], "installed_pending_native_hook_review")
        self.assertTrue(Path(receipt["backup"]).is_dir())
        with self.assertRaises(ValueError):
            installer.install(self.home, 75, "prepare")


if __name__ == "__main__":
    unittest.main()
