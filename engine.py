
import itertools
import json
import random
import traceback

from mahjong.shanten import Shanten
from mahjong.agari import Agari
from mahjong.tile import TilesConverter as tc
import mahjong.utils as mutil
from mahjong.meld import Meld as LibMeld
from mahjong.hand_calculating.hand import HandCalculator
from mahjong.hand_calculating.scores import ScoresCalculator
from mahjong.hand_calculating.hand_config import OptionalRules, HandConfig
import mahjong.constants as constants

from tile import Tile, Tile34, to_tiles, tt, tile34_string_to_136_array



def get_shanten_and_ukeire(tiles136):
    assert len(tiles136) in [13, 10, 7, 4, 1]
    
    shan = Shanten()
    tiles34 = tc.to_34_array(tiles136)
    base_shanten = shan.calculate_shanten(tiles34)
    uke = []
    # Check if adding any tile lowers the shanten
    for t in range(34):
        tiles_copy = tiles34[:]
        tiles_copy[t] += 1
        new_shanten = shan.calculate_shanten(tiles_copy)
        if new_shanten < base_shanten:
            uke.append(Tile34(t))
    return (base_shanten, uke)


class Win(object):
    def __init__(self,
                 player_idx,
                 hand,
                 win_tile, # None for tsumo
                 melds,
                 dora_ind,
                 ura_dora_ind,
                 han,
                 fu,
                 yaku,
                 level,
                 total,
                 points):
        self.player_idx = player_idx
        self.hand = hand
        self.win_tile = win_tile
        self.melds = melds
        self.dora_ind = dora_ind
        self.ura_dora_ind = ura_dora_ind
        self.han = han
        self.fu = fu
        self.yaku = yaku
        self.level = level
        self.total = total
        self.points = points
    def __repr__(self):
        return "({})".format(self.__dict__)

class Meld(object):
    CHI = "chi"
    PON = "pon"
    CKAN = "closed_kan"
    MKAN = "melded_kan"
    AKAN = "added_kan"
    LIBMELD_MAP = {
        CHI: LibMeld.CHI,
        PON: LibMeld.PON,
        CKAN: LibMeld.KAN, # closed
        MKAN: LibMeld.KAN, # open
        AKAN: LibMeld.SHOUMINKAN
    }

    def __init__(self, kind, tiles136, called_from=None, called_tile136=None):
        self.kind = kind
        self.tiles = tiles136
        self.called_from = called_from
        self.called_tile = called_tile136
    
    def promote_to_akan(self, t136):
        assert self.kind == self.PON
        assert self.tiles[0] // 4 == t136 // 4
        self.kind = self.AKAN
        self.tiles.append(t136)
    
    def is_kan(self):
        return self.kind in [Meld.CKAN, Meld.MKAN, Meld.AKAN]

    def __repr__(self):
        if self.kind == self.CKAN:
            return "{} of {}".format(self.kind, to_tiles(self.tiles))
        return "{} of {} ({}) from player {}".format(
            self.kind, to_tiles(self.tiles),
            Tile(self.called_tile), self.called_from
        )
    
    def clone(self):
        return Meld(self.kind, self.tiles[:], self.called_from, self.called_tile)


class Discard(object):
    def __init__(self, tile136, is_tsumogiri=False, is_riichi=False):
        self.tile = tile136
        self.is_tsumogiri = is_tsumogiri
        self.is_riichi = is_riichi
        self.called = None
    
    def call_tile(self, player_idx):
        self.called = player_idx
    
    def __repr__(self):
        return "({}{}{}{})".format(
            Tile(self.tile),
            "!" if self.is_tsumogiri else "",
            "@" if self.is_riichi else "",
            ">" + str(self.called) if self.called is not None else ""
        )

class Draw(object):
    EXHAUSTIVE = "exhaustive"
    FOUR_WINDS = "four_winds"
    NINE_TERMINALS = "nine_terminals"
    FOUR_RIICHI = "four_riichi"
    FOUR_KAN = "four_kan"
    
    def __init__(self, kind, hands, points, wait=None):
        self.kind = kind
        self.hands = hands
        self.points = points
        self.wait = wait

class NoValidTilesError(Exception):
    pass

class CallComputer(object):
    def __init__(self, red_five_enabled=True):
        self.red_five_enabled = True

    def t136_to_t37(self, tiles136):
        t37 = [0]*37
        for t136 in tiles136:
            if self.red_five_enabled and t136 in constants.AKA_DORA_LIST:
                t37[Wall.FIVES[t136//4]] += 1
            else:
                t37[t136//4] += 1
        return t37

    def get_t37_poss(self, t34list):
        poss = []
        t37 = [0]*37
        for t in t34list:
            t37[t] += 1
        poss.append(t37)
        if self.red_five_enabled:
            for red_34 in Wall.FIVES:
                if red_34 in t34list:
                    red_t37 = t37[:]
                    red_t37[red_34] -= 1
                    red_t37[Wall.FIVES[red_34]] += 1
                    poss.append(red_t37)
        return poss



    def compute_possible_calls(self, possible37, tiles136):
        def pop_match(fun, l):
            for i in range(len(l)):
                if fun(l[i]):
                    r = l[i]
                    del l[i]
                    return r
            return None
        tiles136 = tiles136[:]

        # Determine if we have these tiles on hand and filter the possibilities
        tiles37 = self.t136_to_t37(tiles136)

        def has_req_tiles(poss37):
            for i in range(len(poss37)):
                if tiles37[i] < poss37[i]:
                    return False
            return True
        possible37 = filter(has_req_tiles, possible37)

        # Map the possibility maps to sets of 136 that we have on hand
        def poss37_to_tiles136(poss37):
            result136 = []
            avail136 = tiles136[:]
            for i in range(len(poss37)):
                count = poss37[i]
                while count > 0:
                    def match_t136_t37(t136):
                        # Return true if this t136 is the i'th t37
                        if self.red_five_enabled and t136 in constants.AKA_DORA_LIST:
                            return Wall.FIVES[t136//4] == i
                        else:
                            return t136//4 == i
                    result136.append(Tile(pop_match(match_t136_t37, avail136)))
                    count -= 1
            return result136
        possible136 = map(poss37_to_tiles136, possible37)
        return list(possible136)

    def get_pon_sets(self, disc136, tiles136):
        possible37 = self.get_t37_poss([disc136//4]*2)
        return self.compute_possible_calls(possible37, tiles136)
    
    def get_chi_sets(self, disc136, tiles136):
        disc34 = disc136//4
        
        if disc34 >= 27:
            return []
        
        tidx = disc34 % 9
        possible37 = []
        if tidx >= 2: # left chi
            possible37.extend(self.get_t37_poss([disc34-2, disc34-1]))
        if tidx >= 1 and tidx <= 7: # middle chi
            possible37.extend(self.get_t37_poss([disc34-1, disc34+1]))
        if tidx <= 6: # right chi
            possible37.extend(self.get_t37_poss([disc34+1, disc34+2]))
        
        return self.compute_possible_calls(possible37, tiles136)

class Wall(object):
    # Map from real 5 tile to the fake slot in the map
    FIVES = {4: 34, 13: 35, 22: 36}
    FIVES_INV = {34: 4, 35: 13, 36: 22}

    def __init__(self, has_red_five=True):
        self.has_red_five = has_red_five
        self.available = []
        #self.pool
    
    def reset(self):
        self.available = [4]*34 + [0]*3
        if self.has_red_five:
            for five in self.FIVES.keys():
                self.available[five] -= 1
            for red_five in self.FIVES.values():
                self.available[red_five] = 1
    
    def tiles34_to_tiles37(self, t34):
        t34 = t34[:]
        for f in self.FIVES:
            if f in t34:
                t34.append(self.FIVES[f])
        return t34
    
    def draw_many(self, n, prob_sets):
        l = []
        for i in range(n):
            try:
                t136 = self.draw(prob_sets)
                l.append(t136)
            except (NoValidTilesError):
                # Return the tiles before raising
                self.replace_many(l)
                raise
        return l
    
    def replace_many(self, t136):
        for t in t136:
            self.replace(t)
    
    # Pass probability modifier sets with multipliers for the tile types
    # apply all sets and then pick tile
    # special case for 0 prob? how to solve
    def draw(self, prob_sets):
        # Compute the cumulative weights
        weights = [float(n) for n in self.available]
        for prob_set in prob_sets:
            weights = map(lambda x, y: x * y, weights, prob_set)
        
        t37types = [i for i in range(37)]
        try:
            t37 = random.choices(t37types, weights=weights)[0]
        except (ValueError):
            # All weights were 0: no tiles available based on the weights and
            # given probability modifiers
            raise NoValidTilesError()
        
        assert self.available[t37] > 0
        self.available[t37] -= 1
        
        # Get the t34 for tile class, but use t37 for index to get the right
        # tile in the case of red 5
        is_red_five = t37 >= 34
        t34 = t37 if not is_red_five else self.FIVES_INV[t37]
        t136 = t34 * 4 + (0 if is_red_five else (3 - self.available[t37]))
        
        return t136
    
    def take(self, t136):
        t34 = t136 // 4
        is_red_five = self.has_red_five and t34 in self.FIVES and t136 % 4 == 0
        t37 = t34 if not is_red_five else self.FIVES[t34]
        if self.available[t37] == 0:
            raise NoValidTilesError()
        self.available[t37] -= 1
        # remap the tile to the one we just pulled
        t136 = t34 * 4 + (0 if is_red_five else (3 - self.available[t37]))
        return t136

    def replace(self, t136):
        t34 = t136 // 4
        is_red_five = self.has_red_five and t34 in self.FIVES and t136 % 4 == 0
        t37 = t34 if not is_red_five else self.FIVES[t34]
        self.available[t37] += 1

def shanten_test(p, n=100):
    l = []
    w = Wall()
    s = Shanten()
    for i in range(n):
        w.reset()
        h = w.draw_many(13, p)
        l.append(s.calculate_shanten(tc.to_34_array(h)))
    return l


# Events:
#  ev_new_game
#  ev_new_round
#  ev_tile
#  ev_discard
#  ev_call
#  ev_win
#  ev_dora
#  ev_draw
#  ev_cancel_ask
#  
# Queries:
#  ask_discard
#  ask_riichi
#  ask_chi
#  ask_pon
#  ask_kan
#  ask_ron
#  ask_tsumo
#  ask_draw

class Wait(object):
    def __init__(self, tiles34, has_yaku, is_furiten):
        self.tiles = tiles34
        self.has_yaku = has_yaku
        self.is_furiten = is_furiten
    def __repr__(self):
        return "({})".format(self.__dict__)

class Event(object):
    def __init__(self, name):
        self.name = name
    
    def get_for_player(self, player_idx):
        return self
    
    def __repr__(self):
        return "{}({})".format(self.name, self.__dict__)

# A new game has started
class NewGameEvent(Event):
    def __init__(self, player_names, points):
        super().__init__('ev_new_game')
        self.player_names = list(player_names)
        self.points = list(points)

# A new round has started
class NewRoundEvent(Event):
    def __init__(self, wind, round, bonus, hands):
        super().__init__('ev_new_round')
        self.wind = wind
        self.round = round
        self.bonus = bonus
        self.hands = list(hands)
    def get_for_player(self, player_idx):
        nr = NewRoundEvent(self.wind, self.round, self.bonus, None)
        nr.hand = self.hands[player_idx]
        del nr.hands
        return nr

# A tile was drawn
class TileEvent(Event):
    def __init__(self, t136, player):
        super().__init__('ev_tile')
        self.tile = t136
        self.player = player
    def __repr__(self):
        return "P{} draws {}".format(self.player, Tile(self.tile))
    def get_for_player(self, player_idx):
        if self.player == player_idx:
            return self
        return TileEvent(None, self.player)

# A tile was discarded
class DiscardEvent(Event):
    def __init__(self, t136, player, is_tsumogiri, is_riichi=False):
        super().__init__('ev_discard')
        self.tile = t136
        self.player = player
        self.is_tsumogiri = is_tsumogiri
        self.is_riichi = is_riichi
    def __repr__(self):
        return "P{} {} {}{}".format(
            self.player, "riichis" if self.is_riichi else "discards",
            Tile(self.tile), " immediately" if self.is_tsumogiri else "")

# A call was made
class CallEvent(Event):
    def __init__(self, meld, player):
        super().__init__('ev_call')
        self.meld = meld
        self.player = player
    def __repr__(self):
        return "P{} calls {}".format(self.player, self.meld)

# Round was won
class WinEvent(Event):
    def __init__(self, win):
        super().__init__('ev_win')
        self.win = win

# The game is over
class GameOverEvent(Event):
    def __init__(self, points):
        super().__init__('ev_game_over')
        self.points = points

# New dora indicator
class DoraEvent(Event):
    def __init__(self, t136):
        super().__init__('ev_dora')
        self.tile = t136

# Game was a draw
class DrawEvent(Event):
    WIND = "wind"
    TERMINAL = "terminal"
    RIICHI = "riichi"
    KAN = "kan"
    EXHAUSTIVE = "exhaustive"
    
    def __init__(self, draw, ex_hands=None, ex_nagashi=None, ex_points=None):
        super().__init__('ev_draw')
        self.draw = draw
        self.hands = ex_hands
        self.nagashi = ex_nagashi
        self.points = ex_points

class FuritenEvent(Event):
    def __init__(self, is_furiten):
        super().__init__('ev_furiten')
        self.is_furiten = is_furiten



class QueryEvent(Event):
    def __init__(self, name, optional=True):
        super().__init__(name + "_query")
        self.optional = optional

class DiscardQuery(QueryEvent):
    def __init__(self, allowed, waits):
        super().__init__('discard', False)
        self.allowed = allowed
        self.waits = waits

class RiichiQuery(QueryEvent):
    def __init__(self, allowed, waits):
        super().__init__('riichi')
        self.allowed = allowed
        self.waits = waits

class DrawQuery(QueryEvent):
    def __init__(self):
        super().__init__('draw')

class TsumoQuery(QueryEvent):
    def __init__(self):
        super().__init__('tsumo')

class RonQuery(QueryEvent):
    def __init__(self, from_player):
        super().__init__('ron')
        self.from_player = from_player

class CallQuery(QueryEvent):
    CHI = 'chi'
    PON = 'pon'
    KAN = 'kan'

    def __init__(self, kind, choices, from_who, discard_idx):
        super().__init__('call')
        self.kind = kind
        self.choices = choices
        self.from_who = from_who
        self.discard_idx = discard_idx

class Player(object):
    # todo: protoplayers for characters
    def __init__(self, game, name):
        self.game = game
        self.name = name
        self.idx = -1
        self.points = 0
        
        self.hand = []
        self.discards = []
        self.melds = []
        self.ukeire = []
        self.latest_draw = None
        self.shanten = 0
        self.is_riichi = False
        self.is_double_riichi = False
        self.is_ippatsu = False
        self.is_temp_furiten = False
        self.has_pending_dora = False
        self.latest_draw_was_dead_wall = False
        
    
    def reset_round(self):
        self.hand = []
        self.discards = []
        self.melds = []
        self.ukeire = []
        self.latest_draw = None
        self.shanten = 0
        self.is_riichi = False
        self.is_double_riichi = False
        self.is_ippatsu = False
        self.is_temp_furiten = False
        self.has_pending_dora = False
        self.latest_draw_was_dead_wall = False
    
    def calculate_shanten_and_ukeire(self):
        self.shanten, self.ukeire = get_shanten_and_ukeire(self.hand)

    def check_win(self, win_tile=None, dora_inds=[], config=None):
        tiles = self.hand[:]
        for m in self.melds:
            tiles.extend(m.tiles)
        if win_tile is not None:
            tiles.append(win_tile)
        else:
            # If no win tile is given, the latest tile is the win tile
            win_tile = tiles[-1]
        
        # Map from our melds to the mahjong lib melds
        melds = []
        for m in self.melds:
            # Called tile and who doesn't seem to matter for points calculation?
            lm = LibMeld(Meld.LIBMELD_MAP[m.kind], m.tiles, m.kind != Meld.CKAN,
                         m.tiles[0], 0, 0)
            melds.append(lm)
        
        hc = HandCalculator()
        return hc.estimate_hand_value(tiles, win_tile, melds, dora_inds, config)
    
    def is_furiten_for_waits(self, t34waits, extra_discards34=[]):
        # We are furiten on these waits if any of them are in the discards
        disc34 = [d.tile // 4 for d in self.discards] + extra_discards34
        return any([(wait in disc34) for wait in t34waits])
    
    def is_furiten(self):
        # We are in furiten if we are temp furiten (after passing on a win)
        # or if we are in riichi furiten (after passing on a win in riichi)
        if self.is_temp_furiten:
            return True
        # We are also in furiten if we are in tenpai and any of our ukeire is
        # in our discards
        if self.shanten == 0 and self.is_furiten_for_waits(self.ukeire):
            return True
        return False
    
    def has_nagashi_mangan(self):
        # We have nagashi mangan if all of our discards are honors or terminals
        # and none of them were called
        return all((mutil.is_honor(d.tile//4) or mutil.is_terminal(d.tile//4)) and d.called is None for d in self.discards)
    
    def populate_initial_hand(self):
        return

class PreHandPlayer(Player):
    def __init__(self, game, name, hand_str):
        super().__init__(game, name)
        self.pre_hand = hand_str
    
    def populate_initial_hand(self):
        pre136 = tc.one_line_string_to_136_array(self.pre_hand, True)
        pre136 = map(lambda t136: self.game.wall.take(t136), pre136)
        self.hand.extend(to_tiles(list(pre136)))


class InvalidActionError(Exception):
    def __init__(self, msg):
        super().__init__(msg)

class Game(object):
    EAST = 'E'
    SOUTH = 'S'
    WEST = 'W'
    NORTH = 'N'
    NEXT_WIND = {EAST: SOUTH, SOUTH: WEST, WEST: NORTH, NORTH: EAST}
    TILE_WIND = {EAST: constants.EAST, SOUTH: constants.SOUTH,
                 WEST: constants.WEST, NORTH: constants.NORTH}
    WIND_ORDER = [EAST, SOUTH, WEST, NORTH]
    
    def __init__(self):
        self.wind = self.EAST
        self.round = 1
        self.bonus = 0
        self.active_player = 0
        self.players = []
        self.wall = Wall(has_red_five=True) # TODO game config
        self.dora_indicators = []
        self.remaining_draws = 0
        self.riichi_sticks = 0
        
        self.continuation = None
        self.pending_events = []

        self.preset_tiles = None

    def _add_event(self, ev, player=None):
        idx = player.idx if player else None
        self.pending_events.append((idx, ev))

    def pop_events(self):
        evs = self.pending_events
        self.pending_events = []
        return evs

    def run_continuation(self):
        if self.continuation:
            self.continuation()
        self.continuation = None

    def _wait_for_queries(self, cont):
        if self._has_pending_queries():
            self.continuation = cont
        else:
            cont()

    def _has_pending_queries(self):
        return any(isinstance(ev, QueryEvent) for pl, ev in self.pending_events)

    def dealer(self):
        # Dealer is always round-1
        return self.round - 1
    def get_player_wind(self, player):
        return self.WIND_ORDER[(player.idx - self.dealer() + 4) % 4]
    def get_total_round_order(self, wind=None, round=None):
        wind = self.wind if wind is None else wind
        round = self.round if round is None else round
        wind_ordinal = {self.EAST: 0, self.SOUTH: 10, self.WEST: 20, self.NORTH: 30}
        return wind_ordinal[wind] + round

    def start_game(self, players, shuffle_players=True):
        # Randomize players
        self.players = players
        if shuffle_players:
            random.shuffle(self.players)
        for i, p in enumerate(self.players):
            p.idx = i
            p.points = 25000
        
        # Send new game and also start E1-0
        self._add_event(NewGameEvent(
            map(lambda p: p.name, self.players),
            map(lambda p: p.points, self.players)
        ))
        self.start_round((self.EAST, 1, 0))
    
    def _get_base_hand_config(self):
        # TODO: proper optionals config
        op = OptionalRules(
            has_open_tanyao=True,
            has_aka_dora=True,
        )
        c = HandConfig(
            round_wind=self.TILE_WIND[self.wind],
            kyoutaku_number=self.riichi_sticks,
            tsumi_number=self.bonus,
            options=op
        )
        return c
    
    def set_tile_preset(self, t34string):
        self.preset_tiles = tile34_string_to_136_array(t34string)

    def _draw_tile(self, kind='wall', player=None):

        # TODO player handling
        assert kind in ['hand', 'wall', 'dora', 'deadwall']
        
        if kind in ['wall', 'deadwall']:
            # Drawing from the wall or dead wall counts as a drawn tile
            self.remaining_draws -= 1

        if self.preset_tiles and kind != 'hand':
            return Tile(self.wall.take(self.preset_tiles.pop(0)))
        return Tile(self.wall.draw([]))
    
    def _assign_initial_hands(self):
        # 1. Ask players if there's anything it wants to pull manually.
        #    It can populate the whole hand if it wants to.
        # 2. If hands have < 13 tiles, draw new tiles from the pool.
        for p in self.players:
            p.populate_initial_hand()
        
        for p in self.players:
            while len(p.hand) < 13:
                p.hand.append(self._draw_tile('hand', p))
        
            p.calculate_shanten_and_ukeire()

    def _check_for_game_over(self):
        # TODO: config min points and wind count
        last_round_ord = self.get_total_round_order(self.EAST, 4)
        min_win = 30000

        # TODO: The round order logic is faulty for full games, since N wraps around to E
        #       when starting a new round after N4

        # Game is over if:
        game_over = False
        # any player has negative points
        if any(pl.points < 0 for pl in self.players):
            game_over = True
        # it is past the last round and some player has the minimum win points
        elif (self.get_total_round_order() > last_round_ord and
              any(pl.points >= min_win for pl in self.players)):
            game_over = True
        # it is the last round or later, it is a bonus round and the dealer is in the lead
        elif (self.get_total_round_order() >= last_round_ord and
              self.bonus > 0 and
              all(pl.points < self.players[self.dealer()].points
                  for pl in self.players if pl.idx != self.dealer())):
           game_over = True
        
        if not game_over:
            return False

        points = [pl.points for pl in self.players]
        self._add_event(GameOverEvent(points))

        return True

    def start_round(self, round):
        if round == 'same':
            pass
        elif round == 'next':
            # Go to next round, and next wind if we are round 4
            # Reset bonus
            self.round = self.round % 4 + 1
            if self.round == 1:
                self.wind = self.NEXT_WIND[self.wind]
            self.bonus = 0
        elif round == 'bonus':
            # Increase bonus
            self.bonus += 1
        elif type(round) == tuple:
            # Set explicitly
            wind, round, bonus = round
            assert wind in self.NEXT_WIND
            assert round in [1, 2, 3, 4]
            self.wind = wind
            self.round = round
            self.bonus = bonus
        else:
            raise ValueError()
        
        # Check if the game is over after we've advanced
        if self._check_for_game_over():
            return
        
        # Reset the wall
        self.dora_indicators = []
        self.remaining_draws = 70
        self.wall.reset()
        
        # Clear all player round information
        for p in self.players:
            # TODO: Should pass round info?
            p.reset_round()
        
        # Assign hands
        self._assign_initial_hands()
        self._add_event(NewRoundEvent(
            self.wind, self.round, self.bonus,
            map(lambda p: p.hand[:], self.players)))
        
        # Assign first dora
        t136 = self._draw_tile('dora')
        self.dora_indicators.append(t136)
        self._add_event(DoraEvent(t136))
        
        # Draw a tile for the dealer
        self.draw_tile(self.dealer())
    
    def _redistribute_points(self, winner, score, ronned=None):
        winner.points += score["total"]
        for pl in self.players:
            if pl == winner:
                continue
            if ronned:
                if pl == ronned:
                    pl.points -= score["main"] + score["main_bonus"]
            else:
                if pl.idx == self.dealer():
                    pl.points -= score["main"] + score["main_bonus"]
                else:
                    pl.points -= score["additional"] + score["additional_bonus"]
    
    def _check_for_9tile_draw(self, player):
        # Must be the first tile drawn
        if len(player.discards) > 0:
            return
        # Must be no calls
        if sum(len(p.melds) for p in self.players):
            return
        # Hand must have at least 9 honors or terminals
        t34 = tc.to_34_array(player.hand)
        term_hon = [bool(n) for i, n in enumerate(t34) if mutil.is_terminal(i) or mutil.is_honor(i)]
        
        if sum(term_hon) < 9:
            return
        self._add_event(DrawQuery(), player)
    
    def _check_for_4wind_draw(self):
        WINDS = [constants.EAST, constants.SOUTH, constants.WEST, constants.NORTH]
        
        # There must not be any calls
        if any(len(p.melds) > 0 for p in self.players):
            return False
        
        # Must be exactly 4 discards
        if sum(len(p.discards) for p in self.players) != 4:
            return False
        
        # The discards must be the same tile kind
        t34 = self.players[0].discards[0].tile // 4
        if not all(t34 == p.discards[0].tile for p in self.players):
            return False
        
        # The tile must be a wind
        if t34 not in WINDS:
            return False
        
        # 4 wind draw. Send the draw event and start a new bonus round
        self._add_event(DrawEvent(DrawEvent.WIND))
        self.start_round('bonus')
        return True
    
    def _check_for_exhaustive_draw(self):
        if self.remaining_draws > 0:
            return False
        
        hands = [None if p.shanten != 0 else p.hand[:] for p in self.players]
        tenpai_players = sum(h is not None for h in hands)
        # If there's nagashi mangan, this takes precedence for points calc
        if any(p.has_nagashi_mangan() for p in self.players):
            for p in self.players:
                if p.has_nagashi_mangan():
                    c = self._get_base_hand_config()
                    c.player_wind = self.TILE_WIND[self.get_player_wind(p)]
                    c.is_nagashi_mangan = True
                    # Nagashi doesn't get riichi sticks or bonus
                    c.kyoutaku_number = 0
                    c.honba_number = 0
                    result = p.check_win(None, [], c)
                    score = ScoresCalculator().calculate_scores(
                        han=result.han, fu=result.fu, config=c)
                    self._redistribute_points(p, score)
        elif tenpai_players > 0 and tenpai_players < 4:
            # Those who are noten pay to those who aren't
            for pl in self.players:
                if hands[pl.idx] is not None:
                    # Tenpai
                    pl.points += 3000 // tenpai_players
                else:
                    # Noten
                    pl.points -= 3000 // (4 - tenpai_players)
        
        points = [p.points for p in self.players]
        nagashi = [p.has_nagashi_mangan() for p in self.players]
        self._add_event(DrawEvent(DrawEvent.EXHAUSTIVE, hands, nagashi, points))

        if hands[self.dealer()] is not None:
            self.start_round('bonus')
        else:
            self.start_round('next')
        return True
    
    def _get_tsumo(self, player, dead_wall):
        c = self._get_base_hand_config()
        c.is_tsumo = True
        c.player_wind = self.TILE_WIND[self.get_player_wind(player)]
        c.is_dealer = player.idx == self.dealer()
        c.is_riichi = player.is_riichi
        c.is_daburu_riichi = player.is_double_riichi
        c.is_ippatsu = player.is_ippatsu
        # Can't be rinshan and haitei at the same time
        c.is_rinshan = dead_wall
        c.is_haitei = self.remaining_draws == 0
        # Tenhou if this is the dealer and the first draw (no discards)
        c.is_tenhou = player.idx == self.dealer() and len(player.discards) == 0 and \
                      Agari().is_agari(tc.to_34_array(player.hand))
        # Chiihou if this is not the dealer, the first draw and no other player
        # has made any calls
        c.is_chiihou = player.idx != self.dealer() and len(player.discards) == 0 and \
                       sum(map(lambda p: len(p.melds), self.players)) == 0 and \
                       Agari().is_agari(tc.to_34_array(player.hand))
        
        return player.check_win(None, self.dora_indicators, c)
    
    def _check_for_tsumo(self, player, dead_wall):
        result = self._get_tsumo(player, dead_wall)
        no_tsumo_errors = [
            HandCalculator.ERR_HAND_NOT_WINNING,
            HandCalculator.ERR_HAND_NOT_CORRECT,
            HandCalculator.ERR_NO_YAKU
        ]
        if result.error:
            if not result.error in no_tsumo_errors:
                # This is some other error, log this
                print ("tsumo error {} {}".format(result.error, player.hand))
            return  # No tsumo
        
        # This can be tsumo! Tsumo is not affected by furiten, no need to check
        self._add_event(TsumoQuery(), player)
    
    def _get_ron(self, calling_player, discarding_player, chankan=None):
        if calling_player == discarding_player:
            return False

        c = self._get_base_hand_config()
        c.is_tsumo = False
        c.player_wind = self.TILE_WIND[self.get_player_wind(calling_player)]
        c.is_dealer = calling_player.idx == self.dealer()
        c.is_riichi = calling_player.is_riichi
        c.is_daburu_riichi = calling_player.is_double_riichi
        c.is_ippatsu = calling_player.is_ippatsu
        c.is_chankan = chankan is not None
        c.is_houtei = self.remaining_draws == 0 and chankan is None # Don't think this is possible
        
        if chankan is None:
            ron_tile136 = discarding_player.discards[-1].tile
        else:
            # TODO: We don't know which kan... Maybe not important
            ron_tile136 = chankan
        return calling_player.check_win(ron_tile136, self.dora_indicators, c)
    
    def _check_for_ron(self, calling_player, discarding_player, chankan=None):
        result = self._get_ron(calling_player, discarding_player, chankan)
        no_ron_errors = [
            HandCalculator.ERR_HAND_NOT_WINNING,
            HandCalculator.ERR_HAND_NOT_CORRECT,
        ]
        if not result:
            return False
        # If we have no-yaku, this counts as skipping the ron, so we are in furiten
        if result.error:
            if result.error == HandCalculator.ERR_NO_YAKU:
                if not calling_player.is_furiten():
                    self._add_event(FuritenEvent(True), calling_player)
                calling_player.is_temp_furiten = True
            elif not result.error in no_ron_errors:
                print ("ron error {} {}".format(result.error, calling_player.hand))
            return False
        
        if calling_player.is_furiten():
            return False
        
        # Possible ron.
        # TODO: chankan?
        self._add_event(RonQuery(discarding_player.idx), calling_player)
        return True
    
    def _check_for_closed_or_added_kan(self, player):
        # Must be tiles remaining in the wall
        if self.remaining_draws == 0:
            return

        # We can closed kan a group if we have 4 of the tile
        hand34 = tc.to_34_array(player.hand)
        possible_kan = []
        for t34 in range(34):
            if hand34[t34] != 4:
                continue
            # TODO extra riichi restrictions
            #      the wait must not change from removing the tiles
            #      the tile must not be part of a sequence or a pair in a winning hand
            if player.is_riichi:
                return False
            
            possible_kan.append(t34)
        
        # For added kan, check every pon and see if we have the completing tile
        for m in player.melds:
            if m.kind != Meld.PON:
                continue
            pon_t34 = m.tiles[0]//4
            call_t34 = None
            for t136 in player.hand:
                if pon_t34 == t136 // 4:
                    call_t34 = t136 // 4
                    break
            if call_t34 is None:
                continue
            possible_kan.append(call_t34)
        
        if len(possible_kan) == 0:
            return
        # Make a kan query with the possible kans in the list
        choices = []
        for t34 in possible_kan:
            t136 = t34 * 4
            choices.append([t136, t136+1, t136+2, t136+3])
        self._add_event(CallQuery(CallQuery.KAN, choices, None, None), player)
    
    def _check_for_open_kan(self, calling_player, discarding_player):
        # Can't call our own tiles
        if calling_player == discarding_player:
            return
        
        # Must be tiles remaining in the wall
        if self.remaining_draws == 0:
            return
        
        # Can't call if riichi
        if calling_player.is_riichi:
            return

        # Hand must have 3 of the tile
        disc34 = discarding_player.discards[-1].tile // 4
        t34hand = tc.to_34_array(calling_player.hand)
        if t34hand[disc34] < 3:
            return
        
        # Let the player kan
        self._add_event(CallQuery(
            CallQuery.KAN, [[disc34*4, disc34*4+1, disc34*4+2, disc34*4+3]],
            discarding_player.idx, len(discarding_player.discards)-1), calling_player)
    
    def _check_for_pon(self, calling_player, discarding_player):
        # Can't call our own tiles
        if calling_player == discarding_player:
            return
        
        # Must be tiles remaining in the wall
        if self.remaining_draws == 0:
            return
        
        # Can't call if riichi
        if calling_player.is_riichi:
            return

        disc136 = discarding_player.discards[-1].tile
        cc = CallComputer() # TODO: has_red_five
        possible136 = cc.get_pon_sets(disc136, calling_player.hand)
        
        # If the calling player has no available sets, they can't call
        if len(possible136) == 0:
            return
        
        # Add the discarded tile to every possibility
        possible136 = [p + [disc136] for p in possible136]
        
        # Let the player pon
        self._add_event(CallQuery(
            CallQuery.PON, possible136,
            discarding_player.idx, len(discarding_player.discards)-1),
            calling_player)
    
    def _check_for_chi(self, calling_player, discarding_player):
        # Can only call if next player
        if (discarding_player.idx + 1) % 4 != calling_player.idx:
            return
        
        # Must be tiles remaining in the wall
        if self.remaining_draws == 0:
            return
        
        # Can't call if riichi
        if calling_player.is_riichi:
            return

        disc136 = discarding_player.discards[-1].tile
        cc = CallComputer() # TODO: has_red_five
        possible136 = cc.get_chi_sets(disc136, calling_player.hand)
        
        # If the calling player has no available sets, they can't call
        if len(possible136) == 0:
            return
        
        # Add the discarded tile to every possibility
        possible136 = [p + [disc136] for p in possible136]
        
        # Let the player chi
        self._add_event(CallQuery(
            CallQuery.CHI, possible136,
            discarding_player.idx, len(discarding_player.discards)-1),
            calling_player)
    
    def _check_for_riichi(self, player):
        # Can't riichi if the player is riichi
        if player.is_riichi:
            return
        
        # Must have at least 1000 points
        if player.points < 1000:
            return
        
        # Must be at least 4 tiles left in the wall
        if self.remaining_draws < 4:
            return
        
        # Only closed kan allowed
        if any(map(lambda m: m.kind != Meld.CKAN, player.melds)):
            return
        
        # If the complete hand is 0-shanten (tenpai) we can riichi
        shan = Shanten()
        if shan.calculate_shanten(tc.to_34_array(player.hand)) > 0:
            return
        
        # Figure out what we can drop for riichi
        # Anything that doesn't lower the shanten is droppable
        droppable = []
        waits = []
        for i in range(len(player.hand)):
            hand_without_t = player.hand[:i] + player.hand[i+1:]
            shanten, ukeire = get_shanten_and_ukeire(hand_without_t)
            if shanten != 0:
                continue

            droppable.append(player.hand[i])
            furi = player.is_furiten_for_waits(ukeire, [player.hand[i] // 4])
            waits.append(Wait(ukeire, [True]*len(ukeire), furi))
        
        self._add_event(RiichiQuery(droppable, waits), player)
    
    def _ask_for_discard(self, player, kuikae34=None):
        droppable = []
        waits = []
        for i in range(len(player.hand)):
            if player.is_riichi and player.latest_draw != player.hand[i]:
                # If we're riichi we have to discard the drawn tile
                # Does the below calculation work even in riichi?
                continue
            
            # Check kuikae
            if kuikae34 and player.hand[i] // 4 in kuikae34:
                continue
            
            hand_without_t = player.hand[:i] + player.hand[i+1:]
            shanten, ukeire = get_shanten_and_ukeire(hand_without_t)
            
            wait = None
            if shanten == 0:
                # Dropping this would put us in tenpai with some wait
                # TODO: has_yaku calculation
                furi = player.is_furiten_for_waits(ukeire, [player.hand[i] // 4])
                wait = Wait(ukeire, [True]*len(ukeire), furi)
            
            droppable.append(player.hand[i])
            waits.append(wait)
        
        self._add_event(DiscardQuery(droppable, waits), player)
    
    def draw_tile(self, player_idx, dead_wall=False):
        # Many things can happen when you draw a tile
        #  If this is our winning tile, we can tsumo
        #  If we have a quad in the hand, we can kan
        #  If this is the first draw and we have 9 terminals, we can draw the round
        #  If we are closed in tenpai and not riichi, we can riichi
        
        # Exhaustive draw
        if self._check_for_exhaustive_draw():
            return
        
        self.active_player = player_idx
        player = self.players[self.active_player]
        
        t136 = self._draw_tile('wall' if not dead_wall else 'deadwall', player)
        player.hand.append(t136)
        player.latest_draw = t136
        player.latest_draw_was_dead_wall = dead_wall
        self._add_event(TileEvent(t136, player_idx))
        
        # Check for draw
        # If this is the first tile and there's more than 9 unique terminals
        # and honors
        self._check_for_9tile_draw(player)
        
        # Check for tsumo
        # Check if we have a win with this hand
        self._check_for_tsumo(player, dead_wall)
        
        # Check for closed or added kan
        # If we are in riichi, removing the tiles must not change the wait
        self._check_for_closed_or_added_kan(player)

        # Check for riichi
        self._check_for_riichi(player)
        
        # We need to ask the user to discard a tile.
        self._ask_for_discard(player)
    
    def discard_tile(self, player_idx, t136, riichi=False):
        player = self.players[player_idx]
        
        if player.idx != self.active_player:
            # Only the active player may discard
            raise InvalidActionError("P{} isn't active, P{} is, can't discard".format(
                player.idx, self.active_player))
        
        if not t136 in player.hand:
            # The player doesn't have this tile. This is invalid
            raise InvalidActionError("P{} doesn't have {} ({}), can't discard".format(
                player.idx, Tile(t136), int(t136)))
        
        if riichi:
            # Player must have 1000 points or more
            if player.points < 1000:
                raise InvalidActionError("P{} can't riichi with {} points".format(
                    player.idx, player.points))
            
            # Hand must be closed or with closed kan
            if any(map(lambda m: m.kind != Meld.CKAN, player.melds)):
                raise InvalidActionError("P{} can't riichi with {}".format(
                    player.idx, player.melds))
            
            # Dropping this tile must keep us in tenpai
            hand_without_t = player.hand[:]
            hand_without_t.remove(t136)
            shan, uke = get_shanten_and_ukeire(hand_without_t)
            if shan != 0:
                raise InvalidActionError("P{} shanten is {}, can't riichi with {}".format(
                    player.idx, shan, hand_without_t))
        
        was_furiten = player.is_furiten()
        
        # We won't bother checking allowances here, like kuikae. Probably can't.
        self._add_event(DiscardEvent(
            t136,
            player.idx,
            player.latest_draw == t136,
            riichi
        ))
        player.discards.append(Discard(t136, player.latest_draw == t136, riichi))
        player.hand.remove(t136)
        if not player.is_riichi:
            player.is_temp_furiten = False
        player.is_ippatsu = False
        player.calculate_shanten_and_ukeire()
        
        if riichi:
            # Player has declared riichi
            player.is_riichi = True
            # Points should be deducted after checking for ron, but we deduct them here
            # and add them back if a ron happens since we can't rely on the continuation
            # being run in that case
            player.points -= 1000
            self.riichi_sticks += 1
            
            # If this is the player's first discard and no calls have been made,
            # it's double riichi
            if len(player.discards) == 0 and sum(len(p.melds) for p in self.players):
                player.is_double_riichi = True

        # If we have a 4wind draw here, don't continue the discard processing
        if self._check_for_4wind_draw():
            return
        
        # If there are 4 riichi, only issue ron queries
        riichi_count = sum(p.is_riichi for p in self.players)

        # If there are 4 kans by different players, only issue ron queries
        # If there are 4 kans, don't issue kan queries
        kan_count = [sum(m.is_kan() for m in p.melds) for p in self.players]
        kans_same_player = any(kc == 4 for kc in kan_count)
        
        if was_furiten != player.is_furiten():
            # Furiten status changed, send update
            self._add_event(FuritenEvent(player.is_furiten()), player)
        
        if player.has_pending_dora:
            # This player previously called a kan and now reveals a new dora
            t136 = self._draw_tile('dora')
            self.dora_indicators.append(t136)
            self._add_event(DoraEvent(t136))
            player.has_pending_dora = False
        
        ron_players = []
        for other_pl in self.players:
            if riichi_count < 4 and (sum(kan_count) < 4 or kans_same_player):
                # Check kan
                # Any but us
                if sum(kan_count) < 4:
                    self._check_for_open_kan(other_pl, player)
                
                # Check pon
                # Any but us
                self._check_for_pon(other_pl, player)
                
                # Check chi
                # Only next player
                self._check_for_chi(other_pl, player)
            
            # Check ron
            # Any but us
            if self._check_for_ron(other_pl, player):
                ron_players.append(other_pl.idx)
        
        def disc():
            # Riichi points and stick should have been modified here, but it is not
            # TODO: Do we want to send a points update here?
            
            # At this point, we have a draw if there are 4 riichi
            if riichi_count == 4:
                self._add_event(DrawEvent(DrawEvent.RIICHI))
                self.start_round('bonus')
                return
            
            # If there's now a total of 4 kans, and a single player doesn't
            # have all of them, it's a draw
            if sum(kan_count) == 4 and not kans_same_player:
                self._add_event(DrawEvent(DrawEvent.KAN))
                self.start_round('bonus')
                return
            
            # If any ron queried players declined, put them in furiten
            for ron_idx in ron_players:
                p = self.players[ron_idx]
                if not p.is_furiten():
                    self._add_event(FuritenEvent(True), p)
                p.is_temp_furiten = True
            
            # Draw a tile for the next player
            self.draw_tile((player_idx + 1) % 4)
        self._wait_for_queries(disc)
    
    def call_pon(self, tiles136, calling_player_idx, discarding_player_idx):
        calling_player = self.players[calling_player_idx]
        discarding_player = self.players[discarding_player_idx]
        
        # Can't be the same
        if calling_player == discarding_player:
            raise InvalidActionError("P{} can't pon from himself".format(
                calling_player.idx))
        
        # Must be 3 tiles for pon
        if len(tiles136) != 3:
            raise InvalidActionError("Invalid pon {}".format(
                to_tiles(tiles136)))
        
        # Must all be the same tile
        if not all(tiles136[0]//4 == t//4 for t in tiles136):
            raise InvalidActionError("Invalid pon {}".format(
                to_tiles(tiles136)))
        
        # The last discard of the discarding player must be in the tiles list
        discard = discarding_player.discards[-1]
        if not discard.tile in tiles136:
            raise InvalidActionError("P{}'s last discard {} wasn't in {}".format(
                discarding_player.idx, Tile(discard.tile),
                to_tiles(tiles136)))
        
        # The other tiles must be in the calling player's hand
        for t136 in tiles136:
            if t136 == discard.tile:
                continue
            if not t136 in calling_player.hand:
                raise InvalidActionError("{} was not in P{}'s hand {}".format(
                    Tile(t136), calling_player.idx, to_tiles(calling_player.hand)))
        
        # Remove the tiles from the caller's hand
        tiles_from_hand = tiles136[:]
        tiles_from_hand.remove(discard.tile)
        for t in tiles_from_hand:
            calling_player.hand.remove(t)
        
        # Set the discard as called
        discard.call_tile(calling_player.idx)
        
        # Add the meld and send the event
        meld = Meld(Meld.PON, tiles136, discarding_player.idx, discard.tile)
        calling_player.melds.append(meld)
        self._add_event(CallEvent(meld.clone(), calling_player.idx))
        self.active_player = calling_player.idx
        
        # Cancel ippatsus
        for p in self.players:
            p.is_ippatsu = False
        
        # Player must now discard a tile
        self._ask_for_discard(calling_player, [discard.tile // 4])

    def call_chi(self, tiles136, calling_player_idx, discarding_player_idx):
        calling_player = self.players[calling_player_idx]
        discarding_player = self.players[discarding_player_idx]
        
        # Must be the previous player
        if (discarding_player_idx + 1) % 4 != calling_player_idx:
            raise InvalidActionError("P{} can't chi from P{}".format(
                calling_player.idx, discarding_player.idx))
        
        # Must be 3 tiles for chi
        if len(tiles136) != 3:
            raise InvalidActionError("Invalid chi {}".format(
                to_tiles(tiles136)))
        
        tiles34 = sorted([t // 4 for t in tiles136])
        # Cannot be an honor
        if any(mutil.is_honor(t) for t in tiles34):
            raise InvalidActionError("Invalid chi {}".format(
                to_tiles(tiles136)))
        
        # Tiles must be the same suit
        if not all(t//9 == tiles34[0]//9 for t in tiles34):
            raise InvalidActionError("Invalid chi {}".format(
                to_tiles(tiles136)))
        
        # Tiles must be in sequence
        if not (tiles34[2] == tiles34[1]+1 and tiles34[1] == tiles34[0]+1):
            raise InvalidActionError("Invalid chi {}".format(
                to_tiles(tiles136)))

        # The last discard of the discarding player must be in the tiles list
        discard = discarding_player.discards[-1]
        if not discard.tile in tiles136:
            raise InvalidActionError("P{}'s last discard {} wasn't in {}".format(
                discarding_player.idx, Tile(discard.tile),
                to_tiles(tiles136)))
        
        # The other tiles must be in the calling player's hand
        for t136 in tiles136:
            if t136 == discard.tile:
                continue
            if not t136 in calling_player.hand:
                raise InvalidActionError("{} was not in P{}'s hand {}".format(
                    Tile(t136), calling_player.idx, to_tiles(calling_player.hand)))
        
        # Remove the tiles from the caller's hand
        tiles_from_hand = tiles136[:]
        tiles_from_hand.remove(discard.tile)
        for t in tiles_from_hand:
            calling_player.hand.remove(t)
        
        # Set the discard as called
        discard.call_tile(calling_player.idx)
        
        # Add the meld and send the event
        meld = Meld(Meld.CHI, tiles136, discarding_player.idx, discard.tile)
        calling_player.melds.append(meld)
        self._add_event(CallEvent(meld.clone(), calling_player.idx))
        self.active_player = calling_player.idx
        
        # Cancel ippatsus
        for p in self.players:
            p.is_ippatsu = False
        
        # Kuikae says:
        #   * Cannot discard the called tile
        #   * If this is a left or right chi, we can't discard the tile on the
        #     other end
        discard34 = discard.tile // 4
        kuikae = [discard34]
        if tiles34[0] == discard34:
            # Left chi
            if discard34 % 9 <= 5:
                kuikae.append(discard34 + 3)
        elif tiles34[2] == discard34:
            # Right chi
            if discard34 % 9 >= 3:
                kuikae.append(discard34 - 3)

        # Player must now discard a tile
        self._ask_for_discard(calling_player, kuikae)

    def call_closed_or_added_kan(self, tiles136, player_idx):
        player = self.players[player_idx]
        
        # Must be the active player
        if self.active_player != player_idx:
            raise InvalidActionError("P{} is not active player, P{} is".format(
                player_idx, self.active_player))
        
        # Must be 4 tiles
        if len(tiles136) != 4:
            raise InvalidActionError("Invalid kan {}".format(
                to_tiles(tiles136)))
        
        # Must all be the same tile
        if not all(tiles136[0] // 4 == t // 4 for t in tiles136):
            raise InvalidActionError("Invalid kan {}".format(
                to_tiles(tiles136)))
        
        # Must either have all tiles, or a pon and one of the tiles
        if all(t in player.hand for t in tiles136):
            closed = True
        elif any(meld.kind == Meld.PON and meld.tiles[0]//4 == tiles136[0]//4 for meld in player.melds) and \
             any(t//4 == tiles136[0]//4 for t in player.hand):
            closed = False
        else:
            raise InvalidActionError("P{} can't ckan or akan {}".format(
                player_idx, to_tiles(tiles136)))
        
        ron_players = []
        if closed:
            for t in tiles136:
                player.hand.remove(t)
            meld = Meld(Meld.CKAN, tiles136)
            player.melds.append(meld)
            self._add_event(CallEvent(meld.clone(), player.idx))

            # TODO: chankan for kokushi?
        else:
            added_tile = None
            for t in tiles136:
                if t in player.hand:
                    player.hand.remove(t)
                    added_tile = t
            meld = None
            for m in player.melds:
                if m.tiles[0]//4 == tiles136[0]//4:
                    meld = m
                    continue
            meld.promote_to_akan(t)
            self._add_event(CallEvent(meld.clone(), player.idx))
            
            # Check for chankan.
            for other_pl in self.players:
                if self._check_for_ron(other_pl, player, added_tile):
                    ron_players.append(other_pl.idx)
        
        # Cancel ippatsus
        for p in self.players:
            p.is_ippatsu = False

        # We have lost a tile here, so recalculate for rinshan
        player.calculate_shanten_and_ukeire()
        
        def kan1():
            # If any ron queried players declined, put them in furiten
            for ron_idx in ron_players:
                p = self.players[ron_idx]
                was_furiten = p.is_furiten()
                p.is_temp_furiten = True
                if not was_furiten:
                    self._add_event(FuritenEvent(p.is_furiten()), p)
            
            if closed:
                # Reveal new dora instantly
                t136 = self._draw_tile('dora')
                self.dora_indicators.append(t136)
                self._add_event(DoraEvent(t136))
            else:
                # After the player's next discard, it will reveal a dora
                player.has_pending_dora = True
            
            self.draw_tile(player.idx, True) # Dead wall draw

        self._wait_for_queries(kan1)

    def call_open_kan(self, tiles136, calling_player_idx, discarding_player_idx):
        calling_player = self.players[calling_player_idx]
        discarding_player = self.players[discarding_player_idx]
        
        # Can't be the same
        if calling_player == discarding_player:
            raise InvalidActionError("P{} can't kan from himself".format(
                calling_player.idx))
        
        # Must be 4 tiles for kan
        if len(tiles136) != 4:
            raise InvalidActionError("Invalid kan {}".format(
                to_tiles(tiles136)))
        
        # Must all be the same tile
        if not all(tiles136[0]//4 == t//4 for t in tiles136):
            raise InvalidActionError("Invalid kan {}".format(
                to_tiles(tiles136)))
        
        # The last discard of the discarding player must be in the tiles list
        discard = discarding_player.discards[-1]
        if not discard.tile in tiles136:
            raise InvalidActionError("P{}'s last discard {} wasn't in {}".format(
                discarding_player.idx, Tile(discard.tile),
                to_tiles(tiles136)))
        
        # The other tiles must be in the calling player's hand
        for t136 in tiles136:
            if t136 == discard.tile:
                continue
            if not t136 in calling_player.hand:
                raise InvalidActionError("{} was not in P{}'s hand {}".format(
                    Tile(t136), calling_player.idx, to_tiles(calling_player.hand)))
        
        # Remove the tiles from the caller's hand
        tiles_from_hand = tiles136[:]
        tiles_from_hand.remove(discard.tile)
        for t in tiles_from_hand:
            calling_player.hand.remove(t)
        
        # Set the discard as called
        discard.call_tile(calling_player.idx)
        
        # Add the meld and send the event
        meld = Meld(Meld.MKAN, tiles136, discarding_player.idx, discard.tile)
        calling_player.melds.append(meld)
        self._add_event(CallEvent(meld.clone(), calling_player.idx))
        self.active_player = calling_player.idx
        
        calling_player.calculate_shanten_and_ukeire()
        
        def kan1():
            # Cancel ippatsus
            for p in self.players:
                p.is_ippatsu = False
            
            # After the player's next discard, it will reveal a dora
            calling_player.has_pending_dora = True
            
            self.draw_tile(calling_player_idx, True) # Dead wall draw
        
        self._wait_for_queries(kan1)

    def do_9tile_draw(self, player_idx):
        player = self.players[player_idx]
        
        # Must be the first tile drawn
        if len(player.discards) > 0:
            raise InvalidActionError("P{} can't draw, has discards".format(
                player.idx))

        # Must be no calls
        if sum(len(p.melds) for p in self.players):
            raise InvalidActionError("P{} can't draw, there are calls".format(
                player.idx))

        # Hand must have at least 9 honors or terminals
        t34 = tc.to_34_array(player.hand)
        term_hon = [bool(n) for i, n in enumerate(t34) if mutil.is_terminal(i) or mutil.is_honor(i)]
        
        if sum(term_hon) < 9:
            raise InvalidActionError("P{} can't draw with {}".format(
                player.idx, to_tiles(player.hand)))
        
        # It's a draw
        self._add_event(DrawEvent(DrawEvent.TERMINAL))
        self.start_round('bonus')

    def do_tsumo(self, player_idx):
        player = self.players[player_idx]
        
        result = self._get_tsumo(player, player.latest_draw_was_dead_wall)
        
        if result.error:
            raise InvalidActionError("P{} can't tsumo, {}".format(
                player.idx, result.error))

        hand = player.hand[:]
        melds = [m.tiles[:] for m in player.melds]
        dora_ind = self.dora_indicators[:]
        ura_dora_ind = []

        if player.is_riichi:
            # If the player was riichi, fetch ura dora and recalculate the hand value
            # TODO: Technically, we could have alternate logic for ura dora, since non-winning
            # players aren't getting any dora. But it's complicated for ron...
            for i in range(len(dora_ind)):
                ura_dora_ind.append(self._draw_tile('dora'))
            self.dora_indicators.extend(ura_dora_ind)
            result = self._get_tsumo(player, player.latest_draw_was_dead_wall)
        
        han = result.han
        fu = result.fu
        
        # Extract yaku
        c = self._get_base_hand_config()
        yaku = []
        skip_yaku = [c.yaku.dora.name, c.yaku.aka_dora.name]
        for y in result.yaku:
            # Build a list of (name, han) for each yaku
            if y.name in skip_yaku:
                continue
            h = y.han_open if result.is_open_hand else y.han_closed
            assert h is not None
            yaku.append((y.name, h))
        
        # Get the number of dora, aka dora, and ura dora
        # TODO: Does this count double dora?
        dora_count = 0
        aka_dora_count = 0
        ura_dora_count = 0
        all_tiles = hand + [t136 for meld in melds for t136 in meld]
        for t136 in all_tiles:
            dora_count += mutil.plus_dora(t136, dora_ind)
            ura_dora_count += mutil.plus_dora(t136, ura_dora_ind)
            aka_dora_count += mutil.plus_dora(t136, [], True) # TODO: aka dora config
        
        if dora_count > 0:
            yaku.append(("Dora", dora_count))
        if aka_dora_count > 0:
            yaku.append(("Aka Dora", aka_dora_count))
        if ura_dora_count > 0:
            yaku.append(("Ura Dora", ura_dora_count))
        
        total_from_hand = result.cost["main"] + result.cost["additional"] * 2

        self._redistribute_points(player, result.cost, None)
        points = [p.points for p in self.players]

        win = Win(
            player.idx,
            hand,
            None,
            melds,
            dora_ind,
            ura_dora_ind,
            han,
            fu,
            yaku,
            result.cost["yaku_level"],
            total_from_hand,
            points
        )
        self._add_event(WinEvent(win))
        self.riichi_sticks = 0

        if self.dealer() == player.idx:
            self.start_round('bonus')
        else:
            self.start_round('next')

    def do_ron(self, calling_player_idxs, discarding_player_idx, chankan136=None):

        discarding_player = self.players[discarding_player_idx]

        # If this is a normal ron, the discarder must have at least one discard
        if chankan136 is None and len(discarding_player.discards) == 0:
            raise InvalidActionError("P{} has no discards for ron".format(
                    discarding_player_idx))

        # If this is chankan, the chankan tile must be in the discarder's melds
        if (chankan136 is not None and
            not any(m.is_kan() and m.tiles[0]//34 == chankan136//4 for m in discarding_player.melds)):
            raise InvalidActionError("P{} has no {} kan in {}".format(
                    discarding_player_idx, Tile(chankan136), discarding_player.melds))

        # Verify all hands first
        for calling_player_idx in calling_player_idxs:
            if calling_player_idx == discarding_player_idx:
                raise InvalidActionError("P{} can't ron himself".format(
                    discarding_player_idx))
            
            result = self._get_ron(
                self.players[calling_player_idx],
                self.players[discarding_player_idx],
                chankan136
            )

            if result.error:
                raise InvalidActionError("P{} can't ron P{}, {}".format(
                    calling_player_idx, discarding_player_idx, result.error))

        if chankan136 is not None:
            ron136 = chankan136
        else:
            ron136 = discarding_player.discards[-1].tile
            # If the discarding player just riichi'd, return the points
            if discarding_player.discards[-1].is_riichi:
                discarding_player.points += 1000
                self.riichi_sticks -= 1

        # The player who gets riichi sticks + bonus is the next in turn who ronned
        bonus_pl_idx = min(calling_player_idxs, key=lambda cpl_idx: (cpl_idx - discarding_player_idx) % 4)

        # TODO: It would be nice to do something special with ura dora logic,
        #       at least for the common case of a single ron
        dora_ind = self.dora_indicators[:]
        ura_dora_ind = []
        for i in range(len(dora_ind)):
            ura_dora_ind.append(self._draw_tile('dora'))

        for calling_player_idx in calling_player_idxs:
            calling_player = self.players[calling_player_idx]

            # If this is not the player who should get the riichi sticks and bonus,
            # reset the values before calculating scores
            old_riichi_sticks = self.riichi_sticks
            old_bonus = self.bonus
            if bonus_pl_idx != calling_player_idx:
                self.riichi_sticks = 0
                self.bonus = 0

            result = self._get_ron(calling_player, discarding_player, chankan136)

            hand = calling_player.hand[:]
            melds = [m.tiles[:] for m in calling_player.melds]

            if calling_player.is_riichi:
                # If the player was riichi, recalculate the hand value
                # TODO: Technically, we could have alternate logic for ura dora, since non-winning
                # players aren't getting any dora. But it's complicated for ron...
                self.dora_indicators = dora_ind + ura_dora_ind
                result = self._get_ron(calling_player, discarding_player, chankan136)
                self.dora_indicators = dora_ind
            
            # Reset the riichi and bonus after score calculation
            self.riichi_sticks = old_riichi_sticks
            self.bonus = old_bonus

            han = result.han
            fu = result.fu
            
            # Extract yaku
            c = self._get_base_hand_config()
            yaku = []
            skip_yaku = [c.yaku.dora.name, c.yaku.aka_dora.name]
            for y in result.yaku:
                # Build a list of (name, han) for each yaku
                if y.name in skip_yaku:
                    continue
                h = y.han_open if result.is_open_hand else y.han_closed
                assert h is not None
                yaku.append((y.name, h))
            
            # Get the number of dora, aka dora, and ura dora
            # TODO: Does this count double dora?
            dora_count = 0
            aka_dora_count = 0
            ura_dora_count = 0
            all_tiles = hand + [t136 for meld in melds for t136 in meld]
            for t136 in all_tiles:
                dora_count += mutil.plus_dora(t136, dora_ind)
                if calling_player.is_riichi:
                    ura_dora_count += mutil.plus_dora(t136, ura_dora_ind)
                aka_dora_count += mutil.plus_dora(t136, [], True) # TODO: aka dora config
            
            if dora_count > 0:
                yaku.append(("Dora", dora_count))
            if aka_dora_count > 0:
                yaku.append(("Aka Dora", aka_dora_count))
            if ura_dora_count > 0:
                yaku.append(("Ura Dora", ura_dora_count))
            
            total_from_hand = result.cost["main"] + result.cost["additional"] * 2

            self._redistribute_points(calling_player, result.cost, discarding_player)
            points = [p.points for p in self.players]

            win = Win(
                calling_player.idx,
                hand,
                ron136,
                melds,
                dora_ind,
                ura_dora_ind,
                han,
                fu,
                yaku,
                result.cost["yaku_level"],
                total_from_hand,
                points
            )
            self._add_event(WinEvent(win))

        # Riichi sticks reset after any win
        self.riichi_sticks = 0
        if any(pl_idx == self.dealer() for pl_idx in calling_player_idxs):
            self.start_round('bonus')
        else:
            self.start_round('next')

    def dump(self):
        print("{}{}-{} | T:{} | R:{}".format(
            self.wind, self.round, self.bonus, self.remaining_draws, self.riichi_sticks
        ))
        print("Dora: {}".format(self.dora_indicators))
        
        for pl in self.players:
            print("{}{}: {} {}".format(">" if pl.idx == self.active_player else " ", self.get_player_wind(pl), pl.name, sorted(pl.hand)))
            print(" | ".join(str(m) for m in pl.melds))
            print(" ".join(str(d) for d in pl.discards))
            print("=========================================")


class Lobby(object):
    pass


