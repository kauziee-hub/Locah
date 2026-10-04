"""Catalogue import: a sheet of items becomes reviewed drafts, never live items.

What must hold:
* CSV and XLSX are read; headers are recognised (Item / Price (₹) / Section …)
  and can be remapped; nothing that isn't a catalogue sheet is accepted;
* every row is ready, a duplicate or an error — with the exact reason — and
  errors never stop the valid rows;
* imported items are drafts (nothing public changes) through the catalogue's
  own create path; a repeated import creates nothing twice;
* a duplicate is skipped by default, can update an existing draft, never a live
  item; stock is applied only with Inventory on and permission to adjust it;
* the owner reviews the batch and makes chosen drafts live; an item without a
  price cannot go live as fixed-price;
* a person without `offerings.create` cannot import.
"""

from __future__ import annotations

import base64
import io
import os
import zipfile
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app

from platform_core.catalogue_import.reading import ReadProblem, read_table
from platform_core.catalogue_import.rows import apply_mapping, norm_name, parse_duration, parse_price, suggest_mapping
from platform_testing.phase_b import create_business, new_identity, primary_location, sql

DB = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
client = TestClient(app)

MENU_CSV = (
    "Item,Price (₹),Section,Description\n"
    "Filter Coffee,40,Drinks,Strong South Indian coffee\n"
    "Masala Dosa,₹120,Breakfast,\n"
    "Pasta Arrabbiata,220,Mains,\n"
    "Red Velvet Cake,Rs. 650,Cakes,Whole cake\n"
    "  filter coffee ,45,Drinks,\n"
    ",99,Drinks,\n"
    "Lemon Tea,abc,Drinks,\n"
)


def _xlsx(rows: list[list[Any]]) -> bytes:
    """A real minimal .xlsx: inline strings and numbers on the first sheet."""
    def cell(ref: str, v: Any) -> str:
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'
    body = "".join(
        f'<row r="{r + 1}">' + "".join(cell(f"{chr(65 + c)}{r + 1}", v) for c, v in enumerate(row)) + "</row>"
        for r, row in enumerate(rows))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", f'<workbook {ns} {rel}><sheets><sheet name="Menu" sheetId="1" r:id="rId1"/>'
                                      "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="worksheet"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{body}</sheetData></worksheet>")
    return buf.getvalue()


# ------------------------------------------------------------------ pure reading and cleaning
def test_csv_and_xlsx_read_into_the_same_table() -> None:
    csv = read_table("menu.csv", MENU_CSV.encode("utf-8"))
    assert csv.source == "csv" and csv.headers[:2] == ["Item", "Price (₹)"] and len(csv.rows) == 7
    xlsx = read_table("menu.xlsx", _xlsx([["Service", "Rate", "Duration"], ["Haircut", 300, "45 min"],
                                          ["Facial", 800.5, 60]]))
    assert xlsx.source == "xlsx" and xlsx.headers == ["Service", "Rate", "Duration"]
    assert xlsx.rows == [["Haircut", "300", "45 min"], ["Facial", "800.5", "60"]]
    semi = read_table("x.csv", "Name;Price\nTea;20\n".encode("utf-8"))
    assert semi.headers == ["Name", "Price"] and semi.rows == [["Tea", "20"]]


@pytest.mark.parametrize(("name", "data", "says"), [
    ("menu.pdf", b"%PDF-1.4", ".csv or .xlsx"),
    ("menu.xlsx", b"PK\x03\x04 not really a zip", "Excel"),
    ("menu.csv", b"", "empty"),
    ("menu.csv", b"Name,Price\n", "header row"),
    ("menu.xls", b"PK\x03\x04", ".xlsx or .csv"),
])
def test_files_that_are_not_catalogue_sheets_are_refused_in_plain_words(name: str, data: bytes, says: str) -> None:
    with pytest.raises(ReadProblem, match=says):
        read_table(name, data)


def test_headers_are_recognised_and_each_field_is_used_once() -> None:
    assert suggest_mapping(["Item", "Price (₹)", "Section", "Description"]) == ["name", "price", "category",
                                                                              "description"]
    assert suggest_mapping(["Menu Item", "Rate", "Qty", "Branch", "Code"]) == ["name", "price", "stock",
                                                                              "location", "sku"]
    assert suggest_mapping(["Name", "Product", "Mystery"]) == ["name", None, None]
    rows = apply_mapping([["Tea", "20"]], ["name", "price"])
    assert rows[0]["name"] == "Tea" and rows[0]["price"] == "20" and rows[0]["category"] == ""


@pytest.mark.parametrize(("raw", "value"), [("40", "40"), ("₹1,200", "1200"), ("Rs. 99", "99"), ("99/-", "99"),
                                            ("149.50", "149.50"), ("", None)])
def test_prices_are_read_the_way_people_write_them(raw: str, value: str | None) -> None:
    got = parse_price(raw)
    assert (str(got) if got is not None else None) == (str(Decimal(value)) if value else None)


def test_bad_prices_and_durations_say_why() -> None:
    with pytest.raises(ValueError, match="not a price"):
        parse_price("abc")
    assert parse_duration("1h 30m") == 90 and parse_duration("1:15") == 75 and parse_duration("45 mins") == 45
    with pytest.raises(ValueError, match="not a duration"):
        parse_duration("soon")
    assert norm_name("  Filter-Coffee ") == norm_name("filter coffee")


# ------------------------------------------------------------------ through the API
def _shop(monkeypatch: Any, modules: tuple[str, ...] = ("offerings-catalog",)) -> tuple[dict[str, str], str]:
    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, business_type="cafe", modules=modules)
    return owner, bid


def _read(owner: dict[str, str], bid: str, name: str, data: bytes) -> dict[str, Any]:
    r = client.post(f"/v1/platform/businesses/{bid}/catalogue-import/read", headers=owner,
                    json={"filename": name, "content_base64": base64.b64encode(data).decode()})
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


def _mapped(read: dict[str, Any]) -> list[dict[str, str]]:
    return apply_mapping(read["rows"], read["suggested_mapping"])


def _import(owner: dict[str, str], bid: str, read: dict[str, Any], rows: list[dict[str, str]],
            decisions: dict[str, str] | None = None, kind: str | None = "menu_item") -> dict[str, Any]:
    r = client.post(f"/v1/platform/businesses/{bid}/catalogue-import", headers=owner, json={
        "filename": "menu.csv", "file_hash": read["file_hash"], "source": read["source"], "rows": rows,
        "decisions": decisions or {}, "default_kind": kind})
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


@DB
def test_a_menu_sheet_becomes_drafts_with_reasons_for_every_row(monkeypatch: Any) -> None:
    owner, bid = _shop(monkeypatch)
    read = _read(owner, bid, "menu.csv", MENU_CSV.encode("utf-8"))
    rows = _mapped(read)
    checked = client.post(f"/v1/platform/businesses/{bid}/catalogue-import/check", headers=owner,
                          json={"rows": rows, "default_kind": "menu_item"}).json()["data"]
    status = [r["status"] for r in checked["rows"]]
    assert status == ["ready", "ready", "ready", "ready", "duplicate", "error", "error"]
    assert checked["rows"][4]["repeats_row"] == 0  # "  filter coffee " repeats row 1
    assert checked["rows"][5]["problems"] == ["Name is missing"]
    assert "not a price" in checked["rows"][6]["problems"][0]
    assert checked["summary"] == {"ready": 4, "duplicate": 1, "error": 2, "total": 7}

    done = _import(owner, bid, read, rows)
    assert (done["created"], done["skipped"], done["errors"]) == (4, 1, 2)
    items = sql("select title, status, offering_type, price_amount from offerings_catalog_offerings "
                "where business_id = cast(:b as uuid) order by title", b=bid)
    assert [(t, s, k) for t, s, k, _ in items] == [
        ("Filter Coffee", "draft", "menu_item"), ("Masala Dosa", "draft", "menu_item"),
        ("Pasta Arrabbiata", "draft", "menu_item"), ("Red Velvet Cake", "draft", "menu_item")]
    assert Decimal(items[1][3]) == Decimal("120")  # "₹120"
    categories = {r[0] for r in sql("select name from offerings_catalog_categories where business_id = cast(:b as uuid)",
                                    b=bid)}
    assert {"Drinks", "Breakfast", "Mains", "Cakes"} <= categories
    # Nothing is public: the website's catalogue is still empty.
    slug = sql("select slug from businesses where id = cast(:b as uuid)", b=bid)[0][0]
    client.post(f"/v1/b/{bid}/marketplace/visibility", json={"visibility": "unlisted"}, headers=owner)
    public = client.get(f"/v1/public/websites/{slug}/offerings").json()["data"]["offerings"]
    assert public == []

    # Review, then make two live.
    batch = client.get(f"/v1/platform/businesses/{bid}/catalogue-import/{done['id']}", headers=owner).json()["data"]
    assert batch["summary"]["created"] == 4 and all(i["can_go_live"] for i in batch["items"])
    pick = [i["id"] for i in batch["items"][:2]]
    live = client.post(f"/v1/platform/businesses/{bid}/catalogue-import/{done['id']}/make-live", headers=owner,
                       json={"offering_ids": pick}).json()["data"]
    assert live["live"] == 2
    assert len(client.get(f"/v1/public/websites/{slug}/offerings").json()["data"]["offerings"]) == 2


@DB
def test_importing_the_same_file_again_creates_nothing_twice(monkeypatch: Any) -> None:
    owner, bid = _shop(monkeypatch)
    data = MENU_CSV.encode("utf-8")
    read = _read(owner, bid, "menu.csv", data)
    assert read["previous_import"] is None
    _import(owner, bid, read, _mapped(read))
    again = _read(owner, bid, "menu.csv", data)
    assert again["previous_import"] and again["previous_import"]["created"] == 4
    second = _import(owner, bid, again, _mapped(again))
    assert second["created"] == 0 and second["skipped"] == 5
    count = sql("select count(*) from offerings_catalog_offerings where business_id = cast(:b as uuid)", b=bid)[0][0]
    assert count == 4


@DB
def test_a_duplicate_can_update_a_draft_but_never_a_live_item(monkeypatch: Any) -> None:
    owner, bid = _shop(monkeypatch)
    base = f"/v1/platform/businesses/{bid}"
    live = client.post(f"{base}/products", headers=owner, json={
        "title": "Filter Coffee", "offering_type": "menu_item", "status": "active", "visibility": "public",
        "price_amount": 40, "price_type": "fixed"}).json()["data"]["id"]
    draft = client.post(f"{base}/products", headers=owner, json={
        "title": "Masala Dosa", "offering_type": "menu_item", "status": "draft", "price_type": "enquiry"}
    ).json()["data"]["id"]
    sheet = "Item,Price\nFilter coffee,55\nMasala dosa,120\n".encode("utf-8")
    read = _read(owner, bid, "menu.csv", sheet)
    done = _import(owner, bid, read, _mapped(read), decisions={"0": "update", "1": "update"})
    assert done["updated"] == 1 and done["skipped"] == 1
    assert "live" in done["rows"][0]["problems"][0]
    prices = dict(sql("select cast(id as text), price_amount from offerings_catalog_offerings "
                      "where business_id = cast(:b as uuid)", b=bid))
    assert Decimal(prices[live]) == Decimal("40") and Decimal(prices[draft]) == Decimal("120")


@DB
def test_services_keep_their_duration_and_stock_needs_inventory_and_permission(monkeypatch: Any) -> None:
    owner, bid = _shop(monkeypatch, ("offerings-catalog", "bookings"))
    sheet = _xlsx([["Service", "Price", "Duration", "Stock"], ["Haircut", 300, "45 min", 5],
                   ["Bridal makeup", 6500, "3h", ""]])
    read = _read(owner, bid, "services.xlsx", sheet)
    checked = client.post(f"/v1/platform/businesses/{bid}/catalogue-import/check", headers=owner,
                          json={"rows": _mapped(read), "default_kind": "service"}).json()["data"]
    assert checked["stock_allowed"] is False
    assert any("Stock is not applied" in n for n in checked["rows"][0]["notes"])
    _import(owner, bid, read, _mapped(read), kind="service")
    got = sql("select title, attributes->>'duration_minutes', track_inventory from offerings_catalog_offerings "
              "where business_id = cast(:b as uuid) order by title", b=bid)
    assert [(t, d, s) for t, d, s in got] == [("Bridal makeup", "180", False), ("Haircut", "45", False)]

    owner2, shop = _shop(monkeypatch, ("offerings-catalog", "inventory"))
    read = _read(owner2, shop, "stock.csv", "Product,Price,Qty\nBrass Lamp,1200,7\n".encode("utf-8"))
    _import(owner2, shop, read, _mapped(read), kind="product")
    loc = primary_location(client, owner2, shop)
    on_hand = sql("select r.quantity_on_hand from inventory_records r join offerings_catalog_offerings o "
                  "on o.id = r.offering_id where o.business_id = cast(:b as uuid) and r.location_id = cast(:l as uuid)",
                  b=shop, l=loc)
    assert on_hand and Decimal(on_hand[0][0]) == Decimal("7")


@DB
def test_an_item_without_a_price_waits_and_a_member_without_permission_cannot_import(monkeypatch: Any) -> None:
    owner, bid = _shop(monkeypatch)
    read = _read(owner, bid, "menu.csv", "Item,Price\nChef's special,\n".encode("utf-8"))
    done = _import(owner, bid, read, _mapped(read))
    batch = client.get(f"/v1/platform/businesses/{bid}/catalogue-import/{done['id']}", headers=owner).json()["data"]
    item = batch["items"][0]
    assert item["price_type"] == "enquiry" and item["can_go_live"] is True  # price on request is honest
    # A service without a duration can't be booked, so it waits in review with the reason.
    read = _read(owner, bid, "svc.csv", "Service,Price\nHead massage,400\n".encode("utf-8"))
    done = _import(owner, bid, read, _mapped(read), kind="service")
    batch = client.get(f"/v1/platform/businesses/{bid}/catalogue-import/{done['id']}", headers=owner).json()["data"]
    assert batch["items"][0]["can_go_live"] is False and batch["items"][0]["problem"] == "Add how long it takes first"
    refused = client.post(f"/v1/platform/businesses/{bid}/catalogue-import/{done['id']}/make-live", headers=owner,
                          json={"offering_ids": [batch["items"][0]["id"]]}).json()["data"]
    assert refused["live"] == 0 and refused["results"][0]["problem"] == "Add how long it takes first"
    person, member = new_identity(monkeypatch)
    inv = client.post(f"/v1/b/{bid}/team/invitations", json={"identity_id": str(person), "role": "member"},
                      headers=owner).json()["data"]["id"]
    client.post(f"/v1/b/{bid}/team/members/{inv}/activate", headers=owner)
    r = client.post(f"/v1/platform/businesses/{bid}/catalogue-import/read", headers=member,
                    json={"filename": "m.csv", "content_base64": base64.b64encode(b"Item\nTea\n").decode()})
    assert r.status_code == 403


# ------------------------------------------------------------------ a PDF, photo or pasted menu
class _Reader:
    """Stands in for the AI document reader: no network, no paid call."""

    provider_name = "stub"
    model_name = "stub"

    def __init__(self, answer: dict[str, Any] | Exception) -> None:
        self.answer, self.mime_types = answer, []  # type: list[str]

    async def generate_structured_from_file(self, prompt: str, data: bytes, mime_type: str, schema: dict[str, Any],
                                            model_config: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
        self.mime_types.append(mime_type)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


MENU_READING = {"kind": "menu", "groups": [
    {"name": "Coffee", "items": [{"name": "Filter Coffee", "price": "40"},
                                 {"name": "Cold Coffee", "price": "12O", "variant": "Large"}]},
    {"name": "Bakes", "items": [{"name": "Banana Bread", "price": "90", "attributes": "eggless"},
                                {"name": "Croissant", "price": "", "confidence": "low"}]},
]}


def _use_reader(monkeypatch: Any, reader: Any) -> None:
    import platform_core.website.ai_provider as ai_provider

    monkeypatch.setattr(ai_provider, "get_ai_provider", lambda: reader)


@DB
def test_a_photographed_menu_becomes_the_same_reviewable_table(monkeypatch: Any) -> None:
    owner, bid = _shop(monkeypatch)
    reader = _Reader(MENU_READING)
    _use_reader(monkeypatch, reader)
    read = _read(owner, bid, "menu.jpg", b"\xff\xd8\xff\xe0 a photo")
    assert reader.mime_types == ["image/jpeg"] and read["source"] == "document"
    assert read["suggested_mapping"] == ["name", "description", "category", "price"]
    assert [r[0] for r in read["rows"]] == ["Filter Coffee", "Cold Coffee (Large)", "Banana Bread", "Croissant"]
    assert read["rows"][2][1] == "eggless" and read["rows"][2][2] == "Bakes"
    # "12O" was misread and "Croissant" was marked unsure: both are flagged for the owner.
    assert read["uncertain_rows"] == [1, 3]
    # "12O" is not a price, so that row waits for a fix; the owner unticks the unsure
    # Croissant; the rest become drafts, never live.
    done = _import(owner, bid, read, _mapped(read), decisions={"3": "skip"})
    assert (done["created"], done["skipped"], done["errors"]) == (2, 1, 1)
    assert {s for (s,) in sql("select status from offerings_catalog_offerings where business_id = cast(:b as uuid)",
                              b=bid)} == {"draft"}


@DB
def test_a_pasted_menu_is_read_and_a_failed_read_is_said_plainly(monkeypatch: Any) -> None:
    owner, bid = _shop(monkeypatch)
    reader = _Reader(MENU_READING)
    _use_reader(monkeypatch, reader)
    r = client.post(f"/v1/platform/businesses/{bid}/catalogue-import/read", headers=owner,
                    json={"text": "COFFEE\nFilter coffee 40\nCold coffee (L) 120"})
    assert r.status_code == 200 and reader.mime_types == ["text/plain"]
    assert len(r.json()["data"]["rows"]) == 4

    _use_reader(monkeypatch, _Reader(RuntimeError("timeout")))
    pdf = base64.b64encode(b"%PDF-1.4 menu").decode()
    r = client.post(f"/v1/platform/businesses/{bid}/catalogue-import/read", headers=owner,
                    json={"filename": "menu.pdf", "content_base64": pdf})
    assert r.status_code == 422 and "couldn't read that file" in r.text

    from platform_core.website.ai_provider import UnavailableAIProvider
    _use_reader(monkeypatch, UnavailableAIProvider())
    r = client.post(f"/v1/platform/businesses/{bid}/catalogue-import/read", headers=owner,
                    json={"filename": "menu.pdf", "content_base64": pdf})
    assert r.status_code == 422 and ".csv or .xlsx" in r.text


@DB
def test_the_suggested_kind_follows_the_business_before_anything_is_listed(monkeypatch: Any) -> None:
    owner, cafe = _shop(monkeypatch)  # a café: its items are menu items
    read = _read(owner, cafe, "menu.csv", "Item,Price\nTea,20\n".encode("utf-8"))
    checked = client.post(f"/v1/platform/businesses/{cafe}/catalogue-import/check", headers=owner,
                          json={"rows": _mapped(read)}).json()["data"]
    assert checked["default_kind"] == "menu_item"
