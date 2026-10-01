import subprocess
import sys
from pathlib import Path

import pytest

from repo_intel.acceptance import (
    AcceptanceFailure,
    DoctorSnapshot,
    assert_no_unapproved_change,
    confirm_action,
    parse_doctor_output,
    validate_compose_contract,
)


def test_parse_doctor_output_requires_the_complete_module_two_contract() -> None:
    output = """\
git: installed — git is installed.
rg: installed — rg is installed.
ollama: healthy — Ollama is healthy.
docker: healthy — Docker is healthy.
qdrant: stopped — Qdrant is stopped.
nomic-embed-text: missing — nomic-embed-text is missing.
qwen2.5-coder:7b: missing — qwen2.5-coder:7b is missing.
Recommended Qwen model: qwen2.5-coder:7b
Recommendation basis: 32 GiB memory detected.
"""

    snapshot = parse_doctor_output(output)

    assert snapshot.checks == {
        "git": "installed",
        "rg": "installed",
        "ollama": "healthy",
        "docker": "healthy",
        "qdrant": "stopped",
        "nomic-embed-text": "missing",
        "qwen2.5-coder:7b": "missing",
    }
    assert snapshot.recommended_model == "qwen2.5-coder:7b"

    with pytest.raises(AcceptanceFailure, match="qdrant"):
        parse_doctor_output(output.replace("qdrant: stopped — Qdrant is stopped.\n", ""))


def test_compose_contract_requires_the_pinned_image_local_ports_and_data_path() -> None:
    data_dir = "/Users/Test User/Library/Application Support/repo-intel/data/qdrant"
    compose = f'''\
services:
  qdrant:
    image: qdrant/qdrant:v1.19.1
    ports:
      - "127.0.0.1:6333:6333"
      - "127.0.0.1:6334:6334"
    volumes:
      - type: bind
        source: "{data_dir}"
        target: /qdrant/storage
'''

    validate_compose_contract(compose, data_dir)

    with pytest.raises(AcceptanceFailure, match="localhost REST port"):
        validate_compose_contract(compose.replace("127.0.0.1:6333", "0.0.0.0:6333"), data_dir)
    with pytest.raises(AcceptanceFailure, match="pinned Qdrant image"):
        validate_compose_contract(compose.replace("v1.19.1", "latest"), data_dir)


@pytest.mark.parametrize(("answer", "expected"), [("", False), ("n", False), ("yes", True)])
def test_live_action_confirmation_defaults_to_no(answer: str, expected: bool) -> None:
    assert confirm_action("Run live action?", input_fn=lambda _: answer) is expected


def test_live_action_confirmation_treats_end_of_input_as_no() -> None:
    def end_of_input(prompt: str) -> str:
        del prompt
        raise EOFError

    assert confirm_action("Run live action?", input_fn=end_of_input) is False


def test_declined_setup_rejects_an_unapproved_external_state_change() -> None:
    before = DoctorSnapshot(
        checks={
            "qdrant": "stopped",
            "nomic-embed-text": "missing",
            "qwen2.5-coder:7b": "missing",
        },
        recommended_model="qwen2.5-coder:7b",
    )
    unchanged = DoctorSnapshot(dict(before.checks), before.recommended_model)
    changed = DoctorSnapshot(
        {**before.checks, "nomic-embed-text": "installed"},
        before.recommended_model,
    )

    assert_no_unapproved_change(before, unchanged)
    with pytest.raises(AcceptanceFailure, match="nomic-embed-text"):
        assert_no_unapproved_change(before, changed)


def test_acceptance_script_help_discloses_real_retained_side_effects() -> None:
    script = Path(__file__).parents[2] / "scripts" / "acceptance_modules_01_02.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    normalized_help = " ".join(result.stdout.split())
    assert "downloads real Ollama models" in normalized_help
    assert "starts the managed Qdrant service" in normalized_help
    assert "leaves successful setup resources in place" in normalized_help
