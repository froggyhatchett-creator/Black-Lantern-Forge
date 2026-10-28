import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
from fake_ollama import FakeOllama  # noqa: E402
spec = importlib.util.spec_from_file_location('real_model_acceptance', TOOLS / 'real_model_acceptance.py')
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class HarnessWindowTests(unittest.TestCase):
    def test_harness_never_sends_a_request_without_num_ctx(self):
        bodies = []
        original = FakeOllama.chat
        def spy(self, h, body):
            bodies.append(body)
            return original(self, h, body)
        out = Path(tempfile.mkdtemp()) / 'r.json'
        harness.RESULTS.clear(); harness.BENCH.clear()
        argv = ['x', '--simulate', '--runs', '1', '--models', 'qwen3.5:4b', '--think', 'both', '--out', str(out)]
        with patch.object(FakeOllama, 'chat', spy), patch('sys.argv', argv):
            harness.main()
        self.assertGreater(len(bodies), 10)
        missing = [b for b in bodies if (b.get('options') or {}).get('num_ctx') != 8192]
        self.assertEqual(missing, [], 'requests without the explicit window would let Ollama load the model maximum')
        self.assertIn('SIMULATED', json.loads(out.read_text())['mode'])

    def test_custom_window_is_applied_everywhere_and_validated(self):
        with patch('sys.argv', ['x', '--simulate', '--num-ctx', '100']), self.assertRaises(ValueError):
            harness.main()


if __name__ == '__main__':
    unittest.main()
