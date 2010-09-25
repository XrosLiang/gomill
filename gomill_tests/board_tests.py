"""Tests for boards.py and ascii_boards.py

We test these together because it's convenient for later boards tests to use
ascii_boards facilities.

"""

from __future__ import with_statement

from gomill_tests import gomill_test_support
from gomill_tests import board_test_data

from gomill.gomill_common import format_vertex, coords_from_vertex
from gomill import ascii_boards
from gomill import boards

def make_tests(suite):
    suite.addTests(gomill_test_support.make_simple_tests(globals()))
    for t in board_test_data.play_tests:
        suite.addTest(Play_test_TestCase(*t))
    for t in board_test_data.score_tests:
        suite.addTest(Score_test_TestCase(*t))

def test_attributes(tc):
    b = boards.Board(5)
    tc.assertEqual(b.side, 5)
    tc.assertEqual(
        b.board_coords,
        [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4),
         (1, 0), (1, 1), (1, 2), (1, 3), (1, 4),
         (2, 0), (2, 1), (2, 2), (2, 3), (2, 4),
         (3, 0), (3, 1), (3, 2), (3, 3), (3, 4),
         (4, 0), (4, 1), (4, 2), (4, 3), (4, 4)])

def test_basics(tc):
    b = boards.Board(9)

    tc.assertTrue(b.is_empty())
    tc.assertItemsEqual(b.list_occupied_points(), [])

    tc.assertEqual(b.get(2, 3), None)
    b.play(2, 3, 'b')
    tc.assertEqual(b.get(2, 3), 'b')
    tc.assertFalse(b.is_empty())
    b.play(3, 4, 'w')

    with tc.assertRaises(ValueError):
        b.play(3, 4, 'w')

    tc.assertItemsEqual(b.list_occupied_points(),
                        [('b', (2, 3)), ('w', (3, 4))])


_9x9_expected = """\
9  .  .  .  .  .  .  .  .  .
8  .  .  .  .  .  .  .  .  .
7  .  .  .  .  .  .  .  .  .
6  .  .  .  .  .  .  .  .  .
5  .  .  .  .  .  .  .  .  .
4  .  .  .  .  o  .  .  .  .
3  .  .  .  #  .  .  .  .  .
2  .  .  .  .  .  .  .  .  .
1  .  .  .  .  .  .  .  .  .
   A  B  C  D  E  F  G  H  J\
"""

_13x13_expected = """\
13  .  .  .  .  .  .  .  .  .  .  .  .  .
12  .  .  .  .  .  .  .  .  .  .  .  .  .
11  .  .  .  .  .  .  .  .  .  .  .  .  .
10  .  .  .  .  .  .  .  .  .  .  .  .  .
 9  .  .  .  .  .  .  .  .  .  .  .  .  .
 8  .  .  .  .  .  .  .  .  .  .  .  .  .
 7  .  .  .  .  .  .  .  .  .  .  .  .  .
 6  .  .  .  .  .  .  .  .  .  .  .  .  .
 5  .  .  .  .  .  .  .  .  .  .  .  .  .
 4  .  .  .  .  o  .  .  .  .  .  .  .  .
 3  .  .  .  #  .  .  .  .  .  .  .  .  .
 2  .  .  .  .  .  .  .  .  .  .  .  .  .
 1  .  .  .  .  .  .  .  .  .  .  .  .  .
    A  B  C  D  E  F  G  H  J  K  L  M  N\
"""

def test_ascii_9x9(tc):
    b = boards.Board(9)
    b.play(2, 3, 'b')
    b.play(3, 4, 'w')
    tc.assertDiagramEqual(ascii_boards.render_board(b), _9x9_expected)

def test_ascii_13x13(tc):
    b = boards.Board(13)
    b.play(2, 3, 'b')
    b.play(3, 4, 'w')
    tc.assertDiagramEqual(ascii_boards.render_board(b), _13x13_expected)

def test_copy(tc):
    b1 = boards.Board(9)
    b1.play(2, 3, 'b')
    b1.play(3, 4, 'w')
    b2 = b1.copy()
    tc.assertEqual(b1, b2)
    b2.play(5, 5, 'b')
    b2.play(2, 1, 'b')
    tc.assertNotEqual(b1, b2)
    b1.play(5, 5, 'b')
    b1.play(2, 1, 'b')
    tc.assertEqual(b1, b2)


class Play_test_TestCase(gomill_test_support.Gomill_ParameterisedTestCase):
    """Check final position reached by playing a sequence of moves."""
    test_name = "play_test"
    parameter_names = ('moves', 'diagram', 'ko_vertex', 'score')

    def runTest(self):
        b = boards.Board(9)
        ko_point = None
        for move in self.moves:
            colour, vertex = move.split()
            colour = colour.lower()
            row, col = coords_from_vertex(vertex, b.side)
            ko_point = b.play(row, col, colour)
        self.assertDiagramEqual(ascii_boards.render_board(b),
                                self.diagram.rstrip())
        if ko_point is None:
            ko_vertex = None
        else:
            ko_vertex = format_vertex(ko_point)
        self.assertEqual(ko_vertex, self.ko_vertex, "wrong ko point")
        self.assertEqual(b.area_score(), self.score, "wrong score")


class Score_test_TestCase(gomill_test_support.Gomill_ParameterisedTestCase):
    """Check score of a diagram."""
    test_name = "score_test"
    parameter_names = ('diagram', 'score')

    def runTest(self):
        b = boards.Board(9)
        gomill_test_support.play_diagram(b, self.diagram)
        self.assertEqual(b.area_score(), self.score, "wrong score")
