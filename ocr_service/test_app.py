from ocr_service.app import _elements


def test_elements_preserve_parsing_reading_order() -> None:
    payload = {
        "parsing_res_list": [
            {
                "block_label": "text",
                "block_content": "before",
                "block_bbox": [10, 10, 100, 30],
                "block_order": 0,
            },
            {
                "block_label": "table",
                "block_content": "table",
                "block_bbox": [10, 40, 100, 60],
            },
            {
                "block_label": "text",
                "block_content": "after",
                "block_bbox": [10, 70, 100, 90],
                "block_order": 1,
            },
        ]
    }

    assert [item["content"] for item in _elements(payload)] == [
        "before",
        "table",
        "after",
    ]


def test_elements_match_layout_confidence_with_rounded_bbox() -> None:
    payload = {
        "parsing_res_list": [
            {
                "block_label": "formula",
                "block_content": "x^2",
                "block_bbox": [10, 10, 110, 60],
            }
        ],
        "layout_det_res": {
            "boxes": [
                {
                    "label": "formula",
                    "coordinate": [10.4, 9.8, 110.2, 60.3],
                    "score": 0.91,
                }
            ]
        },
    }

    assert _elements(payload)[0]["confidence"] == 0.91
