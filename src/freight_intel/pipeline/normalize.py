"""Turn the many spellings found in documents into one canonical code each.

Charges, ports and container types all work the same way:
  1. clean the text (lowercase, collapse spaces) so trivial differences vanish
  2. look it up EXACTLY in a table of known spellings
  3. if the spelling is unknown, say so (never guess): the caller flags it for a human

No fuzzy matching and no LLM on purpose: a wrong code on a money line is worse
than an honest "I don't know this one".
"""

# --- reference data: canonical code -> spellings we have seen --------------------
# This is data, not logic. Supporting a new carrier's wording means adding a line here.

CHARGE_ALIASES: dict[str, tuple[str, ...]] = {
    "OCEAN_FREIGHT": ("Ocean Freight", "Basic Ocean Freight", "O/F", "Sea Freight"),
    "BAF": ("BAF", "Bunker Adjustment Factor", "Fuel Surcharge", "Bunker Surcharge"),
    "THC_ORIGIN": ("THC Origin", "Origin Terminal Handling", "OTHC", "Terminal Handling - Origin"),
    "THC_DEST": ("THC Destination", "Destination Terminal Handling", "DTHC", "Terminal Handling - Dest"),
    "DOC_FEE": ("Documentation Fee", "B/L Fee", "Bill of Lading Fee", "Document Charge"),
    "ISPS": ("ISPS", "Port Security Surcharge", "ISPS Security Fee", "Security Surcharge"),
    "CAF": ("CAF", "Currency Adjustment Factor", "Currency Surcharge", "FX Adjustment"),
    "INLAND": ("Inland Haulage", "Trucking", "Inland Transport", "Haulage"),
    "DETENTION": ("Container Detention", "Detention"),
    "DEMURRAGE": ("Demurrage Charges", "Demurrage"),
}

# UN/LOCODE -> the name people print. A real system would load the full UN/LOCODE list.
PORT_NAMES: dict[str, str] = {
    "PKKHI": "Karachi", "CNSHA": "Shanghai", "AEJEA": "Jebel Ali", "DEHAM": "Hamburg",
    "NLRTM": "Rotterdam", "USNYC": "New York", "SGSIN": "Singapore", "GBFXT": "Felixstowe",
}
PORT_ALIASES: dict[str, tuple[str, ...]] = {
    code: (name, f"{name} ({code})") for code, name in PORT_NAMES.items()
}

EQUIPMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "20GP": ("20GP", "20' Dry", "20DC", "1 x 20GP"),
    "40GP": ("40GP", "40' Dry", "40DC", "1 x 40GP"),
    "40HC": ("40HC", "40' High Cube", "40HQ", "1 x 40HC"),
}


# --- machinery -------------------------------------------------------------------

def clean(text: str) -> str:
    """'  Terminal  Handling - ORIGIN ' -> 'terminal handling - origin'."""
    return " ".join(text.lower().split())


def build_lookup(aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """Flip {code: spellings} into {cleaned spelling: code} for instant exact lookup.

    The code itself counts as a spelling. If one spelling is claimed by two
    different codes the table is ambiguous, so we refuse to start (loudly, once)
    rather than silently let the last entry win.
    """
    lookup: dict[str, str] = {}
    for code, spellings in aliases.items():
        for spelling in (code, *spellings):
            key = clean(spelling)
            if lookup.get(key, code) != code:
                raise ValueError(f"{spelling!r} is listed under both {lookup[key]} and {code}")
            lookup[key] = code
    return lookup


_CHARGES = build_lookup(CHARGE_ALIASES)
_PORTS = build_lookup(PORT_ALIASES)
_EQUIPMENT = build_lookup(EQUIPMENT_ALIASES)


def normalize_charge(label: str) -> tuple[str, bool]:
    """Return (code, known). An unknown label becomes ('OTHER', False): the charge
    keeps its amount and raw label, but a human must look at it."""
    code = _CHARGES.get(clean(label))
    return (code, True) if code else ("OTHER", False)


def normalize_port(text: str | None) -> str | None:
    """Port text -> UN/LOCODE, or None if missing or not in our table."""
    return _PORTS.get(clean(text)) if text else None


def normalize_equipment(text: str | None) -> str | None:
    """Container text -> '20GP' / '40GP' / '40HC', or None if missing or unknown."""
    return _EQUIPMENT.get(clean(text)) if text else None
