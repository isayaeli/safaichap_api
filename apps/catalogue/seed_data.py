"""
Catalogue ported from the app's lib/src/data/mock/mock_seed.dart so the real
API serves the catalogue the app was designed with. Prices are minor units of
the base currency (USD cents; TZS has no minor unit).
"""


def _img(seed):
    return f"https://picsum.photos/seed/{seed}/900/600"


def _day(n, title, location, description, meals, accommodation):
    return {"day_number": n, "title": title, "location": location, "description": description,
            "meals": meals, "accommodation": accommodation}


def high_seasons():
    """High season (Jul–Oct), festive (Dec 15–Feb 28) and green season (Apr–May) for 2026–2028."""
    seasons = []
    for y in (2026, 2027, 2028):
        seasons += [
            {"start_date": f"{y}-07-01", "end_date": f"{y}-10-31", "multiplier_bps": 12000,
             "label": "High season (+20%)"},
            {"start_date": f"{y}-12-15", "end_date": f"{y + 1}-02-28", "multiplier_bps": 11500,
             "label": "Festive season (+15%)"},
            {"start_date": f"{y}-04-01", "end_date": f"{y}-05-31", "multiplier_bps": 8500,
             "label": "Green season (−15%)"},
        ]
    return seasons


OPERATORS = {
    "op-kilitrails": {"name": "Kili Trails Safaris", "lead_time_days": 14, "email": "bookings@kilitrails.co.tz"},
    "op-coastal": {"name": "Coastal Roots Tours", "lead_time_days": 10, "email": "bookings@coastal.co.tz"},
    "op-savannah": {"name": "Savannah Signature", "lead_time_days": 30, "email": "bookings@savannah.co.tz"},
    "op-southern": {"name": "Southern Wild Expeditions", "lead_time_days": 21, "email": "bookings@southern.co.tz"},
}
OPERATOR_PHONE = "+255754000111"

DESTINATIONS = [
    {"name": "Serengeti", "region": "Northern circuit", "image": _img("serengeti")},
    {"name": "Ngorongoro", "region": "Northern circuit", "image": _img("ngorongoro")},
    {"name": "Tarangire", "region": "Northern circuit", "image": _img("tarangire")},
    {"name": "Lake Manyara", "region": "Northern circuit", "image": _img("manyara")},
    {"name": "Kilimanjaro", "region": "Northern circuit", "image": _img("kilimanjaro")},
    {"name": "Mikumi", "region": "Southern circuit", "image": _img("mikumi")},
    {"name": "Nyerere (Selous)", "region": "Southern circuit", "image": _img("rufiji")},
    {"name": "Ruaha", "region": "Southern circuit", "image": _img("ruaha")},
    {"name": "Zanzibar", "region": "Coast", "image": _img("zanzibar")},
]

ITINERARIES = [
    {
        "title": "3-Day Serengeti & Ngorongoro",
        "slug": "3-day-serengeti-ngorongoro",
        "summary": "Fly-in, drive-out classic: big cats on the Serengeti plains and a full day in the Ngorongoro Crater.",
        "destinations": ["Serengeti", "Ngorongoro"],
        "duration_days": 3,
        "accommodation_level": "mid_range",
        "days": [
            _day(1, "Arusha → Central Serengeti", "Serengeti",
                 "Morning flight to Seronera, afternoon game drive along the Seronera river valley.",
                 ["lunch", "dinner"], "Serengeti Tented Camp"),
            _day(2, "Full day Serengeti", "Serengeti",
                 "Sunrise game drive in search of lion, leopard and cheetah. Picnic lunch in the bush.",
                 ["breakfast", "lunch", "dinner"], "Serengeti Tented Camp"),
            _day(3, "Ngorongoro Crater → Arusha", "Ngorongoro",
                 "Descend 600m into the crater for black rhino and flamingo, then drive back to Arusha.",
                 ["breakfast", "lunch"], "—"),
        ],
        "inclusions": ["Park & conservation fees", "Professional driver-guide", "4x4 Land Cruiser with pop-up roof",
                       "Full board accommodation", "Bottled water on game drives"],
        "exclusions": ["International flights", "Visa", "Tips", "Travel insurance"],
        "images": [_img("serengeti"), _img("ngorongoro"), _img("lion-pride")],
        "operator": "op-kilitrails",
        "lead_time_days": 14,
        "min_group_size": 1,
        "max_group_size": 6,
        "pricing": {"base_currency": "USD", "resident_adult": 45000, "resident_child": 25000,
                    "non_resident_adult": 128000, "non_resident_child": 72000, "seasons": "high"},
    },
    {
        "title": "Zanzibar Beach + Mikumi",
        "slug": "zanzibar-beach-mikumi",
        "summary": "Two days of game drives in Mikumi followed by white-sand beaches and Stone Town.",
        "destinations": ["Mikumi", "Zanzibar"],
        "duration_days": 5,
        "accommodation_level": "budget",
        "days": [
            _day(1, "Dar es Salaam → Mikumi", "Mikumi", "Drive west on the Tan-Zam highway, afternoon game drive.",
                 ["lunch", "dinner"], "Mikumi Wildlife Camp"),
            _day(2, "Mikumi game drives", "Mikumi", "Elephants, giraffes and hippo pools on the Mkata floodplain.",
                 ["breakfast", "lunch", "dinner"], "Mikumi Wildlife Camp"),
            _day(3, "Mikumi → Zanzibar", "Zanzibar", "Return to Dar and take the ferry to Stone Town.",
                 ["breakfast"], "Stone Town guesthouse"),
            _day(4, "Stone Town & spice tour", "Zanzibar", "Guided walk of Stone Town and a spice farm visit.",
                 ["breakfast", "lunch"], "Paje beach bungalow"),
            _day(5, "Beach day & departure", "Zanzibar",
                 "Free morning at Paje beach before transfer to the airport.", ["breakfast"], "—"),
        ],
        "inclusions": ["Park fees", "Ferry tickets", "Shared transport", "Accommodation as listed"],
        "exclusions": ["Flights", "Dinners in Zanzibar", "Tips"],
        "images": [_img("zanzibar"), _img("mikumi"), _img("stone-town")],
        "operator": "op-coastal",
        "lead_time_days": 10,
        "min_group_size": 2,
        "max_group_size": 12,
        "pricing": {"base_currency": "TZS", "resident_adult": 1150000, "resident_child": 650000,
                    "non_resident_adult": 2900000, "non_resident_child": 1700000, "seasons": "high"},
    },
    {
        "title": "Tarangire & Lake Manyara Weekend",
        "slug": "tarangire-manyara-weekend",
        "summary": "A short escape from Arusha: elephant herds under baobabs and tree-climbing lions.",
        "destinations": ["Tarangire", "Lake Manyara"],
        "duration_days": 2,
        "accommodation_level": "budget",
        "days": [
            _day(1, "Arusha → Tarangire", "Tarangire", "Full day in Tarangire with picnic lunch.",
                 ["lunch", "dinner"], "Mto wa Mbu campsite lodge"),
            _day(2, "Lake Manyara → Arusha", "Lake Manyara",
                 "Morning game drive in the groundwater forest, back by evening.", ["breakfast", "lunch"], "—"),
        ],
        "inclusions": ["Park fees", "Driver-guide", "Accommodation", "Meals"],
        "exclusions": ["Drinks", "Tips"],
        "images": [_img("tarangire"), _img("baobab"), _img("manyara")],
        "operator": "op-kilitrails",
        "lead_time_days": 7,
        "min_group_size": 1,
        "max_group_size": 7,
        "pricing": {"base_currency": "TZS", "resident_adult": 480000, "resident_child": 260000,
                    "non_resident_adult": 1250000, "non_resident_child": 700000, "seasons": "high"},
    },
    {
        "title": "7-Day Great Migration Luxury Safari",
        "slug": "great-migration-luxury",
        "summary": "Follow the wildebeest across the northern Serengeti with river-crossing season camps.",
        "destinations": ["Serengeti", "Ngorongoro", "Tarangire"],
        "duration_days": 7,
        "accommodation_level": "luxury",
        "days": [
            _day(1, "Arrival in Arusha", "Arusha", "Private transfer and welcome dinner.", ["dinner"],
                 "Arusha Coffee Lodge"),
            _day(2, "Tarangire", "Tarangire", "Full-day game drive.", ["breakfast", "lunch", "dinner"],
                 "Tarangire Treetops"),
            _day(3, "Ngorongoro highlands", "Ngorongoro", "Crater rim walk.", ["breakfast", "lunch", "dinner"],
                 "Crater Lodge"),
            _day(4, "Fly to Northern Serengeti", "Serengeti", "Kogatende airstrip.",
                 ["breakfast", "lunch", "dinner"], "Mara River Camp"),
            _day(5, "Mara River crossings", "Serengeti", "Waiting for the crossings.",
                 ["breakfast", "lunch", "dinner"], "Mara River Camp"),
            _day(6, "Hot-air balloon", "Serengeti", "Dawn balloon flight and champagne breakfast.",
                 ["breakfast", "lunch", "dinner"], "Mara River Camp"),
            _day(7, "Departure", "Arusha", "Fly back to Arusha.", ["breakfast"], "—"),
        ],
        "inclusions": ["All park fees", "Domestic flights", "Balloon safari", "Luxury full board",
                       "Private vehicle & guide"],
        "exclusions": ["International flights", "Visa", "Gratuities"],
        "images": [_img("wildebeest"), _img("mara-river"), _img("balloon")],
        "operator": "op-savannah",
        "lead_time_days": 30,
        "min_group_size": 2,
        "max_group_size": 6,
        "pricing": {"base_currency": "USD", "resident_adult": 260000, "resident_child": 150000,
                    "non_resident_adult": 690000, "non_resident_child": 380000, "seasons": "high"},
    },
    {
        "title": "Nyerere & Ruaha Southern Circuit",
        "slug": "nyerere-ruaha-southern",
        "summary": "Boat safaris on the Rufiji river and wild dogs in remote Ruaha — far from the crowds.",
        "destinations": ["Nyerere (Selous)", "Ruaha"],
        "duration_days": 4,
        "accommodation_level": "mid_range",
        "days": [
            _day(1, "Dar → Nyerere", "Nyerere (Selous)", "Flight and afternoon boat safari.", ["lunch", "dinner"],
                 "Rufiji River Camp"),
            _day(2, "Walking safari", "Nyerere (Selous)", "Guided bush walk and game drive.",
                 ["breakfast", "lunch", "dinner"], "Rufiji River Camp"),
            _day(3, "Fly to Ruaha", "Ruaha", "Afternoon drive along the Great Ruaha river.",
                 ["breakfast", "lunch", "dinner"], "Ruaha Hilltop Lodge"),
            _day(4, "Ruaha → Dar", "Ruaha", "Morning drive, then fly to Dar.", ["breakfast"], "—"),
        ],
        "inclusions": ["Park fees", "Bush flights", "Boat safari", "Full board"],
        "exclusions": ["Drinks", "Tips", "Insurance"],
        "images": [_img("rufiji"), _img("ruaha"), _img("wild-dog")],
        "operator": "op-southern",
        "lead_time_days": 21,
        "min_group_size": 2,
        "max_group_size": 8,
        "pricing": {"base_currency": "USD", "resident_adult": 98000, "resident_child": 52000,
                    "non_resident_adult": 245000, "non_resident_child": 135000, "seasons": "high"},
    },
    {
        "title": "Kilimanjaro Day Hike & Materuni Falls",
        "slug": "kilimanjaro-day-hike",
        "summary": "Hike to Mandara Hut on Kilimanjaro's Marangu route and cool off at Materuni waterfalls.",
        "destinations": ["Kilimanjaro"],
        "duration_days": 1,
        "accommodation_level": "budget",
        "days": [
            _day(1, "Marangu Gate → Mandara Hut", "Kilimanjaro",
                 "Rainforest hike with a mountain guide, coffee tour in Materuni village.", ["lunch"], "—"),
        ],
        "inclusions": ["Park fees", "Mountain guide", "Packed lunch", "Transport from Moshi"],
        "exclusions": ["Tips"],
        "images": [_img("kilimanjaro"), _img("materuni")],
        "operator": "op-kilitrails",
        "lead_time_days": 3,
        "min_group_size": 1,
        "max_group_size": 15,
        "pricing": {"base_currency": "TZS", "resident_adult": 180000, "resident_child": 90000,
                    "non_resident_adult": 520000, "non_resident_child": 260000, "seasons": None},
    },
]

# TZS per one major unit (same as the app's mock backend).
FX_TZS_PER_UNIT = {"USD": 2600, "EUR": 2800, "GBP": 3300}
