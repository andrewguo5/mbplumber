"""ACR position-label mapping for the adapter (Unit A).

Maps the ACR hand-history position labels onto the frozen 6-max
:class:`mbplumber.models.Position` enum.

ACR labels are expressed as offsets from the button:

    SB, BB, BTN, BTN-1, BTN-2, BTN-3, BTN-4, BTN-5, BTN-6

where ``BTN-n`` means "n seats before the button". In the spec's canonical
6-max ordering the seats are UTG, MP, CO, BTN, SB, BB, so:

    BTN   -> BTN
    BTN-1 -> CO
    BTN-2 -> MP
    BTN-3 -> UTG

Tables with more than 6 players (full-ring) produce deeper offsets
(BTN-4/5/6). Because the downstream model only has a 6-max Position enum,
all offsets of 3 or more collapse to UTG (the earliest position). Unknown
labels raise a clear ``ValueError`` so malformed data surfaces loudly rather
than being silently mis-bucketed.
"""

from __future__ import annotations

from mbplumber.models import Position

# Direct, unambiguous mappings.
_DIRECT: dict[str, Position] = {
    "SB": Position.SB,
    "BB": Position.BB,
    "BTN": Position.BTN,
    "BTN-1": Position.CO,
    "BTN-2": Position.MP,
    # Offset 3 and deeper all collapse to the earliest seat, UTG.
    "BTN-3": Position.UTG,
    "BTN-4": Position.UTG,
    "BTN-5": Position.UTG,
    "BTN-6": Position.UTG,
}


def map_position(acr_label: str) -> Position:
    """Map an ACR position label to a 6-max :class:`Position`.

    Offsets of 3 or more seats from the button (BTN-3 .. BTN-6) collapse to
    UTG, since the 6-max enum has no finer early-position distinction.

    Raises:
        ValueError: if ``acr_label`` is not a recognized ACR label.
    """
    if not isinstance(acr_label, str):
        raise ValueError(f"position label must be a string, got {acr_label!r}")
    label = acr_label.strip().upper()
    try:
        return _DIRECT[label]
    except KeyError:
        raise ValueError(f"unknown ACR position label: {acr_label!r}") from None
