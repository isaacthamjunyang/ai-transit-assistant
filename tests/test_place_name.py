"""Display casing for OneMap names. Original values stay available for logic."""

from onemap import _place, format_display_address, format_place_name


def test_nested_college_name_unwraps_and_keeps_the_inner_acronym():
    assert (
        format_place_name("NUS (RIDGE VIEW RESIDENTIAL COLLEGE (RVRC))")
        == "NUS Ridge View Residential College (RVRC)"
    )


def test_small_words_and_parenthetical_acronyms():
    assert (
        format_place_name("NUS CENTRE FOR ANIMAL RESOURCES (CARE)")
        == "NUS Centre for Animal Resources (CARE)"
    )


def test_address_drops_the_repeated_name_and_keeps_the_postal_line():
    name = "NUS (RIDGE VIEW RESIDENTIAL COLLEGE (RVRC))"
    address = (
        "25 LOWER KENT RIDGE ROAD NUS (RIDGE VIEW RESIDENTIAL COLLEGE (RVRC)) "
        "SINGAPORE 119081"
    )
    assert format_display_address(address, name=name) == (
        "25 Lower Kent Ridge Road, Singapore 119081"
    )


def test_marina_bay_sands_is_title_cased():
    assert format_place_name("MARINA BAY SANDS") == "Marina Bay Sands"


def test_block_and_abbreviation():
    assert format_place_name("BLK 123A BEDOK NORTH AVENUE 2") == (
        "Blk 123A Bedok North Avenue 2"
    )


def test_saint_andrews_keeps_the_apostrophe():
    assert format_place_name("ST. ANDREW'S ROAD") == "St. Andrew's Road"


def test_at_sign_stays_and_the_leading_small_word_is_capitalised():
    assert format_place_name("THE FLOAT @ MARINA BAY") == "The Float @ Marina Bay"


def test_mixed_case_is_unchanged():
    assert format_place_name("Marina Bay Sands") == "Marina Bay Sands"
    assert format_place_name("VivoCity") == "VivoCity"


def test_search_result_keeps_the_original_for_matching():
    place = _place({
        "BUILDING": "MARINA BAY SANDS",
        "SEARCHVAL": "MARINA BAY SANDS",
        "ADDRESS": "10 BAYFRONT AVENUE SINGAPORE 018956",
        "BLK_NO": "10",
        "ROAD_NAME": "BAYFRONT AVENUE",
        "POSTAL": "018956",
        "LATITUDE": "1.2834",
        "LONGITUDE": "103.8607",
    })
    assert place["label"] == "MARINA BAY SANDS"
    assert place["address"] == "10 BAYFRONT AVENUE SINGAPORE 018956"
    assert place["label_display"] == "Marina Bay Sands"
    assert place["address_display"] == "10 Bayfront Avenue, Singapore 018956"
