from purchase_notify import build_message, digits_only


def test_digits_only_strips_spaces_and_plus():
    assert digits_only("+267 71 123 456") == "26771123456"


def test_build_message_includes_whatsapp_and_price():
    subject, body = build_message(
        "Ada", "ada@example.com", "+267 71123456", "Exness", "Ready this week",
    )
    assert "Ada" in subject
    assert "+267 71123456" in subject
    assert "WhatsApp: +267 71123456" in body
    assert "ada@example.com" in body
    assert "P1,500" in body
    assert "P300" in body
    assert "P1,800" in body
