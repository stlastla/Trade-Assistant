import pandas as pd
from structure import detect_structure_breaks


def test_detect_structure_breaks():
    # Hand-traced with left=right=1. Expect: MSS up @5, BOS up @8, MSS down @9.
    df = pd.DataFrame({
        'high':  [5, 8, 5, 10, 7, 9, 12, 9, 14, 8, 6],
        'low':   [3, 4, 3, 6,  4, 6, 8,  6, 9,  3, 2],
        'close': [4, 5, 9, 7,  6, 11, 10, 8, 13, 4, 3],
    })
    ev = detect_structure_breaks(df, left=1, right=1)
    got = [(e['index'], e['direction'], e['kind']) for e in ev]
    assert got == [(5, 'up', 'MSS'), (8, 'up', 'BOS'), (9, 'down', 'MSS')]
    assert ev[0]['level'] == 10 and ev[0]['swing_index'] == 3
    assert ev[2]['level'] == 6 and ev[2]['swing_index'] == 7


def test_no_break_without_close_through():
    # Price wicks above the swing high but never CLOSES above it -> no break.
    df = pd.DataFrame({
        'high':  [5, 8, 5, 10, 9],
        'low':   [3, 4, 3, 6,  4],
        'close': [4, 5, 4, 7,  7],  # close 7 never > swing-high level 8
    })
    assert detect_structure_breaks(df, left=1, right=1) == []
