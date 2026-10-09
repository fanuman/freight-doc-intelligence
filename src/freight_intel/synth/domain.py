"""Static facts about the freight world, plus money/date formatting.

Money is ALWAYS an integer number of minor units (cents). Floats never hold
money: 0.1 + 0.2 != 0.3 in floating point, and a reconciliation tool that
mis-adds invoices would be a bad joke.
"""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# --- Reference data ---------------------------------------------------------

# UN/LOCODE -> display name. Real codes, so the normalizer can later be tested
# against the real standard.
PORTS: dict[str, str] = {
    "PKKHI": "Karachi",
    "CNSHA": "Shanghai",
    "AEJEA": "Jebel Ali",
    "DEHAM": "Hamburg",
    "NLRTM": "Rotterdam",
    "USNYC": "New York",
    "SGSIN": "Singapore",
    "GBFXT": "Felixstowe",
}

CONTAINER_TYPES = ("20GP", "40GP", "40HC")
INCOTERMS = ("FOB", "CIF", "CFR", "EXW")

# Canonical charge codes (see docs/design-doc.md section 4).
CORE_CHARGES = ("OCEAN_FREIGHT", "BAF", "THC_ORIGIN", "THC_DEST", "DOC_FEE")
OPTIONAL_CHARGES = ("ISPS", "CAF", "INLAND")

# (min, max) typical USD amounts in cents. randrange(..., step=500) later keeps
# them to multiples of $5, like real rate sheets.
RATE_RANGES: dict[str, tuple[int, int]] = {
    "OCEAN_FREIGHT": (180_000, 420_000),
    "BAF": (15_000, 45_000),
    "THC_ORIGIN": (10_000, 25_000),
    "THC_DEST": (15_000, 35_000),
    "DOC_FEE": (4_000, 9_000),
    "ISPS": (1_000, 2_500),
    "CAF": (2_000, 8_000),
    "INLAND": (20_000, 60_000),
}

# Several real-world spellings per canonical code. Each carrier picks one by its
# `label_pack`, and invoices deliberately use a *different* spelling than the
# quote did. That is the "THC vs Terminal Handling" noise from the design doc.
LABELS: dict[str, tuple[str, ...]] = {
    "OCEAN_FREIGHT": ("Ocean Freight", "Basic Ocean Freight", "O/F", "Sea Freight"),
    "BAF": ("BAF", "Bunker Adjustment Factor", "Fuel Surcharge", "Bunker Surcharge"),
    "THC_ORIGIN": ("THC Origin", "Origin Terminal Handling", "OTHC", "Terminal Handling - Origin"),
    "THC_DEST": ("THC Destination", "Destination Terminal Handling", "DTHC", "Terminal Handling - Dest"),
    "DOC_FEE": ("Documentation Fee", "B/L Fee", "Bill of Lading Fee", "Document Charge"),
    "ISPS": ("ISPS", "Port Security Surcharge", "ISPS Security Fee", "Security Surcharge"),
    "CAF": ("CAF", "Currency Adjustment Factor", "Currency Surcharge", "FX Adjustment"),
    "INLAND": ("Inland Haulage", "Trucking", "Inland Transport", "Haulage"),
}

# Charges that appear on an invoice without ever having been quoted.
# (canonical code, raw label). "OTHER" is the bucket for surcharges nobody has
# a taxonomy entry for; the raw label is the only thing that identifies it.
UNQUOTED_CHARGES: tuple[tuple[str, str], ...] = (
    ("DETENTION", "Container Detention"),
    ("DEMURRAGE", "Demurrage Charges"),
    ("OTHER", "Peak Season Surcharge"),
    ("OTHER", "Emergency Risk Surcharge"),
    ("OTHER", "Low Sulphur Surcharge"),
)

CHARGE_BASIS = {"DOC_FEE": "per B/L"}  # everything else is "per container"

CURRENCY_SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£"}

# Fixed FX used for CURRENCY_MISMATCH cases. Strings -> Decimal, never floats.
FX = {("USD", "EUR"): Decimal("0.92"), ("EUR", "USD"): Decimal("1.09")}

# --- Carriers (all fictional) ----------------------------------------------


@dataclass(frozen=True)
class CarrierProfile:
    """One carrier's house style. Four of these = four 'templates' to extract."""

    carrier_id: str
    name: str
    domain: str  # used for fake email addresses (.example is reserved, never real)
    home_currency: str
    number_style: str  # "us" 1,234.56 | "eu" 1.234,56 | "space" 1 234.56
    currency_style: str  # "prefix" USD 1,234.56 | "suffix" 1.234,56 EUR | "symbol" $1,234.56
    date_format: str  # strftime pattern
    label_pack: int  # which spelling of each charge this carrier uses
    quote_title: str
    invoice_title: str
    layout: str  # "simple" | "detailed" | "compact"


CARRIERS: tuple[CarrierProfile, ...] = (
    CarrierProfile("meridian", "Meridian Container Line", "meridian-line.example", "USD",
                   "us", "prefix", "%d %b %Y", 0, "QUOTATION", "INVOICE", "simple"),
    CarrierProfile("nordhafen", "Nordhafen Reederei GmbH", "nordhafen-reederei.example", "EUR",
                   "eu", "suffix", "%d.%m.%Y", 1, "Freight Offer", "Rechnung / Invoice", "detailed"),
    CarrierProfile("blueharbor", "Blue Harbor Shipping", "blueharbor-ship.example", "USD",
                   "us", "symbol", "%B %d, %Y", 2, "Rate Quote", "Tax Invoice", "compact"),
    CarrierProfile("orientpacific", "Orient Pacific Lines", "orient-pacific.example", "USD",
                   "space", "prefix", "%Y-%m-%d", 3, "Spot Quotation", "Freight Invoice", "detailed"),
)

# --- Formatting ---------------------------------------------------------------


def format_amount(minor: int, number_style: str) -> str:
    """12345 -> '123.45' in the chosen convention. Integer maths only."""
    sign = "-" if minor < 0 else ""
    whole, cents = divmod(abs(minor), 100)
    grouped = f"{whole:,}"  # always US-style first: 1,234
    if number_style == "us":
        body = f"{grouped}.{cents:02d}"
    elif number_style == "eu":
        body = grouped.replace(",", ".") + f",{cents:02d}"
    elif number_style == "space":
        body = grouped.replace(",", " ") + f".{cents:02d}"
    else:
        raise ValueError(f"unknown number_style: {number_style}")
    return sign + body


def format_money(minor: int, currency: str, number_style: str, currency_style: str) -> str:
    amount = format_amount(minor, number_style)
    if currency_style == "prefix":
        return f"{currency} {amount}"
    if currency_style == "suffix":
        return f"{amount} {currency}"
    if currency_style == "symbol":
        symbol = CURRENCY_SYMBOL.get(currency)
        return f"{symbol}{amount}" if symbol else f"{currency} {amount}"
    raise ValueError(f"unknown currency_style: {currency_style}")


def format_date(value: date, pattern: str) -> str:
    return value.strftime(pattern)


def convert_minor(minor: int, source: str, target: str) -> int:
    """Convert integer minor units with Decimal, rounding half up."""
    rate = FX[(source, target)]
    return int((Decimal(minor) * rate).quantize(Decimal(1), rounding=ROUND_HALF_UP))
