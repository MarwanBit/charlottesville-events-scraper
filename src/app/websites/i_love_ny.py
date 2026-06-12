"""Scraper for iloveny.com individual event pages"""

from bs4 import BeautifulSoup, Tag
import re
from datetime import datetime, timezone
from typing import Optional, Tuple
from urllib.parse import urljoin
from .base import EventsWebsite
import requests

# Selectors for JS-rendered event listing: wait for cards or for pager content (so we proceed after async load even if 0 events)
ILOVENY_LISTING_SELECTOR = "div.shared-item.item, [data-sv-pager] .pagination, [data-sv-pager] a"

# Selectors to click to dismiss cookie/consent popups before parsing (order matters: try Accept first)
ILOVENY_DISMISS_SELECTORS = [
    '[aria-label="Accept"]',
    '[aria-label="Accept All"]',
    '[aria-label="Accept all"]',
    '#onetrust-accept-btn-handler',  # OneTrust
    'button[id*="accept"]',
    '.cc-accept',
    '.cc-dismiss',
    '[data-dismiss="modal"]',
    '.modal-close',
    'button.cookie-accept',
]


class ILoveNYWebsite(EventsWebsite):

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = 'https://www.iloveny.com'
        self.BASE_EVENTS_URL = self.BASE_URL + '/events'

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        """Override to use browser client wait_for_selector so JS-rendered event list is present."""
        if self.soup:
            return
        from ..http_client import NoDriverClient, HybridClient
        session = client.session if client and hasattr(client, "session") else requests.Session()
        if "User-Agent" not in session.headers:
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"
            })
        try:
            if isinstance(client, (NoDriverClient, HybridClient)):
                response = client.get(
                    self.url,
                    timeout=120,
                    wait_for_selector=ILOVENY_LISTING_SELECTOR,
                    wait_for_timeout=45,
                    dismiss_selectors=ILOVENY_DISMISS_SELECTORS,
                )
            else:
                response = session.get(self.url, timeout=10)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as e:
            print(f"[ILoveNYWebsite] Error fetching {self.url}: {e}", flush=True)
            self.soup = None

    def parse_listing_cards(self, client: Optional[requests.session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        cards = self.soup.select("div.shared-item.item")
        return cards

    def extract_event_from_card(self, card: Tag) -> list[dict]:
        event_link_el = card.select_one("div.content a")
        event_link = self.BASE_URL + event_link_el.get('href') if event_link_el and event_link_el.get('href') else ""

        return {
            "event_link": event_link,
            "scraped_at": datetime.now(timezone.utc).isoformat()
        }

    def _is_junk_link(self, url: str) -> bool:
        """True if url is empty or just base + fragment (e.g. https://www.iloveny.com#)."""
        if not url or not url.strip():
            return True
        without_fragment = url.split("#")[0].rstrip("/")
        return without_fragment == self.BASE_URL.rstrip("/") or without_fragment == self.BASE_EVENTS_URL.rstrip("/")

    def _find_next_page_link(self) -> Optional[Tag]:
        """Find the 'next page' link; try multiple selectors (site markup may vary)."""
        # Try common pagination selectors in order
        selectors = [
            'a[aria-label="Next Page"]',
            'a[aria-label="Next"]',
            '[data-sv-pager] a[rel="next"]',
            '[data-sv-pager] a.next',
            '.pagination a[rel="next"]',
            '.pagination a[aria-label="Next"]',
        ]
        for sel in selectors:
            el = self.soup.select_one(sel) if self.soup else None
            if el and el.get("href") and (el["href"] or "").strip() not in ("", "#"):
                return el
        # Fallback: any <a> inside the pager whose text or aria-label suggests "next"
        if self.soup:
            pager = self.soup.select_one("[data-sv-pager]") or self.soup.select_one(".pagination")
            if pager:
                for a in pager.select("a"):
                    href = (a.get("href") or "").strip()
                    if not href or href == "#":
                        continue
                    label = (a.get("aria-label") or "").lower()
                    text = (a.get_text(strip=True) or "").lower()
                    if "next" in label or "next" in text or a.find(string=re.compile(r"\bnext\b", re.I)):
                        return a
        return None

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        res = set[str]()
        # This gets the next page (only if it's a real link, not href="#")
        next_el = self._find_next_page_link()
        if next_el and next_el.get("href"):
            link = (next_el["href"] or "").strip()
            if link and link != "#":
                # Use urljoin so relative links like "/events/?skip=12..." or
                # "?skip=12..." become absolute URLs under BASE_URL.
                full = urljoin(self.BASE_EVENTS_URL, link)
                if full not in res and not self._is_junk_link(full):
                    res.add(full)
        # Now we need to get the links for each of the cards
        for card in self.parse_listing_cards(client):
            event_link = self.extract_event_from_card(card)["event_link"]
            if event_link and not self._is_junk_link(event_link) and event_link not in res:
                res.add(event_link)
        return list[str](res)

    def get_events(self, client: Optional[requests.Session] = None) -> list[str]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        '''
        cards = self.parse_listing_cards(client)
        res = []
        for card in cards:
            res.append(self.extract_event_from_card(card))
        return res
        '''
        return []

    def __str__(self):
        return f"ILoveNYWebsite w/ URL: {self.url}"

class ILoveNYEventWebsite(EventsWebsite):
    '''
    Scraper implementation for individual iloveny.com event pages
    '''

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = 'https://www.iloveny.com'

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        """Override to use browser client wait_for_selector so JS-rendered event page is present."""
        if self.soup:
            return
        from ..http_client import NoDriverClient, HybridClient
        session = client.session if client and hasattr(client, "session") else requests.Session()
        if "User-Agent" not in session.headers:
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"
            })
        try:
            if isinstance(client, (NoDriverClient, HybridClient)):
                response = client.get(
                    self.url,
                    timeout=120,
                    wait_for_selector=ILOVENY_LISTING_SELECTOR,
                    wait_for_timeout=45,
                    dismiss_selectors=ILOVENY_DISMISS_SELECTORS,
                )
            else:
                response = session.get(self.url, timeout=10)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as e:
            print(f"[ILoveNYEventWebsite] Error fetching {self.url}: {e}", flush=True)
            self.soup = None

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        return []

    def __str__(self):
        return f"ILoveNYEventWebsite w/ URL: {self.url}"
    
    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        '''
        Takes html_content from an individual event page and returns
        a list containing a single event's data.
        
        Args:
            html_content: The HTML content of the page
            page_url: The URL of the page (for source_url)
        '''
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        events = []
        
        # Extract data from the individual event page
        event_data = self._extract_event_data(client)
        if event_data:
            events.append(event_data)
        return events
    
    def _extract_event_data(self, client: Optional[requests.session]) -> Optional[dict]:
        '''Extract data from an individual event page'''
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        try:
            # Extract basic information
            name = self._extract_name(self.soup)
            if not name:
                return None
            
            # Extract date information
            start_date, end_date = self._extract_dates(self.soup)
            
            # Extract location
            location_data = self._extract_location(self.soup)
            
            # Extract contact information
            website = self._extract_website(self.soup)
            phone = self._extract_phone(self.soup)
            
            # Extract description
            description = self._extract_description(self.soup)
            
            # Extract image URL
            image_url = self._extract_image_url(self.soup)
            
            # Extract organizer
            organizer = self._extract_organizer(self.soup)
            
            # Extract price if available
            price = self._extract_price(self.soup)
            
            # Extract region/category
            region = self._extract_region(self.soup)
            category = self._extract_category(self.soup)
            
            return {
                'name': name,
                'description': description,
                'start_date': start_date,
                'end_date': end_date,
                'location_name': location_data.get('location_name'),
                'address': location_data.get('address'),
                'city': location_data.get('city'),
                'state': location_data.get('state', 'NY'),
                'zip_code': location_data.get('zip_code'),
                'latitude': location_data.get('latitude'),
                'longitude': location_data.get('longitude'),
                'website': website,
                'phone': phone,
                'image_url': image_url,
                'organizer': organizer,
                'price': price,
                'region': region,
                'category': category,
                'source_website': 'https://www.iloveny.com',
                'source_url': self.url
            }
        except Exception as e:
            print(f"Error extracting event data: {e}")
            return None
    
    def _extract_name(self, soup: BeautifulSoup) -> Optional[str]:
        name_selectors = [
            'h1',
            '.event-title',
            '.page-title',
            '[class*="event"][class*="title"]',
            '.listing-title'
        ]
        
        for selector in name_selectors:
            if selector.startswith('.'):
                elem = soup.find(class_=selector[1:])
            else:
                elem = soup.find(selector)
            
            if elem:
                text = elem.get_text(strip=True)
                if text and len(text) > 3:
                    return text
        
        return None
    
    def _extract_dates(self, soup: BeautifulSoup) -> Tuple[Optional[datetime], Optional[datetime]]:
        '''Extract start and end dates as datetime objects'''
        # Look for date information
        date_selectors = [
            '.event-date',
            '.date',
            '[class*="date"]',
            'time',
            '.event-dates',
            '.date-range'
        ]
        
        date_text = None
        for selector in date_selectors:
            if selector == 'time':
                elem = soup.find('time')
                if elem and elem.has_attr('datetime'):
                    try:
                        date_str = elem['datetime']
                        if 'T' in date_str:
                            date_str = date_str.split('T')[0]
                        return datetime.fromisoformat(date_str), None
                    except (ValueError, TypeError):
                        if elem:
                            date_text = elem.get_text(strip=True)
                        break
            elif selector.startswith('.'):
                elem = soup.find(class_=selector[1:])
            else:
                elem = soup.find(selector)
            
            if elem and not date_text:
                date_text = elem.get_text(strip=True)
                break
        
        if not date_text:
            # Look for date patterns in the page text
            page_text = soup.get_text()
            date_patterns = [
                r'(\w+ \d{1,2}(?:st|nd|rd|th)? - \w+ \d{1,2}(?:st|nd|rd|th)?,? \d{4})',
                r'(\w+ \d{1,2}(?:st|nd|rd|th)?,? \d{4})',
                r'(\d{1,2}/\d{1,2}/\d{4})',
                r'(\d{4}-\d{2}-\d{2})',
                r'Now Through (\w+ \d{1,2},? \d{4})',
                r'Dates vary between (.*?) - (.*?)(?:\d{4})'
            ]
            
            for pattern in date_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    date_text = match.group(0)
                    break
        
        if date_text and date_text.lower() in ['start date', 'date', 'tbd', 'to be announced', '']:
            return None, None
        
        if date_text:
            # Try to parse the date
            return self._parse_date_string(date_text), None
        
        return None, None
    
    def _parse_date_string(self, date_str: str) -> Optional[datetime]:
        """Parse various date string formats into datetime objects"""
        if not date_str:
            return None
        
        # Clean the date string
        date_str = date_str.strip()
        date_str = re.sub(r'(st|nd|rd|th)', '', date_str)
        
        # Handle "Now Through" format
        now_through_match = re.search(r'Now Through (\w+ \d{1,2},? \d{4})', date_str, re.IGNORECASE)
        if now_through_match:
            date_str = now_through_match.group(1)
        
        # Common date formats
        date_formats = [
            '%B %d, %Y',  # January 1, 2024
            '%b %d, %Y',  # Jan 1, 2024
            '%m/%d/%Y',   # 01/01/2024
            '%Y-%m-%d',   # 2024-01-01
            '%B %d %Y',   # January 1 2024
            '%b %d %Y',   # Jan 1 2024
            '%d %B %Y',   # 1 January 2024
            '%d %b %Y',   # 1 Jan 2024
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(date_str, fmt)
            except (ValueError, TypeError):
                continue
        
        return None
    
    def _extract_location(self, soup: BeautifulSoup) -> dict:
        '''Extract location information'''
        location_data = {
            'location_name': None,
            'address': None,
            'city': None,
            'state': 'NY',
            'zip_code': None,
            'latitude': None,
            'longitude': None
        }
        
        location_selectors = [
            '.location',
            '.venue',
            '.address',
            '[class*="location"]',
            '[class*="venue"]',
            '[class*="address"]'
        ]
        
        location_text = None
        for selector in location_selectors:
            if selector.startswith('.'):
                elem = soup.find(class_=selector[1:])
            else:
                elem = soup.find(selector)
            
            if elem:
                location_text = elem.get_text(strip=True)
                break
        
        if location_text:
            location_data['address'] = location_text
            location_data['location_name'] = location_text
            
            # Try to parse address components
            parts = location_text.split(',')
            if len(parts) >= 2:
                location_data['city'] = parts[0].strip()
                
                # Look for zip code
                zip_match = re.search(r'\b(\d{5}(?:-\d{4})?)\b', location_text)
                if zip_match:
                    location_data['zip_code'] = zip_match.group(1)
        
        return location_data
    
    def _extract_website(self, soup: BeautifulSoup) -> Optional[str]:
        '''Extract event website'''
        website_selectors = [
            'a[class*="website"]',
            'a[class*="visit"]',
            'a[class*="button"][href^="http"]',
            '.event-website a',
            '.external-link a',
            'a:has-text("Visit Site")',
            'a:has-text("Website")'
        ]
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text(strip=True).lower()
            
            if href.startswith('http') and ('website' in text or 'visit' in text or 'site' in text):
                return href
            
            # Check for button classes
            classes = ' '.join(link.get('class', [])).lower()
            if 'btn' in classes and 'website' in classes:
                return href
        
        return None
    
    def _extract_phone(self, soup: BeautifulSoup) -> Optional[str]:
        '''Extract phone number'''
        phone_selectors = [
            '.phone',
            '.tel',
            '[class*="phone"]',
            '[class*="contact"]'
        ]
        
        for selector in phone_selectors:
            if selector.startswith('.'):
                elem = soup.find(class_=selector[1:])
            else:
                elem = soup.find(selector)
            
            if elem:
                phone_text = elem.get_text(strip=True)
                phone_match = re.search(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', phone_text)
                if phone_match:
                    return phone_match.group()
        
        # Look for phone in text
        page_text = soup.get_text()
        phone_match = re.search(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', page_text)
        if phone_match:
            return phone_match.group()
        
        return None
    
    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        '''Extract event description'''
        description_selectors = [
            '.description',
            '.event-description',
            '[class*="description"]',
            '.content',
            'article',
            '.main-content'
        ]
        
        for selector in description_selectors:
            if selector.startswith('.'):
                elem = soup.find(class_=selector[1:])
            else:
                elem = soup.find(selector)
            
            if elem:
                text = elem.get_text(strip=True)
                text = ' '.join(text.split())
                if len(text) > 50:
                    return text
        
        # Get all paragraphs
        paragraphs = soup.find_all('p')
        if paragraphs:
            text = ' '.join([p.get_text(strip=True) for p in paragraphs[:5]])
            return ' '.join(text.split())
        
        return None
    
    def _extract_image_url(self, soup: BeautifulSoup) -> Optional[str]:
        '''Extract event image URL'''
        image_selectors = [
            '.event-image img',
            '.featured-image img',
            'meta[property="og:image"]',
            'img[class*="event"]',
            'img[class*="featured"]',
            '.hero-image img'
        ]
        
        for selector in image_selectors:
            if selector.startswith('meta'):
                elem = soup.find('meta', property='og:image')
                if elem and elem.has_attr('content'):
                    return elem['content']
            else:
                elem = soup.select_one(selector)
                if elem and elem.has_attr('src'):
                    src = elem['src']
                    if src.startswith('http'):
                        return src
                    elif src.startswith('/'):
                        return f"https://www.iloveny.com{src}"
        
        return None
    
    def _extract_organizer(self, soup: BeautifulSoup) -> Optional[str]:
        '''Extract event organizer (e.g. from "Presented By" / hosted-by info list item).'''
        # Info list pattern: <li data-name="host"> ... <span class="info-list-value">Organizer Name</span> </li>
        host_li = soup.find('li', attrs={'data-name': 'host'})
        if host_li:
            value_span = host_li.find('span', class_='info-list-value')
            if value_span:
                text = value_span.get_text(strip=True)
                if text:
                    return text

        organizer_selectors = [
            '.organizer',
            '.sponsor',
            '[class*="organizer"]',
            '[class*="sponsor"]',
            '.presented-by',
            '.hosted-by'
        ]

        for selector in organizer_selectors:
            if selector.startswith('.'):
                elem = soup.find(class_=selector[1:])
            else:
                elem = soup.find(selector)

            if elem:
                text = elem.get_text(strip=True)
                text = re.sub(r'^(Presented by|Hosted by|Sponsored by)\s*', '', text, flags=re.IGNORECASE)
                return text.strip()

        return None
    
    def _extract_price(self, soup: BeautifulSoup) -> Optional[str]:
        '''Extract price information'''
        price_selectors = [
            '.price',
            '.cost',
            '.ticket-price',
            '[class*="price"]',
            '[class*="cost"]',
            '.admission'
        ]
        
        for selector in price_selectors:
            if selector.startswith('.'):
                elem = soup.find(class_=selector[1:])
            else:
                elem = soup.find(selector)
            
            if elem:
                price_text = elem.get_text(strip=True)
                if re.search(r'\$|\d+\.\d{2}|free', price_text.lower()):
                    return price_text
        
        # Look for price patterns in text
        page_text = soup.get_text()
        price_patterns = [
            r'\$\d+(?:\.\d{2})?',
            r'Free',
            r'Admission:\s*\$\d+(?:\.\d{2})?',
            r'Tickets?\s*\$\d+(?:\.\d{2})?'
        ]
        
        for pattern in price_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                return match.group(0)
        
        return None
    
    def _extract_region(self, soup: BeautifulSoup) -> Optional[str]:
        '''Extract region from the page'''
        region_selectors = [
            '.region',
            '.event-region',
            '[class*="region"]',
            '.location .region'
        ]
        
        for selector in region_selectors:
            if selector.startswith('.'):
                elem = soup.find(class_=selector[1:])
            else:
                elem = soup.find(selector)
            
            if elem:
                return elem.get_text(strip=True)
        
        return None
    
    def _extract_category(self, soup: BeautifulSoup) -> Optional[str]:
        '''Extract category from the page'''
        category_selectors = [
            '.category',
            '.event-category',
            '[class*="category"]',
            '.categories'
        ]
        
        for selector in category_selectors:
            if selector.startswith('.'):
                elem = soup.find(class_=selector[1:])
            else:
                elem = soup.find(selector)
            
            if elem:
                return elem.get_text(strip=True)
        
        return None