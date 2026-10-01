import pytest

from repo_intel.setup.models import AcceleratorKind, HardwareProfile
from repo_intel.setup.recommendation import recommend_qwen

GIB = 1024**3


@pytest.mark.parametrize(
    ("memory_gib", "accelerator", "expected_model", "uncertain"),
    [
        (15, None, "qwen2.5-coder:1.5b", False),
        (16, None, "qwen2.5-coder:7b", False),
        (47, None, "qwen2.5-coder:7b", False),
        (48, None, "qwen2.5-coder:7b", True),
        (48, AcceleratorKind.APPLE_METAL, "qwen3-coder:30b", False),
        (48, AcceleratorKind.NVIDIA_CUDA, "qwen3-coder:30b", False),
    ],
)
def test_recommendation_uses_exact_memory_and_accelerator_tiers(
    memory_gib: int,
    accelerator: AcceleratorKind | None,
    expected_model: str,
    uncertain: bool,
) -> None:
    profile = HardwareProfile(
        memory_bytes=memory_gib * GIB,
        architecture="arm64",
        accelerator=accelerator,
        complete=True,
    )

    recommendation = recommend_qwen(profile)

    assert recommendation.model == expected_model
    assert recommendation.uncertain is uncertain
    assert str(memory_gib) in recommendation.reason


def test_unknown_memory_uses_the_smallest_model_with_uncertainty() -> None:
    profile = HardwareProfile(
        memory_bytes=None,
        architecture="unknown",
        accelerator=None,
        complete=False,
    )

    recommendation = recommend_qwen(profile)

    assert recommendation.model == "qwen2.5-coder:1.5b"
    assert recommendation.uncertain is True
    assert "memory unavailable" in recommendation.reason.lower()
