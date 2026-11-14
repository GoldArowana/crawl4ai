"""Independent public-call controls; run with the candidate's real dependency env."""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

source = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(source))
import crawl4ai.async_webcrawler as module
from crawl4ai.async_configs import DomainMapperConfig
from crawl4ai.async_webcrawler import AsyncWebCrawler

assert Path(module.__file__).resolve() == source / "crawl4ai/async_webcrawler.py"


async def main():
    observed = []
    constructed = []
    output = [{"url": "https://example.com/retained"}]
    logger = object()
    folder = "/tmp/independent-no-io"

    class Mapper:
        def __init__(self, **kwargs):
            constructed.append(kwargs)

        async def scan(self, domain, config):
            observed.append((domain, config))
            return output

    crawler = object.__new__(AsyncWebCrawler)
    crawler._domain_mapper = None
    crawler.logger = logger
    crawler.crawl4ai_folder = folder
    supplied = DomainMapperConfig(
        source="sitemap", max_urls=3, concurrency=1, include_subdomains=False,
        force=True, verbose=False, probe_paths=["/docs"], source_timeout=0.5,
    )
    original = copy.deepcopy(supplied.to_dict())
    checks = []
    with patch.object(module, "DomainMapper", Mapper):
        result = await crawler.amap_domain("example.com", config=supplied)
        assert result is output
        assert observed[-1] == ("example.com", supplied)
        assert observed[-1][1] is supplied
        assert supplied.to_dict() == original
        assert constructed == [{"logger": logger, "base_directory": folder}]
        mapper = crawler._domain_mapper
        checks.append("explicit config retained on lazy initialization")

        await crawler.amap_domain("other.example", config=supplied, max_urls=0, force=False)
        merged = observed[-1][1]
        assert merged is not supplied
        assert merged.to_dict() == {**original, "max_urls": 0, "force": False}
        assert supplied.to_dict() == original
        assert crawler._domain_mapper is mapper and len(constructed) == 1
        checks.append("override clone preserves originals and mapper lifetime")

        await crawler.amap_domain("example.com")
        first_default = observed[-1][1]
        assert first_default.to_dict() == DomainMapperConfig().to_dict()
        first_default.max_urls = 999
        await crawler.amap_domain("example.com", config=None)
        assert observed[-1][1] is not first_default
        assert observed[-1][1].to_dict() == DomainMapperConfig().to_dict()
        checks.append("omitted and None create independent defaults")

        await crawler.amap_domain("example.com", source="feed", include_subdomains=False)
        assert observed[-1][1].to_dict() == DomainMapperConfig(source="feed", include_subdomains=False).to_dict()
        await crawler.amap_domain("example.com", config=None, max_urls=0, verbose=False)
        assert observed[-1][1].to_dict() == DomainMapperConfig(max_urls=0, verbose=False).to_dict()
        checks.append("kwargs only including false and zero preserved")

        sentinel = RuntimeError("scan failure witness")
        async def failure(domain, config):
            assert config is supplied
            raise sentinel
        mapper.scan = failure
        try:
            await crawler.amap_domain("example.com", config=supplied)
        except RuntimeError as error:
            assert error is sentinel
        else:
            raise AssertionError("scan error suppressed")
        assert crawler._domain_mapper is mapper and len(constructed) == 1
        checks.append("scan error identity propagated without reinitialization")

        sentinel_cancel = asyncio.CancelledError()
        async def cancellation(domain, config):
            raise sentinel_cancel
        mapper.scan = cancellation
        try:
            await crawler.amap_domain("example.com", config=supplied)
        except asyncio.CancelledError as error:
            assert error is sentinel_cancel
        else:
            raise AssertionError("scan cancellation suppressed")
        checks.append("scan cancellation propagated")

    print(json.dumps({
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip(),
        "source_file": str(Path(module.__file__).resolve()),
        "source_sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),
        "checks": checks,
        "passed_control_groups": len(checks),
        "boundary": "Actual imported public method/config; mapper transport and constructor patched; no network/browser execution.",
    }, indent=2))


asyncio.run(main())
