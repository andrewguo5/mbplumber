"""Configuration model and loader.

Loads the YAML config that controls active node dimensions, aggregation
thresholds, and triage scoring weights/flags. Wired into Modules 2, 3, and 4.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# Environment variable that overrides the configured data source. Sits between
# the CLI flag and the config file in the resolution ladder (see resolve_data_source).
DATA_SOURCE_ENV_VAR = "MBPLUMBER_DATA"

# Where mbHUD's `mbhud export` writes ParsedHand JSONL by default (its
# DEFAULT_OUT_DIR is ~/PokerData, hands land in the `hands/` subdirectory). Used
# as the final fallback so a zero-config run finds a standard export.
DEFAULT_DATA_SOURCE = Path.home() / "PokerData" / "hands"

# All toggleable optional node dimensions, in canonical order.
OPTIONAL_DIMENSIONS = [
    "position",  # the 6-way preflop seat name; off by default in favor of in_position
    "pot_size_bucket",
    "stack_depth_bucket",
    "flop_archetype",
    "board_color",
    "board_connectedness",
    "board_paired",
    "board_top_card",
    "num_players_in_hand",
]


class AggregationConfig(BaseModel):
    bootstrap_min_n: int = 10
    bootstrap_resamples: int = 1000
    low_sample_threshold: int = 15
    rng_seed: int = 42


class FlagConfig(BaseModel):
    river_raise_max_freq: float = 0.05
    fold_to_bet_max_freq: float = 0.75
    never_bet_first_to_act: bool = True


class TriageConfig(BaseModel):
    score_weights: dict[str, float] = Field(default_factory=lambda: {"a": 0.5, "b": 0.5})
    ev_divergence_min_samples_per_action: int = 15
    ev_divergence_pctile: float = 95
    street_weights: dict[str, float] = Field(
        default_factory=lambda: {"RIVER": 1.5, "TURN": 1.3, "FLOP": 1.1}
    )
    include_low_sample: bool = False
    flags: FlagConfig = Field(default_factory=FlagConfig)
    # When True, nodes that fired a rule-based flag are ranked above all
    # unflagged nodes (the spec's composite x frequency x street value orders
    # within each tier). This surfaces actionable leaks ahead of high-volume
    # but unremarkable nodes. Set False for pure spec ranking.
    prioritize_flagged: bool = True


class OutputConfig(BaseModel):
    top_n: int = 25


class InputConfig(BaseModel):
    # Directory of ParsedHand JSONL (or a single .jsonl file) to analyze. None
    # means "unset here" — the CLI flag or the MBPLUMBER_DATA env var supplies
    # it, else DEFAULT_DATA_SOURCE. Resolve via resolve_data_source, never read
    # this field directly.
    data_source: str | None = None


class Config(BaseModel):
    node_dimensions: list[str] = Field(
        default_factory=lambda: ["street", "in_position", "pot_type", "action_facing"]
    )
    optional_dimensions: dict[str, bool] = Field(default_factory=dict)
    aggregation: AggregationConfig = Field(default_factory=AggregationConfig)
    triage: TriageConfig = Field(default_factory=TriageConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    input: InputConfig = Field(default_factory=InputConfig)

    def active_dimensions(self) -> list[str]:
        """The full ordered list of dimensions defining a node key:
        the base node_dimensions plus any optional dimensions toggled on."""
        extras = [d for d in OPTIONAL_DIMENSIONS if self.optional_dimensions.get(d)]
        return list(self.node_dimensions) + extras


def load_config(path: str | Path | None = None) -> Config:
    """Load config from YAML, or return defaults if path is None."""
    if path is None:
        return Config()
    data = yaml.safe_load(Path(path).read_text()) or {}
    return Config.model_validate(data)


def resolve_data_source(cli_value: str | Path | None, config: Config) -> Path:
    """Resolve the hand-data source from the highest-priority source available.

    Precedence, highest first:
      1. an explicit CLI value (``--data``),
      2. the ``MBPLUMBER_DATA`` environment variable,
      3. ``input.data_source`` in the loaded config,
      4. :data:`DEFAULT_DATA_SOURCE` (mbHUD's default export location).

    Returns an expanded :class:`~pathlib.Path`; does not check existence — the
    caller reports a missing path to the user.
    """
    for candidate in (cli_value, os.environ.get(DATA_SOURCE_ENV_VAR), config.input.data_source):
        if candidate:
            return Path(candidate).expanduser()
    return DEFAULT_DATA_SOURCE
