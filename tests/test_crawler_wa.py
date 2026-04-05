import ssl
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch

from crawler_wa import (
    ValidationCache,
    GroupCheckResult,
    adapt_query_for_provider,
    extract_aol_targets,
    build_keyword_discovery_queries,
    build_sheet_rows,
    expand_keywords_to_queries,
    extract_member_count_from_text,
    extract_telegram_page_extra,
    extract_brave_targets,
    extract_whatsapp_member_count,
    is_probably_indonesian_group_name,
    is_provider_disabled,
    is_retryable_network_error,
    mark_provider_failure,
    normalize_group_url,
    extract_duckduckgo_targets,
    extract_google_targets,
    extract_group_links,
    extract_invite_links,
    extract_yahoo_targets,
    get_effective_search_delay,
    is_rate_limited_error,
    load_saved_links,
    merge_unique_links,
    normalize_invite_url,
    resolve_providers,
    resolve_max_query_workers,
    resolve_discovery_source_domains,
    reset_provider_runtime_state,
    run_scheduler,
    save_links,
    search_query_with_provider,
    search_queries_concurrently,
    sync_rows_to_sheet,
    validate_group_link,
    validate_telegram_link,
    validate_whatsapp_link,
    validate_invite,
)


class InviteParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_provider_runtime_state()

    def test_normalize_invite_url(self) -> None:
        raw = "https://chat.whatsapp.com/invite/AbCdEfGhIjKlMnOpQrStUv?foo=bar"
        self.assertEqual(
            normalize_invite_url(raw),
            "https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv",
        )

    def test_normalize_group_url_for_telegram_handle(self) -> None:
        self.assertEqual(
            normalize_group_url("https://t.me/pythontelegrambotgroup", "telegram"),
            "https://t.me/pythontelegrambotgroup",
        )

    def test_normalize_group_url_rejects_reserved_telegram_path(self) -> None:
        self.assertIsNone(normalize_group_url("https://t.me/share/url?url=x", "telegram"))

    def test_extract_invite_links_deduplicates(self) -> None:
        text = """
        lihat ini https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv
        dan ini juga https://chat.whatsapp.com/invite/AbCdEfGhIjKlMnOpQrStUv
        """
        self.assertEqual(
            extract_invite_links(text),
            ["https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv"],
        )

    def test_extract_duckduckgo_targets(self) -> None:
        html = """
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">
          Result
        </a>
        """
        self.assertEqual(extract_duckduckgo_targets(html), ["https://example.com/page"])

    def test_extract_group_links_for_telegram(self) -> None:
        text = """
        lihat https://t.me/pythontelegrambotgroup
        dan https://telegram.me/pythontelegrambotgroup
        """
        self.assertEqual(
            extract_group_links(text, "telegram"),
            ["https://t.me/pythontelegrambotgroup"],
        )

    def test_extract_google_targets(self) -> None:
        html = """
        <a href="/url?q=https%3A%2F%2Fexample.com%2Farticle&sa=U">Result</a>
        <a href="https://www.google.com/preferences">Prefs</a>
        """
        self.assertEqual(extract_google_targets(html), ["https://example.com/article"])

    def test_extract_brave_targets(self) -> None:
        payload = """
        {
          "type": "data",
          "nodes": [
            {"type": "data", "data": []},
            {
              "type": "data",
              "data": [
                {"body": 1},
                {"response": 2},
                {"web": 3},
                {"results": 4},
                [5],
                {"url": 6},
                "https://example.com/page"
              ]
            }
          ]
        }
        """
        self.assertEqual(extract_brave_targets(payload), ["https://example.com/page"])

    def test_extract_yahoo_targets(self) -> None:
        html = """
        <a href="https://r.search.yahoo.com/_ylt=abc/RV=2/RE=3/RO=10/RU=https%3a%2f%2fchat.whatsapp.com%2FAbCdEfGhIjKlMnOpQrStUv/RK=2/RS=test-">
          Result
        </a>
        <a href="https://www.yahoo.com/news">Internal</a>
        """
        self.assertEqual(
            extract_yahoo_targets(html),
            ["https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv"],
        )

    def test_extract_aol_targets(self) -> None:
        html = """
        <a href="https://search.aol.com/click/_ylt=abc/RV=2/RE=3/RO=10/RU=https%3a%2f%2ft.me%2Fmahasiswa_mahasiswi/RK=2/RS=test-">
          Result
        </a>
        <a href="https://www.aol.com/video">Internal</a>
        """
        self.assertEqual(extract_aol_targets(html), ["https://t.me/mahasiswa_mahasiswi"])

    def test_expand_keywords_to_queries(self) -> None:
        self.assertEqual(
            expand_keywords_to_queries(["komunitas coding"], "whatsapp", discovery_mode="focused"),
            ["site:chat.whatsapp.com komunitas coding whatsapp indonesia"],
        )

    def test_expand_keywords_to_queries_for_telegram(self) -> None:
        self.assertEqual(
            expand_keywords_to_queries(["komunitas mahasiswa"], "telegram", discovery_mode="focused"),
            ["site:t.me komunitas mahasiswa telegram indonesia"],
        )

    def test_build_keyword_discovery_queries_wide_targets_social_domains(self) -> None:
        queries = build_keyword_discovery_queries(
            "komunitas coding",
            "whatsapp",
            discovery_mode="wide",
            source_domains=["facebook.com", "instagram.com"],
        )
        self.assertIn(
            'site:facebook.com "chat.whatsapp.com" komunitas coding indonesia',
            queries,
        )
        self.assertIn(
            'site:instagram.com "chat.whatsapp.com" komunitas coding indonesia',
            queries,
        )
        self.assertIn('"chat.whatsapp.com" komunitas coding indonesia', queries)

    def test_build_keyword_discovery_queries_normalizes_source_domains(self) -> None:
        queries = build_keyword_discovery_queries(
            "komunitas mahasiswa",
            "telegram",
            discovery_mode="wide",
            source_domains=["https://www.facebook.com/groups", "facebook.com", "m.facebook.com"],
        )
        self.assertIn('site:facebook.com "t.me" komunitas mahasiswa indonesia', queries)
        self.assertIn('site:m.facebook.com "t.me" komunitas mahasiswa indonesia', queries)

    def test_resolve_discovery_source_domains_adds_extra_without_dropping_defaults(self) -> None:
        domains = resolve_discovery_source_domains(["forumkampus.id"])
        self.assertIn("facebook.com", domains)
        self.assertIn("forumkampus.id", domains)

    def test_resolve_providers_uses_platform_defaults(self) -> None:
        self.assertEqual(resolve_providers("whatsapp"), ["brave"])
        self.assertEqual(resolve_providers("telegram"), ["duckduckgo", "yahoo", "aol", "brave"])

    def test_resolve_max_query_workers_lowers_whatsapp_brave_default(self) -> None:
        self.assertEqual(resolve_max_query_workers("whatsapp", ["brave"], 20), 2)
        self.assertEqual(resolve_max_query_workers("telegram", ["duckduckgo", "brave"], 20), 8)

    def test_run_scheduler_without_schedule_runs_once(self) -> None:
        args = Namespace(schedule_every_minutes=None, schedule_max_runs=None, schedule_initial_delay_seconds=0.0)
        parser = MagicMock()
        run_once_fn = MagicMock(return_value=0)
        sleep_fn = MagicMock()
        exit_code = run_scheduler(args, parser, run_once_fn=run_once_fn, sleep_fn=sleep_fn)
        self.assertEqual(exit_code, 0)
        run_once_fn.assert_called_once_with(args, parser)
        sleep_fn.assert_not_called()

    def test_run_scheduler_stops_after_max_runs(self) -> None:
        args = Namespace(schedule_every_minutes=0.1, schedule_max_runs=2, schedule_initial_delay_seconds=0.0)
        parser = MagicMock()
        run_once_fn = MagicMock(return_value=0)
        sleep_fn = MagicMock()
        exit_code = run_scheduler(args, parser, run_once_fn=run_once_fn, sleep_fn=sleep_fn)
        self.assertEqual(exit_code, 0)
        self.assertEqual(run_once_fn.call_count, 2)
        sleep_fn.assert_called_once_with(6.0)

    def test_is_probably_indonesian_group_name(self) -> None:
        self.assertTrue(is_probably_indonesian_group_name("Komunitas Mahasiswa Indonesia"))
        self.assertTrue(is_probably_indonesian_group_name("LOWONGAN KERJA 2025"))
        self.assertTrue(is_probably_indonesian_group_name("WIRAUSAHA MUDA INDONESIA"))
        self.assertFalse(is_probably_indonesian_group_name("Python India"))
        self.assertFalse(is_probably_indonesian_group_name("مجموعة طلاب"))

    def test_adapt_query_for_provider(self) -> None:
        self.assertEqual(
            adapt_query_for_provider("brave", 'site:chat.whatsapp.com "komunitas coding" whatsapp'),
            "komunitas coding whatsapp",
        )

    def test_validate_active_from_meta_title(self) -> None:
        from unittest.mock import patch

        active_html = (
            '<meta property="og:title" content="Komunitas Coding" />'
            '<meta property="og:description" content="120 participants" />'
        )
        with patch("crawler_wa.fetch_text", return_value=active_html):
            result = validate_invite("https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv", 20, 0)
        self.assertEqual(result.status, "active")
        self.assertEqual(result.group_name, "Komunitas Coding")
        self.assertEqual(result.member_count, 120)

    def test_extract_whatsapp_member_count(self) -> None:
        html = '<meta property="og:description" content="2,345 participants" />'
        self.assertEqual(extract_whatsapp_member_count(html), 2345)

    def test_validate_inactive_when_meta_title_empty(self) -> None:
        inactive_html = '<meta property="og:title" content="" />'
        with patch("crawler_wa.fetch_text", return_value=inactive_html):
            result = validate_invite("https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv", 20, 0)
        self.assertEqual(result.status, "inactive")

    def test_extract_telegram_page_extra(self) -> None:
        html = '<div class="tgme_page_extra">10 655 members, 756 online</div>'
        self.assertEqual(extract_telegram_page_extra(html), "10 655 members, 756 online")
        self.assertEqual(extract_member_count_from_text(html, ("member", "members")), 10655)

    def test_validate_telegram_group_active(self) -> None:
        active_html = """
        <meta property="og:title" content="Kelompok Mahasiswa TI" />
        <meta property="og:description" content="Diskusi tugas dan karier." />
        <div class="tgme_page_extra">1 234 members, 10 online</div>
        """
        with patch("crawler_wa.fetch_text", return_value=active_html):
            result = validate_telegram_link("https://t.me/kelompok_mahasiswa_ti", 20, 0)
        self.assertEqual(result.status, "active")
        self.assertEqual(result.group_name, "Kelompok Mahasiswa TI")
        self.assertEqual(result.member_count, 1234)

    def test_validate_whatsapp_member_count_filter(self) -> None:
        active_html = """
        <meta property="og:title" content="Komunitas Coding Indonesia" />
        <meta property="og:description" content="49 participants" />
        """
        with patch("crawler_wa.fetch_text", return_value=active_html):
            result = validate_group_link(
                "https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv",
                "whatsapp",
                20,
                0,
                min_member_count=50,
            )
        self.assertEqual(result.status, "filtered")
        self.assertIn("di bawah minimum 50", result.reason or "")

    def test_validate_whatsapp_unknown_member_count_is_not_filtered(self) -> None:
        active_html = '<meta property="og:title" content="Komunitas Coding Indonesia" />'
        with patch("crawler_wa.fetch_text", return_value=active_html):
            result = validate_group_link(
                "https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv",
                "whatsapp",
                20,
                0,
                min_member_count=50,
            )
        self.assertEqual(result.status, "active")
        self.assertIsNone(result.member_count)

    def test_validate_group_link_filters_non_indonesian_active_name(self) -> None:
        active_html = '<meta property="og:title" content="Programming" />'
        with patch("crawler_wa.fetch_text", return_value=active_html):
            result = validate_group_link(
                "https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv",
                "whatsapp",
                20,
                0,
            )
        self.assertEqual(result.status, "filtered")

    def test_validate_telegram_channel_is_not_group(self) -> None:
        channel_html = """
        <meta property="og:title" content="Channel Kampus" />
        <meta property="og:description" content="Info kampus." />
        <div class="tgme_page_extra">9 999 subscribers</div>
        """
        with patch("crawler_wa.fetch_text", return_value=channel_html):
            result = validate_group_link("https://t.me/channelkampus", "telegram", 20, 0)
        self.assertEqual(result.status, "inactive")
        self.assertIn("channel", result.reason or "")

    def test_validate_telegram_private_invite_is_unsupported(self) -> None:
        result = validate_group_link("https://t.me/+2M7f0hL5R2hlZTI1", "telegram", 20, 0)
        self.assertEqual(result.status, "unsupported")

    def test_expand_keywords_blocks_pornography_terms(self) -> None:
        with self.assertRaises(ValueError):
            expand_keywords_to_queries(["grup bokep"], "whatsapp")

    def test_merge_unique_links(self) -> None:
        merged = merge_unique_links(
            ["https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv"],
            [
                "https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv",
                "https://chat.whatsapp.com/ZyXwVuTsRqPoNmLkJiHgFe",
            ],
        )
        self.assertEqual(
            merged,
            [
                "https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv",
                "https://chat.whatsapp.com/ZyXwVuTsRqPoNmLkJiHgFe",
            ],
        )

    def test_save_links_merges_with_existing_output(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "active_links.txt"
            output.write_text(
                "https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv\n",
                encoding="utf-8",
            )
            total_saved, new_saved = save_links(
                output,
                load_saved_links(output),
                [
                    "https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv",
                    "https://chat.whatsapp.com/ZyXwVuTsRqPoNmLkJiHgFe",
                ],
            )
            self.assertEqual((total_saved, new_saved), (2, 1))
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                (
                    "https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv\n"
                    "https://chat.whatsapp.com/ZyXwVuTsRqPoNmLkJiHgFe\n"
                ),
            )

    def test_build_sheet_rows(self) -> None:
        rows = build_sheet_rows(
            [
                GroupCheckResult(
                    platform="whatsapp",
                    url="https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv",
                    status="active",
                    group_name="Komunitas Coding",
                    member_count=120,
                )
            ]
        )
        self.assertEqual(rows[0]["platform"], "whatsapp")
        self.assertEqual(rows[0]["status"], "active")

    def test_sync_rows_to_sheet_posts_json(self) -> None:
        response = MagicMock()
        response.read.return_value = b'{"ok":true,"inserted":1}'
        response.headers.get_content_charset.return_value = "utf-8"
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        with patch("crawler_wa.urllib.request.urlopen", return_value=response) as mocked_urlopen:
            inserted = sync_rows_to_sheet(
                "https://example.com/webapp",
                [
                    {
                        "timestamp": "2026-03-07T00:00:00+00:00",
                        "platform": "telegram",
                        "group_name": "Kelompok Mahasiswa TI",
                        "url": "https://t.me/kelompok_mahasiswa_ti",
                        "status": "active",
                    }
                ],
                timeout=10,
            )
        self.assertEqual(inserted, 1)
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.com/webapp")

    def test_search_queries_concurrently_collects_all_queries(self) -> None:
        def fake_search_query(
            platform,
            query,
            timeout,
            delay_seconds,
            max_search_pages,
            max_result_pages,
            max_follow_hops,
            max_follow_pages,
            fetch_budget,
            providers,
        ):
            return {provider: [f"https://example.com/{query}/{provider}"] for provider in providers}

        with patch("crawler_wa.search_query", side_effect=fake_search_query):
            results = search_queries_concurrently(
                platform="whatsapp",
                queries=["q1", "q2"],
                timeout=5,
                delay_seconds=0,
                max_search_pages=1,
                max_result_pages=1,
                max_follow_hops=1,
                max_follow_pages=2,
                fetch_budget=None,
                providers=["duckduckgo", "brave"],
                max_query_workers=2,
            )

        self.assertEqual(set(results.keys()), {"q1", "q2"})
        self.assertEqual(
            results["q1"]["duckduckgo"],
            ["https://example.com/q1/duckduckgo"],
        )

    def test_validation_cache_roundtrip(self) -> None:
        with TemporaryDirectory() as tmpdir:
            cache = ValidationCache(Path(tmpdir) / "cache.sqlite3")
            try:
                cache.put(
                    GroupCheckResult(
                        platform="telegram",
                        url="https://t.me/mahasiswa_mahasiswi",
                        status="active",
                        group_name="Grup Mahasiswa Indonesia Raya",
                        member_count=17536,
                    )
                )
                cached = cache.get("telegram", "https://t.me/mahasiswa_mahasiswi", ttl_hours=72)
            finally:
                cache.close()
        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(cached.status, "active")
        self.assertEqual(cached.member_count, 17536)

    def test_search_query_with_provider_follows_one_hop(self) -> None:
        with (
            patch("crawler_wa.fetch_search_body", return_value="<html></html>"),
            patch("crawler_wa.extract_provider_targets", return_value=["https://example.com/root"]),
            patch(
                "crawler_wa.fetch_text",
                side_effect=[
                    '<a href="/inner">lanjut</a>',
                    '<a href="https://t.me/mahasiswa_mahasiswi">grup</a>',
                ],
            ),
        ):
            results = search_query_with_provider(
                platform="telegram",
                provider="duckduckgo",
                query="komunitas mahasiswa",
                timeout=5,
                delay_seconds=0,
                max_search_pages=1,
                max_result_pages=1,
                max_follow_hops=1,
                max_follow_pages=2,
            )
        self.assertIn("https://t.me/mahasiswa_mahasiswi", results)

    def test_retryable_network_error_detects_ssl_eof(self) -> None:
        exc = URLError(ssl.SSLError("EOF occurred in violation of protocol (_ssl.c:1032)"))
        self.assertTrue(is_retryable_network_error(exc))

    def test_rate_limited_error_detects_http_429(self) -> None:
        exc = HTTPError(
            url="https://search.brave.com/search/__data.json",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=None,
        )
        self.assertTrue(is_rate_limited_error(exc))

    def test_google_is_disabled_after_repeated_transport_failures(self) -> None:
        exc = URLError(ssl.SSLError("EOF occurred in violation of protocol (_ssl.c:1032)"))
        self.assertFalse(mark_provider_failure("google", exc))
        self.assertFalse(mark_provider_failure("google", exc))
        self.assertTrue(mark_provider_failure("google", exc))
        self.assertTrue(is_provider_disabled("google"))

    def test_brave_is_disabled_after_repeated_rate_limit_failures(self) -> None:
        exc = HTTPError(
            url="https://search.brave.com/search/__data.json",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=None,
        )
        self.assertFalse(mark_provider_failure("brave", exc))
        self.assertTrue(mark_provider_failure("brave", exc))
        self.assertTrue(is_provider_disabled("brave"))

    def test_effective_search_delay_uses_brave_minimum(self) -> None:
        self.assertEqual(get_effective_search_delay("brave", 1.0), 3.0)
        self.assertEqual(get_effective_search_delay("duckduckgo", 1.0), 1.0)


if __name__ == "__main__":
    unittest.main()
