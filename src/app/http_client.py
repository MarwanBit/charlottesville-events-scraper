from abc import ABC, abstractmethod

import asyncio
import json
import logging
import queue
import random
import threading
import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Optional
from urllib.parse import urlparse

import nodriver as uc
import requests

logger = logging.getLogger(__name__)

def random_delay(min_sec=0.5, max_sec=1.5):
    return random.uniform(min_sec, max_sec)

class BaseClient(ABC):
    @abstractmethod
    def get(self, url: str) -> requests.Response:
        pass

    def close(self) -> None:
        """Release resources (sessions, browser). No-op if already closed. Safe to call multiple times."""
        pass

class HTTPClient(BaseClient):
    '''
    A rate-limited HTTP client with retry logic.

    HTTPClient handles sending GET requests in a way that respects
    rate limits while applying retry logic for reliable retrieval.

    Parameters
    ----------
    rate_per_sec : int, optional
        The number of requests allowed per second (default is 1).
    max_retries : int, optional
        Maximum number of retries upon 4XX/5XX codes (default is 3).

    Attributes
    ----------
    min_interval : float
        Minimum time in seconds between requests.
    last_request_time : float
        Timestamp of the last request.
    session : requests.Session
        Persistent session for connection pooling.

    Examples
    --------
    Basic usage:

    >>> client = HTTPClient()
    >>> response = client.get("https://example.com")
    >>> response.status_code
    200

    See Also
    --------
    requests.Session : The underlying session object used.

    Notes
    -----
    The client uses exponential backoff for retries, starting at 1 second
    and doubling with each attempt (1s, 2s, 4s, etc.).
    '''
    def __init__(self, rate_per_sec=1, max_retries=3):
        '''
        Construct a new HTTPClient object

        Parameters
        ----------
        rate_per_sec: int
            The number of requests allowed per second
        max_retries: int  
            maximum number of retries upon 4XX/5XX codes

        Attributes
        ----------
        min_interval: float
            Minimum time (seconds) between requests
        last_request_time: float
            Timestamp of the last request
        session: requests.Session
            Persistent session for connection pooling, cookie storage, etc.
        '''
        self.rate_per_sec = rate_per_sec
        self.min_interval = 1.0 / rate_per_sec
        self.max_retries = max_retries
        self.last_request_time = 0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def _wait_if_needed(self) -> None:
        '''
        helper/ utility function for waiting until a request can be served in order
        to respect rate limiting.
        '''
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def get(self, url: str) -> requests.Response:
        '''
        sends a get request to the specified url, and returns the requests.Response object

        Parameters
        ----------
        url: string
            the url given as a string of the endpoint the GET request is being sent to.
        
        Returns
        -------
        requests.Response
            The response object from the GET request containg the HTML object.

        Raises
        ------
        requests.RequestException
            When all attempts to reach the endpoint fail.

        Examples
        --------
        >>> client = HTTPClient()
        >>> client.get('www.wikipedia.org')
        Response<[200]>
        '''
        for attempt in range(self.max_retries):
            try:
                self._wait_if_needed()

                response = self.session.get(url, timeout=10)
                response.raise_for_status()

                self.last_request_time = time.time()
                return response

            except requests.RequestException as e:
                if attempt == self.max_retries - 1:
                    raise e

                backoff = 2 ** attempt
                time.sleep(backoff)

    def close(self) -> None:
        """Close the requests session and release connections."""
        self.session.close()


class NoDriverClient(BaseClient):
    """
    Browser client using nodriver (Chrome). Use create_sync() for synchronous usage
    so you can call client.get(url) from normal code. The browser runs in a background
    thread; get() blocks until the page is fetched and DOMContentLoaded has fired.
    """

    def __init__(self):
        self._loop = None
        self.browser = None
        self.session = self  # So generate_soup(client) can do client.session.get(url)
        self.headers = {}  # Session-like interface for base.generate_soup (User-Agent check)

    # Chrome args to reduce automation detection and improve startup (site may 403/504 otherwise)
    _BROWSER_ARGS = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--disable-infobars",
        "--window-size=1920,1080",
    ]

    @classmethod
    async def create(cls):
        instance = cls()
        instance.browser = await uc.start(
            sandbox=False,
            headless=False,
            browser_args=cls._BROWSER_ARGS,
        )
        instance._loop = asyncio.get_running_loop()
        return instance

    async def _close_async(self) -> None:
        """Run in the browser thread: stop browser and clear references."""
        if self.browser is None:
            return
        try:
            self.browser.stop()
        except Exception as e:
            logger.debug("NoDriver: browser.stop() raised %s", e)
        await asyncio.sleep(0.25)
        self.browser = None
        self._loop = None

    def close(self) -> None:
        """Stop the browser and release resources. No-op if already closed. Safe to call multiple times."""
        if self._loop is None:
            return
        loop = self._loop
        self._loop = None
        try:
            future = asyncio.run_coroutine_threadsafe(self._close_async(), loop)
            future.result(timeout=15)
        except Exception as e:
            logger.debug("NoDriver: close() %s", e)
        self.browser = None

    @classmethod
    def create_sync(cls) -> "NoDriverClient":
        """Create a NoDriverClient that can be used with synchronous client.get(url)."""
        result_q = queue.Queue()
        error_holder = []

        def run_browser_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def create_and_serve():
                    client = await cls.create()
                    result_q.put(client)
                    # Keep loop alive so run_coroutine_threadsafe from main thread works
                    while True:
                        await asyncio.sleep(3600)

                loop.run_until_complete(create_and_serve())
            except Exception as e:
                error_holder.append(e)
                # Unregister any Browser that never got a connection so atexit
                # doesn't call .stop() and hit AttributeError on connection.disconnect
                try:
                    from nodriver.core import util as nodriver_util
                    reg = nodriver_util.get_registered_instances()
                    for b in list(reg):
                        if getattr(b, "connection", None) is None:
                            reg.discard(b)
                except Exception:
                    pass

        thread = threading.Thread(target=run_browser_loop, daemon=True)
        thread.start()
        try:
            return result_q.get(timeout=60)
        except queue.Empty:
            if error_holder:
                raise RuntimeError(
                    f"NoDriverClient: browser failed to start: {error_holder[0]}"
                ) from error_holder[0]
            raise RuntimeError(
                "NoDriverClient: browser failed to start within 60s"
            ) from None

    async def _fetch_page_impl(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        wait_for_timeout: int = 30,
    ) -> str:
        logger.info("NoDriver: fetch start %s", url)
        await asyncio.sleep(random.uniform(2, 5))
        logger.info("NoDriver: calling browser.get(%s)", url)
        page = await self.browser.get(url)
        logger.info("NoDriver: waiting for load (timeout 30s)")
        try:
            await asyncio.wait_for(
                page.evaluate(
                    """
                    () => new Promise((resolve) => {
                        if (document.readyState === 'complete') {
                            resolve();
                        } else {
                            window.addEventListener('load', resolve, { once: true });
                        }
                    })
                    """,
                    await_promise=True,
                ),
                timeout=30,
            )
            logger.info("NoDriver: load done")
        except asyncio.TimeoutError:
            logger.warning("NoDriver: load wait timed out after 30s, continuing")
        await asyncio.sleep(random.uniform(1, 3))
        if wait_for_selector:
            logger.info("NoDriver: waiting for selector %r (timeout %ss)", wait_for_selector, wait_for_timeout)
            try:
                # Inline selector and timeout so we don't rely on evaluate() accepting extra args
                wait_script = """
                (() => {
                    const selector = %s;
                    const timeoutMs = %d;
                    return new Promise((resolve) => {
                        const deadline = Date.now() + timeoutMs;
                        const check = () => {
                            if (document.querySelector(selector)) { resolve(); return; }
                            if (Date.now() >= deadline) { resolve(); return; }
                            setTimeout(check, 500);
                        };
                        check();
                    });
                })()
                """ % (json.dumps(wait_for_selector), wait_for_timeout * 1000)
                await asyncio.wait_for(
                    page.evaluate(wait_script, await_promise=True),
                    timeout=wait_for_timeout + 5,
                )
                logger.info("NoDriver: selector appeared or timeout")
            except asyncio.TimeoutError:
                logger.warning("NoDriver: wait_for_selector timed out, continuing")
            await asyncio.sleep(random.uniform(0.5, 1.5))
        logger.info("NoDriver: getting page HTML")
        result = await page.evaluate("document.documentElement.outerHTML", return_by_value=True)
        if result is None:
            html = ""
        elif isinstance(result, str):
            html = result
        else:
            html = str(result)
        logger.info("NoDriver: done len=%s", len(html))
        return html

    async def _fetch_page(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        wait_for_timeout: int = 30,
    ) -> str:
        # Cap total time in browser thread so we don't hang indefinitely
        return await asyncio.wait_for(
            self._fetch_page_impl(url, wait_for_selector=wait_for_selector, wait_for_timeout=wait_for_timeout),
            timeout=90,
        )

    def _error_response(self, url: str, status_code: int = 502, content: bytes = b"") -> requests.Response:
        response = requests.Response()
        response.status_code = status_code
        response.url = url
        response._content = content
        return response

    def get(
        self,
        url: str,
        timeout: Optional[int] = None,
        wait_for_selector: Optional[str] = None,
        wait_for_timeout: int = 30,
    ) -> requests.Response:
        """Fetch the URL with the browser and return a requests.Response-like object (sync).
        If wait_for_selector is set, after initial load the client waits for that CSS selector
        to appear in the DOM (e.g. for JS-rendered content) before capturing HTML.
        """
        if self.browser is None or self._loop is None:
            return self._error_response(url, status_code=502, content=b"client closed")
        timeout_sec = timeout if timeout is not None else 120
        logger.info("NoDriver: get(%s) timeout=%s wait_selector=%s", url, timeout_sec, wait_for_selector)
        future = asyncio.run_coroutine_threadsafe(
            self._fetch_page(
                url,
                wait_for_selector=wait_for_selector,
                wait_for_timeout=wait_for_timeout,
            ),
            self._loop,
        )
        try:
            html = future.result(timeout=timeout_sec)
        except FuturesTimeoutError:
            logger.warning("NoDriver: main-thread timeout after %ss", timeout_sec)
            return self._error_response(url, status_code=504)
        except asyncio.TimeoutError:
            logger.warning("NoDriver: fetch timed out (90s) in browser thread")
            return self._error_response(url, status_code=504)
        except Exception as e:
            logger.exception("NoDriver: fetch failed (502): %s", e)
            return self._error_response(
                url,
                status_code=502,
                content=("NoDriver error: %s" % e).encode("utf-8"),
            )
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response._content = html.encode("utf-8") if isinstance(html, str) else html
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return response


class HybridClient(BaseClient):
    """
    Tries HTTPClient first; on 403 Forbidden, escalates to NoDriverClient (browser).
    NoDriverClient is created lazily only when a 403 is seen, so normal sites never start a browser.
    Caches hosts that returned 403 and uses the browser for them on subsequent requests.
    """

    # Browser loads need more time than HTTP; base.generate_soup uses timeout=10, so don't pass that through.
    _BROWSER_TIMEOUT = 120

    def __init__(self, rate_per_sec: int = 1, max_retries: int = 3):
        self._http = HTTPClient(rate_per_sec=rate_per_sec, max_retries=max_retries)
        self._nodriver: Optional["NoDriverClient"] = None
        self._use_browser_hosts: set[str] = set()
        self._browser_unavailable_hosts: set[str] = set()  # 403 but browser failed to start; return 503
        self.session = self  # So generate_soup(client) calls client.session.get(url) -> self.get(url)
        self.headers = {}

    def _browser_get_or_503(
        self,
        url: str,
        host: str,
        browser_timeout: int,
        wait_for_selector: Optional[str] = None,
        wait_for_timeout: int = 30,
    ) -> requests.Response:
        """Use NoDriverClient for url; on browser startup failure return 503 so pipeline can continue."""
        if host in self._browser_unavailable_hosts:
            r = requests.Response()
            r.status_code = 503
            r.url = url
            r._content = b"browser unavailable (failed to start in this environment)"
            return r
        try:
            if self._nodriver is None:
                self._nodriver = NoDriverClient.create_sync()
            return self._nodriver.get(
                url,
                timeout=browser_timeout,
                wait_for_selector=wait_for_selector,
                wait_for_timeout=wait_for_timeout,
            )
        except RuntimeError as e:
            if "browser failed to start" in str(e):
                logger.warning("HybridClient: browser unavailable for %s, returning 503", url)
                self._browser_unavailable_hosts.add(host)
                r = requests.Response()
                r.status_code = 503
                r.url = url
                r._content = b"browser unavailable (Chrome/nodriver could not start)"
                return r
            raise

    def get(
        self,
        url: str,
        timeout: Optional[int] = None,
        wait_for_selector: Optional[str] = None,
        wait_for_timeout: int = 30,
    ) -> requests.Response:
        host = urlparse(url).netloc
        browser_timeout = timeout if timeout is not None and timeout >= self._BROWSER_TIMEOUT else self._BROWSER_TIMEOUT
        if host in self._browser_unavailable_hosts:
            r = requests.Response()
            r.status_code = 503
            r.url = url
            r._content = b"browser unavailable (failed to start in this environment)"
            return r
        # Use browser when caller asked for wait_for_selector (JS-rendered content) or host already known to need browser
        if wait_for_selector is not None or host in self._use_browser_hosts:
            if wait_for_selector is not None and host not in self._use_browser_hosts:
                self._use_browser_hosts.add(host)
            return self._browser_get_or_503(
                url, host, browser_timeout,
                wait_for_selector=wait_for_selector,
                wait_for_timeout=wait_for_timeout,
            )
        try:
            response = self._http.get(url)
        except requests.HTTPError as e:
            # HTTPClient.get() raises on 4xx/5xx via raise_for_status(); only escalate on 403
            if e.response is not None and e.response.status_code == 403:
                logger.info("HybridClient: 403 for %s, escalating to NoDriverClient", url)
                self._use_browser_hosts.add(host)
                return self._browser_get_or_503(
                    url, host, browser_timeout,
                    wait_for_selector=wait_for_selector,
                    wait_for_timeout=wait_for_timeout,
                )
            raise
        if response.status_code == 403:
            logger.info("HybridClient: 403 for %s, escalating to NoDriverClient", url)
            self._use_browser_hosts.add(host)
            return self._browser_get_or_503(
                url, host, browser_timeout,
                wait_for_selector=wait_for_selector,
                wait_for_timeout=wait_for_timeout,
            )
        # Cloudflare challenge returns 200 with "Just a moment..." / "Enable JavaScript and cookies"
        if response.status_code == 200:
            text = (response.text or "").lower()
            if "just a moment" in text or "enable javascript and cookies to continue" in text:
                logger.info("HybridClient: Cloudflare challenge for %s, escalating to NoDriverClient", url)
                self._use_browser_hosts.add(host)
                return self._browser_get_or_503(
                    url, host, browser_timeout,
                    wait_for_selector=wait_for_selector,
                    wait_for_timeout=wait_for_timeout,
                )
        return response

    def close(self) -> None:
        self._http.close()
        if self._nodriver is not None:
            self._nodriver.close()
            self._nodriver = None
        self._use_browser_hosts.clear()
        self._browser_unavailable_hosts.clear()