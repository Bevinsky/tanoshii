
from engine import Game, Player, PreHandPlayer
from mahjong.tile import TilesConverter as tc
import random
from tile import tt
import tile
import traceback
import unittest

tstr = tc.to_one_line_string

def test_setup():
    g = Game()
    g.set_tile_preset("3p 9s")
    g.start_game([
        PreHandPlayer(g, "A", "222333m8889s555z"),
        Player(g, "B"),
        Player(g, "C"),
        Player(g, "D")
    ], shuffle_players=False)

    while True:
        g.dump()
        evs = g.pop_events()
        for e in evs:
            print(e)
        
        def parse_tile(s, poss):
            if any(c.isalpha() for c in s):
                if len(s) == 2: # t34
                    t34 = tile.TILES.index(s)
                    for t136 in poss:
                        if t136 // 4 == t34:
                            return t136
                return tt(s)
            return int(s)
        def find_qt(n, call=None):
            for ev in evs:
                if ev[1].name != n + "_query":
                    continue
                if call and ev[1].kind != call:
                    continue
                return ev

        while True:
            try:
                print("> ", end="")
                inp = input().split()
                # d, c, p, k, ri, draw, t, r
                if inp[0] == "d":
                    # d <tile>
                    pl, q = find_qt('discard')
                    if len(inp) == 1:
                        g.discard_tile(pl, q.allowed[-1], False)
                    else:
                        g.discard_tile(pl, parse_tile(inp[1], q.allowed), False)
                elif inp[0] == "x":
                    g.run_continuation()
                elif inp[0] == "draw":
                    pl, q = find_qt('draw')
                    g.do_9tile_draw(pl)
                elif inp[0] == "c":
                    # c <choice>
                    pl, q = find_qt('call', 'chi')
                    g.call_chi(q.choices[int(inp[1])], pl, q.from_who)
                elif inp[0] == "p":
                    # p <choice>
                    pl, q = find_qt('call', 'pon')
                    g.call_pon(q.choices[int(inp[1])], pl, q.from_who)
                elif inp[0] == "k":
                    # k <choice>
                    pl, q = find_qt('call', 'kan')
                    if q.from_who is None:
                        g.call_closed_or_added_kan(q.choices[int(inp[1])], pl)
                    else:
                        g.call_open_kan(q.choices[int(inp[1])], pl, q.from_who)
                elif inp[0] == "ri":
                    # ri <tile>
                    pl, q = find_qt('riichi')
                    g.discard_tile(pl, parse_tile(inp[1], q.allowed), True)
                elif inp[0] == "r":
                    # r
                    pl, q = find_qt('ron')
                    g.do_ron([pl], q.from_player, None)
                elif inp[0] == "t":
                    # t
                    pl, q = find_qt('tsumo')
                    g.do_tsumo(pl)
                else:
                    continue
                break
            except EOFError:
                return
            except KeyboardInterrupt:
                return
            except BaseException as e:
                print (traceback.format_exc())

class TestGame(Game):
    def __init__(self, hands, first_tiles):
        super().__init__()
        random.seed(first_tiles)
        self.set_tile_preset(first_tiles)
        self.test_hands = hands
        self.start_game([
            Player(self, "P{}".format(i)) if h is None else PreHandPlayer(self, "P{}".format(i), h) for i, h in enumerate(self.test_hands)
        ], False)

class DrawTest(unittest.TestCase):
    def test_4wind_draw(self):
        g = TestGame([
            "1z",
            "1z",
            "1z",
            "1z"
        ], "")
        g.discard_tile(0, tt("ew0"))
        g.discard_tile(1, tt("ew1"))
        g.discard_tile(2, tt("ew2"))
        g.discard_tile(3, tt("ew3"))
        evs = g.pop_events()
        self.assertTrue(any(ev.name == 'draw_event' and ev.kind == 'wind' for ev in evs))

class EngineTest(unittest.TestCase):
    def test_start_game(self):
        g = TestGame([
            "12679m24s5579p22z",
            "34556m12789p05s1z",
            "689m345067s5572z",
            "134m6667p23556s4z"
        ], "ew sw ww nw")
        



"""




"""



if __name__ == "__main__":
    unittest.main()
    #random.seed(2)
    #test_setup()