"""Tests for competition_schedulers.py"""

import cPickle as pickle

from gomill import competition_schedulers

from gomill_tests import gomill_test_support

def make_tests(suite):
    suite.addTests(gomill_test_support.make_simple_tests(globals()))


def test_simple(tc):
    sc = competition_schedulers.Simple_scheduler()

    def issue(n):
        result = [sc.issue() for _ in xrange(n)]
        sc._check_consistent()
        return result

    sc._check_consistent()
    tc.assertEqual(issue(4), [0, 1, 2, 3])
    sc.fix(2)
    sc._check_consistent()
    sc.fix(1)
    sc._check_consistent()
    tc.assertEqual(sc.issue(), 4)
    tc.assertEqual(sc.fixed, 2)
    tc.assertEqual(sc.issued, 5)
    sc.rollback()
    sc._check_consistent()
    tc.assertEqual(sc.issued, 2)
    tc.assertEqual(sc.fixed, 2)

    tc.assertListEqual(issue(2), [0, 3])

    sc.rollback()
    sc._check_consistent()

    tc.assertListEqual(issue(4), [0, 3, 4, 5])
    sc.fix(3)
    sc._check_consistent()
    sc.fix(5)
    sc._check_consistent()
    tc.assertEqual(sc.issue(), 6)
    sc._check_consistent()

    sc = pickle.loads(pickle.dumps(sc))
    sc._check_consistent()
    sc.rollback()
    sc._check_consistent()

    tc.assertListEqual(issue(6), [0, 4, 6, 7, 8, 9])
    tc.assertEqual(sc.issued, 10)
    tc.assertEqual(sc.fixed, 4)


def test_grouped(tc):
    sc = competition_schedulers.Group_scheduler()
    def issue(n):
        return [sc.issue() for _ in xrange(n)]

    sc.set_groups([('mz', 4), ('my', None)])

    tc.assertTrue(sc.nothing_issued_yet())
    tc.assertFalse(sc.all_fixed())

    tc.assertListEqual(issue(3), [
        ('mz', 0),
        ('my', 0),
        ('mz', 1),
        ])

    tc.assertFalse(sc.nothing_issued_yet())

    sc.fix('mz', 1)
    sc.rollback()
    issued = issue(14)
    tc.assertListEqual(issued, [
        ('my', 0),
        ('mz', 0),
        ('my', 1),
        ('mz', 2),
        ('my', 2),
        ('mz', 3),
        ('my', 3),
        ('my', 4),
        ('my', 5),
        ('my', 6),
        ('my', 7),
        ('my', 8),
        ('my', 9),
        ('my', 10),
        ])
    tc.assertFalse(sc.all_fixed())
    for token in issued:
        sc.fix(*token)
    tc.assertTrue(sc.all_fixed())
