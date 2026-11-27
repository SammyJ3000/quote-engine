class QuoteError(Exception):
    """Base class for all engine errors."""


class FormulaError(QuoteError):
    """A recipe expression could not be evaluated safely."""


class MissingPriceError(QuoteError):
    """A SKU used by a recipe has no price in the active price book."""


class RecipeError(QuoteError):
    """A recipe file is malformed or references something that does not exist."""


class ParameterError(QuoteError):
    """Supplied job parameters are missing or out of range."""
