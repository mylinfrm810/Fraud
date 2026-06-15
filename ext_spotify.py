"""Spotify commands (greed-equivalent "Spotify"/socials category).

Uses the Spotify Web API client-credentials flow (app token, no per-user login)
to search and look up tracks, artists, albums, playlists, covers, previews and
recommendations. Requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET secrets.
"""
import base64
import os
import time
from urllib.parse import quote

import aiohttp
import discord
from discord.ext import commands

H = None
CMDS = []
_TOKEN = {"value": None, "exp": 0}
_API = "https://api.spotify.com/v1"
_GREEN = 0x1DB954


def c(name, syntax, desc, aliases=None):
    def deco(fn):
        CMDS.append((name, aliases or [], syntax, desc, fn))
        return fn
    return deco


def _creds():
    return os.environ.get("SPOTIFY_CLIENT_ID"), os.environ.get("SPOTIFY_CLIENT_SECRET")


def _need_key():
    return H.error(
        "Spotify isn't configured yet. Ask the server owner to add "
        "`SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` secrets "
        "(free from developer.spotify.com)."
    )


async def _token():
    cid, secret = _creds()
    if not cid or not secret:
        return None
    if _TOKEN["value"] and _TOKEN["exp"] > time.time() + 30:
        return _TOKEN["value"]
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                headers={"Authorization": f"Basic {auth}"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status != 200:
                    return None
                j = await r.json()
    except Exception:
        return None
    _TOKEN["value"] = j.get("access_token")
    _TOKEN["exp"] = time.time() + int(j.get("expires_in", 3600))
    return _TOKEN["value"]


async def _get(path, **params):
    tok = await _token()
    if not tok:
        return None
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{_API}{path}", params=params,
                             headers={"Authorization": f"Bearer {tok}"},
                             timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    return None
                return await r.json()
    except Exception:
        return None


async def _search(q, kind, limit=1):
    data = await _get("/search", q=q, type=kind, limit=limit)
    items = (data or {}).get(kind + "s", {}).get("items", [])
    return items


def _ms(ms):
    s = int(ms / 1000)
    return f"{s // 60}:{s % 60:02d}"


# ──────────────────────────── search / track ────────────────────────────
@c("spotify", "spotify <query>", "Search Spotify for a track", ["sp", "spotifytrack"])
async def spotify(ctx, *, query: str = None):
    if not all(_creds()):
        return await ctx.send(embed=_need_key())
    if not query:
        return await ctx.send(embed=H.error("Usage: `$spotify <song name>`"))
    items = await _search(query, "track")
    if not items:
        return await ctx.send(embed=H.error(f"No track found for **{query}**."))
    t = items[0]
    artists = ", ".join(a["name"] for a in t["artists"])
    e = discord.Embed(
        title=t["name"], url=t["external_urls"]["spotify"],
        description=f"by **{artists}**\non *{t['album']['name']}*",
        color=_GREEN,
    )
    e.add_field(name="Duration", value=_ms(t["duration_ms"]))
    e.add_field(name="Popularity", value=f"{t.get('popularity',0)}/100")
    if t["album"].get("images"):
        e.set_thumbnail(url=t["album"]["images"][0]["url"])
    if t.get("preview_url"):
        e.add_field(name="Preview", value=f"[30s clip]({t['preview_url']})", inline=False)
    await ctx.send(embed=e)


@c("spotifyartist", "spotifyartist <name>", "Look up a Spotify artist", ["spartist"])
async def spotifyartist(ctx, *, query: str = None):
    if not all(_creds()):
        return await ctx.send(embed=_need_key())
    if not query:
        return await ctx.send(embed=H.error("Usage: `$spotifyartist <name>`"))
    items = await _search(query, "artist")
    if not items:
        return await ctx.send(embed=H.error(f"No artist found for **{query}**."))
    a = items[0]
    e = discord.Embed(title=a["name"], url=a["external_urls"]["spotify"], color=_GREEN)
    e.add_field(name="Followers", value=f"{a['followers']['total']:,}")
    e.add_field(name="Popularity", value=f"{a.get('popularity',0)}/100")
    if a.get("genres"):
        e.add_field(name="Genres", value=", ".join(a["genres"][:5]), inline=False)
    if a.get("images"):
        e.set_thumbnail(url=a["images"][0]["url"])
    await ctx.send(embed=e)


@c("spotifyalbum", "spotifyalbum <query>", "Look up a Spotify album", ["spalbum"])
async def spotifyalbum(ctx, *, query: str = None):
    if not all(_creds()):
        return await ctx.send(embed=_need_key())
    if not query:
        return await ctx.send(embed=H.error("Usage: `$spotifyalbum <query>`"))
    items = await _search(query, "album")
    if not items:
        return await ctx.send(embed=H.error(f"No album found for **{query}**."))
    a = items[0]
    artists = ", ".join(ar["name"] for ar in a["artists"])
    e = discord.Embed(title=a["name"], url=a["external_urls"]["spotify"],
                      description=f"by **{artists}**", color=_GREEN)
    e.add_field(name="Released", value=a.get("release_date", "?"))
    e.add_field(name="Tracks", value=str(a.get("total_tracks", "?")))
    if a.get("images"):
        e.set_thumbnail(url=a["images"][0]["url"])
    await ctx.send(embed=e)


@c("spotifyplaylist", "spotifyplaylist <query>", "Search Spotify playlists", ["spplaylist"])
async def spotifyplaylist(ctx, *, query: str = None):
    if not all(_creds()):
        return await ctx.send(embed=_need_key())
    if not query:
        return await ctx.send(embed=H.error("Usage: `$spotifyplaylist <query>`"))
    items = await _search(query, "playlist", limit=5)
    items = [p for p in items if p]
    if not items:
        return await ctx.send(embed=H.error(f"No playlist found for **{query}**."))
    lines = [f"[{p['name']}]({p['external_urls']['spotify']}) — {p['tracks']['total']} tracks"
             for p in items[:5]]
    await ctx.send(embed=discord.Embed(title=f"Playlists — {query}",
                                       description="\n".join(lines), color=_GREEN))


@c("spotifycover", "spotifycover <query>", "Album cover art", ["spcover"])
async def spotifycover(ctx, *, query: str = None):
    if not all(_creds()):
        return await ctx.send(embed=_need_key())
    if not query:
        return await ctx.send(embed=H.error("Usage: `$spotifycover <query>`"))
    items = await _search(query, "track")
    if not items or not items[0]["album"].get("images"):
        return await ctx.send(embed=H.error("No cover found."))
    t = items[0]
    e = discord.Embed(title=f"{t['name']} — {t['album']['name']}",
                      url=t["external_urls"]["spotify"], color=_GREEN)
    e.set_image(url=t["album"]["images"][0]["url"])
    await ctx.send(embed=e)


@c("spotifypreview", "spotifypreview <query>", "30-second track preview link", ["sppreview"])
async def spotifypreview(ctx, *, query: str = None):
    if not all(_creds()):
        return await ctx.send(embed=_need_key())
    if not query:
        return await ctx.send(embed=H.error("Usage: `$spotifypreview <query>`"))
    items = await _search(query, "track")
    if not items:
        return await ctx.send(embed=H.error("No track found."))
    t = items[0]
    if not t.get("preview_url"):
        return await ctx.send(embed=H.error("No preview available for that track."))
    artists = ", ".join(a["name"] for a in t["artists"])
    await ctx.send(embed=H.info(f"**{t['name']}** — {artists}\n[▶ 30s preview]({t['preview_url']})"))


@c("spotifytop", "spotifytop <artist>", "An artist's top tracks", ["sptop"])
async def spotifytop(ctx, *, query: str = None):
    if not all(_creds()):
        return await ctx.send(embed=_need_key())
    if not query:
        return await ctx.send(embed=H.error("Usage: `$spotifytop <artist>`"))
    items = await _search(query, "artist")
    if not items:
        return await ctx.send(embed=H.error(f"No artist found for **{query}**."))
    a = items[0]
    data = await _get(f"/artists/{a['id']}/top-tracks", market="US")
    tracks = (data or {}).get("tracks", [])
    if not tracks:
        return await ctx.send(embed=H.error("No top tracks found."))
    lines = [f"`{n}.` [{t['name']}]({t['external_urls']['spotify']})" for n, t in enumerate(tracks[:10], 1)]
    e = discord.Embed(title=f"{a['name']} — top tracks", url=a["external_urls"]["spotify"],
                      description="\n".join(lines), color=_GREEN)
    if a.get("images"):
        e.set_thumbnail(url=a["images"][0]["url"])
    await ctx.send(embed=e)


@c("spotifyrelated", "spotifyrelated <artist>", "Related artists", ["sprelated"])
async def spotifyrelated(ctx, *, query: str = None):
    if not all(_creds()):
        return await ctx.send(embed=_need_key())
    if not query:
        return await ctx.send(embed=H.error("Usage: `$spotifyrelated <artist>`"))
    items = await _search(query, "artist")
    if not items:
        return await ctx.send(embed=H.error(f"No artist found for **{query}**."))
    a = items[0]
    data = await _get(f"/artists/{a['id']}/related-artists")
    rel = (data or {}).get("artists", [])
    if not rel:
        return await ctx.send(embed=H.error("No related artists found."))
    names = "\n".join(f"`{n}.` [{r['name']}]({r['external_urls']['spotify']})"
                      for n, r in enumerate(rel[:10], 1))
    await ctx.send(embed=discord.Embed(title=f"Related to {a['name']}", description=names, color=_GREEN))


@c("spotifygenres", "spotifygenres <artist>", "An artist's genres", ["spgenres"])
async def spotifygenres(ctx, *, query: str = None):
    if not all(_creds()):
        return await ctx.send(embed=_need_key())
    if not query:
        return await ctx.send(embed=H.error("Usage: `$spotifygenres <artist>`"))
    items = await _search(query, "artist")
    if not items:
        return await ctx.send(embed=H.error(f"No artist found for **{query}**."))
    a = items[0]
    if not a.get("genres"):
        return await ctx.send(embed=H.error(f"No genres listed for **{a['name']}**."))
    await ctx.send(embed=H.info(f"**{a['name']}** genres: {', '.join(a['genres'])}"))


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
        CATEGORIES["spotify"] = {"emoji": "🟢", "commands": added}
    return len(added)
