from abc import ABC, abstractmethod

import asyncio
import json
import logging
import os
import queue
import random
import shutil
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
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
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
                status = response.status_code
                print(f"[HTTPClient] attempt {attempt + 1}/{self.max_retries} GET {url} -> {status}", flush=True)
                response.raise_for_status()
                self.last_request_time = time.time()
                return response

            except requests.RequestException as e:
                if attempt == self.max_retries - 1:
                    print(f"[HTTPClient] giving up on {url}: {e}", flush=True)
                    raise e

                backoff = 2 ** attempt
                print(f"[HTTPClient] error on {url}: {e} (retrying in {backoff}s)", flush=True)
                time.sleep(backoff)

    def close(self) -> None:
        """Close the requests session and release connections."""
        self.session.close()


class NoDriverClient(BaseClient):
    """
    Browser client using nodriver (Chrome). Use create_sync() for synchronous usage
    so you can call client.get(url) from normal code. The browser runs in a background
    thread; get() blocks until the page is fetched and DOMContentLoaded has fired.
    Rate-limited so requests are at least min_interval_sec apart.
    """

    def __init__(self, min_interval_sec: float = 2.0):
        self._loop = None
        self.browser = None
        self.session = self  # So generate_soup(client) can do client.session.get(url)
        self.headers = {}  # Session-like interface for base.generate_soup (User-Agent check)
        # Default: no rate limiting unless explicitly requested.
        env_min = os.environ.get("NODRIVER_MIN_INTERVAL_SEC")
        if env_min is not None:
            try:
                self._min_interval = float(env_min)
            except ValueError:
                self._min_interval = 0.0
        else:
            self._min_interval = 0.0
        self._last_request_time = 0.0
        self._rate_lock = threading.Lock()

    def _wait_if_needed(self) -> None:
        """Optionally wait between browser requests. No-op when _min_interval <= 0."""
        if self._min_interval <= 0:
            return
        now = time.time()
        # Do not delay the very first request in a session; only enforce spacing between completed requests.
        if self._last_request_time <= 0:
            self._last_request_time = now
            return
        elapsed = now - self._last_request_time
        interval = self._min_interval
        if elapsed < interval:
            time.sleep(interval - elapsed)

    # Chrome args to reduce automation detection and improve startup (site may 403/504 otherwise)
    _BROWSER_ARGS = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--disable-infobars",
        "--window-size=1280,720",
        "--disable-gpu",
        "--disable-dev-shm-usage",
    ]

    @classmethod
    async def create(cls, min_interval_sec: float = 2.0):
        # Use headless when HEADLESS=1 (e.g. Docker/EC2) so there is no display.
        headless = os.environ.get("HEADLESS", "").strip().lower() in ("1", "true", "yes")
        if not headless:
            # Ensure Chrome uses the same display as Xvfb/VNC (e.g. :99 in run-headed-vnc.sh).
            os.environ.setdefault("DISPLAY", ":99")

        # Ensure nodriver's local HTTP calls to the DevTools endpoint (127.0.0.1:port)
        # are NOT routed through HTTP(S)_PROXY, which would otherwise break inside Docker
        # when the app container is configured to use a forward proxy.
        no_proxy_current = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
        tokens = [t.strip() for t in no_proxy_current.split(",") if t.strip()]
        for host in ("127.0.0.1", "localhost", "::1"):
            if host not in tokens:
                tokens.append(host)
        no_proxy_new = ",".join(tokens)
        os.environ["NO_PROXY"] = no_proxy_new
        os.environ["no_proxy"] = no_proxy_new

        # If a forward proxy is configured specifically for the browser (e.g. tinyproxy
        # on the host), tell Chromium to use it for outbound HTTP(S) traffic.
        # IMPORTANT: we only look at BROWSER_PROXY here so that generic HTTP(S)_PROXY
        # used by requests/HTTPClient does not break nodriver/DevTools connectivity.
        proxy_url = os.environ.get("BROWSER_PROXY")

        # Build browser args per-instance so we can append proxy flags without mutating
        # the class-level defaults.
        browser_args = list(cls._BROWSER_ARGS)
        if proxy_url:
            browser_args.append(f"--proxy-server={proxy_url}")

        # Optional: shared user data dir so a human can solve challenges once (via
        # headed Chromium in VNC) and the automated browser reuses the same profile
        # (cookies, local storage, etc.). Defaults to a stable path under /app.
        # Use a dedicated automation profile and proactively clear any leftover
        # Chrome singleton lock files, otherwise Chromium may abort on startup.
        user_data_dir = os.environ.get(
            "BROWSER_USER_DATA_DIR", "/app/browser-profile-automation"
        )
        try:
            os.makedirs(user_data_dir, exist_ok=True)
            for name in os.listdir(user_data_dir):
                if name.startswith("Singleton"):
                    try:
                        os.remove(os.path.join(user_data_dir, name))
                    except OSError:
                        pass
        except Exception:
            # Profile directory issues should not crash the whole client; nodriver
            # will still start with its own defaults if this path is unusable.
            user_data_dir = None

        print(
            "[NoDriverClient.create] "
            f"headless={headless} "
            f"browser_path={os.environ.get('BROWSER_PATH') or os.environ.get('CHROME_PATH') or 'auto'} "
            f"proxy={proxy_url!r} "
            f"user_data_dir={user_data_dir!r}",
            flush=True,
        )

        instance = cls(min_interval_sec=min_interval_sec)
        # Explicitly tell nodriver which browser binary to use when running in Docker.
        # Prefer environment overrides, then common Chromium/Chrome paths.
        browser_path = (
            os.environ.get("BROWSER_PATH")
            or os.environ.get("CHROME_PATH")
            or shutil.which("chromium")
            or shutil.which("chromium-browser")
            or shutil.which("google-chrome")
            or None
        )
        # Use no_sandbox=True so nodriver's internal root/container checks are satisfied,
        # in addition to the explicit --no-sandbox flag in _BROWSER_ARGS.
        instance.browser = await uc.start(
            browser_executable_path=browser_path,
            no_sandbox=True,
            headless=headless,
            user_data_dir=user_data_dir,
            browser_args=browser_args,
        )
        print("[NoDriverClient.create] browser started successfully", flush=True)
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
    def create_sync(cls, min_interval_sec: float = 2.0) -> "NoDriverClient":
        """Create a NoDriverClient that can be used with synchronous client.get(url)."""
        result_q = queue.Queue()
        error_holder = []

        def run_browser_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def create_and_serve():
                    print(
                        "[NoDriverClient.create_sync] starting browser event loop thread",
                        flush=True,
                    )
                    client = await cls.create(min_interval_sec=min_interval_sec)
                    result_q.put(client)
                    print(
                        "[NoDriverClient.create_sync] client created and queued back to main thread",
                        flush=True,
                    )
                    # Keep loop alive so run_coroutine_threadsafe from main thread works
                    while True:
                        await asyncio.sleep(3600)

                loop.run_until_complete(create_and_serve())
            except Exception as e:
                error_holder.append(e)
                print(
                    f"[NoDriverClient.create_sync] browser loop error: {e}",
                    flush=True,
                )
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
                print(
                    f"[NoDriverClient.create_sync] timed out waiting for client; error_holder[0]={error_holder[0]}",
                    flush=True,
                )
                raise RuntimeError(
                    f"NoDriverClient: browser failed to start: {error_holder[0]}"
                ) from error_holder[0]
            print(
                "[NoDriverClient.create_sync] timed out waiting for client; no specific error captured",
                flush=True,
            )
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
        # Local/dev runs often want maximum speed; skip artificial pre-delays.
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
        Only one request runs at a time; each request waits (min_interval + jitter) after the previous finished.
        """
        if self.browser is None or self._loop is None:
            return self._error_response(url, status_code=502, content=b"client closed")
        timeout_sec = timeout if timeout is not None else 120
        with self._rate_lock:
            self._wait_if_needed()
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
                self._last_request_time = time.time()
                return self._error_response(url, status_code=504)
            except asyncio.TimeoutError:
                logger.warning("NoDriver: fetch timed out (90s) in browser thread")
                self._last_request_time = time.time()
                return self._error_response(url, status_code=504)
            except Exception as e:
                logger.exception("NoDriver: fetch failed (502): %s", e)
                self._last_request_time = time.time()
                return self._error_response(
                    url,
                    status_code=502,
                    content=("NoDriver error: %s" % e).encode("utf-8"),
                )
            self._last_request_time = time.time()
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
        """
        Use NoDriverClient for url.
        During debugging, do NOT mask browser failures as synthetic 503s; let errors surface.
        """
        print(
            f"[HybridClient] using browser for host={host} url={url}",
            flush=True,
        )
        try:
            if self._nodriver is None:
                print(
                    "[HybridClient] creating NoDriverClient via create_sync()",
                    flush=True,
                )
                self._nodriver = NoDriverClient.create_sync()
                print(
                    "[HybridClient] NoDriverClient created successfully",
                    flush=True,
                )
            print(
                "[HybridClient] calling NoDriverClient.get()",
                flush=True,
            )
            response = self._nodriver.get(
                url,
                timeout=browser_timeout,
                wait_for_selector=wait_for_selector,
                wait_for_timeout=wait_for_timeout,
            )
            print(
                f"[HybridClient] NoDriverClient.get() returned status={response.status_code}",
                flush=True,
            )
            return response
        except RuntimeError as e:
            # Surface full browser/nodriver error; do not convert to 503.
            logger.exception("HybridClient: browser error for %s: %s", url, e)
            print(
                f"[HybridClient] RuntimeError from browser for {url}: {e}",
                flush=True,
            )
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
        # Use browser when caller asked for wait_for_selector (JS-rendered content) or host already known to need browser
        if wait_for_selector is not None or host in self._use_browser_hosts:
            if wait_for_selector is not None and host not in self._use_browser_hosts:
                self._use_browser_hosts.add(host)
            resp = self._browser_get_or_503(
                url, host, browser_timeout,
                wait_for_selector=wait_for_selector,
                wait_for_timeout=wait_for_timeout,
            )
            if resp.status_code in (502, 503, 504):
                self._use_browser_hosts.discard(host)
                logger.info(
                    "HybridClient: browser got %s for %s, will try HTTP first next time for this host",
                    resp.status_code, host,
                )
            print(f"[HybridClient] BROWSER GET {url} -> {resp.status_code}", flush=True)
            return resp
        try:
            response = self._http.get(url)
        except requests.HTTPError as e:
            # HTTPClient.get() raises on 4xx/5xx via raise_for_status(); only escalate on 403
            if e.response is not None and e.response.status_code == 403:
                logger.info("HybridClient: 403 for %s, escalating to NoDriverClient", url)
                self._use_browser_hosts.add(host)
                resp = self._browser_get_or_503(
                    url, host, browser_timeout,
                    wait_for_selector=wait_for_selector,
                    wait_for_timeout=wait_for_timeout,
                )
                if resp.status_code in (502, 503, 504):
                    self._use_browser_hosts.discard(host)
                    logger.info(
                        "HybridClient: browser got %s for %s, will try HTTP first next time for this host",
                        resp.status_code, host,
                    )
                print(f"[HybridClient] BROWSER GET {url} after HTTP 403 -> {resp.status_code}", flush=True)
                return resp
            raise
        if response.status_code == 403:
            logger.info("HybridClient: 403 for %s, escalating to NoDriverClient", url)
            self._use_browser_hosts.add(host)
            resp = self._browser_get_or_503(
                url, host, browser_timeout,
                wait_for_selector=wait_for_selector,
                wait_for_timeout=wait_for_timeout,
            )
            if resp.status_code in (502, 503, 504):
                self._use_browser_hosts.discard(host)
                logger.info(
                    "HybridClient: browser got %s for %s, will try HTTP first next time for this host",
                    resp.status_code, host,
                )
            print(f"[HybridClient] BROWSER GET {url} after 403 -> {resp.status_code}", flush=True)
            return resp
        # Cloudflare challenge returns 200 with "Just a moment..." / "Enable JavaScript and cookies"
        if response.status_code == 200:
            text = (response.text or "").lower()
            if "just a moment" in text or "enable javascript and cookies to continue" in text:
                logger.info("HybridClient: Cloudflare challenge for %s, escalating to NoDriverClient", url)
                self._use_browser_hosts.add(host)
                resp = self._browser_get_or_503(
                    url, host, browser_timeout,
                    wait_for_selector=wait_for_selector,
                    wait_for_timeout=wait_for_timeout,
                )
                if resp.status_code in (502, 503, 504):
                    self._use_browser_hosts.discard(host)
                    logger.info(
                        "HybridClient: browser got %s for %s, will try HTTP first next time for this host",
                        resp.status_code, host,
                    )
                print(f"[HybridClient] BROWSER GET {url} after JS challenge -> {resp.status_code}", flush=True)
                return resp
        print(f"[HybridClient] HTTP GET {url} -> {response.status_code}", flush=True)
        return response

    def close(self) -> None:
        self._http.close()
        if self._nodriver is not None:
            self._nodriver.close()
            self._nodriver = None
        self._use_browser_hosts.clear()
        self._browser_unavailable_hosts.clear()