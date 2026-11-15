"""Reference data. Every company, broker and insurer name here is fictional."""

from __future__ import annotations

from dataclasses import dataclass

TOWNS: list[tuple[str, str, list[int]]] = [
    ("Leeds", "LS", [1, 2, 9, 10, 11, 12]),
    ("Manchester", "M", [1, 4, 12, 17, 40]),
    ("Birmingham", "B", [4, 6, 7, 11, 18]),
    ("Bristol", "BS", [1, 2, 3, 11, 16]),
    ("Sheffield", "S", [3, 4, 9, 13]),
    ("Nottingham", "NG", [1, 2, 7, 16]),
    ("Leicester", "LE", [1, 3, 4, 19]),
    ("Glasgow", "G", [2, 3, 5, 40]),
    ("Cardiff", "CF", [10, 11, 24]),
    ("Reading", "RG", [1, 2, 7, 30]),
    ("Coventry", "CV", [1, 3, 6]),
    ("Hull", "HU", [1, 2, 9]),
    ("Southampton", "SO", [14, 15, 16]),
    ("Northampton", "NN", [1, 3, 4, 5]),
    ("Peterborough", "PE", [1, 2, 7]),
    ("Preston", "PR", [1, 2, 5]),
    ("Derby", "DE", [1, 21, 24]),
    ("Stoke-on-Trent", "ST", [1, 4, 6]),
    ("Bradford", "BD", [1, 3, 4]),
    ("Norwich", "NR", [1, 3, 6]),
]

POSTCODE_LETTERS = "ABDEFGHJLNPQRSTUWXYZ"

STREET_NAMES = [
    "Station", "Mill", "Canal", "Victoria", "Albert", "Church", "Bridge", "Wharf",
    "Foundry", "Kingsway", "Holbeck", "Clarence", "Sovereign", "Brunel", "Riverside",
    "Hawthorn", "Gelderd", "Stanningley", "Tyburn", "Armley", "Ropewalk", "Tannery",
]
STREET_TYPES = ["Road", "Street", "Lane", "Way", "Avenue", "Close", "Drive"]
ESTATE_NAMES = [
    "Kirkstall", "Aire Valley", "Tameside", "Meridian", "Fosse", "Severnside", "Calder",
    "Trent Vale", "Brindley", "Phoenix", "Centurion", "Waterside", "Ashfield",
]
ESTATE_TYPES = ["Industrial Estate", "Business Park", "Trading Estate", "Enterprise Park"]

COMPANY_WORDS = [
    "Pennine", "Calder", "Brindley", "Harrow", "Kestrel", "Ashdown", "Mercia", "Oakridge",
    "Thornbury", "Halcyon", "Fenwick", "Wolds", "Severn", "Granite", "Northlight",
    "Bramwell", "Cotswold", "Ridgeway", "Hartley", "Lindum", "Ellery", "Corran",
]
COMPANY_SUFFIXES = ["Ltd", "Limited", "Ltd", "Ltd", "Group Ltd", "& Sons Ltd"]

FIRST_NAMES = [
    "Sarah", "James", "Priya", "Tom", "Aisha", "Gareth", "Helen", "Mark", "Fiona", "Dev",
    "Claire", "Rob", "Nadia", "Steve", "Laura", "Kwame", "Emma", "Paul", "Rachel", "Imran",
]
LAST_NAMES = [
    "Whitfield", "Okafor", "Patel", "Brennan", "Hughes", "Kowalski", "Marsden", "Ahmed",
    "Lowther", "Sinclair", "Dobson", "Achterberg", "Reilly", "Thornton", "Mensah", "Clegg",
]

BROKER_FIRMS = [
    ("Halden & Pryce Insurance Brokers", "haldenpryce.co.uk"),
    ("Carrow Risk Partners", "carrowrisk.co.uk"),
    ("Wexcombe Insurance Services", "wexcombe.co.uk"),
    ("Morland Broking", "morlandbroking.co.uk"),
]

INSURERS = [
    "Albion Mutual", "Northgate Insurance plc", "Harbourline Specialty", "Meridian General",
    "Castlegate Underwriting", "Fernhill Assurance", "Saltire Commercial", "Eastwick Re & General",
]

CONSTRUCTION = [
    ("Brick/slate", 5),
    ("Brick walls, steel truss roof", 4),
    ("Steel frame, composite panel", 3),
    ("Steel frame, brick infill", 3),
    ("Concrete frame", 2),
    ("Timber frame", 1),
]

PACKAGING = [
    "Palletised and shrink-wrapped",
    "Cartons on pallets",
    "Crated",
    "Refrigerated containers",
    "Bulk bags",
]

GEO_LIMITS = [
    "UK only",
    "UK & EU",
    "UK, Europe and Turkey",
    "Worldwide excl. sanctioned territories",
]

CLAIM_CAUSES = {
    "property": [
        ("Escape of water", (1_500, 45_000)),
        ("Fire", (8_000, 250_000)),
        ("Theft", (1_000, 30_000)),
        ("Storm damage", (2_000, 40_000)),
        ("Accidental damage", (500, 12_000)),
        ("Flood", (10_000, 180_000)),
        ("Malicious damage", (700, 9_000)),
    ],
    "cyber": [
        ("Business email compromise", (5_000, 90_000)),
        ("Ransomware", (20_000, 300_000)),
        ("Data breach", (3_000, 60_000)),
        ("System outage", (2_000, 25_000)),
    ],
    "cargo": [
        ("Theft in transit", (3_000, 80_000)),
        ("Wet damage", (1_000, 25_000)),
        ("Handling damage", (500, 15_000)),
        ("Vehicle overturned", (5_000, 60_000)),
    ],
}


@dataclass(frozen=True)
class Trade:
    description: str
    noun: str
    occupancies: tuple[str, ...]
    lines: tuple[str, ...]
    revenue: tuple[int, int]
    employees: tuple[int, int]
    commodities: str = ""


TRADES = [
    Trade("Food wholesaler", "Foods", ("Warehouse & distribution", "Cold store", "Offices"),
          ("property", "cargo"), (2_000_000, 25_000_000), (12, 140), "Chilled and ambient foodstuffs"),
    Trade("Precision engineering", "Engineering", ("Light engineering workshop", "Machine shop", "Offices"),
          ("property", "cargo"), (1_500_000, 18_000_000), (10, 120), "Machined metal components"),
    Trade("Furniture manufacturer", "Furniture", ("Woodworking factory", "Showroom", "Warehouse"),
          ("property", "cargo"), (1_200_000, 15_000_000), (15, 160), "Flat-pack and assembled furniture"),
    Trade("Commercial printer", "Print", ("Print works", "Warehouse", "Offices"),
          ("property", "cyber"), (900_000, 9_000_000), (8, 70)),
    Trade("Wine importer", "Wines", ("Bonded warehouse", "Offices", "Retail shop"),
          ("property", "cargo"), (1_000_000, 20_000_000), (5, 45), "Bottled wine and spirits"),
    Trade("Software consultancy", "Digital", ("Offices",),
          ("cyber",), (800_000, 12_000_000), (6, 90)),
    Trade("Dental practice group", "Dental", ("Dental surgery",),
          ("property", "cyber"), (1_000_000, 8_000_000), (12, 110)),
    Trade("Recruitment agency", "Recruitment", ("Offices",),
          ("cyber",), (1_500_000, 30_000_000), (8, 75)),
    Trade("Electronics distributor", "Electronics", ("Warehouse & distribution", "Offices"),
          ("property", "cargo", "cyber"), (3_000_000, 40_000_000), (15, 150),
          "Consumer electronics and components"),
    Trade("Accountancy practice", "Accountants", ("Offices",),
          ("cyber",), (600_000, 7_000_000), (5, 60)),
    Trade("Plastics moulder", "Plastics", ("Injection moulding factory", "Warehouse"),
          ("property",), (2_000_000, 22_000_000), (20, 180)),
    Trade("Garden centre operator", "Garden Centres", ("Garden centre & retail", "Glasshouse"),
          ("property",), (1_000_000, 10_000_000), (10, 90)),
]
