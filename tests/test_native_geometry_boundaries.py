"""Native geometry preserves the reference buffer and integer boundaries."""

import logging

import pytest

import hotcore
from hotcore import geometry

LOGGER = logging.getLogger(__name__)


def _implementations():
    yield geometry
    if hotcore._native is not None:
        yield hotcore._native


@pytest.mark.parametrize("buffer_type", [bytes, bytearray])
def test_mask_scans_accept_mutable_and_immutable_byte_buffers(buffer_type):
    mask = buffer_type([0, 255, 255, 0, 255, 255, 255, 255, 255, 0])
    for implementation in _implementations():
        LOGGER.debug("Checking mask buffer parity with %s", implementation.__name__)
        assert implementation.row_widths(mask, 5, 2) == [2, 4]
        assert implementation.band_span(mask, 5, 2, 0, 2) == [1, 2]


def test_box_gap_does_not_wrap_when_a_rectangle_crosses_i64_maximum():
    near_limit = [2**63 - 6, 0, 10, 10]
    origin = [0, 0, 1, 1]
    for implementation in _implementations():
        assert implementation.box_gap(near_limit, origin) == pytest.approx(2**63 - 7)


def test_cluster_boxes_does_not_merge_distant_rectangles_after_overflow():
    near_limit = [2**63 - 6, 0, 10, 10]
    origin = [0, 0, 1, 1]
    for implementation in _implementations():
        assert implementation.cluster_boxes([near_limit, origin]) == [[near_limit], [origin]]
