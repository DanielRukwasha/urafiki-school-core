"""Published reports expose audit history, never editable report values."""

from tests.integration.test_bulletin_versions import published as published_fixture

published = published_fixture


def test_published_history_and_motivated_correction(client, published):
    response = client.get(published["base"])
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-bulletin-version="1"' in html
    assert published["user"].full_name in html
    assert "Première publication" in html
    assert 'name="motif"' in html and 'required minlength="10"' in html
    assert "irréversible" in html
    assert 'class="grade-input"' not in html
    assert 'name="score"' not in html

    motif = "Correction documentée <script>alert(1)</script>"
    assert client.post(published["base"] + "/correction", data={"motif": motif}).status_code == 302
    html = client.get(published["base"]).get_data(as_text=True)
    assert 'data-bulletin-version="2"' in html
    assert 'data-bulletin-version="1"' in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
