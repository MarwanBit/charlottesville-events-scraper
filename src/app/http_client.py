from abc import ABC, abstractmethod

import requests
import time

class BaseClient(ABC):
    
    @abstractmethod
    def get(self, url: str) -> requests.Response:
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