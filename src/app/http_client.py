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
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

def random_delay(min_sec=0.5, max_sec=1.5):
    return random.uniform(min_sec, max_sec)


def _retry_after_seconds(response: requests.Response, cap_sec: float = 300.0) -> Optional[float]:
    """Parse Retry-After header (seconds or HTTP-date). Returns None if missing/invalid."""
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return min(float(raw), cap_sec)
    try:
        dt = parsedate_to_datetime(raw)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        sec = (dt - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, min(sec, cap_sec))
    except (TypeError, ValueError, OverflowError):
        return None

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

        Environment
        -------------
        HTTP_RATE_PER_SEC — requests per second (e.g. 0.2 ≈ one GET every 5s) when sites return 429.
        HTTP_MAX_RETRIES — total attempts per URL (each 429 retry counts as an attempt).
        '''
        env_rate = os.environ.get("HTTP_RATE_PER_SEC")
        if env_rate:
            try:
                r = float(env_rate)
                if r > 0:
                    rate_per_sec = r
            except ValueError:
                pass
        env_retries = os.environ.get("HTTP_MAX_RETRIES")
        if env_retries:
            try:
                max_retries = int(env_retries)
            except ValueError:
                pass
        self.rate_per_sec = float(rate_per_sec)
        self.min_interval = 1.0 / self.rate_per_sec
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

                if status == 429 and attempt < self.max_retries - 1:
                    wait = _retry_after_seconds(response)
                    if wait is None:
                        wait = min(120.0, 2.0 ** (attempt + 1))
                    wait = max(1.0, wait) + random.uniform(0, 0.75)
                    logger.warning("HTTP 429 for %s, sleeping %.1fs then retrying", url, wait)
                    print(f"[HTTPClient] 429 Too Many Requests, sleeping {wait:.1f}s", flush=True)
                    time.sleep(wait)
                    continue

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
        import nodriver as uc
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
    def create_sync(
        cls,
        min_interval_sec: float = 2.0,
        start_timeout_sec: float = 180.0,
    ) -> "NoDriverClient":
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
            return result_q.get(timeout=start_timeout_sec)
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
                f"[NoDriverClient.create_sync] timed out waiting for client after {start_timeout_sec}s; no specific error captured",
                flush=True,
            )
            raise RuntimeError(
                f"NoDriverClient: browser failed to start within {start_timeout_sec}s"
            ) from None

    @staticmethod
    def _merge_vlist_accum_js(vlink_sel: str) -> str:
        """Merge current DOM detail hrefs into #__scraper_vlist_accum__ JSON (union with previous)."""
        return """
            (() => {
                const linkSel = %s;
                function isCitySparkDetailHref(h) {
                    if (!h) return false;
                    const t = h.trim();
                    if (/details\\/[^/?#\\s]+\\/\\d+\\/\\d{4}-\\d{2}-\\d{2}T[^/?#\\s]*/i.test(t)) return true;
                    if (/(?:#|\\/)details\\/[^/?#\\s]+\\/\\d+\\//i.test(t)) return true;
                    if (/[/#]details\\/[^/?#\\s]+\\/\\d+(?:\\/|[?#]|$)/i.test(t)) return true;
                    return false;
                }
                function queryDeep(selector) {
                    const roots = [];
                    function visit(root) {
                        if (!root || !root.querySelectorAll) return;
                        roots.push(root);
                        let all;
                        try {
                            all = root.querySelectorAll('*');
                        } catch (e) {
                            return;
                        }
                        for (let i = 0; i < all.length; i++) {
                            const el = all[i];
                            if (el.shadowRoot) visit(el.shadowRoot);
                        }
                    }
                    visit(document);
                    const seenEl = new Set();
                    const out = [];
                    for (let i = 0; i < roots.length; i++) {
                        try {
                            roots[i].querySelectorAll(selector).forEach((el) => {
                                if (seenEl.has(el)) return;
                                seenEl.add(el);
                                out.push(el);
                            });
                        } catch (e) {}
                    }
                    return out;
                }
                const s = new Set();
                try {
                    const prev = document.getElementById('__scraper_vlist_accum__');
                    if (prev && prev.textContent) {
                        const arr = JSON.parse(prev.textContent);
                        if (Array.isArray(arr)) {
                            arr.forEach((h) => {
                                if (h) s.add(String(h).trim());
                            });
                        }
                    }
                } catch (e) {}
                try {
                    queryDeep(linkSel).forEach((a) => {
                        const h = (a.getAttribute('href') || '').trim();
                        if (h && isCitySparkDetailHref(h)) s.add(h);
                    });
                } catch (e) {}
                const old = document.getElementById('__scraper_vlist_accum__');
                if (old) old.remove();
                const holder = document.createElement('script');
                holder.id = '__scraper_vlist_accum__';
                holder.type = 'application/json';
                holder.setAttribute('data-events-scraper', 'accumulated-links');
                holder.textContent = JSON.stringify(Array.from(s));
                document.body.appendChild(holder);
            })()
            """ % (json.dumps(vlink_sel),)

    @staticmethod
    def _fetch_coroutine_timeout_sec(
        max_load_more_clicks: int,
        load_more_pause_sec: float,
        scroll_load_max_rounds: int,
        scroll_load_pause_sec: float,
        wait_for_timeout: int,
        scroll_load_settle_max_ms: int = 0,
        interleave_scroll_and_load_more_rounds: int = 0,
        virtualized_list_link_selector: Optional[str] = None,
        virtualized_list_collect_max_steps: int = 0,
        listing_simple_two_phase: bool = False,
        listing_scroll_load_passes: int = 0,
    ) -> float:
        """Inner asyncio budget: base navigation + wait_for_selector + load-more + scroll."""
        base = 95.0
        load_more = float(max(0, max_load_more_clicks)) * max(0.2, load_more_pause_sec + 2.0)
        if scroll_load_max_rounds > 0:
            settle_sec = max(0, int(scroll_load_settle_max_ms)) / 1000.0 + 5.0
            scroll = float(scroll_load_max_rounds) * max(settle_sec, scroll_load_pause_sec + 2.0)
        else:
            scroll = 0.0
        interleave = 0.0
        if interleave_scroll_and_load_more_rounds > 0:
            settle_sec = max(0, int(scroll_load_settle_max_ms)) / 1000.0 + 5.0
            interleave = float(interleave_scroll_and_load_more_rounds) * (
                settle_sec + max(0.2, load_more_pause_sec) + 10.0
            )
        vlist = 0.0
        if virtualized_list_link_selector and virtualized_list_link_selector.strip():
            raw = int(virtualized_list_collect_max_steps)
            if raw <= 0:
                # Snapshot-only: one DOM pass after load-more/interleave (no stepped scroll loop).
                vlist = 35.0
            else:
                vsteps = max(80, min(3000, raw))
                vlist = 120.0 + float(vsteps) * 0.35
        listing_phase = 0.0
        if (
            listing_simple_two_phase
            and virtualized_list_link_selector
            and virtualized_list_link_selector.strip()
            and int(listing_scroll_load_passes) > 0
        ):
            settle_sec = max(0, int(scroll_load_settle_max_ms)) / 1000.0 + 5.0
            passes = max(1, int(listing_scroll_load_passes))
            listing_phase = float(passes) * (settle_sec + max(0.2, load_more_pause_sec) + 8.0)
        wait_part = float(max(30, wait_for_timeout)) + 15.0
        # Long interleave + virtualized listings (e.g. CitySpark) need well above 12 minutes; outer
        # HybridClient/NoDriver.get(timeout=...) remains the hard cap for the caller thread.
        return min(7200.0, base + wait_part + load_more + scroll + interleave + vlist + listing_phase)

    async def _fetch_page_impl(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        wait_for_timeout: int = 30,
        dismiss_selectors: Optional[List[str]] = None,
        load_more_selector: Optional[str] = None,
        load_more_text_contains: Optional[str] = None,
        max_load_more_clicks: int = 0,
        load_more_pause_sec: float = 1.0,
        scroll_load_max_rounds: int = 0,
        scroll_load_pause_sec: float = 0.85,
        scroll_load_stable_rounds: int = 2,
        scroll_container_selector: Optional[str] = None,
        scroll_load_settle_max_ms: int = 20000,
        scroll_load_settle_poll_ms: int = 320,
        scroll_load_settle_quiet_polls: int = 6,
        scroll_load_growth_selector: Optional[str] = None,
        interleave_scroll_and_load_more_rounds: int = 0,
        interleave_stop_after_consecutive_misses: int = 12,
        virtualized_list_link_selector: Optional[str] = None,
        virtualized_list_collect_max_steps: int = 400,
        wait_for_all_selectors: Optional[List[str]] = None,
        wait_for_nonempty_text_selector: Optional[str] = None,
        wait_for_nonempty_text_min_len: int = 12,
        listing_simple_two_phase: bool = False,
        listing_scroll_load_passes: int = 150,
        virtualized_list_return_full_html: bool = False,
        snapshot_html_eval: Optional[str] = None,
    ) -> str:
        logger.info("NoDriver: fetch start %s", url)
        print(f"[NoDriver] navigating {url}", flush=True)
        page = await self.browser.get(url)
        # Do not wait for window "load" (images/ads); SPAs mount after DOMContentLoaded.
        # wait_for_selector / SPA waits handle CitySpark mounting tiles.
        logger.info("NoDriver: waiting for DOM ready (not full load), timeout 12s")
        print("[NoDriver] waiting for DOMContentLoaded / interactive …", flush=True)
        try:
            await asyncio.wait_for(
                page.evaluate(
                    """
                    () => new Promise((resolve) => {
                        if (document.readyState !== 'loading') {
                            resolve();
                            return;
                        }
                        document.addEventListener('DOMContentLoaded', resolve, { once: true });
                        setTimeout(resolve, 12000);
                    })
                    """,
                    await_promise=True,
                ),
                timeout=14.0,
            )
            logger.info("NoDriver: DOM ready")
            print("[NoDriver] DOM ready, running selector / SPA waits …", flush=True)
        except asyncio.TimeoutError:
            logger.warning("NoDriver: DOM ready wait timed out, continuing")
        w_all = [str(s).strip() for s in (wait_for_all_selectors or []) if s and str(s).strip()]
        text_wait_sel = (wait_for_nonempty_text_selector or "").strip()
        text_min = max(1, int(wait_for_nonempty_text_min_len))
        if w_all or text_wait_sel:
            logger.info(
                "NoDriver: SPA wait selectors=%s text_sel=%r min_len=%s (timeout %ss)",
                w_all,
                text_wait_sel or None,
                text_min,
                wait_for_timeout,
            )
            try:
                combined_wait = """
                (() => {
                    const selectors = %s;
                    const textSel = %s;
                    const minLen = %d;
                    const timeoutMs = %d;
                    return new Promise((resolve) => {
                        const deadline = Date.now() + timeoutMs;
                        const check = () => {
                            const structOk = selectors.length === 0
                                || selectors.every((s) => document.querySelector(s));
                            let textOk = true;
                            if (textSel) {
                                const el = document.querySelector(textSel);
                                const t = el ? (el.innerText || '').replace(/\\s+/g, ' ').trim() : '';
                                textOk = t.length >= minLen;
                            }
                            if (structOk && textOk) { resolve(); return; }
                            if (Date.now() >= deadline) { resolve(); return; }
                            setTimeout(check, 120);
                        };
                        check();
                    });
                })()
                """ % (
                    json.dumps(w_all),
                    json.dumps(text_wait_sel),
                    text_min,
                    wait_for_timeout * 1000,
                )
                await asyncio.wait_for(
                    page.evaluate(combined_wait, await_promise=True),
                    timeout=max(wait_for_timeout + 10, 60),
                )
                logger.info("NoDriver: SPA wait finished or timed out")
            except asyncio.TimeoutError:
                logger.warning("NoDriver: SPA combined wait evaluate timed out, continuing")
        elif wait_for_selector:
            use_pierce = bool((snapshot_html_eval or "").strip())
            logger.info(
                "NoDriver: waiting for selector %r (timeout %ss, shadow_pierce=%s)",
                wait_for_selector,
                wait_for_timeout,
                use_pierce,
            )
            print(
                f"[NoDriver] waiting for selector (timeout {wait_for_timeout}s, "
                f"shadow_pierce={use_pierce}) …",
                flush=True,
            )
            try:
                if use_pierce:
                    # Embedded widgets (e.g. Afton) often mount tiles inside shadow roots / iframes;
                    # document.querySelector would never see them.
                    wait_script = """
                    (() => {
                        const selector = %s;
                        const timeoutMs = %d;
                        const parts = selector.split(',').map((s) => s.trim()).filter(Boolean);
                        function matchInRoot(root) {
                            if (!root || !root.querySelector) return false;
                            for (let i = 0; i < parts.length; i++) {
                                try {
                                    if (root.querySelector(parts[i])) return true;
                                } catch (e) {}
                            }
                            const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
                            for (let j = 0; j < nodes.length; j++) {
                                if (nodes[j].shadowRoot && matchInRoot(nodes[j].shadowRoot)) return true;
                            }
                            return false;
                        }
                        function matchAnywhere(doc) {
                            if (matchInRoot(doc)) return true;
                            const ifr = doc.querySelectorAll('iframe');
                            for (let k = 0; k < ifr.length; k++) {
                                try {
                                    const d = ifr[k].contentDocument;
                                    if (d && matchAnywhere(d)) return true;
                                } catch (e) {}
                            }
                            return false;
                        }
                        return new Promise((resolve) => {
                            const deadline = Date.now() + timeoutMs;
                            const check = () => {
                                if (matchAnywhere(document)) { resolve(); return; }
                                if (Date.now() >= deadline) { resolve(); return; }
                                setTimeout(check, 100);
                            };
                            check();
                        });
                    })()
                    """ % (json.dumps(wait_for_selector), wait_for_timeout * 1000)
                else:
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
                                setTimeout(check, 100);
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
                print("[NoDriver] selector wait done", flush=True)
            except asyncio.TimeoutError:
                logger.warning("NoDriver: wait_for_selector timed out, continuing")
                print("[NoDriver] selector wait timed out (continuing)", flush=True)
        if dismiss_selectors:
            logger.info("NoDriver: dismissing overlays (%d selectors)", len(dismiss_selectors))
            for sel in dismiss_selectors:
                try:
                    click_script = """
                    (() => {
                        const el = document.querySelector(%s);
                        if (el) { el.click(); return true; }
                        return false;
                    })()
                    """ % json.dumps(sel)
                    clicked = await page.evaluate(click_script)
                    if clicked:
                        logger.info("NoDriver: clicked dismiss selector %r", sel)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.debug("NoDriver: dismiss selector %r failed: %s", sel, e)
            await asyncio.sleep(1)
        text_sub = (load_more_text_contains or "").strip()
        sel_sub = (load_more_selector or "").strip()
        listing_simple = bool(listing_simple_two_phase) and bool(
            (virtualized_list_link_selector or "").strip()
        ) and bool(text_sub)
        if listing_simple:
            print(
                "[NoDriver] mode: listing_simple_two_phase — "
                "(1) scroll to bottom + See/More Events "
                "(2) extract links from cards → #__scraper_vlist_accum__",
                flush=True,
            )
        want_load_more = max_load_more_clicks > 0 and (bool(text_sub) or bool(sel_sub))
        interleave_rounds = max(0, int(interleave_scroll_and_load_more_rounds))
        if interleave_rounds > 0 and not (text_sub or sel_sub):
            logger.warning(
                "NoDriver: interleave_scroll_and_load_more_rounds=%s but no load_more text/selector; skipping",
                interleave_rounds,
            )
            interleave_rounds = 0

        vlink_sel = (virtualized_list_link_selector or "").strip()
        inject_accum_js = (
            NoDriverClient._merge_vlist_accum_js(vlink_sel) if vlink_sel else None
        )

        use_text = bool(text_sub)
        visible_click_script = None
        visible_text_click_script = None
        if (interleave_rounds > 0 or want_load_more or listing_simple) and (text_sub or sel_sub):
            if not use_text:
                visible_click_script = """
                (() => {
                    const el = document.querySelector(%s);
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                        return false;
                    }
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 1 || rect.height < 1) return false;
                    el.click();
                    return true;
                })()
                """ % json.dumps(sel_sub)
            else:
                # Vue/SPAs: label may be nested; "button" may be a div with role/cursor. Use text
                # nodes + walk-up, scrollIntoView, and synthetic pointer/mouse events (not only .click()).
                visible_text_click_script = """
                (() => {
                    const needle = %s;
                    const n = needle.toLowerCase();
                    function normText(el) {
                        return (el.innerText || el.textContent || el.value || '')
                            .replace(/\\s+/g, ' ').trim().toLowerCase();
                    }
                    function visible(el) {
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        if (parseFloat(style.opacity || '1') < 0.05) return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width >= 2 && rect.height >= 2;
                    }
                    function isClickable(el) {
                        const tag = (el.tagName || '').toLowerCase();
                        if (tag === 'button') return true;
                        if (tag === 'a') {
                            if (el.getAttribute('href')) return true;
                            const ca = (el.className && String(el.className).toLowerCase()) || '';
                            if (ca.includes('pseudo-link') || ca.includes('cs-pseudo-link')) return true;
                        }
                        if (tag === 'input' && ['button', 'submit'].includes((el.type || '').toLowerCase())) {
                            return true;
                        }
                        const role = ((el.getAttribute && el.getAttribute('role')) || '').toLowerCase();
                        if (role === 'button' || role === 'link') return true;
                        if (el.getAttribute && el.getAttribute('tabindex') === '0') return true;
                        const cur = window.getComputedStyle(el).cursor;
                        if (cur === 'pointer') return true;
                        const cls = (el.className && String(el.className).toLowerCase()) || '';
                        if (cls.includes('btn') || cls.includes('button') || cls.includes('csbtn')
                            || cls.includes('load-more') || cls.includes('loadmore') || cls.includes('see-more')) {
                            return true;
                        }
                        return false;
                    }
                    function synthesizeClick(el) {
                        try {
                            el.scrollIntoView({ block: 'center', behavior: 'instant' });
                        } catch (e) {}
                        const o = { bubbles: true, cancelable: true, view: window };
                        if (typeof PointerEvent === 'function') {
                            el.dispatchEvent(new PointerEvent('pointerdown',
                                { ...o, pointerId: 1, pointerType: 'mouse', buttons: 1 }));
                            el.dispatchEvent(new PointerEvent('pointerup',
                                { ...o, pointerId: 1, pointerType: 'mouse', buttons: 0 }));
                        }
                        el.dispatchEvent(new MouseEvent('mousedown', { ...o, button: 0, buttons: 1 }));
                        el.dispatchEvent(new MouseEvent('mouseup', { ...o, button: 0, buttons: 0 }));
                        el.dispatchEvent(new MouseEvent('click', { ...o, button: 0, detail: 1 }));
                        if (typeof el.click === 'function') {
                            el.click();
                        }
                    }
                    const candidates = [];
                    const seenEl = new Set();
                    const walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_TEXT,
                        null
                    );
                    let tn;
                    while ((tn = walker.nextNode())) {
                        const chunk = (tn.textContent || '').trim().toLowerCase();
                        if (!chunk.includes(n)) continue;
                        let el = tn.parentElement;
                        for (let depth = 0; depth < 14 && el; depth++) {
                            if (!visible(el)) {
                                el = el.parentElement;
                                continue;
                            }
                            const raw = normText(el);
                            if (!raw.includes(n)) {
                                el = el.parentElement;
                                continue;
                            }
                            if (raw.length > 220) {
                                el = el.parentElement;
                                continue;
                            }
                            if (isClickable(el)) {
                                if (seenEl.has(el)) break;
                                seenEl.add(el);
                                const r = el.getBoundingClientRect();
                                candidates.push({ el, area: r.width * r.height });
                                break;
                            }
                            el = el.parentElement;
                        }
                    }
                    if (candidates.length === 0) {
                        const q = 'button, a[href], a.cs-pseudo-link, a.pseudo-link, [role="button"], '
                            + 'input[type="button"], input[type="submit"]';
                        document.querySelectorAll(q).forEach((el) => {
                            if (seenEl.has(el)) return;
                            if (!visible(el)) return;
                            const raw = normText(el);
                            if (!raw.includes(n)) return;
                            seenEl.add(el);
                            const r = el.getBoundingClientRect();
                            candidates.push({ el, area: r.width * r.height });
                        });
                    }
                    candidates.sort((a, b) => a.area - b.area);
                    for (let i = 0; i < candidates.length; i++) {
                        const el = candidates[i].el;
                        if (!visible(el)) continue;
                        synthesizeClick(el);
                        return true;
                    }
                    return false;
                })()
                """ % json.dumps(text_sub)

        if interleave_rounds > 0 or listing_simple:
            settle_max_ms = max(500, int(scroll_load_settle_max_ms))
            poll_ms = max(80, int(scroll_load_settle_poll_ms))
            quiet_polls = max(2, int(scroll_load_settle_quiet_polls))
            container_sel_json = json.dumps(scroll_container_selector or "")
            growth_sel_json = json.dumps(scroll_load_growth_selector or "")
            print(
                f"[NoDriver] interleave: {interleave_rounds} rounds (scroll + load-more) …",
                flush=True,
            )
            logger.info(
                "NoDriver: interleave scroll-then-load-more rounds=%s settle_max_ms=%s poll_ms=%s "
                "quiet_polls=%s growth_sel=%s",
                interleave_rounds,
                settle_max_ms,
                poll_ms,
                quiet_polls,
                scroll_load_growth_selector or "(none)",
            )
            scroll_one_pass_js = """
            (() => {
                const settleMaxMs = %d;
                const pollMs = %d;
                const quietPolls = %d;
                const containerSel = %s;
                const growthSel = %s;
                function discoverAllScrollables() {
                    if (containerSel) {
                        return Array.from(document.querySelectorAll(containerSel)).filter(
                            (el) => el.scrollHeight > el.clientHeight + 6);
                    }
                    const out = [];
                    const stack = document.body ? [document.body] : [];
                    while (stack.length) {
                        const el = stack.pop();
                        if (!el || !el.children) continue;
                        for (let i = 0; i < el.children.length; i++) stack.push(el.children[i]);
                        try {
                            const st = window.getComputedStyle(el);
                            const oy = st.overflowY;
                            if ((oy === 'auto' || oy === 'scroll' || oy === 'overlay')
                                && el.scrollHeight > el.clientHeight + 6) {
                                out.push(el);
                            }
                        } catch (e) {}
                    }
                    return out;
                }
                function primaryScrollEls() {
                    if (containerSel) {
                        const els = discoverAllScrollables();
                        if (els.length) return els;
                    }
                    const inner = discoverAllScrollables();
                    if (!inner.length) return [];
                    let best = inner[0];
                    let bestRoom = inner[0].scrollHeight - inner[0].clientHeight;
                    for (let i = 1; i < inner.length; i++) {
                        const el = inner[i];
                        const room = el.scrollHeight - el.clientHeight;
                        if (room > bestRoom) { bestRoom = room; best = el; }
                    }
                    return bestRoom > 12 ? [best] : [];
                }
                function fireScroll(el) {
                    try {
                        el.dispatchEvent(new Event('scroll', { bubbles: true }));
                    } catch (e) {}
                }
                function scrollElementToBottom(el) {
                    const maxSteps = 600;
                    let steps = 0;
                    const ch = el.clientHeight || 400;
                    const chunk = Math.max(120, Math.min(500, Math.floor(ch * 0.85)));
                    while (el.scrollTop + el.clientHeight < el.scrollHeight - 2 && steps < maxSteps) {
                        el.scrollTop = Math.min(el.scrollTop + chunk, el.scrollHeight);
                        fireScroll(el);
                        steps++;
                    }
                    el.scrollTop = el.scrollHeight;
                    fireScroll(el);
                }
                function scrollEverything() {
                    const de = document.documentElement;
                    const b = document.body;
                    const y = Math.max(
                        de.scrollHeight,
                        b ? b.scrollHeight : 0,
                        de.clientHeight
                    );
                    window.scrollTo(0, y);
                    fireScroll(window);
                    scrollElementToBottom(de);
                    if (b) {
                        scrollElementToBottom(b);
                    }
                    for (const el of primaryScrollEls()) {
                        scrollElementToBottom(el);
                    }
                }
                function growthSignal() {
                    const de = document.documentElement;
                    const b = document.body;
                    let s = Math.max(de.scrollHeight, b ? b.scrollHeight : 0);
                    s += de.scrollTop * 11 + (b ? b.scrollTop * 11 : 0);
                    for (const el of discoverAllScrollables()) {
                        s += el.scrollHeight * 1009 + el.scrollTop * 3;
                    }
                    if (growthSel) {
                        try {
                            s += document.querySelectorAll(growthSel).length * 999983;
                        } catch (e) {}
                    }
                    return s;
                }
                function waitForSettleAfterScroll() {
                    return new Promise((resolveSettle) => {
                        let last = growthSignal();
                        let quiet = 0;
                        const start = Date.now();
                        const tick = () => {
                            if (Date.now() - start >= settleMaxMs) { resolveSettle(); return; }
                            const sig = growthSignal();
                            if (sig === last) {
                                quiet++;
                                if (quiet >= quietPolls) { resolveSettle(); return; }
                            } else {
                                quiet = 0;
                                last = sig;
                            }
                            setTimeout(tick, pollMs);
                        };
                        setTimeout(tick, pollMs);
                    });
                }
                return new Promise((resolve) => {
                    scrollEverything();
                    waitForSettleAfterScroll().then(() => resolve());
                });
            })()
            """ % (
                settle_max_ms,
                poll_ms,
                quiet_polls,
                container_sel_json,
                growth_sel_json,
            )
            pass_timeout = min(180.0, settle_max_ms / 1000.0 + 50.0)
            if listing_simple:
                passes = max(1, int(listing_scroll_load_passes))
                print(
                    "[NoDriver] listing phase 1/2: scroll to bottom + See/More Events …",
                    flush=True,
                )
                print(
                    f"[NoDriver]   max_passes={passes} load_more_text_contains={text_sub!r}",
                    flush=True,
                )
                _read_growth_count_js_ls = (
                    """
                    () => {
                        const sel = %s;
                        if (!sel) return -1;
                        try {
                            return document.querySelectorAll(sel).length;
                        } catch (e) {
                            return -1;
                        }
                    }
                    """
                    % (growth_sel_json,)
                )
                stable_run = 0
                last_tiles = -1
                for i in range(passes):
                    print(f"[NoDriver]   pass {i+1}/{passes}: scroll + settle …", flush=True)
                    try:
                        await asyncio.wait_for(
                            page.evaluate(scroll_one_pass_js, await_promise=True),
                            timeout=pass_timeout,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "NoDriver: listing_simple scroll+settle timed out pass %s/%s",
                            i + 1,
                            passes,
                        )
                    await asyncio.sleep(0.2)
                    clicked = False
                    try:
                        if visible_text_click_script:
                            clicked = bool(await page.evaluate(visible_text_click_script))
                    except Exception as e:
                        logger.debug("NoDriver: listing_simple load-more click: %s", e)
                    n_tiles = -1
                    try:
                        n_tiles = int(
                            await page.evaluate(_read_growth_count_js_ls, return_by_value=True)
                        )
                    except (TypeError, ValueError):
                        n_tiles = -1
                    print(
                        f"[NoDriver]   pass {i+1}/{passes}: tiles={n_tiles} "
                        f"see_more_clicked={clicked}",
                        flush=True,
                    )
                    if n_tiles == last_tiles and not clicked:
                        stable_run += 1
                        if stable_run >= 16:
                            print(
                                "[NoDriver] listing phase 1 done (no tile growth, no button).",
                                flush=True,
                            )
                            break
                    else:
                        stable_run = 0
                    last_tiles = n_tiles
                    await asyncio.sleep(max(0.05, load_more_pause_sec))
                print(
                    "[NoDriver] listing phase 2/2: extract detail links from cards → accum …",
                    flush=True,
                )
            if interleave_rounds > 0:
                # Stop once the load-more control is gone; do not burn the full round cap every time.
                # 0 = never stop early (only interleave_rounds limits); needed for huge CitySpark lists.
                _raw_miss = int(interleave_stop_after_consecutive_misses)
                stop_after_misses = (
                    interleave_rounds + 1 if _raw_miss <= 0 else max(1, _raw_miss)
                )
                _interleave_thr_label = "off" if _raw_miss <= 0 else str(stop_after_misses)
                print(
                    f"[NoDriver] interleave: {interleave_rounds} rounds, "
                    f"early stop after {_interleave_thr_label} stale rounds "
                    f"(no click AND no accum/tile growth)",
                    flush=True,
                )
                consecutive_no_click = 0
                rounds_used = 0
                _read_accum_len_js = """
                () => {
                    const n = document.getElementById('__scraper_vlist_accum__');
                    if (!n) return 0;
                    try {
                        const a = JSON.parse(n.textContent || '[]');
                        return Array.isArray(a) ? a.length : 0;
                    } catch (e) {
                        return 0;
                    }
                }
                """
                _growth_track = bool((scroll_load_growth_selector or "").strip())
                _read_growth_count_js = (
                    """
                    () => {
                        const sel = %s;
                        if (!sel) return -1;
                        try {
                            return document.querySelectorAll(sel).length;
                        } catch (e) {
                            return -1;
                        }
                    }
                    """
                    % (growth_sel_json,)
                )
                prev_accum_len = 0
                prev_growth_count = -1
                if inject_accum_js:
                    try:
                        await asyncio.wait_for(
                            page.evaluate(inject_accum_js, await_promise=False),
                            timeout=35.0,
                        )
                    except Exception as e:
                        logger.debug("NoDriver: interleave pre-merge accum failed: %s", e)
                    try:
                        prev_accum_len = int(
                            await page.evaluate(_read_accum_len_js, return_by_value=True)
                        )
                    except (TypeError, ValueError):
                        prev_accum_len = 0
                if _growth_track:
                    try:
                        prev_growth_count = int(
                            await page.evaluate(_read_growth_count_js, return_by_value=True)
                        )
                    except (TypeError, ValueError):
                        prev_growth_count = -1
                for idx in range(interleave_rounds):
                    try:
                        await asyncio.wait_for(
                            page.evaluate(scroll_one_pass_js, await_promise=True),
                            timeout=pass_timeout,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "NoDriver: interleave scroll+settle timed out at step %s/%s",
                            idx + 1,
                            interleave_rounds,
                        )
                    await asyncio.sleep(0.18)
                    clicked = False
                    try:
                        if use_text:
                            clicked = bool(await page.evaluate(visible_text_click_script))
                        else:
                            clicked = bool(await page.evaluate(visible_click_script))
                    except Exception as e:
                        logger.debug("NoDriver: interleave load-more click: %s", e)
                    logger.info(
                        "NoDriver: interleave step %s/%s load_more_clicked=%s",
                        idx + 1,
                        interleave_rounds,
                        clicked,
                    )
                    await asyncio.sleep(max(0.05, load_more_pause_sec))
                    accum_len = prev_accum_len
                    growth_count = prev_growth_count
                    if inject_accum_js:
                        try:
                            await asyncio.wait_for(
                                page.evaluate(inject_accum_js, await_promise=False),
                                timeout=35.0,
                            )
                        except Exception as e:
                            logger.debug("NoDriver: interleave accum merge failed: %s", e)
                        try:
                            accum_len = int(
                                await page.evaluate(_read_accum_len_js, return_by_value=True)
                            )
                        except (TypeError, ValueError):
                            accum_len = prev_accum_len
                    if _growth_track and prev_growth_count >= 0:
                        try:
                            growth_count = int(
                                await page.evaluate(_read_growth_count_js, return_by_value=True)
                            )
                        except (TypeError, ValueError):
                            growth_count = prev_growth_count
                    accum_grew = inject_accum_js and accum_len > prev_accum_len
                    growth_grew = _growth_track and prev_growth_count >= 0 and growth_count > prev_growth_count
                    if clicked or accum_grew or growth_grew:
                        consecutive_no_click = 0
                    else:
                        consecutive_no_click += 1
                        if consecutive_no_click >= stop_after_misses:
                            rounds_used = idx + 1
                            print(
                                f"[NoDriver] interleave early stop: {stop_after_misses} stale rounds "
                                f"(no click / accum / tile growth; stopped at {rounds_used}/{interleave_rounds})",
                                flush=True,
                            )
                            logger.info(
                                "NoDriver: interleave early stop after %s stale rounds",
                                stop_after_misses,
                            )
                            break
                    prev_accum_len = accum_len
                    if _growth_track and prev_growth_count >= 0:
                        prev_growth_count = growth_count
                    rounds_used = idx + 1
                    step_n = idx + 1
                    if (
                        step_n == 1
                        or step_n % 3 == 0
                        or (not clicked and consecutive_no_click >= 6)
                    ):
                        print(
                            f"[NoDriver] interleave {step_n}/{interleave_rounds} "
                            f"load_more_clicked={clicked} accum_links={accum_len} "
                            f"consecutive_stale={consecutive_no_click} "
                            f"(threshold={_interleave_thr_label})",
                            flush=True,
                        )
                else:
                    rounds_used = interleave_rounds
                print(
                    f"[NoDriver] interleave finished ({rounds_used}/{interleave_rounds} rounds)",
                    flush=True,
                )
        elif want_load_more:
            logger.info(
                "NoDriver: load-more max=%s pause=%ss %s",
                max_load_more_clicks,
                load_more_pause_sec,
                ("text_contains=%r" % text_sub) if use_text else ("selector=%r" % sel_sub),
            )
            for i in range(max_load_more_clicks):
                try:
                    if use_text:
                        clicked = await page.evaluate(visible_text_click_script)
                    else:
                        clicked = await page.evaluate(visible_click_script)
                except Exception as e:
                    logger.debug("NoDriver: load-more click failed: %s", e)
                    break
                if not clicked:
                    logger.info("NoDriver: load-more stopped after %s clicks (no visible control)", i)
                    break
                logger.info("NoDriver: load-more click %s/%s", i + 1, max_load_more_clicks)
                await asyncio.sleep(max(0.05, load_more_pause_sec))
        if scroll_load_max_rounds > 0 and interleave_rounds == 0:
            stable = max(1, int(scroll_load_stable_rounds))
            rounds = int(scroll_load_max_rounds)
            settle_max_ms = max(500, int(scroll_load_settle_max_ms))
            poll_ms = max(80, int(scroll_load_settle_poll_ms))
            quiet_polls = max(2, int(scroll_load_settle_quiet_polls))
            container_sel_json = json.dumps(scroll_container_selector or "")
            growth_sel_json = json.dumps(scroll_load_growth_selector or "")
            logger.info(
                "NoDriver: scroll-load rounds=%s settle_max_ms=%s poll_ms=%s quiet_polls=%s "
                "stable_rounds=%s container_sel=%s growth_sel=%s",
                rounds,
                settle_max_ms,
                poll_ms,
                quiet_polls,
                stable,
                scroll_container_selector or "(auto overflow elements + window)",
                scroll_load_growth_selector or "(none)",
            )
            # After each scroll, poll growthSignal until it stops changing (async batches), then next round.
            scroll_script = """
            (() => {
                const maxRounds = %d;
                const settleMaxMs = %d;
                const pollMs = %d;
                const quietPolls = %d;
                const stableNeeded = %d;
                const containerSel = %s;
                const growthSel = %s;
                function discoverAllScrollables() {
                    if (containerSel) {
                        return Array.from(document.querySelectorAll(containerSel)).filter(
                            (el) => el.scrollHeight > el.clientHeight + 6);
                    }
                    const out = [];
                    const stack = document.body ? [document.body] : [];
                    while (stack.length) {
                        const el = stack.pop();
                        if (!el || !el.children) continue;
                        for (let i = 0; i < el.children.length; i++) stack.push(el.children[i]);
                        try {
                            const st = window.getComputedStyle(el);
                            const oy = st.overflowY;
                            if ((oy === 'auto' || oy === 'scroll' || oy === 'overlay')
                                && el.scrollHeight > el.clientHeight + 6) {
                                out.push(el);
                            }
                        } catch (e) {}
                    }
                    return out;
                }
                function primaryScrollEls() {
                    if (containerSel) {
                        const els = discoverAllScrollables();
                        if (els.length) return els;
                    }
                    const inner = discoverAllScrollables();
                    if (!inner.length) return [];
                    let best = inner[0];
                    let bestRoom = inner[0].scrollHeight - inner[0].clientHeight;
                    for (let i = 1; i < inner.length; i++) {
                        const el = inner[i];
                        const room = el.scrollHeight - el.clientHeight;
                        if (room > bestRoom) { bestRoom = room; best = el; }
                    }
                    return bestRoom > 12 ? [best] : [];
                }
                function fireScroll(el) {
                    try {
                        el.dispatchEvent(new Event('scroll', { bubbles: true }));
                    } catch (e) {}
                }
                function scrollElementToBottom(el) {
                    const maxSteps = 600;
                    let steps = 0;
                    const ch = el.clientHeight || 400;
                    const chunk = Math.max(120, Math.min(500, Math.floor(ch * 0.85)));
                    while (el.scrollTop + el.clientHeight < el.scrollHeight - 2 && steps < maxSteps) {
                        el.scrollTop = Math.min(el.scrollTop + chunk, el.scrollHeight);
                        fireScroll(el);
                        steps++;
                    }
                    el.scrollTop = el.scrollHeight;
                    fireScroll(el);
                }
                function scrollEverything() {
                    const de = document.documentElement;
                    const b = document.body;
                    const y = Math.max(
                        de.scrollHeight,
                        b ? b.scrollHeight : 0,
                        de.clientHeight
                    );
                    window.scrollTo(0, y);
                    fireScroll(window);
                    scrollElementToBottom(de);
                    if (b) {
                        scrollElementToBottom(b);
                    }
                    for (const el of primaryScrollEls()) {
                        scrollElementToBottom(el);
                    }
                }
                function growthSignal() {
                    const de = document.documentElement;
                    const b = document.body;
                    let s = Math.max(de.scrollHeight, b ? b.scrollHeight : 0);
                    s += de.scrollTop * 11 + (b ? b.scrollTop * 11 : 0);
                    for (const el of discoverAllScrollables()) {
                        s += el.scrollHeight * 1009 + el.scrollTop * 3;
                    }
                    if (growthSel) {
                        try {
                            s += document.querySelectorAll(growthSel).length * 999983;
                        } catch (e) {}
                    }
                    return s;
                }
                function waitForSettleAfterScroll() {
                    return new Promise((resolveSettle) => {
                        let last = growthSignal();
                        let quiet = 0;
                        const start = Date.now();
                        const tick = () => {
                            if (Date.now() - start >= settleMaxMs) { resolveSettle(); return; }
                            const sig = growthSignal();
                            if (sig === last) {
                                quiet++;
                                if (quiet >= quietPolls) { resolveSettle(); return; }
                            } else {
                                quiet = 0;
                                last = sig;
                            }
                            setTimeout(tick, pollMs);
                        };
                        setTimeout(tick, pollMs);
                    });
                }
                return new Promise((resolve) => {
                    let round = 0;
                    let lastSig = null;
                    let stableCount = 0;
                    const step = () => {
                        if (round >= maxRounds) { resolve(); return; }
                        scrollEverything();
                        round++;
                        waitForSettleAfterScroll().then(() => {
                            const sig = growthSignal();
                            if (lastSig === null) {
                                lastSig = sig;
                                step();
                                return;
                            }
                            if (sig === lastSig) {
                                stableCount++;
                                if (stableCount >= stableNeeded) { resolve(); return; }
                            } else {
                                stableCount = 0;
                                lastSig = sig;
                            }
                            step();
                        });
                    };
                    step();
                });
            })()
            """ % (
                rounds,
                settle_max_ms,
                poll_ms,
                quiet_polls,
                stable,
                container_sel_json,
                growth_sel_json,
            )
            eval_budget = 35.0 + float(rounds) * (settle_max_ms / 1000.0 + 8.0)
            try:
                await asyncio.wait_for(
                    page.evaluate(scroll_script, await_promise=True),
                    timeout=min(540.0, eval_budget),
                )
            except asyncio.TimeoutError:
                logger.warning("NoDriver: scroll-load timed out, continuing with current DOM")
        v_container_json = json.dumps(scroll_container_selector or "")
        if inject_accum_js:
            print("[NoDriver] collecting listing links into accum …", flush=True)
            _vraw = int(virtualized_list_collect_max_steps)
            if _vraw <= 0:
                logger.info(
                    "NoDriver: virtual list snapshot-only (selector=%r); skipping stepped scroll sweep",
                    vlink_sel,
                )
                try:
                    await asyncio.wait_for(
                        page.evaluate(inject_accum_js, await_promise=False),
                        timeout=45.0,
                    )
                except Exception as e:
                    logger.warning("NoDriver: virtual list snapshot inject failed: %s", e)
            else:
                vmax = max(80, min(3000, _vraw))
                logger.info(
                    "NoDriver: virtualized list link sweep selector=%r max_steps=%s",
                    vlink_sel,
                    vmax,
                )
                # Scroll only the window + one primary inner scroller (or scroll_container_selector).
                # Scrolling every overflow:auto subtree every tick breaks SPAs like CitySpark (lost scroll / stall).
                v_collect_js = """
                (() => {
                    return new Promise((resolve) => {
                        const linkSel = %s;
                        const maxSteps = %d;
                        const containerSel = %s;
                        function pickContainers() {
                            const out = [];
                            const stack = document.body ? [document.body] : [];
                            while (stack.length) {
                                const el = stack.pop();
                                if (!el || !el.children) continue;
                                for (let i = 0; i < el.children.length; i++) stack.push(el.children[i]);
                                try {
                                    const st = window.getComputedStyle(el);
                                    const oy = st.overflowY;
                                    if ((oy === 'auto' || oy === 'scroll' || oy === 'overlay')
                                        && el.scrollHeight > el.clientHeight + 6) {
                                        out.push(el);
                                    }
                                } catch (e) {}
                            }
                            return out;
                        }
                        function primaryScrollEls() {
                            if (containerSel) {
                                const els = Array.from(document.querySelectorAll(containerSel));
                                const ok = els.filter((el) => el.scrollHeight > el.clientHeight + 6);
                                if (ok.length) return ok;
                            }
                            const inner = pickContainers();
                            if (!inner.length) return [];
                            let best = inner[0];
                            let bestRoom = inner[0].scrollHeight - inner[0].clientHeight;
                            for (let i = 1; i < inner.length; i++) {
                                const el = inner[i];
                                const room = el.scrollHeight - el.clientHeight;
                                if (room > bestRoom) { bestRoom = room; best = el; }
                            }
                            return bestRoom > 12 ? [best] : [];
                        }
                        function fireScroll(el) {
                            try { el.dispatchEvent(new Event('scroll', { bubbles: true })); } catch (e) {}
                        }
                        function scrollStepDown() {
                            const vy = Math.min(500, Math.max(200, window.innerHeight * 0.6));
                            window.scrollBy(0, vy);
                            fireScroll(window);
                            const de = document.documentElement;
                            const b = document.body;
                            const targets = primaryScrollEls();
                            [de, b, ...targets].forEach((el) => {
                                if (!el) return;
                                try {
                                    const ch = el.clientHeight || 400;
                                    const delta = Math.min(500, Math.max(150, ch * 0.65));
                                    const next = Math.min(el.scrollTop + delta, el.scrollHeight);
                                    el.scrollTop = next;
                                    fireScroll(el);
                                } catch (e) {}
                            });
                        }
                        function goTop() {
                            window.scrollTo(0, 0);
                            fireScroll(window);
                            try {
                                document.documentElement.scrollTop = 0;
                            } catch (e) {}
                            try {
                                if (document.body) document.body.scrollTop = 0;
                            } catch (e) {}
                            // Do not reset the primary inner list scroller — CitySpark can remount empty.
                        }
                        function listScrollAtBottom() {
                            try {
                                const st = window.pageYOffset
                                    || (document.documentElement && document.documentElement.scrollTop)
                                    || 0;
                                const vh = window.innerHeight || 0;
                                const sh = Math.max(
                                    document.documentElement ? document.documentElement.scrollHeight : 0,
                                    document.body ? document.body.scrollHeight : 0
                                );
                                if (sh > vh + 40 && st + vh < sh - 28) return false;
                            } catch (e) {}
                            const targets = primaryScrollEls();
                            for (let i = 0; i < targets.length; i++) {
                                const el = targets[i];
                                try {
                                    if (el.scrollTop + el.clientHeight < el.scrollHeight - 18) return false;
                                } catch (e) {}
                            }
                            return true;
                        }
                        function isCitySparkDetailHref(h) {
                            if (!h) return false;
                            const t = h.trim();
                            if (/details\\/[^/?#\\s]+\\/\\d+\\/\\d{4}-\\d{2}-\\d{2}T[^/?#\\s]*/i.test(t)) return true;
                            if (/(?:#|\\/)details\\/[^/?#\\s]+\\/\\d+\\//i.test(t)) return true;
                            if (/[/#]details\\/[^/?#\\s]+\\/\\d+(?:\\/|[?#]|$)/i.test(t)) return true;
                            return false;
                        }
                        function queryDeep(selector) {
                            const roots = [];
                            function visit(root) {
                                if (!root || !root.querySelectorAll) return;
                                roots.push(root);
                                let all;
                                try {
                                    all = root.querySelectorAll('*');
                                } catch (e) {
                                    return;
                                }
                                for (let i = 0; i < all.length; i++) {
                                    const el = all[i];
                                    if (el.shadowRoot) visit(el.shadowRoot);
                                }
                            }
                            visit(document);
                            const seenEl = new Set();
                            const out = [];
                            for (let i = 0; i < roots.length; i++) {
                                try {
                                    roots[i].querySelectorAll(selector).forEach((el) => {
                                        if (seenEl.has(el)) return;
                                        seenEl.add(el);
                                        out.push(el);
                                    });
                                } catch (e) {}
                            }
                            return out;
                        }
                        function collectInto(set) {
                            try {
                                queryDeep(linkSel).forEach((a) => {
                                    const h = (a.getAttribute('href') || '').trim();
                                    if (h && isCitySparkDetailHref(h)) set.add(h);
                                });
                            } catch (e) {}
                        }
                        const seen = new Set();
                        try {
                            const prev = document.getElementById('__scraper_vlist_accum__');
                            if (prev && prev.textContent) {
                                const arr = JSON.parse(prev.textContent);
                                if (Array.isArray(arr)) {
                                    arr.forEach((h) => {
                                        if (h) seen.add(String(h).trim());
                                    });
                                }
                            }
                        } catch (e) {}
                        goTop();
                        let step = 0;
                        let lastSize = -1;
                        let stable = 0;
                        const stableNeed = 72;
                        const tick = () => {
                            collectInto(seen);
                            const n = seen.size;
                            const bottom = listScrollAtBottom();
                            if (n === lastSize) {
                                if (bottom) stable++;
                                else stable = 0;
                            } else {
                                stable = 0;
                                lastSize = n;
                            }
                            if (step >= maxSteps || (stable >= stableNeed && bottom)) {
                                const old = document.getElementById('__scraper_vlist_accum__');
                                if (old) old.remove();
                                const holder = document.createElement('script');
                                holder.id = '__scraper_vlist_accum__';
                                holder.type = 'application/json';
                                holder.setAttribute('data-events-scraper', 'accumulated-links');
                                holder.textContent = JSON.stringify(Array.from(seen));
                                document.body.appendChild(holder);
                                resolve();
                                return;
                            }
                            scrollStepDown();
                            step++;
                            setTimeout(tick, 280);
                        };
                        setTimeout(tick, 300);
                    });
                })()
                """ % (json.dumps(vlink_sel), vmax, v_container_json)
                v_eval_budget = min(3600.0, 120.0 + vmax * 0.52)
                try:
                    await asyncio.wait_for(
                        page.evaluate(v_collect_js, await_promise=True),
                        timeout=v_eval_budget,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "NoDriver: virtualized link collection timed out (partial set may be injected)"
                    )
                    try:
                        await asyncio.wait_for(
                            page.evaluate(inject_accum_js, await_promise=False),
                            timeout=45.0,
                        )
                    except Exception as e:
                        logger.debug("NoDriver: virtual list timeout snapshot failed: %s", e)
            try:
                need_refill = bool(
                    await page.evaluate(
                        """
                        () => {
                          const n = document.getElementById('__scraper_vlist_accum__');
                          if (!n) return true;
                          try {
                            const a = JSON.parse(n.textContent || '[]');
                            return !Array.isArray(a) || a.length === 0;
                          } catch (e) {
                            return true;
                          }
                        }
                        """,
                        return_by_value=True,
                    )
                )
            except Exception:
                need_refill = True
            if need_refill:
                print(
                    "[NoDriver] accum empty — DOM snapshot refill …",
                    flush=True,
                )
                try:
                    await asyncio.wait_for(
                        page.evaluate(inject_accum_js, await_promise=False),
                        timeout=45.0,
                    )
                except Exception as e:
                    logger.warning(
                        "NoDriver: virtual list snapshot refill failed: %s",
                        e,
                    )
        logger.info("NoDriver: getting page HTML")
        used_vlist = bool((virtualized_list_link_selector or "").strip())
        outer_budget = 600.0
        skip_minimal = used_vlist and bool(virtualized_list_return_full_html)
        if used_vlist and not skip_minimal:
            print("[NoDriver] building response HTML …", flush=True)
            try:
                result = await asyncio.wait_for(
                    page.evaluate(
                        """
                        () => {
                          const n = document.getElementById('__scraper_vlist_accum__');
                          if (!n) return '';
                          return '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'
                            + n.outerHTML + '</body></html>';
                        }
                        """,
                        return_by_value=True,
                    ),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                logger.warning("NoDriver: minimal HTML capture timed out")
                result = None
            html = ""
            if result is not None:
                html = result if isinstance(result, str) else str(result)
            if html and len(html) >= 40:
                logger.info("NoDriver: done minimal len=%s", len(html))
                print(f"[NoDriver] fetch complete (minimal HTML, {len(html)} chars)", flush=True)
                return html
            logger.warning(
                "NoDriver: accum node missing/empty after virtual list; falling back to full outerHTML "
                "(may be slow on huge pages)"
            )
            print("[NoDriver] full-page outerHTML (slow path) …", flush=True)
        elif skip_minimal:
            logger.info("NoDriver: skipping minimal HTML (virtualized_list_return_full_html)")
            print(
                "[NoDriver] capturing full page HTML for DOM/card parsing (skip minimal accum-only) …",
                flush=True,
            )
        else:
            print("[NoDriver] capturing full page HTML …", flush=True)
        snap_src = (snapshot_html_eval or "").strip()
        try:
            if snap_src:
                print("[NoDriver] snapshot_html_eval (shadow-safe card extract) …", flush=True)
                result = await asyncio.wait_for(
                    page.evaluate(snap_src, return_by_value=True),
                    timeout=outer_budget,
                )
            else:
                result = await asyncio.wait_for(
                    page.evaluate("document.documentElement.outerHTML", return_by_value=True),
                    timeout=outer_budget,
                )
        except asyncio.TimeoutError:
            logger.warning(
                "NoDriver: HTML snapshot timed out after %ss",
                outer_budget,
            )
            result = ""
        if result is None:
            html = ""
        elif isinstance(result, str):
            html = result
        else:
            html = str(result)
        logger.info("NoDriver: done len=%s", len(html))
        print(f"[NoDriver] fetch complete (full HTML, {len(html)} chars)", flush=True)
        return html

    async def _fetch_page(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        wait_for_timeout: int = 30,
        dismiss_selectors: Optional[List[str]] = None,
        load_more_selector: Optional[str] = None,
        load_more_text_contains: Optional[str] = None,
        max_load_more_clicks: int = 0,
        load_more_pause_sec: float = 1.0,
        scroll_load_max_rounds: int = 0,
        scroll_load_pause_sec: float = 0.85,
        scroll_load_stable_rounds: int = 2,
        scroll_container_selector: Optional[str] = None,
        scroll_load_settle_max_ms: int = 20000,
        scroll_load_settle_poll_ms: int = 320,
        scroll_load_settle_quiet_polls: int = 6,
        scroll_load_growth_selector: Optional[str] = None,
        interleave_scroll_and_load_more_rounds: int = 0,
        interleave_stop_after_consecutive_misses: int = 12,
        virtualized_list_link_selector: Optional[str] = None,
        virtualized_list_collect_max_steps: int = 400,
        wait_for_all_selectors: Optional[List[str]] = None,
        wait_for_nonempty_text_selector: Optional[str] = None,
        wait_for_nonempty_text_min_len: int = 12,
        listing_simple_two_phase: bool = False,
        listing_scroll_load_passes: int = 150,
        virtualized_list_return_full_html: bool = False,
        snapshot_html_eval: Optional[str] = None,
    ) -> str:
        use_settle_budget = (
            scroll_load_max_rounds > 0
            or interleave_scroll_and_load_more_rounds > 0
            or (
                listing_simple_two_phase
                and bool((virtualized_list_link_selector or "").strip())
                and bool((load_more_text_contains or "").strip())
            )
        )
        inner_timeout = self._fetch_coroutine_timeout_sec(
            max_load_more_clicks,
            load_more_pause_sec,
            scroll_load_max_rounds,
            scroll_load_pause_sec,
            wait_for_timeout,
            scroll_load_settle_max_ms=scroll_load_settle_max_ms if use_settle_budget else 0,
            interleave_scroll_and_load_more_rounds=interleave_scroll_and_load_more_rounds,
            virtualized_list_link_selector=virtualized_list_link_selector,
            virtualized_list_collect_max_steps=virtualized_list_collect_max_steps,
            listing_simple_two_phase=listing_simple_two_phase,
            listing_scroll_load_passes=listing_scroll_load_passes,
        )
        return await asyncio.wait_for(
            self._fetch_page_impl(
                url,
                wait_for_selector=wait_for_selector,
                wait_for_timeout=wait_for_timeout,
                dismiss_selectors=dismiss_selectors,
                load_more_selector=load_more_selector,
                load_more_text_contains=load_more_text_contains,
                max_load_more_clicks=max_load_more_clicks,
                load_more_pause_sec=load_more_pause_sec,
                scroll_load_max_rounds=scroll_load_max_rounds,
                scroll_load_pause_sec=scroll_load_pause_sec,
                scroll_load_stable_rounds=scroll_load_stable_rounds,
                scroll_container_selector=scroll_container_selector,
                scroll_load_settle_max_ms=scroll_load_settle_max_ms,
                scroll_load_settle_poll_ms=scroll_load_settle_poll_ms,
                scroll_load_settle_quiet_polls=scroll_load_settle_quiet_polls,
                scroll_load_growth_selector=scroll_load_growth_selector,
                interleave_scroll_and_load_more_rounds=interleave_scroll_and_load_more_rounds,
                interleave_stop_after_consecutive_misses=interleave_stop_after_consecutive_misses,
                virtualized_list_link_selector=virtualized_list_link_selector,
                virtualized_list_collect_max_steps=virtualized_list_collect_max_steps,
                wait_for_all_selectors=wait_for_all_selectors,
                wait_for_nonempty_text_selector=wait_for_nonempty_text_selector,
                wait_for_nonempty_text_min_len=wait_for_nonempty_text_min_len,
                listing_simple_two_phase=listing_simple_two_phase,
                listing_scroll_load_passes=listing_scroll_load_passes,
                virtualized_list_return_full_html=virtualized_list_return_full_html,
                snapshot_html_eval=snapshot_html_eval,
            ),
            timeout=inner_timeout,
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
        dismiss_selectors: Optional[List[str]] = None,
        load_more_selector: Optional[str] = None,
        load_more_text_contains: Optional[str] = None,
        max_load_more_clicks: int = 0,
        load_more_pause_sec: float = 1.0,
        scroll_load_max_rounds: int = 0,
        scroll_load_pause_sec: float = 0.85,
        scroll_load_stable_rounds: int = 2,
        scroll_container_selector: Optional[str] = None,
        scroll_load_settle_max_ms: int = 20000,
        scroll_load_settle_poll_ms: int = 320,
        scroll_load_settle_quiet_polls: int = 6,
        scroll_load_growth_selector: Optional[str] = None,
        interleave_scroll_and_load_more_rounds: int = 0,
        interleave_stop_after_consecutive_misses: int = 12,
        virtualized_list_link_selector: Optional[str] = None,
        virtualized_list_collect_max_steps: int = 400,
        wait_for_all_selectors: Optional[List[str]] = None,
        wait_for_nonempty_text_selector: Optional[str] = None,
        wait_for_nonempty_text_min_len: int = 12,
        listing_simple_two_phase: bool = False,
        listing_scroll_load_passes: int = 150,
        virtualized_list_return_full_html: bool = False,
        snapshot_html_eval: Optional[str] = None,
    ) -> requests.Response:
        """Fetch the URL with the browser and return a requests.Response-like object (sync).
        If wait_for_selector is set, after initial load the client waits for that CSS selector
        to appear in the DOM (e.g. for JS-rendered content) before capturing HTML.
        If dismiss_selectors is set, each selector is clicked in order (e.g. to close cookie/consent popups).
        If max_load_more_clicks > 0 and load_more_text_contains is set, clicks the first visible
        button/link whose text includes that substring (case-insensitive). Otherwise if load_more_selector
        is set, uses querySelector. Stops when nothing matches or the cap is reached.
        If interleave_scroll_and_load_more_rounds > 0, each iteration scrolls to the bottom (with settle),
        then attempts one load-more click; the standalone load-more loop and multi-round scroll block
        are skipped (use this when the site needs scroll-before-click repeatedly).
        interleave_stop_after_consecutive_misses (default 12) ends the interleave early after that many
        rounds in a row with no successful load-more click; use 0 to disable and run all rounds.
        If scroll_load_max_rounds > 0, scrolls to the bottom repeatedly until the document height
        is stable for scroll_load_stable_rounds steps or max rounds is reached (infinite-scroll lists).
        Scroll targets the window, documentElement, body, every overflow:auto|scroll descendant, and
        optionally elements matching scroll_container_selector. Nested panels use stepped scrolling
        so virtualized / intersection-based loaders can run.
        After each scroll, the DOM is polled until growthSignal (layout + optional tile count) is
        unchanged for scroll_load_settle_quiet_polls samples or scroll_load_settle_max_ms elapses,
        so lazy-loaded batches can finish before the next scroll.
        If virtualized_list_link_selector is set, after load-more/scroll phases the page collects
        unique hrefs matching that selector into a JSON script tag #__scraper_vlist_accum__.
        If virtualized_list_collect_max_steps <= 0, collection is a single DOM snapshot (no stepped
        scroll sweep). If > 0, the page is stepped from top to bottom up to that many ticks.
        When a virtual list was used, captured HTML is minimal (that script node only) so huge
        post-load DOMs do not stall serializing document.documentElement.outerHTML. Set
        virtualized_list_return_full_html=True to always capture full outerHTML after the sweep
        (e.g. so BeautifulSoup can parse real listing tiles).
        If wait_for_all_selectors is set (or wait_for_nonempty_text_selector), the client polls until
        every listed selector matches and optionally until the text selector's innerText reaches
        wait_for_nonempty_text_min_len characters (for SPAs that mount shells before API data).
        If snapshot_html_eval is set, that JavaScript expression is evaluated to produce the
        response body HTML instead of ``document.documentElement.outerHTML`` (use to extract
        markup from shadow DOM / iframes).
        Only one request runs at a time.
        """
        if self.browser is None or self._loop is None:
            return self._error_response(url, status_code=502, content=b"client closed")
        use_settle_budget = (
            scroll_load_max_rounds > 0
            or interleave_scroll_and_load_more_rounds > 0
            or (
                listing_simple_two_phase
                and bool((virtualized_list_link_selector or "").strip())
                and bool((load_more_text_contains or "").strip())
            )
        )
        default_wait = self._fetch_coroutine_timeout_sec(
            max_load_more_clicks,
            load_more_pause_sec,
            scroll_load_max_rounds,
            scroll_load_pause_sec,
            wait_for_timeout,
            scroll_load_settle_max_ms=scroll_load_settle_max_ms if use_settle_budget else 0,
            interleave_scroll_and_load_more_rounds=interleave_scroll_and_load_more_rounds,
            virtualized_list_link_selector=virtualized_list_link_selector,
            virtualized_list_collect_max_steps=virtualized_list_collect_max_steps,
            listing_simple_two_phase=listing_simple_two_phase,
            listing_scroll_load_passes=listing_scroll_load_passes,
        )
        timeout_sec = timeout if timeout is not None else max(120.0, default_wait + 15.0)
        with self._rate_lock:
            self._wait_if_needed()
            logger.info("NoDriver: get(%s) timeout=%s wait_selector=%s", url, timeout_sec, wait_for_selector)
            future = asyncio.run_coroutine_threadsafe(
                self._fetch_page(
                    url,
                    wait_for_selector=wait_for_selector,
                    wait_for_timeout=wait_for_timeout,
                    dismiss_selectors=dismiss_selectors,
                    load_more_selector=load_more_selector,
                    load_more_text_contains=load_more_text_contains,
                    max_load_more_clicks=max_load_more_clicks,
                    load_more_pause_sec=load_more_pause_sec,
                    scroll_load_max_rounds=scroll_load_max_rounds,
                    scroll_load_pause_sec=scroll_load_pause_sec,
                    scroll_load_stable_rounds=scroll_load_stable_rounds,
                    scroll_container_selector=scroll_container_selector,
                    scroll_load_settle_max_ms=scroll_load_settle_max_ms,
                    scroll_load_settle_poll_ms=scroll_load_settle_poll_ms,
                    scroll_load_settle_quiet_polls=scroll_load_settle_quiet_polls,
                    scroll_load_growth_selector=scroll_load_growth_selector,
                    interleave_scroll_and_load_more_rounds=interleave_scroll_and_load_more_rounds,
                    interleave_stop_after_consecutive_misses=interleave_stop_after_consecutive_misses,
                    virtualized_list_link_selector=virtualized_list_link_selector,
                    virtualized_list_collect_max_steps=virtualized_list_collect_max_steps,
                    wait_for_all_selectors=wait_for_all_selectors,
                    wait_for_nonempty_text_selector=wait_for_nonempty_text_selector,
                    wait_for_nonempty_text_min_len=wait_for_nonempty_text_min_len,
                    listing_simple_two_phase=listing_simple_two_phase,
                    listing_scroll_load_passes=listing_scroll_load_passes,
                    virtualized_list_return_full_html=virtualized_list_return_full_html,
                    snapshot_html_eval=snapshot_html_eval,
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
                logger.warning("NoDriver: fetch timed out in browser thread (inner budget exceeded)")
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

    @staticmethod
    def _wants_browser_up_front(
        wait_for_selector: Optional[str],
        load_more_selector: Optional[str],
        load_more_text_contains: Optional[str],
        max_load_more_clicks: int,
        scroll_load_max_rounds: int,
        interleave_scroll_and_load_more_rounds: int,
        virtualized_list_link_selector: Optional[str] = None,
        wait_for_all_selectors: Optional[List[str]] = None,
        wait_for_nonempty_text_selector: Optional[str] = None,
        snapshot_html_eval: Optional[str] = None,
    ) -> bool:
        if snapshot_html_eval and str(snapshot_html_eval).strip():
            return True
        if wait_for_all_selectors:
            return True
        if wait_for_nonempty_text_selector and str(wait_for_nonempty_text_selector).strip():
            return True
        if wait_for_selector is not None:
            return True
        if interleave_scroll_and_load_more_rounds > 0:
            return True
        if virtualized_list_link_selector and virtualized_list_link_selector.strip():
            return True
        if max_load_more_clicks > 0:
            if load_more_text_contains and load_more_text_contains.strip():
                return True
            if load_more_selector and load_more_selector.strip():
                return True
        if scroll_load_max_rounds > 0:
            return True
        return False

    def _browser_get_or_503(
        self,
        url: str,
        host: str,
        browser_timeout: int,
        wait_for_selector: Optional[str] = None,
        wait_for_timeout: int = 30,
        dismiss_selectors: Optional[List[str]] = None,
        load_more_selector: Optional[str] = None,
        load_more_text_contains: Optional[str] = None,
        max_load_more_clicks: int = 0,
        load_more_pause_sec: float = 1.0,
        scroll_load_max_rounds: int = 0,
        scroll_load_pause_sec: float = 0.85,
        scroll_load_stable_rounds: int = 2,
        scroll_container_selector: Optional[str] = None,
        scroll_load_settle_max_ms: int = 20000,
        scroll_load_settle_poll_ms: int = 320,
        scroll_load_settle_quiet_polls: int = 6,
        scroll_load_growth_selector: Optional[str] = None,
        interleave_scroll_and_load_more_rounds: int = 0,
        interleave_stop_after_consecutive_misses: int = 12,
        virtualized_list_link_selector: Optional[str] = None,
        virtualized_list_collect_max_steps: int = 400,
        wait_for_all_selectors: Optional[List[str]] = None,
        wait_for_nonempty_text_selector: Optional[str] = None,
        wait_for_nonempty_text_min_len: int = 12,
        listing_simple_two_phase: bool = False,
        listing_scroll_load_passes: int = 150,
        virtualized_list_return_full_html: bool = False,
        snapshot_html_eval: Optional[str] = None,
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
                dismiss_selectors=dismiss_selectors,
                load_more_selector=load_more_selector,
                load_more_text_contains=load_more_text_contains,
                max_load_more_clicks=max_load_more_clicks,
                load_more_pause_sec=load_more_pause_sec,
                scroll_load_max_rounds=scroll_load_max_rounds,
                scroll_load_pause_sec=scroll_load_pause_sec,
                scroll_load_stable_rounds=scroll_load_stable_rounds,
                scroll_container_selector=scroll_container_selector,
                scroll_load_settle_max_ms=scroll_load_settle_max_ms,
                scroll_load_settle_poll_ms=scroll_load_settle_poll_ms,
                scroll_load_settle_quiet_polls=scroll_load_settle_quiet_polls,
                scroll_load_growth_selector=scroll_load_growth_selector,
                interleave_scroll_and_load_more_rounds=interleave_scroll_and_load_more_rounds,
                interleave_stop_after_consecutive_misses=interleave_stop_after_consecutive_misses,
                virtualized_list_link_selector=virtualized_list_link_selector,
                virtualized_list_collect_max_steps=virtualized_list_collect_max_steps,
                wait_for_all_selectors=wait_for_all_selectors,
                wait_for_nonempty_text_selector=wait_for_nonempty_text_selector,
                wait_for_nonempty_text_min_len=wait_for_nonempty_text_min_len,
                listing_simple_two_phase=listing_simple_two_phase,
                listing_scroll_load_passes=listing_scroll_load_passes,
                virtualized_list_return_full_html=virtualized_list_return_full_html,
                snapshot_html_eval=snapshot_html_eval,
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
        dismiss_selectors: Optional[List[str]] = None,
        load_more_selector: Optional[str] = None,
        load_more_text_contains: Optional[str] = None,
        max_load_more_clicks: int = 0,
        load_more_pause_sec: float = 1.0,
        scroll_load_max_rounds: int = 0,
        scroll_load_pause_sec: float = 0.85,
        scroll_load_stable_rounds: int = 2,
        scroll_container_selector: Optional[str] = None,
        scroll_load_settle_max_ms: int = 20000,
        scroll_load_settle_poll_ms: int = 320,
        scroll_load_settle_quiet_polls: int = 6,
        scroll_load_growth_selector: Optional[str] = None,
        interleave_scroll_and_load_more_rounds: int = 0,
        interleave_stop_after_consecutive_misses: int = 12,
        virtualized_list_link_selector: Optional[str] = None,
        virtualized_list_collect_max_steps: int = 400,
        wait_for_all_selectors: Optional[List[str]] = None,
        wait_for_nonempty_text_selector: Optional[str] = None,
        wait_for_nonempty_text_min_len: int = 12,
        listing_simple_two_phase: bool = False,
        listing_scroll_load_passes: int = 150,
        virtualized_list_return_full_html: bool = False,
        snapshot_html_eval: Optional[str] = None,
    ) -> requests.Response:
        host = urlparse(url).netloc
        use_settle_budget = (
            scroll_load_max_rounds > 0
            or interleave_scroll_and_load_more_rounds > 0
            or (
                listing_simple_two_phase
                and bool((virtualized_list_link_selector or "").strip())
                and bool((load_more_text_contains or "").strip())
            )
        )
        fetch_budget = NoDriverClient._fetch_coroutine_timeout_sec(
            max_load_more_clicks,
            load_more_pause_sec,
            scroll_load_max_rounds,
            scroll_load_pause_sec,
            wait_for_timeout,
            scroll_load_settle_max_ms=scroll_load_settle_max_ms if use_settle_budget else 0,
            interleave_scroll_and_load_more_rounds=interleave_scroll_and_load_more_rounds,
            virtualized_list_link_selector=virtualized_list_link_selector,
            virtualized_list_collect_max_steps=virtualized_list_collect_max_steps,
            listing_simple_two_phase=listing_simple_two_phase,
            listing_scroll_load_passes=listing_scroll_load_passes,
        )
        if timeout is not None and timeout >= self._BROWSER_TIMEOUT:
            browser_timeout = max(timeout, int(fetch_budget) + 20)
        else:
            browser_timeout = max(self._BROWSER_TIMEOUT, int(fetch_budget) + 20)
        wants_browser = self._wants_browser_up_front(
            wait_for_selector,
            load_more_selector,
            load_more_text_contains,
            max_load_more_clicks,
            scroll_load_max_rounds,
            interleave_scroll_and_load_more_rounds,
            virtualized_list_link_selector=virtualized_list_link_selector,
            wait_for_all_selectors=wait_for_all_selectors,
            wait_for_nonempty_text_selector=wait_for_nonempty_text_selector,
            snapshot_html_eval=snapshot_html_eval,
        )
        if wants_browser or host in self._use_browser_hosts:
            if wants_browser and host not in self._use_browser_hosts:
                self._use_browser_hosts.add(host)
            resp = self._browser_get_or_503(
                url, host, browser_timeout,
                wait_for_selector=wait_for_selector,
                wait_for_timeout=wait_for_timeout,
                dismiss_selectors=dismiss_selectors,
                load_more_selector=load_more_selector,
                load_more_text_contains=load_more_text_contains,
                max_load_more_clicks=max_load_more_clicks,
                load_more_pause_sec=load_more_pause_sec,
                scroll_load_max_rounds=scroll_load_max_rounds,
                scroll_load_pause_sec=scroll_load_pause_sec,
                scroll_load_stable_rounds=scroll_load_stable_rounds,
                scroll_container_selector=scroll_container_selector,
                scroll_load_settle_max_ms=scroll_load_settle_max_ms,
                scroll_load_settle_poll_ms=scroll_load_settle_poll_ms,
                scroll_load_settle_quiet_polls=scroll_load_settle_quiet_polls,
                scroll_load_growth_selector=scroll_load_growth_selector,
                interleave_scroll_and_load_more_rounds=interleave_scroll_and_load_more_rounds,
                interleave_stop_after_consecutive_misses=interleave_stop_after_consecutive_misses,
                virtualized_list_link_selector=virtualized_list_link_selector,
                virtualized_list_collect_max_steps=virtualized_list_collect_max_steps,
                wait_for_all_selectors=wait_for_all_selectors,
                wait_for_nonempty_text_selector=wait_for_nonempty_text_selector,
                wait_for_nonempty_text_min_len=wait_for_nonempty_text_min_len,
                listing_simple_two_phase=listing_simple_two_phase,
                listing_scroll_load_passes=listing_scroll_load_passes,
                virtualized_list_return_full_html=virtualized_list_return_full_html,
                snapshot_html_eval=snapshot_html_eval,
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
                    dismiss_selectors=dismiss_selectors,
                    load_more_selector=load_more_selector,
                    load_more_text_contains=load_more_text_contains,
                    max_load_more_clicks=max_load_more_clicks,
                    load_more_pause_sec=load_more_pause_sec,
                    scroll_load_max_rounds=scroll_load_max_rounds,
                    scroll_load_pause_sec=scroll_load_pause_sec,
                    scroll_load_stable_rounds=scroll_load_stable_rounds,
                    scroll_container_selector=scroll_container_selector,
                    scroll_load_settle_max_ms=scroll_load_settle_max_ms,
                    scroll_load_settle_poll_ms=scroll_load_settle_poll_ms,
                    scroll_load_settle_quiet_polls=scroll_load_settle_quiet_polls,
                    scroll_load_growth_selector=scroll_load_growth_selector,
                    interleave_scroll_and_load_more_rounds=interleave_scroll_and_load_more_rounds,
                    interleave_stop_after_consecutive_misses=interleave_stop_after_consecutive_misses,
                    virtualized_list_link_selector=virtualized_list_link_selector,
                    virtualized_list_collect_max_steps=virtualized_list_collect_max_steps,
                    wait_for_all_selectors=wait_for_all_selectors,
                    wait_for_nonempty_text_selector=wait_for_nonempty_text_selector,
                    wait_for_nonempty_text_min_len=wait_for_nonempty_text_min_len,
                    listing_simple_two_phase=listing_simple_two_phase,
                    listing_scroll_load_passes=listing_scroll_load_passes,
                    virtualized_list_return_full_html=virtualized_list_return_full_html,
                    snapshot_html_eval=snapshot_html_eval,
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
                dismiss_selectors=dismiss_selectors,
                load_more_selector=load_more_selector,
                load_more_text_contains=load_more_text_contains,
                max_load_more_clicks=max_load_more_clicks,
                load_more_pause_sec=load_more_pause_sec,
                scroll_load_max_rounds=scroll_load_max_rounds,
                scroll_load_pause_sec=scroll_load_pause_sec,
                scroll_load_stable_rounds=scroll_load_stable_rounds,
                scroll_container_selector=scroll_container_selector,
                scroll_load_settle_max_ms=scroll_load_settle_max_ms,
                scroll_load_settle_poll_ms=scroll_load_settle_poll_ms,
                scroll_load_settle_quiet_polls=scroll_load_settle_quiet_polls,
                scroll_load_growth_selector=scroll_load_growth_selector,
                interleave_scroll_and_load_more_rounds=interleave_scroll_and_load_more_rounds,
                interleave_stop_after_consecutive_misses=interleave_stop_after_consecutive_misses,
                virtualized_list_link_selector=virtualized_list_link_selector,
                virtualized_list_collect_max_steps=virtualized_list_collect_max_steps,
                wait_for_all_selectors=wait_for_all_selectors,
                wait_for_nonempty_text_selector=wait_for_nonempty_text_selector,
                wait_for_nonempty_text_min_len=wait_for_nonempty_text_min_len,
                listing_simple_two_phase=listing_simple_two_phase,
                listing_scroll_load_passes=listing_scroll_load_passes,
                virtualized_list_return_full_html=virtualized_list_return_full_html,
                snapshot_html_eval=snapshot_html_eval,
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
                    dismiss_selectors=dismiss_selectors,
                    load_more_selector=load_more_selector,
                    load_more_text_contains=load_more_text_contains,
                    max_load_more_clicks=max_load_more_clicks,
                    load_more_pause_sec=load_more_pause_sec,
                    scroll_load_max_rounds=scroll_load_max_rounds,
                    scroll_load_pause_sec=scroll_load_pause_sec,
                    scroll_load_stable_rounds=scroll_load_stable_rounds,
                    scroll_container_selector=scroll_container_selector,
                    scroll_load_settle_max_ms=scroll_load_settle_max_ms,
                    scroll_load_settle_poll_ms=scroll_load_settle_poll_ms,
                    scroll_load_settle_quiet_polls=scroll_load_settle_quiet_polls,
                    scroll_load_growth_selector=scroll_load_growth_selector,
                    interleave_scroll_and_load_more_rounds=interleave_scroll_and_load_more_rounds,
                    interleave_stop_after_consecutive_misses=interleave_stop_after_consecutive_misses,
                    virtualized_list_link_selector=virtualized_list_link_selector,
                    virtualized_list_collect_max_steps=virtualized_list_collect_max_steps,
                    wait_for_all_selectors=wait_for_all_selectors,
                    wait_for_nonempty_text_selector=wait_for_nonempty_text_selector,
                    wait_for_nonempty_text_min_len=wait_for_nonempty_text_min_len,
                    listing_simple_two_phase=listing_simple_two_phase,
                    listing_scroll_load_passes=listing_scroll_load_passes,
                    virtualized_list_return_full_html=virtualized_list_return_full_html,
                    snapshot_html_eval=snapshot_html_eval,
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