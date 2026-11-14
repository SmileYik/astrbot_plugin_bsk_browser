"""测试 bsk/logger.py 的日志截断工具函数 truncate_log_text。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from bsk.logger import truncate_log_text  # noqa: E402


class TestLoggerTruncation(unittest.TestCase):
    def test_truncate_within_limit(self):
        self.assertEqual(truncate_log_text("hello", 10), "hello")
        self.assertEqual(truncate_log_text("hello", 5), "hello")

    def test_truncate_exceeds_limit(self):
        result = truncate_log_text("abcdefghij", 5)
        self.assertEqual(result, "abcde... [已截断，共 10 字符]")

    def test_truncate_disabled_when_zero_or_negative(self):
        self.assertEqual(truncate_log_text("abcdefghij", 0), "abcdefghij")
        self.assertEqual(truncate_log_text("abcdefghij", -1), "abcdefghij")

    def test_truncate_non_str_safe(self):
        self.assertEqual(truncate_log_text(12345, 3), "123... [已截断，共 5 字符]")
        self.assertEqual(truncate_log_text(None, 5), "")
        self.assertEqual(truncate_log_text(["item1", "item2"], 10), "['item1', ... [已截断，共 18 字符]")


if __name__ == "__main__":
    unittest.main()
