"""Tests of batch-list parsing and monitor command construction (utils/batch_config.py)."""
import importlib.util, json, os, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("batch_config", os.path.join(HERE, os.pardir, "src", "utils", "batch_config.py"))
bc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bc)


def write(tmp, name, content):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content if isinstance(content, str) else json.dumps(content))
    return p


class BatchConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_text_list(self):
        p = write(self.tmp, "list.txt", "# comment\nmacros/a.pmr\n\nmacros/b.pmr, WINWORD.EXE\n")
        cfg, entries = bc.load_batch_list(p)
        self.assertEqual([os.path.basename(e["path"]) for e in entries], ["a.pmr", "b.pmr"])
        self.assertEqual(entries[1]["app"], "WINWORD.EXE")
        self.assertTrue(os.path.isabs(entries[0]["path"]))
        self.assertFalse(cfg["clear_app_caches"])
        self.assertEqual(cfg["app_exit_timeout"], 5)
        self.assertIsNone(bc.monitor_invocation(cfg, "WINWORD.EXE", entries[1]["path"]))

    def test_app_exit_timeout_from_json(self):
        p = write(self.tmp, "list.json", {"entries": ["a.pmr"], "app_exit_timeout": 12})
        cfg, _ = bc.load_batch_list(p)
        self.assertEqual(cfg["app_exit_timeout"], 12)

    def test_json_monitor_command(self):
        out = os.path.join(self.tmp, "runs")
        p = write(self.tmp, "list.json", {"entries": ["w.pmr", {"path": "c.pmr", "app": "chrome"}],
                                          "data_dump_path": out, "test_type": "t1",
                                          "monitor_command": ["mon", "--name", "{name}", "{output}"]})
        cfg, entries = bc.load_batch_list(p, test_type_override="t2")
        args, cwd, out_dir, name = bc.monitor_invocation(cfg, "chrome", entries[1]["path"])
        self.assertEqual(name, "chrome")
        self.assertEqual(out_dir, os.path.normpath(os.path.join(out, "t2")))
        self.assertEqual(args, ["mon", "--name", "chrome", os.path.join(out_dir, "chrome.csv")])

    def test_monitor_without_output_folder(self):
        p = write(self.tmp, "list.json", {"entries": ["w.pmr"], "monitor_command": ["mon", "-i", "100", "{output}"]})
        cfg, entries = bc.load_batch_list(p)
        args, _, out_dir, name = bc.monitor_invocation(cfg, None, entries[0]["path"])
        self.assertEqual(args, ["mon"]); self.assertIsNone(out_dir); self.assertEqual(name, "w")

    def test_malformed_list(self):
        p = write(self.tmp, "bad.json", "{not json")
        cfg, entries = bc.load_batch_list(p)
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
