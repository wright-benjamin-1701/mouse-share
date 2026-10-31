"""Tests for the escape hotkey detector."""

from __future__ import annotations

from mouse_share.hotkey import ESCAPE_COMBO, HotkeyDetector

_LCTRL = 0xE0
_LALT = 0xE2
_ESCAPE = 0x29


class TestHotkeyDetector:
    def test_single_key_does_not_trigger(self) -> None:
        hk = HotkeyDetector()
        assert not hk.key_event(_LCTRL, True)
        assert not hk.key_event(_LALT, True)
        assert not hk.key_event(0x04, True)  # 'A' key

    def test_two_keys_do_not_trigger(self) -> None:
        hk = HotkeyDetector()
        assert not hk.key_event(_LCTRL, True)
        assert not hk.key_event(_LALT, True)

    def test_full_combo_triggers(self) -> None:
        hk = HotkeyDetector()
        assert not hk.key_event(_LCTRL, True)
        assert not hk.key_event(_LALT, True)
        assert hk.key_event(_ESCAPE, True)

    def test_combo_order_independent(self) -> None:
        hk = HotkeyDetector()
        assert not hk.key_event(_ESCAPE, True)
        assert not hk.key_event(_LCTRL, True)
        assert hk.key_event(_LALT, True)

    def test_release_one_clears(self) -> None:
        hk = HotkeyDetector()
        hk.key_event(_LCTRL, True)
        hk.key_event(_LALT, True)
        assert hk.key_event(_ESCAPE, True)
        # Release ctrl — combo no longer active
        assert not hk.key_event(_LCTRL, False)

    def test_repress_retriggers(self) -> None:
        hk = HotkeyDetector()
        hk.key_event(_LCTRL, True)
        hk.key_event(_LALT, True)
        assert hk.key_event(_ESCAPE, True)
        # Release and re-press escape
        hk.key_event(_ESCAPE, False)
        assert hk.key_event(_ESCAPE, True)

    def test_unrelated_keys_ignored(self) -> None:
        hk = HotkeyDetector()
        hk.key_event(0x04, True)  # 'A'
        hk.key_event(0x05, True)  # 'B'
        hk.key_event(_LCTRL, True)
        hk.key_event(_LALT, True)
        # Extra keys don't prevent trigger
        assert hk.key_event(_ESCAPE, True)

    def test_escape_combo_constant(self) -> None:
        assert frozenset({_LCTRL, _LALT, _ESCAPE}) == ESCAPE_COMBO
