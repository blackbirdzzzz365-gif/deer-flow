"""Verify that all sub-config Pydantic models are frozen (immutable).

Frozen models reject attribute assignment after construction, raising
pydantic.ValidationError. This test collects every BaseModel subclass
defined in the deerflow.config package and asserts that mutation is
blocked.
"""

import inspect
import pkgutil

import pytest
from pydantic import BaseModel, ValidationError

import deerflow.config as config_pkg


def _collect_config_models() -> list[type[BaseModel]]:
    """Walk deerflow.config.* and return all concrete BaseModel subclasses."""
    import importlib

    models: list[type[BaseModel]] = []
    package_path = config_pkg.__path__
    package_prefix = config_pkg.__name__ + "."

    for _importer, modname, _ispkg in pkgutil.walk_packages(package_path, prefix=package_prefix):
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        for _name, obj in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(obj, BaseModel)
                and obj is not BaseModel
                and obj.__module__ == mod.__name__
            ):
                models.append(obj)

    return models


_EXCLUDED: set[str] = set()

_ALL_MODELS = [m for m in _collect_config_models() if m.__name__ not in _EXCLUDED]

# Sanity: make sure we actually collected a meaningful set.
assert len(_ALL_MODELS) >= 15, f"Expected at least 15 config models, found {len(_ALL_MODELS)}: {[m.__name__ for m in _ALL_MODELS]}"


@pytest.mark.parametrize("model_cls", _ALL_MODELS, ids=lambda cls: cls.__name__)
def test_config_model_is_frozen(model_cls: type[BaseModel]):
    """Every sub-config model must have frozen=True in its model_config."""
    cfg = model_cls.model_config
    assert cfg.get("frozen") is True, (
        f"{model_cls.__name__} is not frozen. "
        f"Add `model_config = ConfigDict(frozen=True)` or add `frozen=True` to the existing ConfigDict."
    )


@pytest.mark.parametrize("model_cls", _ALL_MODELS, ids=lambda cls: cls.__name__)
def test_config_model_rejects_mutation(model_cls: type[BaseModel]):
    """Constructing then mutating any field must raise ValidationError."""
    # Build a minimal instance -- use model_construct to skip validation for
    # required fields, then pick the first field to try mutating.
    fields = list(model_cls.model_fields.keys())
    if not fields:
        pytest.skip(f"{model_cls.__name__} has no fields")

    instance = model_cls.model_construct()
    first_field = fields[0]

    with pytest.raises(ValidationError):
        setattr(instance, first_field, "MUTATED")
