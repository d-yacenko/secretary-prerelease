from pathlib import Path


def test_compose_shares_local_files_volume_between_api_and_worker() -> None:
    compose_path = Path(__file__).resolve().parents[2] / "infra" / "compose.yaml"
    content = compose_path.read_text(encoding="utf-8")
    assert "local_files_data:/var/lib/secretary/local-files" in content
    assert content.count("local_files_data:/var/lib/secretary/local-files") >= 2
    assert "LOCAL_FILES_ROOT: /var/lib/secretary/local-files" in content
    assert content.count("LOCAL_FILES_ROOT: /var/lib/secretary/local-files") >= 2
    assert "\n  local_files_data:\n" in content
