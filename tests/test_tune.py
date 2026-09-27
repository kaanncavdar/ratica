from ratica.tune import CALIBRATION, pick_slots


def test_picks_the_fastest_setting():
    assert pick_slots({1: 50, 2: 80, 4: 110, 6: 118}) == 6


def test_prefers_fewer_slots_when_the_gain_is_small():
    # 6 slots is only 2% faster than 4: not worth the extra memory
    assert pick_slots({1: 50, 2: 80, 4: 115, 6: 117}) == 4


def test_single_slot_when_parallel_does_not_help():
    assert pick_slots({1: 6.0, 2: 5.8}) == 1


def test_calibration_text_is_several_plain_paragraphs():
    assert len(CALIBRATION) >= 6
    assert all(40 <= len(p.split()) <= 120 for p in CALIBRATION)
