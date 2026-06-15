"""Last.fm commands (greed-equivalent "LastFM" category).

Real Last.fm Web API integration: link an account, now-playing, recent tracks,
top artists/albums/tracks, artist/album/track lookups, loved tracks, weekly
charts, who-knows and an album-art collage. Requires the LASTFM_API_KEY secret.

Registered via the shared collector pattern: a CMDS list of
(name, aliases, syntax, desc, fn) tuples plus register(bot, CATEGORIES, helpers).
"""
import asyncio
import io
import os
from urllib.parse import quote

import aiohttp
import discord
from discord.ext import commands

H = None              # helpers namespace (.error/.success/.info/.load_data/.save_data)
CMDS = []             # (name, aliases, syntax, desc, callback)
_STORE = "data/lastfm.json"
_API = "http://ws.audioscrobbler.com/2.0/"


def c(name, syntax, desc, aliases=None):
    def deco(fn):
        CMDS.append((name, aliases or [], syntax, desc, fn))
        return fn
    return deco


def _key():
    return os.environ.get("LASTFM_API_KEY")


def _links():
    return H.load_data(_STORE, {})


def _save_links(d):
    H.save_data(_STORE, d)


async def _api(method, **params):
    """Call the Last.fm API; returns parsed JSON dict or None on failure."""
    key = _key()
    if not key:
        return None
    q = {"method": method, "api_key": key, "format": "json"}
    q.update({k: v for k, v in params.items() if v is not None})
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(_API, params=q, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    return None
                return await r.json()
    except Exception:
        return None


async def _fetch_bytes(url):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    return None
                return await r.read()
    except Exception:
        return None


def _need_key(ctx):
    return H.error(
        "Last.fm isn't configured yet. Ask the server owner to add a "
        "`LASTFM_API_KEY` secret (free from last.fm/api)."
    )


def _resolve(ctx, arg):
    """Resolve a Last.fm username from: a mention (their linked account), a raw
    username argument, or the caller's own linked account. Returns (username, err)."""
    links = _links()
    if ctx.message.mentions:
        m = ctx.message.mentions[0]
        u = links.get(str(m.id))
        if not u:
            return None, H.error(f"{m.mention} hasn't linked a Last.fm account.")
        return u, None
    if arg:
        return arg.strip().lstrip("@"), None
    u = links.get(str(ctx.author.id))
    if not u:
        return None, H.error("Link your account first with `$fmset <username>`.")
    return u, None


def _img(images, size="extralarge"):
    if not images:
        return None
    by = {i.get("size"): i.get("#text") for i in images if i.get("#text")}
    return by.get(size) or by.get("large") or by.get("medium") or next(iter(by.values()), None)


def _profile_url(user):
    return f"https://www.last.fm/user/{quote(user)}"


# ──────────────────────────── account linking ────────────────────────────
@c("fmset", "fmset <username>", "Link your Last.fm account", ["setfm", "fmlogin"])
async def fmset(ctx, username: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    if not username:
        return await ctx.send(embed=H.error("Usage: `$fmset <your last.fm username>`"))
    data = await _api("user.getInfo", user=username)
    if not data or "user" not in data:
        return await ctx.send(embed=H.error(f"No Last.fm user named **{username}** found."))
    links = _links()
    links[str(ctx.author.id)] = data["user"]["name"]
    _save_links(links)
    await ctx.send(embed=H.success(f"Linked your Last.fm account: **{data['user']['name']}**."))


@c("fmunset", "fmunset", "Unlink your Last.fm account", ["fmlogout"])
async def fmunset(ctx):
    links = _links()
    if links.pop(str(ctx.author.id), None) is None:
        return await ctx.send(embed=H.error("You don't have a linked Last.fm account."))
    _save_links(links)
    await ctx.send(embed=H.success("Unlinked your Last.fm account."))


# ──────────────────────────── now playing ────────────────────────────
@c("fm", "fm [user|username]", "Show what you're scrobbling now", ["nowplaying", "np"])
async def fm(ctx, *, arg: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    user, err = _resolve(ctx, arg)
    if err:
        return await ctx.send(embed=err)
    data = await _api("user.getRecentTracks", user=user, limit=1)
    if not data or "recenttracks" not in data:
        return await ctx.send(embed=H.error(f"Couldn't fetch tracks for **{user}**."))
    tracks = data["recenttracks"].get("track", [])
    if not tracks:
        return await ctx.send(embed=H.error(f"**{user}** has no scrobbles."))
    t = tracks[0] if isinstance(tracks, list) else tracks
    now = t.get("@attr", {}).get("nowplaying")
    title = t.get("name", "?")
    artist = t.get("artist", {}).get("#text", "?")
    album = t.get("album", {}).get("#text", "")
    e = discord.Embed(
        title=title, url=t.get("url"),
        description=f"by **{artist}**" + (f"\non *{album}*" if album else ""),
        color=0xD51007,
    )
    art = _img(t.get("image"))
    if art:
        e.set_thumbnail(url=art)
    state = "Now playing" if now else "Last played"
    e.set_author(name=f"{state} — {user}", url=_profile_url(user))
    await ctx.send(embed=e)


@c("fmrecent", "fmrecent [user]", "Your recent scrobbles", ["recenttracks", "fmrt"])
async def fmrecent(ctx, *, arg: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    user, err = _resolve(ctx, arg)
    if err:
        return await ctx.send(embed=err)
    data = await _api("user.getRecentTracks", user=user, limit=10)
    tracks = (data or {}).get("recenttracks", {}).get("track", [])
    if not tracks:
        return await ctx.send(embed=H.error(f"No recent tracks for **{user}**."))
    lines = []
    for t in (tracks if isinstance(tracks, list) else [tracks])[:10]:
        a = t.get("artist", {}).get("#text", "?")
        lines.append(f"**{t.get('name','?')}** — {a}")
    e = discord.Embed(title=f"Recent tracks — {user}", url=_profile_url(user),
                      description="\n".join(lines)[:4096], color=0xD51007)
    await ctx.send(embed=e)


# ──────────────────────────── top charts ────────────────────────────
def _period(arg):
    m = {"week": "7day", "7day": "7day", "month": "1month", "1month": "1month",
         "3month": "3month", "6month": "6month", "year": "12month",
         "12month": "12month", "all": "overall", "overall": "overall"}
    return m.get((arg or "all").lower(), "overall")


async def _top(ctx, arg, method, key, label, fmt):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    parts = (arg or "").split()
    period = "overall"
    rest = []
    for p in parts:
        if p.lower() in ("week", "month", "year", "all", "7day", "1month",
                         "3month", "6month", "12month", "overall"):
            period = _period(p)
        else:
            rest.append(p)
    user, err = _resolve(ctx, " ".join(rest) if rest else None)
    if err:
        return await ctx.send(embed=err)
    data = await _api(method, user=user, period=period, limit=10)
    items = (data or {}).get(key, {}).get(label, [])
    if not items:
        return await ctx.send(embed=H.error(f"No data for **{user}**."))
    lines = [fmt(i, n) for n, i in enumerate(items[:10], 1)]
    e = discord.Embed(title=f"Top {label} ({period}) — {user}", url=_profile_url(user),
                      description="\n".join(lines)[:4096], color=0xD51007)
    await ctx.send(embed=e)


@c("fmtopartists", "fmtopartists [period] [user]", "Your top artists", ["fmta", "topartists"])
async def fmtopartists(ctx, *, arg: str = None):
    await _top(ctx, arg, "user.getTopArtists", "topartists", "artist",
               lambda i, n: f"`{n}.` **{i.get('name','?')}** — {i.get('playcount','0')} plays")


@c("fmtoptracks", "fmtoptracks [period] [user]", "Your top tracks", ["fmtt", "toptracks"])
async def fmtoptracks(ctx, *, arg: str = None):
    await _top(ctx, arg, "user.getTopTracks", "toptracks", "track",
               lambda i, n: f"`{n}.` **{i.get('name','?')}** — {i.get('artist',{}).get('name','?')} ({i.get('playcount','0')})")


@c("fmtopalbums", "fmtopalbums [period] [user]", "Your top albums", ["fmtal", "topalbums"])
async def fmtopalbums(ctx, *, arg: str = None):
    await _top(ctx, arg, "user.getTopAlbums", "topalbums", "album",
               lambda i, n: f"`{n}.` **{i.get('name','?')}** — {i.get('artist',{}).get('name','?')} ({i.get('playcount','0')})")


# ──────────────────────────── profile / stats ────────────────────────────
@c("fmprofile", "fmprofile [user]", "Your Last.fm profile", ["fminfo"])
async def fmprofile(ctx, *, arg: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    user, err = _resolve(ctx, arg)
    if err:
        return await ctx.send(embed=err)
    data = await _api("user.getInfo", user=user)
    u = (data or {}).get("user")
    if not u:
        return await ctx.send(embed=H.error(f"No profile for **{user}**."))
    e = discord.Embed(title=u.get("name"), url=u.get("url"), color=0xD51007)
    e.add_field(name="Scrobbles", value=f"{int(u.get('playcount',0)):,}")
    e.add_field(name="Artists", value=f"{int(u.get('artist_count',0)):,}")
    e.add_field(name="Tracks", value=f"{int(u.get('track_count',0)):,}")
    if u.get("country"):
        e.add_field(name="Country", value=u["country"])
    art = _img(u.get("image"))
    if art:
        e.set_thumbnail(url=art)
    await ctx.send(embed=e)


@c("fmscrobbles", "fmscrobbles [user]", "Your total scrobble count", ["scrobbles"])
async def fmscrobbles(ctx, *, arg: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    user, err = _resolve(ctx, arg)
    if err:
        return await ctx.send(embed=err)
    data = await _api("user.getInfo", user=user)
    u = (data or {}).get("user")
    if not u:
        return await ctx.send(embed=H.error(f"No profile for **{user}**."))
    await ctx.send(embed=H.info(f"**{user}** has **{int(u.get('playcount',0)):,}** scrobbles."))


# ──────────────────────────── lookups ────────────────────────────
@c("fmartist", "fmartist <artist>", "Artist info + your playcount")
async def fmartist(ctx, *, artist: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    if not artist:
        return await ctx.send(embed=H.error("Usage: `$fmartist <artist>`"))
    user = _links().get(str(ctx.author.id))
    data = await _api("artist.getInfo", artist=artist, username=user)
    a = (data or {}).get("artist")
    if not a:
        return await ctx.send(embed=H.error(f"No artist **{artist}** found."))
    stats = a.get("stats", {})
    bio = (a.get("bio", {}).get("summary") or "").split("<a")[0].strip()
    e = discord.Embed(title=a.get("name"), url=a.get("url"),
                      description=bio[:600] or None, color=0xD51007)
    e.add_field(name="Listeners", value=f"{int(stats.get('listeners',0)):,}")
    e.add_field(name="Plays", value=f"{int(stats.get('playcount',0)):,}")
    if user and stats.get("userplaycount"):
        e.add_field(name="Your plays", value=f"{int(stats['userplaycount']):,}")
    tags = ", ".join(t["name"] for t in a.get("tags", {}).get("tag", [])[:5])
    if tags:
        e.add_field(name="Tags", value=tags, inline=False)
    await ctx.send(embed=e)


@c("fmplays", "fmplays <artist>", "Your playcount for an artist")
async def fmplays(ctx, *, artist: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    if not artist:
        return await ctx.send(embed=H.error("Usage: `$fmplays <artist>`"))
    user = _links().get(str(ctx.author.id))
    if not user:
        return await ctx.send(embed=H.error("Link your account first with `$fmset`."))
    data = await _api("artist.getInfo", artist=artist, username=user)
    a = (data or {}).get("artist")
    if not a:
        return await ctx.send(embed=H.error(f"No artist **{artist}** found."))
    pc = a.get("stats", {}).get("userplaycount", "0")
    await ctx.send(embed=H.info(f"You've played **{a.get('name')}** **{int(pc):,}** times."))


@c("fmalbum", "fmalbum <artist> - <album>", "Album info")
async def fmalbum(ctx, *, arg: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    if not arg or " - " not in arg:
        return await ctx.send(embed=H.error("Usage: `$fmalbum <artist> - <album>`"))
    artist, album = [x.strip() for x in arg.split(" - ", 1)]
    user = _links().get(str(ctx.author.id))
    data = await _api("album.getInfo", artist=artist, album=album, username=user)
    a = (data or {}).get("album")
    if not a:
        return await ctx.send(embed=H.error(f"No album **{album}** by **{artist}**."))
    e = discord.Embed(title=a.get("name"), url=a.get("url"),
                      description=f"by **{a.get('artist')}**", color=0xD51007)
    e.add_field(name="Listeners", value=f"{int(a.get('listeners',0)):,}")
    e.add_field(name="Plays", value=f"{int(a.get('playcount',0)):,}")
    if user and a.get("userplaycount"):
        e.add_field(name="Your plays", value=f"{int(a['userplaycount']):,}")
    art = _img(a.get("image"))
    if art:
        e.set_thumbnail(url=art)
    await ctx.send(embed=e)


@c("fmtrack", "fmtrack <artist> - <track>", "Track info")
async def fmtrack(ctx, *, arg: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    if not arg or " - " not in arg:
        return await ctx.send(embed=H.error("Usage: `$fmtrack <artist> - <track>`"))
    artist, track = [x.strip() for x in arg.split(" - ", 1)]
    user = _links().get(str(ctx.author.id))
    data = await _api("track.getInfo", artist=artist, track=track, username=user)
    t = (data or {}).get("track")
    if not t:
        return await ctx.send(embed=H.error(f"No track **{track}** by **{artist}**."))
    e = discord.Embed(title=t.get("name"), url=t.get("url"),
                      description=f"by **{t.get('artist',{}).get('name','?')}**", color=0xD51007)
    e.add_field(name="Listeners", value=f"{int(t.get('listeners',0)):,}")
    e.add_field(name="Plays", value=f"{int(t.get('playcount',0)):,}")
    if user and t.get("userplaycount"):
        e.add_field(name="Your plays", value=f"{int(t['userplaycount']):,}")
    await ctx.send(embed=e)


@c("fmsimilar", "fmsimilar <artist>", "Similar artists")
async def fmsimilar(ctx, *, artist: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    if not artist:
        return await ctx.send(embed=H.error("Usage: `$fmsimilar <artist>`"))
    data = await _api("artist.getSimilar", artist=artist, limit=10)
    items = (data or {}).get("similarartists", {}).get("artist", [])
    if not items:
        return await ctx.send(embed=H.error(f"No similar artists for **{artist}**."))
    names = "\n".join(f"`{n}.` {i['name']}" for n, i in enumerate(items[:10], 1))
    await ctx.send(embed=discord.Embed(title=f"Similar to {artist}", description=names, color=0xD51007))


@c("fmtags", "fmtags <artist>", "Top tags for an artist")
async def fmtags(ctx, *, artist: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    if not artist:
        return await ctx.send(embed=H.error("Usage: `$fmtags <artist>`"))
    data = await _api("artist.getTopTags", artist=artist)
    tags = (data or {}).get("toptags", {}).get("tag", [])
    if not tags:
        return await ctx.send(embed=H.error(f"No tags for **{artist}**."))
    names = ", ".join(t["name"] for t in tags[:15])
    await ctx.send(embed=H.info(f"**{artist}** tags: {names}"))


@c("fmloved", "fmloved [user]", "Loved tracks", ["fmlovedtracks"])
async def fmloved(ctx, *, arg: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    user, err = _resolve(ctx, arg)
    if err:
        return await ctx.send(embed=err)
    data = await _api("user.getLovedTracks", user=user, limit=10)
    items = (data or {}).get("lovedtracks", {}).get("track", [])
    if not items:
        return await ctx.send(embed=H.error(f"**{user}** has no loved tracks."))
    lines = [f"**{t.get('name','?')}** — {t.get('artist',{}).get('name','?')}" for t in items[:10]]
    e = discord.Embed(title=f"Loved tracks — {user}", url=_profile_url(user),
                      description="\n".join(lines)[:4096], color=0xD51007)
    await ctx.send(embed=e)


@c("fmcover", "fmcover [user]", "Album art of your current track")
async def fmcover(ctx, *, arg: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    user, err = _resolve(ctx, arg)
    if err:
        return await ctx.send(embed=err)
    data = await _api("user.getRecentTracks", user=user, limit=1)
    tracks = (data or {}).get("recenttracks", {}).get("track", [])
    if not tracks:
        return await ctx.send(embed=H.error(f"No scrobbles for **{user}**."))
    t = tracks[0] if isinstance(tracks, list) else tracks
    art = _img(t.get("image"))
    if not art:
        return await ctx.send(embed=H.error("No album art available."))
    e = discord.Embed(title=f"{t.get('name','?')} — {t.get('artist',{}).get('#text','?')}", color=0xD51007)
    e.set_image(url=art)
    await ctx.send(embed=e)


@c("fmcollage", "fmcollage [size] [period]", "Album-art collage grid", ["fmchart", "fmgrid"])
async def fmcollage(ctx, *, arg: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    from PIL import Image
    parts = (arg or "").split()
    size = 3
    period = "overall"
    for p in parts:
        if "x" in p.lower() and p.lower().split("x")[0].isdigit():
            size = max(2, min(5, int(p.lower().split("x")[0])))
        elif p.lower() in ("week", "month", "year", "all", "7day", "1month",
                           "3month", "6month", "12month", "overall"):
            period = _period(p)
    user = _links().get(str(ctx.author.id))
    if not user:
        return await ctx.send(embed=H.error("Link your account first with `$fmset`."))
    n = size * size
    data = await _api("user.getTopAlbums", user=user, period=period, limit=n)
    albums = (data or {}).get("topalbums", {}).get("album", [])
    if not albums:
        return await ctx.send(embed=H.error("Not enough album data for a collage."))
    async with ctx.typing():
        cell = 300
        canvas = Image.new("RGB", (cell * size, cell * size), (20, 20, 20))
        for idx, alb in enumerate(albums[:n]):
            url = _img(alb.get("image"))
            if not url:
                continue
            raw = await _fetch_bytes(url)
            if not raw:
                continue
            try:
                im = Image.open(io.BytesIO(raw)).convert("RGB").resize((cell, cell))
            except Exception:
                continue
            x = (idx % size) * cell
            y = (idx // size) * cell
            canvas.paste(im, (x, y))
        buf = io.BytesIO()
        canvas.save(buf, "PNG")
        buf.seek(0)
    await ctx.send(
        embed=H.info(f"**{user}** — top albums ({period}), {size}x{size}"),
        file=discord.File(buf, "collage.png"),
    )


@c("fmwhoknows", "fmwhoknows <artist>", "Who in this server knows an artist", ["whoknows", "wk"])
@commands.guild_only()
async def fmwhoknows(ctx, *, artist: str = None):
    if not _key():
        return await ctx.send(embed=_need_key(ctx))
    if not artist:
        return await ctx.send(embed=H.error("Usage: `$fmwhoknows <artist>`"))
    links = _links()
    member_ids = {str(m.id) for m in ctx.guild.members}
    linked = [(uid, name) for uid, name in links.items() if uid in member_ids]
    if not linked:
        return await ctx.send(embed=H.error("Nobody in this server has linked a Last.fm account."))
    linked = linked[:25]  # cap API fan-out
    results = []
    async with ctx.typing():
        for uid, name in linked:
            data = await _api("artist.getInfo", artist=artist, username=name)
            a = (data or {}).get("artist")
            if not a:
                continue
            pc = int(a.get("stats", {}).get("userplaycount", 0) or 0)
            if pc > 0:
                results.append((pc, uid, name))
    if not results:
        return await ctx.send(embed=H.error(f"Nobody here has scrobbled **{artist}**."))
    results.sort(reverse=True)
    lines = []
    for n, (pc, uid, name) in enumerate(results[:15], 1):
        member = ctx.guild.get_member(int(uid))
        who = member.display_name if member else name
        crown = " 👑" if n == 1 else ""
        lines.append(f"`{n}.` **{who}** — {pc:,} plays{crown}")
    e = discord.Embed(title=f"Who knows {artist}?", description="\n".join(lines), color=0xD51007)
    await ctx.send(embed=e)


def register(bot, CATEGORIES, helpers):
    global H
    H = helpers
    taken = set()
    for cmd in bot.commands:
        taken.add(cmd.name)
        taken.update(cmd.aliases)
    added = []
    for name, aliases, syntax, desc, fn in CMDS:
        if name in taken:
            continue
        live = [a for a in aliases if a not in taken]
        bot.add_command(commands.Command(fn, name=name, aliases=live))
        taken.add(name)
        taken.update(live)
        added.append((syntax, desc))
    if added:
        CATEGORIES["lastfm"] = {"emoji": "🎧", "commands": added}
    return len(added)
