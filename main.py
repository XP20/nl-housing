import re
import requests
from time import sleep, time
from dataclasses import dataclass
from bs4 import BeautifulSoup
from bs4.element import PageElement


# Scraping options
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
INTERVAL = 180  # seconds

# Search options
CITIES = [
    "eindhoven",
    # "veldhoven",
    # "geldrop",
    # "nuenen",
    # "mierlo",
]
MAX_PRICE = 1600
MIN_AREA = 25
FURNISHED = True  # False to include unfurnished
NTFY_URL = "https://ntfy.sh/mytopic"

# Pararius options
PARARIUS_MIN_MONTHS = 6  # options are 6, 12, 24, 36 or 60
PARARIUS_URL = (
    f"https://www.pararius.com/apartments/{{}}/huurperiode-{PARARIUS_MIN_MONTHS}-600"
)

# Kamernet options
# Radius options:
#   1 = 0km
#   2 = 1km
#   3 = 2km
#   4 = 5km
#   5 = 10km
#   7 = 20km
KAMERNET_RADIUS = 4  # 5km
KAMERNET_PERSONS = 2  # 17 to disable
KAMERNET_URL = f"https://kamernet.nl/en/for-rent/properties-{{}}?radius={KAMERNET_RADIUS}&suitableForNumberOfPersons={KAMERNET_PERSONS}"


@dataclass
class Apartment:
    name: str
    location: str
    city: str
    price: float
    util: bool | None
    area: int
    rooms: int | None
    furnished: bool | None
    link: str

    def format(self) -> tuple[str, str]:
        title = f"€{self.price}/m"
        if len(CITIES) > 1:
            title = f"{self.city.capitalize()} - " + title
        if self.util is not None:
            title += f" {'incl.' if self.util else 'excl.'} util"

        content_arr = [f"{self.area} m²"]
        if self.rooms is not None and self.rooms != -1:
            content_arr.append(f"{self.rooms} rooms")
        if self.furnished is not None:
            content_arr.append(f'{"" if self.furnished else "un"}furnished')

        content = ", ".join(content_arr)
        content += f"\n{self.link}"

        return (title, content)


def el_to_str(el: PageElement | None) -> str:
    if not el:
        return "Unknown"
    return el.get_text().strip()


def el_to_int(el: PageElement | None) -> int:
    if not el:
        return -1
    digits = "".join(c for c in el_to_str(el) if c.isdigit() and c.isascii())
    return int(digits)


def el_to_bool(el: PageElement | None, regex: str) -> bool | None:
    if not el:
        return None
    string = el_to_str(el)
    return bool(re.search(regex, string))


def pararius_apartments(ignore_urls: list[str]) -> list[Apartment]:
    result: list[Apartment] = []

    for city in CITIES:
        url = PARARIUS_URL.format(city)
        res = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(res.text, "html.parser")

        listings = soup.select("ul.search-list > li.search-list__item--listing")
        for listing in listings:
            # Skip invalid or seen listings
            el_link = listing.find(
                "a", {"class": "listing-search-item__link"}, href=True
            )
            href = el_link["href"]
            link = "/".join(url.split("/", 3)[:3]) + href
            if not href or link in ignore_urls:
                continue

            # Get listing information
            el_title = listing.select_one("h2.listing-search-item__title")
            el_location = listing.select_one("div.listing-search-item__sub-title")
            el_price = listing.select_one("div.listing-search-item__price")
            el_area = listing.select_one("li.illustrated-features__item--surface-area")
            el_rooms = listing.select_one(
                "li.illustrated-features__item--number-of-rooms"
            )
            el_interior = listing.select_one("li.illustrated-features__item--interior")
            el_transparency = listing.select_one("wc-price-transparency-badge")

            # Parse listing information
            title = el_to_str(el_title)
            location = el_to_str(el_location)
            price = el_to_int(el_price)
            area = el_to_int(el_area)
            rooms = el_to_int(el_rooms)
            interior = el_to_bool(el_interior, r"(?i)furnished")
            util = el_transparency is not None

            # Check listing page for utility
            res_page = requests.get(link, headers=HEADERS)
            soup_page = BeautifulSoup(res_page.text, "html.parser")
            el_inclusive = soup_page.select_one("ul.listing-features__sub-description")
            if not util:
                util = el_to_bool(
                    el_inclusive, r"(?i)(?=.*\b(gas|water|electricity)\b){3}|upholstery"
                )

            # Pack listing data
            apartment = Apartment(
                title, location, city, price, util, area, rooms, interior, link
            )
            result.append(apartment)

    return result


def kamernet_apartments(ignore_urls: list[str]) -> list[Apartment]:
    result: list[Apartment] = []

    for city in CITIES:
        url = KAMERNET_URL.format(city)
        res = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(res.text, "html.parser")

        listings = soup.select('[class*="SearchResultCard_root__"]', href=True)
        for listing in listings:
            # Skip invalid or seen listings
            link = "/".join(url.split("/", 3)[:3]) + listing["href"]
            if link in ignore_urls:
                continue

            # Check listing page
            res_page = requests.get(link, headers=HEADERS)
            soup_page = BeautifulSoup(res_page.text, "html.parser")

            # Scraping listing information
            el_name = soup_page.select_one("#page-content > section > h3")
            el_details = soup_page.select_one(
                'div[class*="ListingFound"] > section > div[class^="Overview"]'
            ).select('[class*="PropertyDetails_row___"]')
            el_price = el_details[0].select_one('[class*="PropertyDetails_price__"]')
            el_util = el_price.parent.select_one("p")
            el_area = el_details[1].select_one("h6")
            el_interior = el_details[1].select_one("p")
            el_location = soup_page.select_one(
                '#map > p[class*="CommonStyles_margin_bottom_2__"]'
            )

            # Parse listing information
            name = el_to_str(el_name)
            price = el_to_int(el_price)
            util = el_to_bool(el_util, r"(?i)incl")
            area = el_to_int(el_area)
            interior = el_to_bool(el_interior, r"(?i)furnished")
            location = el_to_str(el_location)

            # Pack listing data
            apartment = Apartment(
                name, location, city, price, util, area, None, interior, link
            )
            result.append(apartment)

    return result


seen_urls = []
with open("cache.txt", "a+", newline="") as f:
    _ = f.seek(0)
    seen_urls = list(line.strip() for line in f.readlines())

while True:
    # Gathering new listings
    listings: list[Apartment] = []
    listings.extend(pararius_apartments(seen_urls))
    listings.extend(kamernet_apartments(seen_urls))

    # Evaluating listings
    new_urls: list[str] = []
    for listing in listings:
        new_urls.append(listing.link)
        if (
            listing.price <= MAX_PRICE
            and listing.area >= MIN_AREA
            and (listing.furnished or not FURNISHED)
        ):
            title, content = listing.format()
            requests.post(
                NTFY_URL,
                data=content.encode(encoding="utf-8"),
                headers={
                    "Title": title.encode(encoding="utf-8"),
                    "Tags": "house",
                },
            )

    # Caching seen urls
    with open("cache.txt", "a+", newline="") as f:
        for url in new_urls:
            f.write(url + "\n")

    # Waiting to avoid ratelimit
    msec = round(time() * 1000)
    print(f"[{str(msec)}] Waiting {INTERVAL} sec...")
    sleep(INTERVAL)
