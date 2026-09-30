"""네트워크 호출 없이 검색 결과와 원문 수집 계약을 검증한다."""

import unittest
from unittest.mock import Mock, patch

from tools.web import fetch_page, web_search


class WebToolTests(unittest.TestCase):
    @patch("tools.web._client")
    def test_search_returns_urls_without_snippets(self, client):
        client.return_value.search.return_value = {
            "results": [
                {"url": "https://example.org/article#section", "title": "기사", "content": "잘린 요약"},
                {"url": "https://example.org/article#other", "title": "중복"},
                {"url": "file:///etc/passwd", "title": "잘못된 URL"},
            ]
        }
        self.assertEqual(web_search("신약 투자"), [{"url": "https://example.org/article", "title": "기사"}])
        client.return_value.search.assert_called_once_with(
            query="신약 투자", search_depth="basic", max_results=5,
            include_answer=False, include_raw_content=False,
        )

    @patch("tools.web.requests.get")
    def test_fetch_page_reads_original_html_and_publication_date(self, get):
        response = Mock()
        response.url = "https://example.org/final"
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.content = b"""
            <html><head><meta property="article:published_time" content="2025-09-12T10:00:00+09:00">
            <script>ignore this script</script></head>
            <body><nav>navigation only</nav>
            <article><h1>Clinical update</h1><p>The first patient was dosed.</p></article></body></html>
        """
        get.return_value = response
        page = fetch_page("https://example.org/original")
        self.assertEqual(page["url"], "https://example.org/final")
        self.assertEqual(page["published"], "2025-09-12")
        self.assertIn("The first patient was dosed.", page["text"])
        self.assertNotIn("navigation only", page["text"])
        self.assertNotIn("ignore this script", page["text"])
        self.assertRegex(page["accessed"], r"^\d{4}-\d{2}-\d{2}$")
        get.assert_called_once()

    @patch("tools.web.requests.get")
    def test_fetch_page_rejects_empty_body(self, get):
        response = Mock()
        response.url = "https://example.org/empty"
        response.headers = {"Content-Type": "text/html"}
        response.content = b"<html><body><script>only script</script></body></html>"
        get.return_value = response
        with self.assertRaises(ValueError):
            fetch_page(response.url)

    @patch("tools.web.requests.get")
    def test_fetch_page_uses_body_when_article_is_empty(self, get):
        response = Mock()
        response.url = "https://example.org/article"
        response.headers = {"Content-Type": "text/html"}
        response.content = (
            b"<html><body><article><span></span></article>"
            b"<section>Clinical update</section></body></html>"
        )
        get.return_value = response
        self.assertIn("Clinical update", fetch_page(response.url)["text"])

    def test_fetch_page_rejects_non_http_url(self):
        with self.assertRaises(ValueError):
            fetch_page("file:///tmp/private")


if __name__ == "__main__":
    unittest.main()
