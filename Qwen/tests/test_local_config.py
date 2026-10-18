import os
import unittest
from unittest.mock import patch

from agent.common.config import get_vllm_config


class LocalConfigTests(unittest.TestCase):
    def test_defaults_match_local_service(self):
        with patch.dict(os.environ,{},clear=True):
            config=get_vllm_config()
        self.assertEqual(config.base_url,"http://127.0.0.1:8000/v1")
        self.assertEqual(config.model,"qwen-local")

    def test_explicit_remote_override_still_supported(self):
        with patch.dict(os.environ,{"VLLM_BASE_URL":"http://example.test:8000/v1/",
                                   "VLLM_MODEL":"remote-model"},clear=True):
            config=get_vllm_config()
        self.assertEqual(config.base_url,"http://example.test:8000/v1")
        self.assertEqual(config.model,"remote-model")
