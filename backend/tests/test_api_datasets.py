"""Tests for the dataset endpoints: upload validation, listing, and profiles."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def upload(client: TestClient, name: str, content: bytes, content_type: str = "text/csv"):
    return client.post("/datasets/upload", files={"file": (name, content, content_type)})


def stored_files(api_env: Path) -> list[Path]:
    uploads = api_env / "uploads"
    return sorted(uploads.glob("*")) if uploads.exists() else []


class TestUpload:
    def test_upload_csv_returns_profile(self, client: TestClient, api_env: Path, sales_csv_bytes: bytes):
        response = upload(client, "sales.csv", sales_csv_bytes)
        assert response.status_code == 201
        body = response.json()
        assert body["filename"] == "sales.csv"
        assert body["row_count"] == 6
        assert body["column_count"] == 4
        assert body["size_bytes"] == len(sales_csv_bytes)
        assert body["profile"]["row_count"] == 6
        assert body["profile"]["candidate_metrics"] == ["revenue", "units"]
        assert body["profile"]["missing_values"]["units"]["count"] == 1
        assert len(stored_files(api_env)) == 1

    def test_server_path_is_never_exposed(self, client: TestClient, sales_csv_bytes: bytes):
        body = upload(client, "sales.csv", sales_csv_bytes).json()
        assert "file_path" not in body
        listing = client.get("/datasets").json()
        assert all("file_path" not in item for item in listing)

    def test_upload_xlsx(self, client: TestClient, sales_xlsx_bytes: bytes):
        response = upload(client, "sales.xlsx", sales_xlsx_bytes, "application/octet-stream")
        assert response.status_code == 201
        assert response.json()["profile"]["column_types"]["date"] == "datetime"

    def test_response_is_valid_json_with_missing_values(self, client: TestClient):
        csv = b"a,b\n1,\n2,3\n,\n"
        response = upload(client, "gaps.csv", csv)
        assert response.status_code == 201
        assert response.json()["profile"]["sample_rows"][0]["b"] is None

    def test_filename_is_sanitised_and_file_stored_under_uuid(
        self, client: TestClient, api_env: Path, sales_csv_bytes: bytes
    ):
        response = upload(client, "../../etc/evil.csv", sales_csv_bytes)
        assert response.status_code == 201
        assert response.json()["filename"] == "evil.csv"
        (path,) = stored_files(api_env)
        assert path.parent == api_env / "uploads"
        assert path.stem == response.json()["id"]

    def test_unsupported_extension(self, client: TestClient, api_env: Path):
        response = upload(client, "data.json", b"{}")
        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]
        assert stored_files(api_env) == []

    def test_missing_extension(self, client: TestClient):
        assert upload(client, "noextension", b"a,b\n1,2\n").status_code == 400

    def test_empty_file(self, client: TestClient, api_env: Path):
        response = upload(client, "empty.csv", b"")
        assert response.status_code == 400
        assert "empty" in response.json()["detail"]
        assert stored_files(api_env) == []

    def test_oversized_file_rejected_and_removed(self, client: TestClient, api_env: Path):
        big = b"a,b\n" + b"1,2\n" * (400 * 1024)  # ~1.6 MB > 1 MB limit
        response = upload(client, "big.csv", big)
        assert response.status_code == 413
        assert "1 MB" in response.json()["detail"]
        assert stored_files(api_env) == []

    def test_fake_xlsx_rejected(self, client: TestClient, api_env: Path):
        response = upload(client, "fake.xlsx", b"a,b\n1,2\n")
        assert response.status_code == 400
        assert "not a valid .xlsx" in response.json()["detail"]
        assert stored_files(api_env) == []

    def test_truncated_xlsx_rejected(self, client: TestClient, sales_xlsx_bytes: bytes):
        response = upload(client, "cut.xlsx", sales_xlsx_bytes[:200])
        assert response.status_code == 400

    def test_fake_xls_rejected(self, client: TestClient):
        assert upload(client, "fake.xls", b"a,b\n1,2\n").status_code == 400

    def test_binary_csv_rejected(self, client: TestClient):
        response = upload(client, "bin.csv", b"a,b\n\x00\x01\x02\n")
        assert response.status_code == 400

    def test_header_only_csv_rejected_with_cleanup(self, client: TestClient, api_env: Path):
        response = upload(client, "header.csv", b"a,b,c\n")
        assert response.status_code == 422
        assert "no data rows" in response.json()["detail"]
        assert stored_files(api_env) == []

    def test_unparseable_csv_gives_sanitised_422(self, client: TestClient, api_env: Path):
        response = upload(client, "blank.csv", b"\n\n\n")
        assert response.status_code == 422
        assert stored_files(api_env) == []

    def test_latin1_csv_accepted(self, client: TestClient):
        response = upload(client, "latin.csv", "city,sales\nZ\xfcrich,10\n".encode("latin-1"))
        assert response.status_code == 201

    def test_no_file_field(self, client: TestClient):
        assert client.post("/datasets/upload").status_code == 422


class TestCleanFilename:
    def test_strips_directories_and_control_characters(self):
        from app.api.datasets import _clean_filename

        assert _clean_filename("..\\..\\win\\evil\x00.csv") == "evil.csv"
        assert _clean_filename("/abs/path/data\n.csv") == "data.csv"
        assert _clean_filename(None) == "upload"
        assert _clean_filename("") == "upload"

    def test_long_names_keep_extension(self):
        from app.api.datasets import MAX_FILENAME_LENGTH, _clean_filename

        name = _clean_filename("a" * 400 + ".csv")
        assert len(name) == MAX_FILENAME_LENGTH and name.endswith(".csv")


class TestListAndProfile:
    def test_list_empty(self, client: TestClient):
        response = client.get("/datasets")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_newest_first(self, client: TestClient, sales_csv_bytes: bytes):
        first = upload(client, "first.csv", sales_csv_bytes).json()["id"]
        second = upload(client, "second.csv", sales_csv_bytes).json()["id"]
        ids = [d["id"] for d in client.get("/datasets").json()]
        assert ids == [second, first]

    def test_trailing_slash_also_works(self, client: TestClient, dataset_id: str):
        assert client.get("/datasets/").status_code == 200

    def test_get_profile(self, client: TestClient, dataset_id: str):
        response = client.get(f"/datasets/{dataset_id}/profile")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == dataset_id
        assert body["profile"]["schema"]["revenue"] == "float64"
        assert body["profile"]["quality_flags"] == []

    def test_profile_not_found(self, client: TestClient):
        response = client.get("/datasets/does-not-exist/profile")
        assert response.status_code == 404
        assert response.json()["detail"] == "Dataset not found."

    def test_sql_metacharacters_in_id_are_harmless(self, client: TestClient):
        assert client.get("/datasets/x'%20OR%20'1'='1/profile").status_code == 404

    def test_datasets_survive_restart(self, api_env: Path, sales_csv_bytes: bytes):
        from app.main import app

        with TestClient(app) as first:
            dataset_id = upload(first, "sales.csv", sales_csv_bytes).json()["id"]
        with TestClient(app) as second:
            assert [d["id"] for d in second.get("/datasets").json()] == [dataset_id]


def test_root_health(client: TestClient):
    assert client.get("/").json()["status"] == "running"
