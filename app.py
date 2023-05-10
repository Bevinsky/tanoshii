import asyncio
import logging
import random
import re
import socketio
import uvicorn

NAME_RE = re.compile("^[a-zA-Z0-9_-]+$")

sio = socketio.AsyncServer(async_mode='asgi')
app = socketio.ASGIApp(sio, static_files={
    '/': 'templates/index.html',
    '/static': './static'
})

def is_valid_name(name : str, for_room=None):
    #if not NAME_RE.match(name):
    #    return False
    if len(name) < 3:
        return False
    if len(name) > 20:
        return False
    if for_room:
        for pl in for_room.players:
            if pl is not None and pl.name == name:
                return False
    return name

class AppError(Exception):
    def __init__(self, msg):
        self.msg = msg
    def __str__(self):
        return "AppError({})".format(self.msg)

class Player(object):
    def __init__(self, sid, name):
        self.sid = sid
        self.name = name
        self.host = False
        self.ready = False
        self.room = None
        self.slot = None
        self.seat = None

class Room(object):
    def __init__(self, name):
        self.name = name
        self.players = [None] * 4
        self.game = None

    async def update(self):
        if not any([pl.host for pl in self.players if pl is not None]):
            valid_slots = [i for i, pl in enumerate(self.players) if pl is not None]
            self.players[valid_slots[0]].host = True

        await sio.emit("room_update", {
            "config": None,
            "players": [
                None if pl is None else
                {"name": pl.name, "archetype": None, "host": pl.host, "ready": pl.ready}
                for pl in self.players
            ]
        }, to=self.name)

    async def join(self, pl):
        if not is_valid_name(pl.name, self):
            raise AppError("Name is not valid")
        empty_slots = [i for i, pl in enumerate(self.players) if pl is None]
        if not empty_slots:
            raise AppError("Room is full")
        idx = empty_slots[0]
        pl.slot = idx
        pl.room = self
        self.players[idx] = pl
        async with sio.session(pl.sid) as sess:
            sess['player'] = pl
        await sio.emit("enter_room", {
            "code": self.name,
            "nickname": pl.name,
            "lobby_idx": pl.slot
        }, to=pl.sid)
        sio.enter_room(pl.sid, self.name)
        await self.update()

    async def leave(self, pl):
        for i, player in enumerate(self.players):
            if pl == player:
                sio.leave_room(pl.sid, self.name)
                self.players[i] = None
                if all(pl is None for pl in self.players):
                    del rooms[self.name]
                    break
                await self.update()
                break

rooms : dict[str, Room] = {}






@sio.event
async def connect(sid, environ, auth):
    pass

@sio.event
async def create_game(sid, name):
    async with sio.session(sid) as sess:
        if 'player' in sess:
            await sio.emit('server_error', "Already in a room")
            return

    pl = Player(sid, name)
    if not is_valid_name(name):
        await sio.emit('server_error', "Name is not valid")
        return
    r = Room(str(random.randint(10000, 99999)))
    rooms[r.name] = r
    try:
        await r.join(pl)
    except AppError as e:
        await sio.emit('server_error', e.msg)

    
@sio.event
async def join_game(sid, room_code, name):
    async with sio.session(sid) as sess:
        if 'player' in sess:
            await sio.emit('server_error', "Already in a room")
            return

    try:
        r = rooms[room_code]
        pl = Player(sid, name)
        await r.join(pl)
    except KeyError:
        await sio.emit('server_error', 'Room does not exist', to=sid)
    except AppError as e:
        await sio.emit('server_error', e.msg, to=sid)


@sio.event
async def disconnect(sid):
    async with sio.session(sid) as sess:
        if 'player' in sess:
            pl = sess['player']
            await pl.room.leave(pl)




if __name__ == "__main__":
    uvicorn.run(app, host='127.0.0.1', port=5000)