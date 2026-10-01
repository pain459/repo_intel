"""Pure Qwen model recommendation policy."""

from repo_intel.setup.models import HardwareProfile, ModelRecommendation

_GIB = 1024**3
_SMALL_MODEL = "qwen2.5-coder:1.5b"
_MEDIUM_MODEL = "qwen2.5-coder:7b"
_LARGE_MODEL = "qwen3-coder:30b"


def recommend_qwen(profile: HardwareProfile) -> ModelRecommendation:
    """Choose the safest Qwen tier supported by the available evidence."""
    if profile.memory_bytes is None:
        return ModelRecommendation(
            _SMALL_MODEL,
            "Memory unavailable; using the conservative model tier.",
            uncertain=True,
        )

    memory_gib = profile.memory_bytes // _GIB
    incomplete = not profile.complete
    if memory_gib < 16:
        return ModelRecommendation(
            _SMALL_MODEL,
            f"{memory_gib} GiB memory detected; using the lightweight model tier.",
            uncertain=incomplete,
        )
    if memory_gib < 48:
        return ModelRecommendation(
            _MEDIUM_MODEL,
            f"{memory_gib} GiB memory detected; using the standard model tier.",
            uncertain=incomplete,
        )
    if profile.accelerator is not None:
        return ModelRecommendation(
            _LARGE_MODEL,
            f"{memory_gib} GiB memory and supported acceleration detected.",
            uncertain=incomplete,
        )
    return ModelRecommendation(
        _MEDIUM_MODEL,
        f"{memory_gib} GiB memory detected without confirmed supported acceleration.",
        uncertain=True,
    )


__all__ = ["recommend_qwen"]
