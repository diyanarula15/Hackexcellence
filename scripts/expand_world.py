"""Static description of the five new destinations (pure data, no logic).

Everything here is synthetic. Place names are real public places so the data reads naturally,
but every price, opening time, timetable and seat count is invented. Money is INR.
"""

# ---- time zones: minutes east of UTC (no daylight saving anywhere in this data)
TZ_OFFSET = {
    "Asia/Kolkata": 330, "Asia/Bangkok": 420, "Asia/Singapore": 480,
    "Asia/Kuala_Lumpur": 480, "Asia/Jakarta": 420, "Asia/Makassar": 480,
    "Asia/Ho_Chi_Minh": 420,
}

# ---- destinations ---------------------------------------------------------------------------
# city: code (used in ids), centre lat/lng, price factor for hotels, areas (hotel / transfer areas)
COUNTRIES = [
    {"code": "TH", "name": "Thailand", "tz": "Asia/Bangkok", "cities": [
        {"name": "Bangkok", "code": "BKK", "airports": ["BKK", "DMK"], "lat": 13.7563, "lng": 100.5018, "pf": 1.0,
         "areas": ["Sukhumvit", "Silom", "Riverside", "Siam", "Khao San"]},
        {"name": "Phuket", "code": "HKT", "airports": ["HKT"], "lat": 7.8804, "lng": 98.3923, "pf": 1.3,
         "areas": ["Patong", "Kata", "Karon", "Phuket Town"]},
        {"name": "Chiang Mai", "code": "CNX", "airports": ["CNX"], "lat": 18.7883, "lng": 98.9853, "pf": 0.75,
         "areas": ["Old City", "Nimman", "Riverside"]},
    ]},
    {"code": "SG", "name": "Singapore", "tz": "Asia/Singapore", "cities": [
        {"name": "Singapore", "code": "SIN", "airports": ["SIN"], "lat": 1.3521, "lng": 103.8198, "pf": 1.6,
         "areas": ["Marina Bay", "Orchard", "Sentosa", "Chinatown", "Little India"]},
    ]},
    {"code": "MY", "name": "Malaysia", "tz": "Asia/Kuala_Lumpur", "cities": [
        {"name": "Kuala Lumpur", "code": "KUL", "airports": ["KUL"], "lat": 3.139, "lng": 101.6869, "pf": 0.9,
         "areas": ["KLCC", "Bukit Bintang", "Bangsar", "Petaling Street"]},
        {"name": "Penang", "code": "PEN", "airports": ["PEN"], "lat": 5.4141, "lng": 100.3288, "pf": 0.85,
         "areas": ["George Town", "Batu Ferringhi", "Gurney"]},
        {"name": "Langkawi", "code": "LGK", "airports": ["LGK"], "lat": 6.35, "lng": 99.8, "pf": 1.0,
         "areas": ["Pantai Cenang", "Kuah", "Pantai Tengah"]},
    ]},
    {"code": "ID", "name": "Indonesia", "tz": "Asia/Jakarta", "cities": [
        {"name": "Bali", "code": "DPS", "airports": ["DPS"], "lat": -8.4095, "lng": 115.1889, "pf": 1.15,
         "areas": ["Seminyak", "Ubud", "Kuta", "Nusa Dua", "Sanur"]},
        {"name": "Jakarta", "code": "JKT", "airports": ["CGK"], "lat": -6.2088, "lng": 106.8456, "pf": 0.9,
         "areas": ["Menteng", "Sudirman", "Kota Tua", "Kemang"]},
        {"name": "Yogyakarta", "code": "JOG", "airports": ["YIA"], "lat": -7.7956, "lng": 110.3695, "pf": 0.6,
         "areas": ["Malioboro", "Prawirotaman", "Sleman"]},
    ]},
    {"code": "VN", "name": "Vietnam", "tz": "Asia/Ho_Chi_Minh", "cities": [
        {"name": "Hanoi", "code": "HAN", "airports": ["HAN"], "lat": 21.0278, "lng": 105.8342, "pf": 0.7,
         "areas": ["Old Quarter", "Hoan Kiem", "West Lake", "Tay Ho"]},
        {"name": "Da Nang", "code": "DAD", "airports": ["DAD"], "lat": 16.0544, "lng": 108.2022, "pf": 0.8,
         "areas": ["My Khe Beach", "Son Tra", "Han River"]},
        {"name": "Ho Chi Minh City", "code": "SGN", "airports": ["SGN"], "lat": 10.8231, "lng": 106.6297, "pf": 0.85,
         "areas": ["District 1", "District 3", "Thao Dien", "District 7"]},
    ]},
]

# ---- airports: code -> (name, city the airport is in, country code, timezone, lat, lng)
AIRPORTS = {
    "BKK": ("Suvarnabhumi Airport", "Bangkok", "TH", "Asia/Bangkok", 13.69, 100.7501),
    "DMK": ("Don Mueang International Airport", "Bangkok", "TH", "Asia/Bangkok", 13.9126, 100.6067),
    "HKT": ("Phuket International Airport", "Phuket", "TH", "Asia/Bangkok", 8.1132, 98.3169),
    "CNX": ("Chiang Mai International Airport", "Chiang Mai", "TH", "Asia/Bangkok", 18.7668, 98.9626),
    "SIN": ("Singapore Changi Airport", "Singapore", "SG", "Asia/Singapore", 1.3644, 103.9915),
    "KUL": ("Kuala Lumpur International Airport", "Kuala Lumpur", "MY", "Asia/Kuala_Lumpur", 2.7456, 101.7099),
    "PEN": ("Penang International Airport", "Penang", "MY", "Asia/Kuala_Lumpur", 5.2971, 100.2767),
    "LGK": ("Langkawi International Airport", "Langkawi", "MY", "Asia/Kuala_Lumpur", 6.3297, 99.7287),
    "DPS": ("Ngurah Rai International Airport", "Bali", "ID", "Asia/Makassar", -8.7482, 115.1675),
    "CGK": ("Soekarno-Hatta International Airport", "Jakarta", "ID", "Asia/Jakarta", -6.1256, 106.6559),
    "YIA": ("Yogyakarta International Airport", "Yogyakarta", "ID", "Asia/Jakarta", -7.9, 110.0569),
    "HAN": ("Noi Bai International Airport", "Hanoi", "VN", "Asia/Ho_Chi_Minh", 21.2212, 105.8072),
    "DAD": ("Da Nang International Airport", "Da Nang", "VN", "Asia/Ho_Chi_Minh", 16.0439, 108.1994),
    "SGN": ("Tan Son Nhat International Airport", "Ho Chi Minh City", "VN", "Asia/Ho_Chi_Minh", 10.8188, 106.6519),
}
AIRPORT_SHORT = {"BKK": "Suvarnabhumi", "DMK": "Don Mueang", "HKT": "Phuket airport", "CNX": "Chiang Mai airport",
                 "SIN": "Changi", "KUL": "KLIA", "PEN": "Penang airport", "LGK": "Langkawi airport",
                 "DPS": "Ngurah Rai", "CGK": "Soekarno-Hatta", "YIA": "Yogyakarta airport", "HAN": "Noi Bai",
                 "DAD": "Da Nang airport", "SGN": "Tan Son Nhat"}
# typical airport -> city-centre ride in minutes (hotel areas add a little)
AIRPORT_RIDE = {"BKK": 55, "DMK": 45, "HKT": 55, "CNX": 20, "SIN": 30, "KUL": 55, "PEN": 25, "LGK": 20,
                "DPS": 40, "CGK": 55, "YIA": 70, "HAN": 50, "DAD": 20, "SGN": 35}

# ---- flights: airport -> {origin: (direct minutes, probability a flight has one stop, flights per day)}
ROUTES = {
    "BKK": {"BLR": (245, .10, 1.1), "DEL": (255, .10, 1.2), "BOM": (285, .15, 1.0), "MAA": (215, .10, .9)},
    "DMK": {"DEL": (260, .20, .7), "BOM": (290, .30, .6)},
    "HKT": {"BLR": (270, .45, .6), "DEL": (300, .55, .5), "BOM": (300, .50, .5), "MAA": (230, .20, .7)},
    "CNX": {"BLR": (330, .90, .5), "DEL": (270, .40, .5), "BOM": (330, .70, .4), "MAA": (290, .60, .4)},
    "SIN": {"BLR": (270, .05, 1.2), "DEL": (340, .10, 1.0), "BOM": (340, .10, 1.0), "MAA": (245, .05, 1.0)},
    "KUL": {"BLR": (260, .05, 1.1), "DEL": (330, .10, 1.0), "BOM": (320, .15, .8), "MAA": (240, .05, 1.0)},
    "PEN": {"BLR": (280, .70, .5), "MAA": (230, .20, .6), "DEL": (360, .85, .4)},
    "LGK": {"BLR": (330, .90, .4), "MAA": (270, .60, .4)},
    "DPS": {"BLR": (400, .30, .7), "DEL": (480, .50, .6), "BOM": (450, .45, .6), "MAA": (380, .30, .5)},
    "CGK": {"BLR": (320, .10, .9), "DEL": (400, .20, .8), "BOM": (380, .25, .7), "MAA": (295, .10, .7)},
    "YIA": {"BLR": (440, .90, .4), "DEL": (500, .95, .3)},
    "HAN": {"DEL": (285, .05, .9), "BLR": (345, .30, .6), "BOM": (360, .35, .6), "MAA": (345, .35, .5)},
    "DAD": {"BLR": (385, .85, .4), "DEL": (330, .60, .5)},
    "SGN": {"BLR": (285, .05, .9), "DEL": (330, .10, .8), "BOM": (330, .15, .7), "MAA": (270, .05, .8)},
}
AIRLINES = {
    "TH": [("Lotus Airways", "LW"), ("Sandline Airways", "SL"), ("AirVeda", "AV"), ("Siam Jet", "SJ")],
    "SG": [("Merlion Air", "MA"), ("AirVeda", "AV"), ("Sandline Airways", "SL")],
    "MY": [("Orchid Air", "OA"), ("AirVeda", "AV"), ("Sandline Airways", "SL")],
    "ID": [("Islander Air", "IA"), ("AirVeda", "AV"), ("Coral Jet", "CJ")],
    "VN": [("Mekong Wings", "MW"), ("AirVeda", "AV"), ("Coral Jet", "CJ")],
}
OUT_SLOTS = ["00:30", "02:15", "04:40", "06:30", "08:10", "10:20", "12:45", "15:30", "18:50", "21:10", "22:45", "23:50"]
BACK_SLOTS = ["01:30", "04:20", "06:15", "08:30", "10:40", "12:10", "14:50", "17:30", "20:20", "22:35", "23:55"]

# ---- hotels
HOTEL_ADJ = ["Pearl", "Orchid", "Lotus", "Garden", "Grand", "Heritage", "Skyline", "Riverside", "Palm", "Lagoon", "Jade",
             "Coral", "Sunrise", "Harbour", "Bamboo", "Golden", "Silk", "Monsoon", "Emerald", "Tropic", "Moonlight",
             "Banyan", "Frangipani", "Teak"]
HOTEL_KINDS = {2: ["Inn", "Lodge", "Guesthouse", "Hostel"], 3: ["Hotel", "Residency", "Suites", "Inn"],
               4: ["Hotel", "Suites", "Boutique Hotel", "Residence"], 5: ["Grand Hotel", "Resort", "Palace Hotel", "Residences"]}
HOTEL_IMAGES = {5: ["images/hotels/HOTEL-LUXURY-1.jpg", "images/hotels/HOTEL-LUXURY-2.jpg"],
                4: ["images/hotels/HOTEL-BUSINESS-1.jpg", "images/hotels/HOTEL-BUSINESS-2.jpg"],
                3: ["images/hotels/HOTEL-TWIN-1.jpg", "images/hotels/HOTEL-TWIN-2.jpg"],
                2: ["images/hotels/HOTEL-CAPSULE-1.jpg", "images/hotels/HOTEL-TWIN-2.jpg"]}
FAMILY_IMAGE = "images/hotels/HOTEL-FAMILY-1.jpg"
# capacity of ONE room: type -> (max_adults, max_children, price factor, display name)
ROOM_TYPES = {"SINGLE": (1, 0, .6, "Single Room"), "TWIN": (2, 0, 1.0, "Twin Room"),
              "DOUBLE": (2, 0, 1.05, "Double Room"), "TRIPLE": (3, 0, 1.5, "Triple Room"),
              "FAMILY": (2, 2, 1.7, "Family Room"), "FAMILY_SUITE": (4, 2, 3.0, "Family Suite")}
STAR_FACTOR = {2: .55, 3: 1.0, 4: 1.8, 5: 3.4}
# whole-city events: nights when most rooms in the listed cities are sold out (flights still exist)
SOLD_OUT_EVENTS = [
    ("Songkran holiday", ["Bangkok", "Chiang Mai", "Phuket"], "2027-04-12", "2027-04-16", .75),
    ("Ubud festival", ["Bali"], "2027-04-07", "2027-04-10", .8),
]

# ---- intercity links: (from, to, [services]); service = (kind, name, from_point, to_point, minutes, window,
#      frequency or None, adult price, child price or None, max_passengers, door_to_door or None)
def _svc(kind, label, fp, tp, mins, win, freq, price, child, cap=99, d2d=None):
    return dict(kind=kind, label=label, fp=fp, tp=tp, mins=mins, win=win, freq=freq, price=price, child=child,
                cap=cap, d2d=d2d)


def _pair(country, a, b, services):
    return [(country, a, b, services), (country, b, a, [dict(s, fp=s["tp"], tp=s["fp"]) for s in services])]


INTERCITY = (
    _pair("TH", "Bangkok", "Chiang Mai", [
        _svc("TRAIN", "Day train", "Krung Thep Aphiwat Central Terminal", "Chiang Mai Railway Station", 705, ("06:00", "19:30"), 90, 2210, 1105),
        _svc("INTERCITY_BUS", "Intercity bus", "Mo Chit bus terminal", "Chiang Mai Arcade bus terminal", 600, ("07:00", "21:00"), 60, 1385, 830)])
    + _pair("TH", "Bangkok", "Phuket", [
        _svc("INTERCITY_BUS", "Intercity bus", "Southern bus terminal", "Phuket bus terminal 2", 720, ("06:00", "19:00"), 120, 1960, 1180)])
    + _pair("MY", "Kuala Lumpur", "Penang", [
        _svc("TRAIN", "ETS train", "KL Sentral", "Butterworth station", 240, ("06:00", "21:00"), 120, 1480, 740),
        _svc("INTERCITY_BUS", "Intercity bus", "TBS bus terminal", "Sungai Nibong bus terminal", 270, ("06:00", "23:30"), 30, 920, 550),
        _svc("INTERCITY_TAXI", "Intercity taxi (hotel to hotel)", "Kuala Lumpur hotels", "Penang hotels", 240, ("00:00", "24:00"), None, 17800, None, 4, True)])
    + _pair("ID", "Jakarta", "Yogyakarta", [
        _svc("TRAIN", "Executive train", "Gambir station", "Yogyakarta Tugu station", 480, ("06:00", "20:00"), 120, 2590, 1295),
        _svc("INTERCITY_BUS", "Intercity bus", "Pulo Gebang terminal", "Giwangan terminal", 600, ("05:00", "21:00"), 60, 1320, 790)])
    + _pair("VN", "Hanoi", "Da Nang", [
        _svc("TRAIN", "Reunification Express", "Hanoi railway station", "Da Nang railway station", 900, ("06:00", "19:30"), 90, 3100, 1550),
        _svc("INTERCITY_BUS", "Sleeper bus", "My Dinh bus station", "Da Nang bus station", 780, ("17:00", "21:30"), 60, 1650, 990)])
    + _pair("VN", "Da Nang", "Ho Chi Minh City", [
        _svc("TRAIN", "Reunification Express", "Da Nang railway station", "Saigon railway station", 1000, ("06:00", "18:00"), 120, 3550, 1775),
        _svc("INTERCITY_BUS", "Sleeper bus", "Da Nang bus station", "Mien Dong bus station", 1020, ("16:00", "20:30"), 60, 1990, 1190)])
)
TRANSFER_CODES = {"TRAIN": "TRN", "INTERCITY_BUS": "BUS", "INTERCITY_TAXI": "TAXI"}

# ---- attractions: city name -> rows
# (name, category, lat, lng, days, open, close, minutes, adult INR, child INR | None = same price, child friendly, accessible)
D_ALL = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
DAYS = {"all": D_ALL, "noMon": D_ALL[1:], "noTue": [d for d in D_ALL if d != "TUE"], "noFri": [d for d in D_ALL if d != "FRI"],
        "noMonFri": [d for d in D_ALL if d not in ("MON", "FRI")], "satSun": ["SAT", "SUN"], "sun": ["SUN"],
        "wedSun": D_ALL[2:], "friSun": D_ALL[4:], "noSun": D_ALL[:6]}
ATTRACTIONS = {
    "Bangkok": [
        ("Grand Palace", "PALACE", 13.75, 100.4913, "all", "08:30", "15:30", 180, 1300, 0, True, False),
        ("Wat Pho", "TEMPLE", 13.7465, 100.493, "all", "08:00", "18:30", 90, 650, None, True, True),
        ("Wat Arun", "TEMPLE", 13.7437, 100.4889, "all", "08:00", "18:00", 60, 330, None, True, False),
        ("Chatuchak Weekend Market", "MARKET", 13.7999, 100.5502, "satSun", "09:00", "18:00", 150, 0, None, True, True),
        ("Jim Thompson House", "MUSEUM", 13.7492, 100.5284, "all", "09:00", "18:00", 90, 520, 260, True, True),
        ("Lumphini Park", "PARK", 13.7314, 100.5414, "all", "05:00", "21:00", 60, 0, None, True, True),
        ("Chao Phraya Sunset Cruise", "VIEWPOINT", 13.7236, 100.5136, "all", "17:00", "22:00", 120, 2900, 1800, True, True),
        ("Bangkok National Museum", "MUSEUM", 13.7578, 100.4924, "wedSun", "09:00", "16:00", 90, 250, 0, False, True),
        ("SEA LIFE Bangkok Ocean World", "AQUARIUM", 13.7465, 100.5349, "all", "10:00", "20:00", 150, 1900, 1400, True, True),
        ("Asiatique The Riverfront", "MARKET", 13.7041, 100.5039, "all", "16:00", "23:30", 120, 0, None, True, True),
        ("Erawan Shrine", "SHRINE", 13.7444, 100.5403, "all", "06:00", "23:00", 30, 0, None, True, True),
        ("Golden Mount at Wat Saket", "VIEWPOINT", 13.7536, 100.5066, "all", "07:30", "19:00", 60, 130, None, False, False),
    ],
    "Phuket": [
        ("Big Buddha Phuket", "MONUMENT", 7.8278, 98.3139, "all", "08:00", "19:00", 60, 0, None, True, False),
        ("Wat Chalong", "TEMPLE", 7.8461, 98.3374, "all", "07:00", "17:00", 60, 0, None, True, True),
        ("Old Phuket Town Walk", "DISTRICT", 7.8847, 98.3881, "all", "00:00", "24:00", 120, 0, None, True, True),
        ("Phi Phi Islands Day Trip", "NATURE", 7.7407, 98.7784, "noSun", "08:00", "17:00", 480, 4800, 3200, True, False),
        ("Promthep Cape Sunset Point", "VIEWPOINT", 7.7619, 98.3053, "all", "16:00", "20:00", 60, 0, None, True, True),
        ("Patong Beach", "BEACH", 7.8961, 98.2965, "all", "00:00", "24:00", 150, 0, None, True, True),
        ("Phuket Aquarium", "AQUARIUM", 7.8007, 98.4021, "all", "09:00", "16:30", 90, 600, 300, True, True),
        ("Kata Beach", "BEACH", 7.8208, 98.2978, "all", "00:00", "24:00", 150, 0, None, True, True),
        ("Sirinat National Park", "NATURE", 8.1, 98.2999, "all", "06:00", "18:00", 120, 330, 160, True, False),
        ("Naka Weekend Market", "MARKET", 7.8704, 98.3719, "satSun", "16:00", "22:00", 90, 0, None, True, True),
        ("Thai Cooking Class", "MUSEUM", 7.8885, 98.3893, "noSun", "09:00", "13:00", 240, 2800, 1900, True, True),
    ],
    "Chiang Mai": [
        ("Wat Phra That Doi Suthep", "TEMPLE", 18.8049, 98.9215, "all", "06:00", "18:00", 120, 270, 130, True, False),
        ("Wat Phra Singh", "TEMPLE", 18.7881, 98.9822, "all", "08:00", "17:00", 60, 0, None, True, True),
        ("Old City Walk", "DISTRICT", 18.7883, 98.9853, "all", "00:00", "24:00", 120, 0, None, True, True),
        ("Sunday Walking Street", "MARKET", 18.7878, 98.9887, "sun", "16:00", "23:00", 120, 0, None, True, True),
        ("Elephant Nature Park", "NATURE", 19.0, 98.9667, "all", "08:00", "17:00", 360, 5600, 2800, True, False),
        ("Chiang Mai Night Bazaar", "MARKET", 18.7871, 99.0003, "all", "17:00", "23:30", 90, 0, None, True, True),
        ("Doi Inthanon National Park", "NATURE", 18.5858, 98.4868, "all", "06:00", "18:00", 480, 650, 330, True, False),
        ("Wat Chedi Luang", "TEMPLE", 18.7869, 98.9867, "all", "06:00", "18:00", 60, 130, None, True, True),
        ("Three Kings Monument", "MONUMENT", 18.7903, 98.9919, "all", "00:00", "24:00", 30, 0, None, True, True),
        ("Chiang Mai Zoo", "PARK", 18.8, 98.9494, "all", "08:00", "17:00", 180, 600, 300, True, True),
        ("Lanna Folklife Museum", "MUSEUM", 18.7889, 98.9871, "noMon", "08:30", "17:00", 90, 330, 0, True, True),
        ("Bua Thong Sticky Waterfalls", "NATURE", 19.0214, 98.9456, "all", "08:00", "17:00", 90, 0, None, True, False),
    ],
    "Singapore": [
        ("Gardens by the Bay", "PARK", 1.2816, 103.8636, "all", "09:00", "21:00", 150, 2200, 1500, True, True),
        ("Marina Bay Sands SkyPark", "VIEWPOINT", 1.2834, 103.8607, "all", "11:00", "21:00", 60, 2100, 1700, True, True),
        ("Singapore Zoo", "PARK", 1.4043, 103.793, "all", "08:30", "18:00", 240, 2700, 1750, True, True),
        ("Night Safari", "NATURE", 1.4025, 103.7895, "all", "19:30", "24:00", 150, 3100, 2100, True, True),
        ("Universal Studios Singapore", "THEME_PARK", 1.2540, 103.8238, "all", "10:00", "19:00", 480, 6500, 4900, True, True),
        ("S.E.A. Aquarium", "AQUARIUM", 1.2582, 103.8203, "all", "10:00", "17:00", 180, 3000, 2200, True, True),
        ("Singapore Botanic Gardens", "PARK", 1.3138, 103.8159, "all", "05:00", "24:00", 120, 0, None, True, True),
        ("Merlion Park", "MONUMENT", 1.2868, 103.8545, "all", "00:00", "24:00", 30, 0, None, True, True),
        ("Chinatown Complex Market", "MARKET", 1.2822, 103.8436, "all", "10:00", "21:00", 90, 0, None, True, True),
        ("National Gallery Singapore", "MUSEUM", 1.2903, 103.8515, "all", "10:00", "19:00", 120, 1600, 0, True, True),
        ("ArtScience Museum", "MUSEUM", 1.2863, 103.8593, "all", "10:00", "19:00", 150, 2400, 1700, True, True),
        ("Sultan Mosque", "MOSQUE", 1.3022, 103.8587, "noFri", "10:00", "16:00", 45, 0, None, False, True),
        ("Buddha Tooth Relic Temple", "TEMPLE", 1.2815, 103.8444, "all", "07:00", "19:00", 60, 0, None, True, True),
        ("Siloso Beach Sentosa", "BEACH", 1.2563, 103.8118, "all", "00:00", "24:00", 150, 0, None, True, True),
        ("Little India Arcade", "DISTRICT", 1.3067, 103.8512, "all", "10:00", "22:00", 90, 0, None, True, True),
    ],
    "Kuala Lumpur": [
        ("Petronas Twin Towers Observation Deck", "VIEWPOINT", 3.1579, 101.7116, "noMon", "09:00", "21:30", 90, 1900, 1100, True, True),
        ("Batu Caves", "TEMPLE", 3.2379, 101.684, "all", "07:00", "19:00", 120, 0, None, True, False),
        ("KL Tower", "VIEWPOINT", 3.1528, 101.7036, "all", "09:00", "22:00", 60, 1200, 700, True, True),
        ("Central Market", "MARKET", 3.1450, 101.6958, "all", "10:00", "21:00", 90, 0, None, True, True),
        ("Jalan Alor Food Street", "MARKET", 3.1459, 101.7078, "all", "17:00", "24:00", 120, 0, None, True, True),
        ("National Mosque", "MOSQUE", 3.1423, 101.6917, "noFri", "09:00", "16:00", 45, 0, None, False, True),
        ("Islamic Arts Museum Malaysia", "MUSEUM", 3.1426, 101.6914, "all", "10:00", "18:00", 120, 700, 350, True, True),
        ("Perdana Botanical Garden", "PARK", 3.1428, 101.6866, "all", "07:00", "20:00", 90, 0, None, True, True),
        ("KL Bird Park", "NATURE", 3.1431, 101.6881, "all", "09:00", "18:00", 120, 1050, 650, True, True),
        ("Aquaria KLCC", "AQUARIUM", 3.1537, 101.7127, "all", "10:00", "20:00", 120, 1100, 800, True, True),
        ("Merdeka Square", "MONUMENT", 3.1478, 101.6939, "all", "00:00", "24:00", 45, 0, None, True, True),
        ("Thean Hou Temple", "TEMPLE", 3.1197, 101.6869, "all", "09:00", "18:00", 45, 0, None, True, False),
    ],
    "Penang": [
        ("George Town Street Art Walk", "DISTRICT", 5.4141, 100.3379, "all", "00:00", "24:00", 120, 0, None, True, True),
        ("Kek Lok Si Temple", "TEMPLE", 5.3989, 100.2733, "all", "08:30", "17:30", 90, 0, None, True, False),
        ("Penang Hill Funicular", "VIEWPOINT", 5.4256, 100.2693, "all", "06:30", "23:00", 150, 250, 120, True, True),
        ("Khoo Kongsi Clan House", "MUSEUM", 5.4145, 100.3367, "all", "09:00", "17:00", 60, 330, 160, True, True),
        ("Fort Cornwallis", "CASTLE", 5.4204, 100.3436, "all", "09:00", "18:00", 60, 190, 90, True, True),
        ("Batu Ferringhi Night Market", "MARKET", 5.4741, 100.2443, "all", "18:00", "23:30", 90, 0, None, True, True),
        ("Penang Botanic Gardens", "PARK", 5.4382, 100.2897, "all", "05:00", "20:00", 90, 0, None, True, True),
        ("Entopia Butterfly Farm", "NATURE", 5.4592, 100.2308, "all", "09:00", "17:00", 120, 1050, 700, True, True),
        ("Chew Jetty", "DISTRICT", 5.4136, 100.3402, "all", "08:00", "21:00", 60, 0, None, True, True),
        ("Pinang Peranakan Mansion", "MUSEUM", 5.4175, 100.3358, "noMon", "09:30", "17:00", 90, 380, 190, True, True),
    ],
    "Langkawi": [
        ("Langkawi Sky Bridge", "VIEWPOINT", 6.3866, 99.6643, "noMon", "09:30", "19:00", 120, 1100, 700, True, False),
        ("Pantai Cenang Beach", "BEACH", 6.2925, 99.7273, "all", "00:00", "24:00", 150, 0, None, True, True),
        ("Langkawi Cable Car", "VIEWPOINT", 6.3849, 99.6684, "all", "10:00", "18:30", 90, 950, 650, True, True),
        ("Eagle Square", "MONUMENT", 6.3159, 99.8575, "all", "00:00", "24:00", 30, 0, None, True, True),
        ("Underwater World Langkawi", "AQUARIUM", 6.2967, 99.7272, "all", "10:00", "18:00", 120, 650, 420, True, True),
        ("Kilim Karst Mangrove Tour", "NATURE", 6.4, 99.8667, "all", "09:00", "16:00", 240, 1800, 1200, True, False),
        ("Telaga Tujuh Waterfalls", "NATURE", 6.3917, 99.6697, "all", "08:00", "18:00", 90, 0, None, True, False),
        ("Oriental Village", "MARKET", 6.3849, 99.6706, "all", "09:00", "19:00", 90, 0, None, True, True),
        ("Pantai Tengah Beach", "BEACH", 6.2822, 99.7297, "all", "00:00", "24:00", 150, 0, None, True, True),
        ("Laman Padi Rice Museum", "MUSEUM", 6.3, 99.7167, "all", "09:00", "18:00", 60, 190, 90, True, True),
    ],
    "Bali": [
        ("Uluwatu Temple", "TEMPLE", -8.8291, 115.0849, "all", "07:00", "19:00", 90, 450, 230, True, False),
        ("Tanah Lot Temple", "TEMPLE", -8.6212, 115.0868, "all", "07:00", "19:00", 90, 340, 170, True, True),
        ("Sacred Monkey Forest Sanctuary", "NATURE", -8.5189, 115.2588, "all", "08:30", "18:00", 90, 440, 290, True, True),
        ("Tegallalang Rice Terrace", "NATURE", -8.4312, 115.2793, "all", "08:00", "18:00", 120, 130, None, True, False),
        ("Ubud Royal Palace", "PALACE", -8.5069, 115.2625, "all", "08:00", "18:00", 60, 0, None, True, True),
        ("Ubud Art Market", "MARKET", -8.5072, 115.2622, "all", "08:00", "18:00", 90, 0, None, True, True),
        ("Kuta Beach", "BEACH", -8.7184, 115.1686, "all", "00:00", "24:00", 150, 0, None, True, True),
        ("Tirta Empul Temple", "TEMPLE", -8.4153, 115.3153, "all", "08:00", "18:00", 90, 270, 140, True, False),
        ("Garuda Wisnu Kencana Cultural Park", "PARK", -8.8103, 115.1672, "all", "09:00", "21:00", 150, 940, 640, True, True),
        ("Bali Museum", "MUSEUM", -8.6559, 115.2166, "noMon", "08:00", "17:00", 90, 190, 100, True, True),
        ("Jimbaran Bay Seafood Beach", "BEACH", -8.7845, 115.1625, "all", "16:00", "23:00", 120, 0, None, True, True),
    ],
    "Jakarta": [
        ("National Monument (Monas)", "MONUMENT", -6.1754, 106.8272, "noMon", "08:00", "16:00", 90, 130, 60, True, True),
        ("Kota Tua Old Town", "DISTRICT", -6.1352, 106.8133, "all", "08:00", "21:00", 120, 0, None, True, True),
        ("Jakarta History Museum", "MUSEUM", -6.1352, 106.8133, "noMon", "09:00", "17:00", 90, 60, 30, True, True),
        ("Istiqlal Mosque", "MOSQUE", -6.1702, 106.8312, "all", "08:00", "18:00", 60, 0, None, False, True),
        ("Ancol Dreamland", "THEME_PARK", -6.1255, 106.8426, "all", "06:00", "22:00", 360, 1100, 800, True, True),
        ("Taman Mini Indonesia Indah", "PARK", -6.3025, 106.8951, "all", "08:00", "17:00", 240, 120, 60, True, True),
        ("Sunda Kelapa Harbour", "DISTRICT", -6.1217, 106.8078, "all", "09:00", "17:00", 60, 40, None, True, False),
        ("Ragunan Zoo", "PARK", -6.3126, 106.82, "noMon", "07:00", "16:00", 180, 40, 20, True, True),
        ("National Museum of Indonesia", "MUSEUM", -6.1763, 106.8219, "noMon", "08:30", "16:00", 120, 40, 0, True, True),
        ("Grand Indonesia Skyline Deck", "VIEWPOINT", -6.1953, 106.8199, "all", "10:00", "22:00", 60, 500, 300, True, True),
    ],
    "Yogyakarta": [
        ("Borobudur Temple", "TEMPLE", -7.6079, 110.2038, "all", "06:30", "17:00", 150, 1900, 950, True, False),
        ("Prambanan Temple", "TEMPLE", -7.752, 110.4914, "all", "06:30", "17:00", 120, 1600, 800, True, True),
        ("Kraton Yogyakarta Palace", "PALACE", -7.8052, 110.3642, "noFri", "08:30", "14:00", 90, 190, 100, True, True),
        ("Taman Sari Water Castle", "CASTLE", -7.8100, 110.3594, "all", "09:00", "15:30", 60, 100, None, True, False),
        ("Malioboro Street", "MARKET", -7.7928, 110.3656, "all", "08:00", "22:00", 90, 0, None, True, True),
        ("Sonobudoyo Museum", "MUSEUM", -7.8003, 110.3653, "noMon", "08:00", "16:00", 90, 40, 20, True, True),
        ("Mount Merapi Sunrise Jeep Tour", "NATURE", -7.5407, 110.4457, "all", "05:00", "11:00", 240, 2800, 2100, True, False),
        ("Ratu Boko Sunset Plateau", "VIEWPOINT", -7.7704, 110.4888, "all", "06:00", "17:00", 90, 560, 280, True, False),
        ("Parangtritis Beach", "BEACH", -8.0256, 110.3317, "all", "00:00", "24:00", 150, 0, None, True, True),
        ("Beringharjo Market", "MARKET", -7.7986, 110.3656, "all", "09:00", "17:00", 90, 0, None, True, True),
    ],
    "Hanoi": [
        ("Hoan Kiem Lake", "PARK", 21.0288, 105.8523, "all", "00:00", "24:00", 60, 0, None, True, True),
        ("Temple of Literature", "TEMPLE", 21.0277, 105.8355, "all", "08:00", "17:00", 90, 190, 0, True, True),
        ("Ho Chi Minh Mausoleum", "MONUMENT", 21.0368, 105.8346, "noMonFri", "07:30", "10:30", 60, 0, None, False, True),
        ("Old Quarter Walking Tour", "DISTRICT", 21.0345, 105.8501, "all", "00:00", "24:00", 150, 0, None, True, True),
        ("Hoa Lo Prison Museum", "MUSEUM", 21.0254, 105.8468, "all", "08:00", "17:00", 90, 130, 60, False, True),
        ("Vietnam Museum of Ethnology", "MUSEUM", 21.0399, 105.7983, "noMon", "08:30", "17:30", 120, 190, 0, True, True),
        ("Tran Quoc Pagoda", "TEMPLE", 21.0482, 105.8365, "all", "08:00", "18:00", 60, 0, None, True, True),
        ("Thang Long Water Puppet Theatre", "MUSEUM", 21.0309, 105.8523, "all", "17:00", "21:00", 60, 650, 450, True, True),
        ("Dong Xuan Market", "MARKET", 21.0384, 105.8497, "all", "06:00", "18:00", 90, 0, None, True, True),
        ("Long Bien Bridge", "MONUMENT", 21.0442, 105.8587, "all", "00:00", "24:00", 45, 0, None, True, False),
        ("Imperial Citadel of Thang Long", "CASTLE", 21.0371, 105.8403, "noMon", "08:00", "17:00", 90, 280, 0, True, True),
    ],
    "Da Nang": [
        ("Marble Mountains", "NATURE", 16.0036, 108.2638, "all", "07:00", "17:30", 120, 330, 160, True, False),
        ("Dragon Bridge", "MONUMENT", 16.0612, 108.2279, "all", "00:00", "24:00", 60, 0, None, True, True),
        ("Ba Na Hills and Golden Bridge", "THEME_PARK", 15.9977, 107.9886, "all", "08:00", "17:00", 360, 3800, 3100, True, True),
        ("My Khe Beach", "BEACH", 16.0544, 108.2478, "all", "00:00", "24:00", 150, 0, None, True, True),
        ("Linh Ung Pagoda and Lady Buddha", "TEMPLE", 16.1006, 108.2778, "all", "06:00", "18:00", 90, 0, None, True, False),
        ("Museum of Cham Sculpture", "MUSEUM", 16.0603, 108.2237, "all", "07:00", "17:00", 90, 190, 0, True, True),
        ("Han Market", "MARKET", 16.0687, 108.2243, "all", "06:00", "19:00", 90, 0, None, True, True),
        ("Son Tra Peninsula Viewpoint", "VIEWPOINT", 16.1203, 108.2916, "all", "06:00", "18:00", 120, 0, None, True, False),
        ("Asia Park Sun Wheel", "THEME_PARK", 16.0397, 108.2268, "all", "15:00", "22:00", 180, 1250, 850, True, True),
        ("Helio Night Market", "MARKET", 16.0481, 108.2174, "friSun", "17:00", "23:00", 90, 0, None, True, True),
    ],
    "Ho Chi Minh City": [
        ("War Remnants Museum", "MUSEUM", 10.7794, 106.6922, "all", "07:30", "17:30", 90, 130, 0, False, True),
        ("Saigon Central Post Office", "MONUMENT", 10.7798, 106.6999, "all", "07:00", "18:00", 30, 0, None, True, True),
        ("Ben Thanh Market", "MARKET", 10.7725, 106.698, "all", "06:00", "19:00", 90, 0, None, True, True),
        ("Independence Palace", "PALACE", 10.777, 106.6955, "all", "08:00", "16:00", 90, 190, 0, True, True),
        ("Cu Chi Tunnels Half-Day Tour", "MUSEUM", 11.1428, 106.4617, "all", "07:00", "17:00", 300, 1650, 1100, True, False),
        ("Jade Emperor Pagoda", "TEMPLE", 10.7918, 106.6983, "all", "07:30", "18:00", 60, 0, None, True, True),
        ("Bui Vien Walking Street", "DISTRICT", 10.7677, 106.6935, "all", "17:00", "24:00", 120, 0, None, False, True),
        ("Saigon Skydeck", "VIEWPOINT", 10.7717, 106.7043, "all", "09:30", "21:30", 60, 950, 650, True, True),
        ("Mekong Delta Day Tour", "NATURE", 10.3604, 106.3601, "noSun", "08:00", "17:00", 480, 2400, 1600, True, False),
        ("Ho Chi Minh City Museum", "MUSEUM", 10.7766, 106.7013, "all", "08:00", "16:30", 90, 130, 60, True, True),
        ("Saigon Central Park Walk", "PARK", 10.7869, 106.7005, "all", "05:00", "22:00", 90, 0, None, True, True),
    ],
}
