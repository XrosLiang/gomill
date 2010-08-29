"""Organise processing jobs based around playing many GTP games."""

import os
import shlex
import sys

from gomill import game_jobs
from gomill import gtp_controller
from gomill import handicap_layout
from gomill import settings


def log_to_stdout(s):
    print s

def log_discard(s):
    pass

NoGameAvailable = object()

class CompetitionError(StandardError):
    """Error from competition code.

    Might be a bug in tuner code, or an error in a user-provided function.

    The ringmaster should display the error and terminate immediately.

    """

class ControlFileError(StandardError):
    """Error interpreting the control file."""

class Player_config(object):
    """Player description for use in tournament files."""
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

class Matchup_config(object):
    """Matchup description for use in tournament files."""
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

# We provide the same globals to all tournament files, because until we've
# exec'd it we don't know what type of competition we've got.
control_file_globals = {
    'Player' : Player_config,
    'Matchup' : Matchup_config,
    }

def game_jobs_player_from_config(player_config):
    """Make a game_jobs.Player from a Player_config.

    Raises ControlFileError with a description if there is an error in the
    configuration.

    Returns a game_jobs.Player with all required attributes set except 'code'.

    """
    args = player_config.args
    kwargs = player_config.kwargs
    player = game_jobs.Player()
    for key in kwargs:
        if key not in ('command_string', 'gtp_translations',
                       'startup_gtp_commands'):
            raise ControlFileError("unknown argument '%s'" % key)
    try:
        if len(args) > 1:
            raise ControlFileError("too many arguments")
        if len(args) == 1:
            if 'command_string' in kwargs:
                raise ControlFileError(
                    "command_string specified both implicitly and explicitly")
            command_string = args[0]
        else:
            command_string = kwargs['command_string']

        if not isinstance(command_string, str):
            raise ControlFileError("command_string not a string")
        try:
            player.cmd_args = shlex.split(command_string)
            player.cmd_args[0] = os.path.expanduser(player.cmd_args[0])
        except StandardError, e:
            raise ControlFileError("%s in command_string" % e)

        player.startup_gtp_commands = []
        if 'startup_gtp_commands' in kwargs:
            try:
                startup_gtp_commands = list(kwargs['startup_gtp_commands'])
            except StandardError:
                raise ControlFileError("'startup_gtp_commands': not a list")
            for s in startup_gtp_commands:
                try:
                    words = s.split()
                    player.startup_gtp_commands.append((words[0], words[1:]))
                except StandardError:
                    raise ControlFileError(
                        "'startup_gtp_commands': invalid command string %s" % s)

        player.gtp_translations = kwargs.get('gtp_translations', {})
        try:
            translation_items = player.gtp_translations.items()
        except StandardError:
            raise ControlFileError("'gtp_translations': not a dictionary")
        for cmd1, cmd2 in translation_items:
            if not gtp_controller.is_well_formed_gtp_word(cmd1):
                raise ControlFileError(
                    "'gtp_translations': invalid command %s" % cmd1)
            if not gtp_controller.is_well_formed_gtp_word(cmd2):
                raise ControlFileError(
                    "'gtp_translations': invalid command %s" % cmd2)

    except KeyError, e:
        raise ControlFileError("%s not specified" % e)
    return player

class Competition(object):
    """A resumable processing job based around playing many GTP games.

    This is an abstract base class.

    """
    def __init__(self, competition_code):
        self.competition_code = competition_code
        self.logger = log_to_stdout
        self.history_logger = log_discard

    def set_logger(self, logger):
        self.logger = logger

    def log(self, s):
        self.logger(s)

    def set_history_logger(self, logger):
        self.history_logger = logger

    def log_history(self, s):
        self.history_logger(s)

    # List of Settings, for overriding in subclasses.
    global_settings = []

    def initialise_from_control_file(self, config):
        """Initialise competition data from the control file.

        config -- namespace produced by the control file.

        (When resuming from saved state, this is called before set_state()).

        This processes all global_settings and sets attributes (named by the
        setting names).

        It also handles the following settings and sets the corresponding
        attributes:
          players
          preferred_scorers

        Raises ControlFileError with a description if the control file has a bad
        or missing value.

        """
        # Implementations in subclasses should have their own backstop exception
        # handlers, so they can at least show what part of the control file was
        # being interpreted when the exception occurred.

        # We should accept that there may be unexpected exceptions, because
        # control files are allowed to do things like substitute list-like
        # objects for Python lists.

        try:
            to_set = settings.load_settings(self.global_settings, config)
        except ValueError, e:
            raise ControlFileError(str(e))
        for name, value in to_set.items():
            setattr(self, name, value)

        try:
            config_players = config['players']
        except KeyError, e:
            raise ControlFileError("%s not specified" % e)
        self.players = {}
        try:
            try:
                player_items = config_players.items()
            except StandardError:
                raise ControlFileError("'players': not a dictionary")
            # pre-check player codes before trying to sort them, just in case
            for player_code, _ in player_items:
                if not isinstance(player_code, basestring):
                    raise ControlFileError("'players': bad code (not a string)")
            for player_code, player_config in sorted(player_items):
                try:
                    player_code = settings.interpret_identifier(player_code)
                except ValueError, e:
                    if isinstance(player_code, unicode):
                        player_code = player_code.encode("ascii", "replace")
                    raise ControlFileError(
                        "'players': bad code (%s): %s" % (e, player_code))
                if not isinstance(player_config, Player_config):
                    raise ControlFileError("player %s is %r, not a Player" %
                                           (player_code, player_config))
                try:
                    player = game_jobs_player_from_config(player_config)
                except StandardError, e:
                    raise ControlFileError("player %s: %s" % (player_code, e))
                player.code = player_code
                self.players[player_code] = player

            # NB, this isn't properly validated. I'm planning to change the
            # system anyway.
            self.preferred_scorers = config.get('preferred_scorers')
        except ControlFileError:
            raise
        except StandardError, e:
            raise ControlFileError("'players': unexpected error: %s" % e)

    def get_status(self):
        """Return full state of the competition, so it can be resumed later.

        The returned result must be serialisable using json. In addition, it can
        include Game_result objects.

        """
        raise NotImplementedError

    def set_status(self, status):
        """Reset competition state to previously a reported value.

        'status' will be a value previously reported by get_status().

        This is called for the 'show' command, so it mustn't log anything.

        """
        raise NotImplementedError

    def set_clean_status(self):
        """Reset competition state to its initial value.

        This is called before logging is set up, so it mustn't log anything.

        """
        raise NotImplementedError

    def get_game(self):
        """Return the details of the next game to play.

        Returns a game_jobs.Game_job, or NoGameAvailable

        (Doesn't set sgf_pathname: the ringmaster does that).

        """
        raise NotImplementedError

    def process_game_result(self, response):
        """Process the results from a completed game.

        response -- game_jobs.Game_job_result

        """
        raise NotImplementedError

    def process_game_error(self, job, previous_error_count):
        """Process a report that a job failed.

        job                  -- game_jobs.Game_job
        previous_error_count -- int >= 0

        Returns a pair of bools (stop_competition, retry_game)

        If stop_competition is True, the ringmaster will stop starting new
        games. Otherwise, if retry_game is true the ringmaster will try running
        the same game again.

        The job is one previously returned by get_game(). previous_error_count
        is the number of times that this particular job has failed before.

        Failed jobs are ones in which there was an error more serious than one
        which just causes an engine to forfeit the game. For example, the job
        will fail if one of the engines fails to respond to GTP commands at all,
        or (in particular) if it exits as soon as it's invoked because it
        doesn't like its command-line options.

        (Competition provides a default implementation which will retry a game
         once and then stop the competition.)

        """
        if previous_error_count > 0:
            return (True, True)
        else:
            return (False, True)

    def write_static_description(self, out):
        """Write a description of the competition.

        out -- writeable file-like object

        This reports on 'static' data, rather than the game results.

        """
        raise NotImplementedError

    def write_status_summary(self, out):
        """Write a summary of current competition status.

        out -- writeable file-like object

        This reports on the game results, and shouldn't duplicate information
        from write_static_description().

        """
        raise NotImplementedError

    def write_results_report(self, out):
        """Write a detailed report of a completed competition.

        out -- writeable file-like object

        This reports on the game results, and shouldn't duplicate information
        from write_static_description() or write_status_summary().

        """
        raise NotImplementedError


## Helper functions for settings

def interpret_board_size(i):
    i = settings.interpret_int(i)
    if i < 2:
        raise ValueError("too small")
    if i > 25:
        raise ValueError("too large")
    return i

def validate_handicap(handicap, handicap_style, board_size):
    """Check whether a handicap is allowed.

    handicap       -- int or None
    handicap_style -- 'free' or 'fixed'
    board_size     -- int

    Raises ControlFileError with a description if it isn't.

    """
    if handicap is None:
        return True
    if handicap < 2:
        raise ControlFileError("handicap too small")
    if handicap_style == 'fixed':
        limit = handicap_layout.max_fixed_handicap_for_board_size(board_size)
    else:
        limit = handicap_layout.max_free_handicap_for_board_size(board_size)
    if handicap > limit:
        raise ControlFileError(
            "%s handicap out of range for board size %d" %
            (handicap_style, board_size))


class Id_allocator(object):
    """Allocate numeric IDs, keeping track of which have been finished with.

    The issued ids are integers counting up from zero.

    After rollback() is called, all ids which have not been fixed will be
    reissued on subsequent calls to issue().

    This class is suitable for pickling.

    """
    def __init__(self):
        self.next_new = 0
        self.outstanding = set()
        self.to_reissue = set()

    def __getstate__(self):
        return (self.next_new, self.outstanding, self.to_reissue)

    def __setstate__(self, state):
        (self.next_new, self.outstanding, self.to_reissue) = state

    def issue(self):
        if self.to_reissue:
            result = min(self.to_reissue)
            self.to_reissue.discard(result)
        else:
            result = self.next_new
            self.next_new += 1
        self.outstanding.add(result)
        return result

    def fix(self, i):
        self.outstanding.remove(i)

    def rollback(self):
        self.to_reissue.update(self.outstanding)
        self.outstanding = set()

    def count_issued(self):
        """Return the number of ids which have been issued."""
        return self.next_new - len(self.to_reissue)

    def count_fixed(self):
        """Return the number of ids which have been fixed."""
        return self.next_new - len(self.outstanding) - len(self.to_reissue)

class Tagged_id_allocator(object):
    """Convenience class for managing multiple Id_allocators.

    This class is suitable for pickling.

    The issued ids are strings of the form '<tag>_<i>'.

    """
    def __init__(self):
        self.allocators = {}

    def __getstate__(self):
        return self.allocators

    def __setstate__(self, state):
        self.allocators = state

    def add_tag(self, tag):
        if '_' in tag:
            raise ValueError
        self.allocators[tag] = Id_allocator()

    def issue(self, tag):
        if tag not in self.allocators:
            self.add_tag(tag)
        return "%s_%d" % (tag, self.allocators[tag].issue())

    def fix(self, id_string):
        tag, i_s = id_string.split("_")
        self.allocators[tag].fix(int(i_s))

    def rollback(self):
        for allocator in self.allocators.itervalues():
            allocator.rollback()

    def lowest_issued(self):
        """Find the tag with the fewest issued ids, and how many ids there were.

        Returns a pair (tag, number issued)

        If there are multiple tags with the same number issued, chooses the
        alphabetically first tag.

        """
        n, tag = min(
            (allocator.count_issued(), tag)
            for (tag, allocator) in self.allocators.iteritems())
        return tag, n

    def highest_issued(self):
        """Find the tag with the most issued ids, and how many ids there were.

        Returns a pair (tag, number issued)

        If there are multiple tags with the same number issued, chooses the
        alphabetically last tag.

        """
        n, tag = max(
            (allocator.count_issued(), tag)
            for (tag, allocator) in self.allocators.iteritems())
        return tag, n

    def lowest_fixed(self):
        """Find the tag with the fewest fixed ids, and how many ids there were.

        Returns a pair (tag, number fixed)

        If there are multiple tags with the same number fixed, chooses the
        alphabetically first tag.

        """
        n, tag = min(
            (allocator.count_fixed(), tag)
            for (tag, allocator) in self.allocators.iteritems())
        return tag, n

    def highest_fixed(self):
        """Find the tag with the most fixed ids, and how many ids there were.

        Returns a pair (tag, number fixed)

        If there are multiple tags with the same number fixed, chooses the
        alphabetically last tag.

        """
        n, tag = max(
            (allocator.count_fixed(), tag)
            for (tag, allocator) in self.allocators.iteritems())
        return tag, n


class Group_scheduler(object):
    """Schedule multiple lists of games in parallel.

    This schedules for a number of _groups_, each of which may have a limit on
    the number of games to play. It schedules from the group (of those which
    haven't reached their limit) with the fewest issued games, with smallest
    group code breaking ties.

    group codes might be ints or short strings
    (any sortable, pickleable and hashable object should do).

    The issued tokens are pairs (group code, game number), with game numbers
    counting up from 0 independently for each group code.

    This class is suitable for pickling.

    """
    def __init__(self):
        self.allocators = {}
        self.limits = {}

    def __getstate__(self):
        return (self.allocators, self.limits)

    def __setstate__(self, state):
        (self.allocators, self.limits) = state

    def set_groups(self, group_specs):
        """Set the groups to be scheduled.

        group_specs -- iterable of pairs (group code, limit)
          limit -- int or None

        You can call this again after the first time. The limits will be set to
        the new values. Any existing groups not in the list are forgotten.

        """
        new_allocators = {}
        new_limits = {}
        for group_code, limit in group_specs:
            if group_code in self.allocators:
                new_allocators[group_code] = self.allocators[group_code]
            else:
                new_allocators[group_code] = Id_allocator()
            new_limits[group_code] = limit
        self.allocators = new_allocators
        self.limits = new_limits

    def issue(self):
        """Choose the next game to start.

        Returns a pair (group code, game number)

        Returns (None, None) if all groups have reached their limit.

        """
        groups = [
            (group_code, allocator.count_issued(), self.limits[group_code])
            for (group_code, allocator) in self.allocators.iteritems()
            ]
        available = [
            (issue_count, group_code)
            for (group_code, issue_count, limit) in groups
            if limit is None or issue_count < limit
            ]
        if not available:
            return None, None
        _, group_code = min(available)
        return group_code, self.allocators[group_code].issue()

    def fix(self, group_code, game_number):
        """Note that a game's result has been reliably stored."""
        self.allocators[group_code].fix(game_number)

    def rollback(self):
        """Make issued-but-not-fixed tokens available again."""
        for allocator in self.allocators.itervalues():
            allocator.rollback()

