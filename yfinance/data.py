import functools
from functools import lru_cache

import requests as requests
import re

from frozendict import frozendict

try:
    import ujson as json
except ImportError:
    import json as json

cache_maxsize = 64

prune_session_cache = True


def lru_cache_freezeargs(func):
    """
    Decorator transforms mutable dictionary and list arguments into immutable types
    Needed so lru_cache can cache method calls what has dict or list arguments.
    """

    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        args = tuple([frozendict(arg) if isinstance(arg, dict) else arg for arg in args])
        kwargs = {k: frozendict(v) if isinstance(v, dict) else v for k, v in kwargs.items()}
        args = tuple([tuple(arg) if isinstance(arg, list) else arg for arg in args])
        kwargs = {k: tuple(v) if isinstance(v, list) else v for k, v in kwargs.items()}
        return func(*args, **kwargs)

    # copy over the lru_cache extra methods to this wrapper to be able to access them
    # after this decorator has been applied
    wrapped.cache_info = func.cache_info
    wrapped.cache_clear = func.cache_clear
    return wrapped


_SCRAPE_URL_ = 'https://finance.yahoo.com/quote'


def enable_prune_session_cache():
    global prune_session_cache
    prune_session_cache = True
def disable_prune_session_cache():
    global prune_session_cache
    prune_session_cache = False

class TickerData:
    """
    Have one place to retrieve data from Yahoo API in order to ease caching and speed up operations
    """
    user_agent_headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}

    def __init__(self, ticker: str, session=None):
        self.ticker = ticker
        self._session = session or requests

    @lru_cache_freezeargs
    @lru_cache(maxsize=cache_maxsize)
    def get(self, url, user_agent_headers=None, params=None, proxy=None, timeout=30):
        proxy = self._get_proxy(proxy)
        response = self._session.get(
            url=url,
            params=params,
            proxies=proxy,
            timeout=timeout,
            headers=user_agent_headers or self.user_agent_headers)
        return response

    def _get_proxy(self, proxy):
        # setup proxy in requests format
        if proxy is not None:
            if isinstance(proxy, dict) and "https" in proxy:
                proxy = proxy["https"]
            proxy = {"https": proxy}
        return proxy

    def session_cache_prune_url(self, url):
        global prune_session_cache
        if not prune_session_cache:
            return

        if not isinstance(url, str):
            return

        try:
            c = self._session.cache
        except AttributeError:
            # Not a caching session
            return

        # Only import requests_cache if session has a cache attribute, 
        # because it's an optional module
        import requests_cache
        if not isinstance(c, requests_cache.BaseCache):
            # Unlikely but technically possible
            return

        c.delete(urls=[url])

    @lru_cache_freezeargs
    @lru_cache(maxsize=cache_maxsize)
    def get_json_data_stores(self, sub_page: str = None, proxy=None) -> dict:
        '''
        get_json_data_stores returns a python dictionary of the data stores in yahoo finance web page.
        '''
        if sub_page:
            ticker_url = "{}/{}/{}".format(_SCRAPE_URL_, self.ticker, sub_page)
        else:
            ticker_url = "{}/{}".format(_SCRAPE_URL_, self.ticker)

        html = self.get(url=ticker_url, proxy=proxy).text

        # The actual json-data for stores is in a javascript assignment in the webpage
        json_str = html.split('root.App.main =')[1].split(
            '(this)')[0].split(';\n}')[0].strip()
        data = json.loads(json_str)['context']['dispatcher']['stores']

        # return data
        new_data = json.dumps(data).replace('{}', 'null')
        new_data = re.sub(
            r'{[\'|\"]raw[\'|\"]:(.*?),(.*?)}', r'\1', new_data)

        json_data = json.loads(new_data)

        try:
            quote_summary_store = json_data['QuoteSummaryStore']
        except KeyError:
            # Problem with data so clear from session cache
            self.session_cache_prune_url(ticker_url)

        return json_data
