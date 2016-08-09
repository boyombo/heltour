from django.shortcuts import get_object_or_404, render, redirect
from django.http.response import Http404
from django.utils import timezone
from datetime import timedelta
from .models import *
from .forms import *
from heltour.tournament.templatetags.tournament_extras import leagueurl
import itertools
from django.db.models.query import Prefetch

def league_home(request, league_tag=None, season_id=None):
    league = _get_league(league_tag, allow_none=True)
    if league is None:
        return render(request, 'tournament/no_leagues.html', {})
    
    rules_doc = LeagueDocument.objects.filter(league=league, type='rules').first()
    rules_doc_tag = rules_doc.tag if rules_doc is not None else None
    intro_doc = LeagueDocument.objects.filter(league=league, type='intro').first()
    
    current_season = _get_default_season(league_tag, allow_none=True)
    if current_season is None:
        context = {
            'league_tag': league_tag,
            'league': league,
            'season_id': season_id,
            'rules_doc_tag': rules_doc_tag,
            'intro_doc': intro_doc,
            'can_edit_document': request.user.has_perm('tournament.change_document'),
        }
        return render(request, 'tournament/league_home.html', context)
    
    season_list = Season.objects.filter(league=_get_league(league_tag)).order_by('-start_date', '-id').exclude(pk=current_season.pk)
    registration_season = Season.objects.filter(league=league, registration_open=True).order_by('-start_date').first()
    
    team_scores = list(enumerate(sorted(TeamScore.objects.filter(team__season=current_season), reverse=True)[:5], 1))
    
    # TODO: Use the lichess api to check the game status and remove games even if a game link hasn't been posted yet
    # TODO: Convert game times to the user's local time (maybe in JS?)
    current_game_time_min = timezone.now() - timedelta(hours=3)
    current_game_time_max = timezone.now() + timedelta(minutes=5)
    current_games = PlayerPairing.objects.filter(result=u'\u2694', scheduled_time__gt=current_game_time_min, scheduled_time__lt=current_game_time_max).exclude(game_link='').order_by('scheduled_time')
    upcoming_game_time_min = timezone.now() - timedelta(minutes=5)
    upcoming_game_time_max = timezone.now() + timedelta(hours=12)
    upcoming_games = PlayerPairing.objects.filter(game_link='', result='', scheduled_time__gt=upcoming_game_time_min, scheduled_time__lt=upcoming_game_time_max).order_by('scheduled_time')
    
    context = {
        'league_tag': league_tag,
        'league': league,
        'season_id': season_id,
        'season': current_season,
        'team_scores': team_scores,
        'season_list': season_list,
        'rules_doc_tag': rules_doc_tag,
        'intro_doc': intro_doc,
        'can_edit_document': request.user.has_perm('tournament.change_document'),
        'registration_season': registration_season,
        'current_games': current_games,
        'upcoming_games': upcoming_games,
    }
    return render(request, 'tournament/league_home.html', context)

def season_landing(request, league_tag=None, season_id=None):
    season = _get_season(league_tag, season_id)
    default_season = _get_default_season(league_tag)
    season_list = Season.objects.filter(league=_get_league(league_tag)).order_by('-start_date', '-id').exclude(pk=default_season.pk)
    
    active_round = Round.objects.filter(season=season, publish_pairings=True, is_completed=False, start_date__lt=timezone.now(), end_date__gt=timezone.now()).order_by('-number').first()
    last_round = Round.objects.filter(season=season, is_completed=True).order_by('-number').first()
    last_round_pairings = last_round.teampairing_set.all() if last_round is not None else None
    team_scores = list(enumerate(sorted(TeamScore.objects.filter(team__season=season), reverse=True)[:5], 1))
    tie_score = season.boards
    
    context = {
        'league_tag': league_tag,
        'league': _get_league(league_tag),
        'season_id': season_id,
        'season': season,
        'default_season': default_season,
        'season_list': season_list,
        'active_round': active_round,
        'last_round': last_round,
        'last_round_pairings': last_round_pairings,
        'team_scores': team_scores,
        'tie_score': tie_score,
    }
    return render(request, 'tournament/season_landing.html', context)

def pairings(request, league_tag=None, season_id=None, round_number=None, team_number=None):
    specified_round = round_number is not None
    season = _get_season(league_tag, season_id)
    round_number_list = [round_.number for round_ in Round.objects.filter(season=season, publish_pairings=True).order_by('-number')]
    if round_number is None:
        try:
            round_number = round_number_list[0]
        except IndexError:
            pass
    team_list = season.team_set.order_by('name')
    team_pairings = TeamPairing.objects.filter(round__number=round_number, round__season=season).order_by('pairing_order').select_related('white_team', 'black_team').nocache()
    if team_number is not None:
        current_team = get_object_or_404(team_list, number=team_number)
        team_pairings = team_pairings.filter(white_team=current_team) | team_pairings.filter(black_team=current_team)
    else:
        current_team = None
    pairing_lists = [list(team_pairing.teamplayerpairing_set.order_by('board_number').select_related('player_pairing__white', 'player_pairing__black').nocache()) for team_pairing in team_pairings]
    unavailable_players = {pa.player for pa in PlayerAvailability.objects.filter(round__season=season, round__number=round_number, is_available=False).select_related('player').nocache()}
    context = {
        'league_tag': league_tag,
        'league': _get_league(league_tag),
        'season_id': season_id,
        'season': season,
        'round_number': round_number,
        'round_number_list': round_number_list,
        'current_team': current_team,
        'team_list': team_list,
        'pairing_lists': pairing_lists,
        'unavailable_players': unavailable_players,
        'specified_round': specified_round,
        'specified_team': team_number is not None,
        'can_edit': request.user.has_perm('tournament.change_pairing')
    }
    return render(request, 'tournament/pairings.html', context)

def register(request, league_tag=None, season_id=None):
    try:
        if season_id is None:
            season = Season.objects.filter(league=_get_league(league_tag), registration_open=True).order_by('-start_date')[0]
        else:
            season = Season.objects.filter(league=_get_league(league_tag), registration_open=True, pk=season_id)[0]
    except IndexError:
        return registration_closed(request, league_tag, season_id)
    if request.method == 'POST':
        form = RegistrationForm(request.POST, season=season)
        if form.is_valid():
            registration = form.save()
            return redirect(leagueurl('registration_success', league_tag=league_tag, season_id=season_id))
    else:
        form = RegistrationForm(season=season)
    
    context = {
        'league_tag': league_tag,
        'league': _get_league(league_tag),
        'season_id': season_id,
        'season': _get_season(league_tag, season_id),
        'form': form,
        'registration_season': season
    }
    return render(request, 'tournament/register.html', context)

def registration_success(request, league_tag=None, season_id=None):
    try:
        if season_id is None:
            season = Season.objects.filter(league=_get_league(league_tag), registration_open=True).order_by('-start_date')[0]
        else:
            season = Season.objects.filter(league=_get_league(league_tag), registration_open=True, pk=season_id)[0]
    except IndexError:
        return registration_closed(request, league_tag, season_id)
    context = {
        'league_tag': league_tag,
        'league': _get_league(league_tag),
        'season_id': season_id,
        'season': _get_season(league_tag, season_id),
        'registration_season': season
    }
    return render(request, 'tournament/registration_success.html', context)

def registration_closed(request, league_tag=None, season_id=None):
    context = {
        'league_tag': league_tag,
        'league': _get_league(league_tag),
        'season_id': season_id,
        'season': _get_season(league_tag, season_id)
    }
    return render(request, 'tournament/registration_closed.html', context)

def faq(request, league_tag=None, season_id=None):
    league = _get_league(league_tag)
    league_document = LeagueDocument.objects.filter(league=league, type='faq').first()
    # If the FAQ document doesn't exist, create a placeholder
    if league_document is None:
        league_document = LeagueDocument.objects.filter(league=league, tag='faq').first()
    if league_document is None:
        document = Document.objects.create(name='FAQ', content='Coming soon.')
        league_document = LeagueDocument.objects.create(league=league, document=document, tag='faq', type='faq')
    context = {
        'league_tag': league_tag,
        'league': league,
        'season_id': season_id,
        'season': _get_season(league_tag, season_id),
        'league_document': league_document,
        'can_edit': request.user.has_perm('tournament.change_document'),
    }
    return render(request, 'tournament/document.html', context)

def rosters(request, league_tag=None, season_id=None):
    season = _get_season(league_tag, season_id)
    if season is None:
        return no_rosters_available(request, league_tag, season_id)
    teams = Team.objects.filter(season=season).order_by('number').prefetch_related(
        Prefetch('teammember_set', queryset=TeamMember.objects.select_related('player'))
    ).nocache()
    board_numbers = list(range(1, season.boards + 1))
    
    alternates = Alternate.objects.filter(season_player__season=season)
    alternates_by_board = [sorted(alternates.filter(board_number=n).select_related('season_player__registration', 'season_player__player').nocache(), key=lambda alt: alt.priority_date()) for n in board_numbers]
    alternate_rows = list(enumerate(itertools.izip_longest(*alternates_by_board), 1))
    if len(alternate_rows) == 0:
        alternate_rows.append((1, [None for _ in board_numbers]))
    
    current_round = Round.objects.filter(season=season, publish_pairings=True).order_by('-number').first()
    scheduled_alternates = {assign.player for assign in AlternateAssignment.objects.filter(round=current_round).select_related('player').nocache()}
    unresponsive_players = {sp.player for sp in SeasonPlayer.objects.filter(season=season, unresponsive=True).select_related('player').nocache()}
    
    games_missed_by_player = {sp.player: sp.games_missed for sp in SeasonPlayer.objects.filter(season=season).select_related('player').nocache()}
    yellow_card_players = {player for player, games_missed in games_missed_by_player.items() if games_missed == 1}
    red_card_players = {player for player, games_missed in games_missed_by_player.items() if games_missed >= 2}
    
    context = {
        'league_tag': league_tag,
        'league': _get_league(league_tag),
        'season_id': season_id,
        'season': season,
        'teams': teams,
        'board_numbers': board_numbers,
        'alternate_rows': alternate_rows,
        'scheduled_alternates': scheduled_alternates,
        'unresponsive_players': unresponsive_players,
        'yellow_card_players': yellow_card_players,
        'red_card_players': red_card_players,
        'can_edit': request.user.has_perm('tournament.edit_rosters'),
    }
    return render(request, 'tournament/rosters.html', context)

def no_rosters_available(request, league_tag=None, season_id=None):
    context = {
        'league_tag': league_tag,
        'league': _get_league(league_tag),
        'season_id': season_id,
        'season': _get_season(league_tag, season_id)
    }
    return render(request, 'tournament/no_rosters.html', context)

def standings(request, league_tag=None, season_id=None):
    season = _get_season(league_tag, season_id)
    round_numbers = list(range(1, season.rounds + 1))
    team_scores = list(enumerate(sorted(TeamScore.objects.filter(team__season=season).select_related('team').nocache(), reverse=True), 1))
    tie_score = season.boards / 2.0
    context = {
        'league_tag': league_tag,
        'league': _get_league(league_tag),
        'season_id': season_id,
        'season': season,
        'round_numbers': round_numbers,
        'team_scores': team_scores,
        'tie_score': tie_score
    }
    return render(request, 'tournament/standings.html', context)

def crosstable(request, league_tag=None, season_id=None):
    season = _get_season(league_tag, season_id)
    team_scores = TeamScore.objects.filter(team__season=season).order_by('team__number').select_related('team').nocache()
    tie_score = season.boards / 2.0
    context = {
        'league_tag': league_tag,
        'league': _get_league(league_tag),
        'season_id': season_id,
        'season': season,
        'team_scores': team_scores,
        'tie_score': tie_score
    }
    return render(request, 'tournament/crosstable.html', context)

def result(request, pairing_id, league_tag=None, season_id=None):
    season = _get_season(league_tag, season_id)
    team_pairing = get_object_or_404(TeamPairing, round__season=season, pk=pairing_id)
    pairings = team_pairing.teamplayerpairing_set.order_by('board_number')
    tie_score = season.boards
    context = {
        'league_tag': league_tag,
        'league': _get_league(league_tag),
        'season_id': season_id,
        'season': season,
        'team_pairing': team_pairing,
        'pairings': pairings,
        'round_number': team_pairing.round.number,
        'tie_score': tie_score
    }
    return render(request, 'tournament/match_result.html', context)

def _count_results(pairings, board_num=None):
    total = 0.0
    counts = [0, 0, 0, 0]
    rating_delta = 0
    for p in pairings:
        if p.game_link == '' or p.result == '':
            # Don't count forfeits etc
            continue
        total += 1
        if p.white.rating is not None and p.black.rating is not None:
            rating_delta += p.white.rating - p.black.rating
        if p.result == '1-0':
            counts[0] += 1
            counts[3] += 1
        elif p.result == '0-1':
            counts[2] += 1
            counts[3] -= 1
        elif p.result == '1/2-1/2':
            counts[1] += 1
    if total == 0:
        return board_num, tuple(counts), (0, 0, 0, 0), 0.0
    percents = (counts[0] / total, counts[1] / total, counts[2] / total, counts[3] / total)
    return board_num, tuple(counts), percents, rating_delta / total

def stats(request, league_tag=None, season_id=None):
    season = _get_season(league_tag, season_id)
    
    all_pairings = PlayerPairing.objects.filter(teamplayerpairing__team_pairing__round__season=season).select_related('teamplayerpairing', 'white', 'black').nocache()
    
    _, total_counts, total_percents, total_rating_delta = _count_results(all_pairings)
    boards = [_count_results(filter(lambda p: p.teamplayerpairing.board_number == n, all_pairings), n) for n in season.board_number_list()]
    
    context = {
        'league_tag': league_tag,
        'league': _get_league(league_tag),
        'season_id': season_id,
        'season': season,
        'has_win_rate_stats': total_counts != (0, 0, 0, 0),
        'total_rating_delta': total_rating_delta,
        'total_counts': total_counts,
        'total_percents': total_percents,
        'boards': boards,
    }
    return render(request, 'tournament/stats.html', context)

def document(request, document_tag, league_tag=None, season_id=None):
    league_document = LeagueDocument.objects.get(league=_get_league(league_tag), tag=document_tag)
    context = {
        'league_tag': league_tag,
        'league': _get_league(league_tag),
        'season_id': season_id,
        'season': _get_season(league_tag, season_id, allow_none=True),
        'league_document': league_document,
        'can_edit': request.user.has_perm('tournament.change_document'),
    }
    return render(request, 'tournament/document.html', context)

def _get_league(league_tag, allow_none=False):
    if league_tag is None:
        return _get_default_league(allow_none)
    else:
        return get_object_or_404(League, tag=league_tag)

def _get_default_league(allow_none=False):
    try:
        return League.objects.filter(is_default=True).order_by('id')[0]
    except IndexError:
        league = League.objects.order_by('id').first()
        if not allow_none and league is None:
            raise Http404
        return league

def _get_season(league_tag, season_id, allow_none=False):
    if season_id is None:
        return _get_default_season(league_tag, allow_none)
    else:
        return get_object_or_404(Season, league=_get_league(league_tag), pk=season_id)

def _get_default_season(league_tag, allow_none=False):
    season = Season.objects.filter(league=_get_league(league_tag), is_active=True).order_by('-start_date', '-id').first()
    if not allow_none and season is None:
        raise Http404
    return season
