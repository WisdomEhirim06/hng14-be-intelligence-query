"""
if we build a cache key directly from the raw filter dict, key ordering or value casing differences
can produce different keys for the same query, bypassing the cache.

normalize_filters() produces a canonical, deterministic representation of any
filter dict. make_cache_key() turns that into a stable Redis key.
"""


# Canonical age group values stored in the database
_AGE_GROUP_CANONICAL = {
    "child": "child",
    "children": "child",
    "teenager": "teenager",
    "teenagers": "teenager",
    "teen": "teenager",
    "teens": "teenager",
    "adult": "adult",
    "adults": "adult",
    "senior": "senior",
    "seniors": "senior",
    "elderly": "senior",
}

# Canonical gender values
_GENDER_CANONICAL = {
    "male": "male",
    "males": "male",
    "man": "male",
    "men": "male",
    "boy": "male",
    "boys": "male",
    "female": "female",
    "females": "female",
    "woman": "female",
    "women": "female",
    "girl": "female",
    "girls": "female",
}


def normalize_filters(filters: dict) -> dict:
    
    normalized = {}

    if filters.get("gender"):
        raw = filters["gender"].lower().strip()
        normalized["gender"] = _GENDER_CANONICAL.get(raw, raw)

    if filters.get("age_group"):
        raw = filters["age_group"].lower().strip()
        normalized["age_group"] = _AGE_GROUP_CANONICAL.get(raw, raw)

    if filters.get("country_id"):
        normalized["country_id"] = filters["country_id"].upper().strip()

    if filters.get("min_age") is not None:
        normalized["min_age"] = int(filters["min_age"])

    if filters.get("max_age") is not None:
        normalized["max_age"] = int(filters["max_age"])

    if filters.get("min_gender_probability") is not None:
        normalized["min_gender_probability"] = round(float(filters["min_gender_probability"]), 4)

    if filters.get("min_country_probability") is not None:
        normalized["min_country_probability"] = round(float(filters["min_country_probability"]), 4)

    # Sort keys so insertion order never affects the result
    return dict(sorted(normalized.items()))


def make_cache_key(
    filters: dict,
    page: int = 1,
    limit: int = 10,
    sort_by: str = "created_at",
    order: str = "desc",
) -> str:
    """
    Build a deterministic Redis cache key from a filter dict.

    Always normalizes filters first so semantically equivalent queries
    map to the same key regardless of how they were expressed.
    """
    canonical = normalize_filters(filters)
    parts = [f"{k}={v}" for k, v in canonical.items()]
    parts += [f"page={page}", f"limit={limit}", f"sort={sort_by}", f"order={order}"]
    return "profiles:" + "|".join(parts)
