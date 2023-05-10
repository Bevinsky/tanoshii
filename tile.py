
uni_tile = False

# convert tile string to 
def tt(s):
    return TILES.index(s[0:2]) * 4 + int(s[2])

def to_tiles(l):
    if type(l) == list:
        return [Tile(t) for t in l]
    elif type(l) == tuple:
        return tuple([Tile(t) for t in l])

UNICODE_TILES = """
    🀇 🀈 🀉 🀊 🀋 🀌 🀍 🀎 🀏
    🀙 🀚 🀛 🀜 🀝 🀞 🀟 🀠 🀡
    🀐 🀑 🀒 🀓 🀔 🀕 🀖 🀗 🀘
    🀀 🀁 🀂 🀃
    🀆 🀅 🀄
""".split()

TILES = """
    1m 2m 3m 4m 5m 6m 7m 8m 9m
    1p 2p 3p 4p 5p 6p 7p 8p 9p
    1s 2s 3s 4s 5s 6s 7s 8s 9s
    ew sw ww nw
    wd gd rd
""".split()

class Tile(int):
    def __repr__(self):
        if uni_tile:
            return UNICODE_TILES[self // 4] + " " + str(self % 4)
        return TILES[self // 4] + str(self % 4)

class Tile34(int):
    def __repr__(self):
        return TILES[self]

def tile34_string_to_136_array(s : str):
    l = []
    pool = [0]*34
    for t34s in map(''.join, zip(*[iter(s.replace(" ", ""))]*2)):
        t34 = TILES.index(t34s)
        l.append(t34 * 4 + pool[t34])
        pool[t34] += 1
    return to_tiles(l)