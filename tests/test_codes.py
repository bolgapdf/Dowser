from __future__ import annotations

import pytest

from dowser import encode, parse


def test_address_is_byte_swapped():
    """The reason published codes look back to front."""
    code = encode(0xDA19, 0xFF)[0]
    assert code.text == "01FF19DA"


def test_round_trip():
    original = encode(0xC123, 0x63)[0]
    assert parse(original.text) == original


def test_parse_accepts_the_formatting_people_paste():
    for text in ("01FF19DA", "01ff19da", "01FF-19DA", " 01 FF 19 DA ", "01FF:19DA"):
        assert parse(text).address == 0xDA19
        assert parse(text).value == 0xFF


def test_parse_rejects_the_wrong_length():
    with pytest.raises(ValueError, match="eight-digit"):
        parse("01FF19")


def test_sixteen_bit_value_becomes_two_codes_low_byte_first():
    codes = encode(0xD100, 9999, width=16)
    assert len(codes) == 2
    assert codes[0].value == 9999 & 0xFF
    assert codes[1].value == 9999 >> 8
    assert codes[1].address == 0xD101


def test_high_work_ram_banks_are_flagged_not_guessed():
    assert encode(0xD040, 1, bank=5)[0].ambiguous_bank
    # Bank 1 is what a mono game always sees at 0xD000, so it needs no caveat.
    assert not encode(0xD040, 1, bank=1)[0].ambiguous_bank
    # 0xC000 isn't banked at all.
    assert not encode(0xC040, 1, bank=5)[0].ambiguous_bank


def test_values_must_fit():
    with pytest.raises(ValueError, match="does not fit"):
        encode(0xC000, 256)
    with pytest.raises(ValueError, match="does not fit"):
        encode(0xC000, 70000, width=16)


def test_address_range_is_checked():
    with pytest.raises(ValueError, match="out of range"):
        encode(0x1FFFF, 1)
