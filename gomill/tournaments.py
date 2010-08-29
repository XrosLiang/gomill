"""Competitions made up of repeated matchups between specified players."""

from __future__ import division

import cPickle as pickle
from collections import defaultdict

from gomill import game_jobs
from gomill import competitions
from gomill.competitions import (
    Competition, NoGameAvailable, Matchup_config, ControlFileError)
from gomill.settings import *


class Matchup(object):
    """Internal description of a matchup from the configuration file.

    Public attributes:
      p1             -- player code
      p2             -- player code
      name           -- shortish string to show in reports
      games_started  -- int

    All Tournament matchup_settings are also available as attributes.

    If alternating is False, p1 plays black and p2 plays white; otherwise they
    alternate.

    """
    def __init__(self):
        self.games_started = 0


class _Required_in_matchup(object):
    def __str__(self):
        return "(no global default)"
_required_in_matchup = _Required_in_matchup()

class Matchup_setting(Setting):
    # Treat 'default' as a keyword-only argument
    def __init__(self, *args, **kwargs):
        if 'default' not in kwargs:
            kwargs['default'] = _required_in_matchup
        Setting.__init__(self, *args, **kwargs)


class Tournament(Competition):
    """A Competition made up of repeated matchups between specified players."""

    # These settings can be specified both globally and in matchups.
    # The global values (stored as Tournament attributes) are defaults for the
    # matchup values (stored as Matchup attributes).
    matchup_settings = [
        Matchup_setting('board_size', competitions.interpret_board_size),
        Matchup_setting('komi', interpret_float),
        Matchup_setting('alternating', interpret_bool, default=False),
        Matchup_setting('handicap', allow_none(interpret_int), default=None),
        Matchup_setting('handicap_style', interpret_enum('fixed', 'free'),
                        default='fixed'),
        Matchup_setting('move_limit', interpret_positive_int, default=1000),
        Matchup_setting('scorer', interpret_enum('internal', 'players'),
                        default='players'),
        Matchup_setting('number_of_games', allow_none(interpret_int),
                        default=None),
        ]

    global_settings = matchup_settings + [
        Setting('description', interpret_as_utf8, default=""),
        ]

    def matchup_from_config(self, matchup_config):
        """Make a Matchup from a Matchup_config.

        Raises ControlFileError if there is an error in the configuration.

        Returns a Matchup with all attributes set.

        """
        if not isinstance(matchup_config, Matchup_config):
            raise ControlFileError("not a Matchup")

        args = matchup_config.args
        kwargs = matchup_config.kwargs
        matchup = Matchup()
        argument_names = set(setting.name for setting in self.matchup_settings)
        argument_names.update(('name',))
        for key in kwargs:
            if key not in argument_names:
                raise ControlFileError("unknown argument '%s'" % key)
        if len(args) > 2:
            raise ControlFileError("too many arguments")
        if len(args) < 2:
            raise ControlFileError("not enough arguments")
        matchup.p1, matchup.p2 = args

        if matchup.p1 not in self.players:
            raise ControlFileError("unknown player %s" % matchup.p1)
        if matchup.p2 not in self.players:
            raise ControlFileError("unknown player %s" % matchup.p2)

        for setting in self.matchup_settings:
            if setting.name in kwargs:
                try:
                    v = setting.interpret(kwargs[setting.name])
                except ValueError, e:
                    raise ControlFileError(str(e))
            else:
                v = getattr(self, setting.name)
                if v is _required_in_matchup:
                    raise ControlFileError("'%s' not specified" % setting.name)
            setattr(matchup, setting.name, v)

        competitions.validate_handicap(
            matchup.handicap, matchup.handicap_style, matchup.board_size)

        name = kwargs.get('name')
        if name is None:
            name = "%s v %s" % (matchup.p1, matchup.p2)
        else:
            try:
                name = interpret_as_utf8(name)
            except ValueError, e:
                raise ControlFileError("name: %s" % e)
        matchup.name = name
        return matchup

    def initialise_from_control_file(self, config):
        Competition.initialise_from_control_file(self, config)

        # Check default handicap settings when possible, for friendlier error
        # reporting (would be caught in the matchup anyway).
        if self.board_size is not _required_in_matchup:
            try:
                competitions.validate_handicap(
                    self.handicap, self.handicap_style, self.board_size)
            except ControlFileError, e:
                raise ControlFileError("default %s" % e)

        try:
            try:
                config_matchups = config['matchups']
            except KeyError, e:
                raise ControlFileError("%s not specified" % e)
            try:
                config_matchups = list(config_matchups)
            except StandardError:
                raise ControlFileError("'matchups': not a list")
            if not config_matchups:
                raise ControlFileError("no matchups specified")

            # List of Matchups indexed by matchup_id
            self.matchups = []
            for i, matchup in enumerate(config_matchups):
                try:
                    m = self.matchup_from_config(matchup)
                except StandardError, e:
                    raise ControlFileError("matchup entry %d: %s" % (i, e))
                m.id = i
                self.matchups.append(m)
        except ControlFileError:
            raise
        except StandardError, e:
            raise ControlFileError("'matchups': unexpected error: %s" % e)


    # State attributes (*: in persistent state):
    #  *results             -- list of pairs (matchup_id, Game_result)
    #  *game_id_allocator   -- Id_allocator
    #  *engine_names        -- map player code -> string
    #  *engine_descriptions -- map player code -> string
    #   outstanding_games   -- map game id ->
    #                                (matchup_id, b_player_code, w_player_code)
    #  (number of games started is in the Matchup objects, and not persisted)

    def set_clean_status(self):
        self.results = []
        self.engine_names = {}
        self.engine_descriptions = {}
        self.outstanding_games = {}
        self.game_id_allocator = competitions.Id_allocator()

    def get_status(self):
        return {
            'results' : self.results,
            'game_id_allocator' : pickle.dumps(self.game_id_allocator),
            'engine_names' : self.engine_names,
            'engine_descriptions' : self.engine_descriptions,
            }

    def set_status(self, status):
        self.results = status['results']
        self.game_id_allocator = pickle.loads(
            status['game_id_allocator'].encode('iso-8859-1'))
        self.game_id_allocator.rollback()
        self.engine_names = status['engine_names']
        self.engine_descriptions = status['engine_descriptions']
        for matchup_id, result in self.results:
            self.matchups[matchup_id].games_started += 1
        self.outstanding_games = {}

    def find_match(self):
        """Find the players for the next game.

        Returns a tuple (matchup, black player code, white player code)

        Returns (None, None, None) if all matchups are complete.

        """
        available = [
            m for m in self.matchups
            if m.number_of_games is None or m.games_started < m.number_of_games
            ]
        if not available:
            return None, None, None
        matchup = min(available, key=lambda m: (m.games_started, m.id))

        if matchup.alternating and (matchup.games_started % 2):
            pb, pw = matchup.p2, matchup.p1
        else:
            pb, pw = matchup.p1, matchup.p2
        return matchup, pb, pw

    def get_game(self):
        game_id = str(self.game_id_allocator.issue())

        matchup, player_b, player_w = self.find_match()
        if matchup is None:
            return NoGameAvailable
        matchup.games_started += 1
        self.outstanding_games[game_id] = (matchup.id, player_b, player_w)

        job = game_jobs.Game_job()
        job.game_id = game_id
        job.player_b = self.players[player_b]
        job.player_w = self.players[player_w]
        job.board_size = matchup.board_size
        job.komi = matchup.komi
        job.move_limit = matchup.move_limit
        job.handicap = matchup.handicap
        job.handicap_is_free = (matchup.handicap_style == 'free')
        job.use_internal_scorer = (matchup.scorer == 'internal')
        job.preferred_scorers = self.preferred_scorers
        job.sgf_event = self.competition_code
        return job

    def process_game_result(self, response):
        self.engine_names.update(response.engine_names)
        self.engine_descriptions.update(response.engine_descriptions)
        self.game_id_allocator.fix(int(response.game_id))
        matchup_id, player_b, player_w = self.outstanding_games.pop(
            response.game_id)
        assert player_b == response.game_result.player_b
        assert player_w == response.game_result.player_w
        self.results.append((matchup_id, response.game_result))
        self.log_history("%4s %s" %
                         (response.game_id, response.game_result.describe()))

    def write_static_description(self, out):
        def p(s):
            print >>out, s
        p("tournament: %s" % self.competition_code)
        for code, description in sorted(self.engine_descriptions.items()):
            p("player %s: %s" % (code, description))
        p("board size: %s" % self.board_size)
        p("komi: %s" % self.komi)
        p(self.description)

    def write_status_summary(self, out):
        results_by_matchup_id = defaultdict(list)
        for matchup_id, result in self.results:
            results_by_matchup_id[matchup_id].append(result)
        for (i, matchup) in enumerate(self.matchups):
            results = results_by_matchup_id[i]
            if results:
                self.write_matchup_report(out, matchup, results)

    def write_results_report(self, out):
        pass

    def write_matchup_report(self, out, matchup, results):
        def p(s):
            print >>out, s
        total = len(results)
        assert total != 0
        player_x = matchup.p1
        player_y = matchup.p2
        x_wins = sum(r.winning_player == player_x for r in results)
        y_wins = sum(r.winning_player == player_y for r in results)
        unknown = sum(r.winning_player is None for r in results)
        b_wins = sum(r.winning_colour == 'b' for r in results)
        w_wins = sum(r.winning_colour == 'w' for r in results)
        xb_wins = sum(r.winning_player == player_x and r.winning_colour == 'b'
                      for r in results)
        xw_wins = sum(r.winning_player == player_x and r.winning_colour == 'w'
                      for r in results)
        yb_wins = sum(r.winning_player == player_y and r.winning_colour == 'b'
                      for r in results)
        yw_wins = sum(r.winning_player == player_y and r.winning_colour == 'w'
                      for r in results)
        xb_played = sum(r.player_b == player_x for r in results)
        xw_played = sum(r.player_w == player_x for r in results)
        yb_played = sum(r.player_b == player_y for r in results)
        yw_played = sum(r.player_w == player_y for r in results)

        x_times = [r.cpu_times[player_x] for r in results]
        x_known_times = [t for t in x_times if t is not None and t != '?']
        if x_known_times:
            x_avg_time_s = "%7.2f" % (sum(x_known_times) / len(x_known_times))
        else:
            x_avg_time_s = "----"
        y_times = [r.cpu_times[player_y] for r in results]
        y_known_times = [t for t in y_times if t is not None and t != '?']
        if y_known_times:
            y_avg_time_s = "%7.2f" % (sum(y_known_times) / len(y_known_times))
        else:
            y_avg_time_s = "----"

        if matchup.number_of_games is None:
            played_s = "%d" % total
        else:
            played_s = "%d/%d" % (total, matchup.number_of_games)
        p("%s (%s games)" % (matchup.name, played_s))
        def pct(n, baseline):
            if baseline == 0:
                if n == 0:
                    return "--"
                else:
                    return "??"
            return "%.2f%%" % (100 * n/baseline)
        if unknown > 0:
            p("unknown results: %d %s" % (unknown, pct(unknown, total)))

        pad = max(len(player_x), len(player_y)) + 2
        xname = player_x.ljust(pad)
        yname = player_y.ljust(pad)

        p(" " * (pad+17) + "   black         white        avg cpu")
        p("%s %4d %7s    %4d %7s  %4d %7s  %s"
          % (xname, x_wins, pct(x_wins, total),
             xb_wins, pct(xb_wins, xb_played),
             xw_wins, pct(xw_wins, xw_played),
             x_avg_time_s))
        p("%s %4d %7s    %4d %7s  %4d %7s  %s"
          % (yname, y_wins, pct(y_wins, total),
             yb_wins, pct(yb_wins, yb_played),
             yw_wins, pct(yw_wins, yw_played),
             y_avg_time_s))
        p(" " * (pad+17) + "%4d %7s  %4d %7s"
          % (b_wins, pct(b_wins, total), w_wins, pct(w_wins, total)))
        p("")

