# -*- coding: utf-8 -*-

from pathlib import Path

import Image2PDF as image2pdf


def test_allowed_extensions_are_case_insensitive():
    assert image2pdf.__isAllow_file("scan.JPG")
    assert image2pdf.__isAllow_file("scan.PnG")
    assert not image2pdf.__isAllow_file("scan.txt")


def test_sort_pages_uses_callback_without_mutating_input():
    pages = [
        "test_01_doc_11.png",
        "test_01_doc_2.png",
        "test_01_doc_1.png",
    ]

    sorted_pages = image2pdf.__sort_pages(
        pages,
        lambda name: Path(name).stem.split("_")[-1],
    )

    assert sorted_pages == [
        "test_01_doc_1.png",
        "test_01_doc_2.png",
        "test_01_doc_11.png",
    ]
    assert pages == [
        "test_01_doc_11.png",
        "test_01_doc_2.png",
        "test_01_doc_1.png",
    ]


def test_more_dirs_uses_full_directory_paths_and_unique_pdf_names(tmp_path, monkeypatch):
    first_book = tmp_path / "a" / "same"
    second_book = tmp_path / "b" / "same"
    first_book.mkdir(parents=True)
    second_book.mkdir(parents=True)
    (first_book / "page_1.JPG").write_bytes(b"not a real image")
    (second_book / "page_1.png").write_bytes(b"not a real image")

    captured = []

    def fake_convert(save_name, pages, filename_sort_fn=None):
        captured.append((Path(save_name).name, [Path(page).name for page in pages]))

    monkeypatch.setattr(image2pdf, "__converted", fake_convert)

    image2pdf.convert_images2PDF_more_dirs(str(tmp_path))

    output_names = {name for name, pages in captured}
    assert len(captured) == 2
    assert "same.pdf" in output_names
    assert len(output_names) == 2
    assert any(name.endswith("_same.pdf") for name in output_names)
    assert {pages[0] for name, pages in captured} == {"page_1.JPG", "page_1.png"}
