import sys
import os
import unittest

# Add src to python path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from algorithms import (
    has_cjk,
    super_clean,
    simplified_metaphone,
    calculate_similarity,
    check_fuzzy_match,
    sanitize_hallucinations
)

class TestAlgorithms(unittest.TestCase):

    def test_has_cjk(self):
        self.assertFalse(has_cjk("hello"))
        self.assertFalse(has_cjk("123"))
        self.assertTrue(has_cjk("你好"))
        self.assertTrue(has_cjk("こんにちは")) # Japanese
        self.assertTrue(has_cjk("안녕하세요")) # Korean
        self.assertTrue(has_cjk("hello 你好"))
        self.assertFalse(has_cjk(""))
        self.assertFalse(has_cjk(None))

    def test_super_clean(self):
        self.assertEqual(super_clean("Hello, World!"), "helloworld")
        self.assertEqual(super_clean("123-456"), "123456")
        self.assertEqual(super_clean("It's a test."), "itsatest")
        self.assertEqual(super_clean("你好，世界！"), "你好世界")
        self.assertEqual(super_clean(""), "")
        self.assertEqual(super_clean(None), "")

    def test_simplified_metaphone(self):
        self.assertEqual(simplified_metaphone("hello"), "h4")
        self.assertEqual(simplified_metaphone("world"), "w643")
        self.assertEqual(simplified_metaphone("test"), "323")
        self.assertEqual(simplified_metaphone("apple"), "a14")

    def test_calculate_similarity(self):
        self.assertEqual(calculate_similarity("test", "test"), 1.0)
        self.assertTrue(calculate_similarity("abcd", "xyzq") < 0.3)
        self.assertTrue(calculate_similarity("testing", "testin") > 0.8)

    def test_check_fuzzy_match(self):
        self.assertTrue(check_fuzzy_match("hello", "hello"))
        self.assertTrue(check_fuzzy_match("Hello!", "hello"))
        self.assertTrue(check_fuzzy_match("testing", "testin"))
        self.assertTrue(check_fuzzy_match("apple", "aple"))
        self.assertFalse(check_fuzzy_match("hello", "world"))
        self.assertFalse(check_fuzzy_match("apple", "orange"))
        self.assertFalse(check_fuzzy_match("are", "a"))

    def test_sanitize_hallucinations(self):
        def make_word(text, start, end):
            return {"text": text, "start": start, "end": end}

        words = [
            make_word("hello", 0.0, 0.5),
            make_word("world", 0.6, 1.0)
        ]
        self.assertEqual(sanitize_hallucinations(words), words)

        hallucination = [
            make_word("test", 0.0, 0.1),
            make_word("test", 0.1, 0.2),
            make_word("test", 0.2, 0.3),
            make_word("test", 0.3, 0.4),
            make_word("test", 0.4, 0.5),
        ]
        sanitized = sanitize_hallucinations(hallucination)
        self.assertEqual(len(sanitized), 2)
        self.assertEqual(sanitized[0]["text"], "test")
        self.assertEqual(sanitized[1]["text"], "test")

if __name__ == '__main__':
    unittest.main()
