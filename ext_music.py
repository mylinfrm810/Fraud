"""Music / Voice commands (greed-equivalent "Voice"/"Music" category).

Voice playback using yt-dlp for source resolution and FFmpeg for streaming.
Per-guild queue with play/pause/resume/skip/stop/queue/nowplaying/volume/loop/
shuffle/remove/clear/join/leave.

NOTE: streaming reliability depends on the host network — YouTube frequently
rate-limits datacenter IPs, so playback may intermittently fail on cloud hosts.
"""
import asyncio
import logging
import random
import re
from collections import deque

import discord
from discord.ext import commands

H = None
CMDS = []
_log = logging.getLogger("fraud.music")

_SPOTIFY_RE = re.compile(r"open\.spotify\.com/(?:intl-[a-z]+/)?(track|album|playlist)/([A-Za-z0-9]+)")

try:
    import yt_dlp
    _YTDLP = True
except Exception:
    _YTDLP = False

_YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}
_FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

# guild_id -> {"queue": deque, "current": dict, "loop": bool, "volume": float}
_STATE = {}


def c(name, syntax, desc, aliases=None):
    def deco(fn):
        CMDS.append((name, aliases or [], syntax, desc, fn))
        return fn
    return deco


def _gs(guild_id):
    return _STATE.setdefault(guild_id, {"queue": deque(), "current": None,
                                        "loop": False, "volume": 0.5})


async def _resolve(query):
    """Resolve a search/URL to a playable stream via yt-dlp (off the loop)."""
    def _extract():
        with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
            info = ydl.extract_info(query, download=False)
            if "entries" in info:
                info = info["entries"][0]
            return {"url": info["url"], "title": info.get("title", "Unknown"),
                    "webpage": info.get("webpage_url"), "duration": info.get("duration")}
    return await asyncio.to_thread(_extract)


def _meta(html, prop):
    m = re.search(r'<meta property="%s" content="([^"]*)"' % re.escape(prop), html)
    if not m:
        return None
    return (m.group(1).replace("&amp;", "&").replace("&#x27;", "'")
            .replace("&quot;", '"').replace("&#39;", "'").replace("&gt;", ">")
            .replace("&lt;", "<"))


async def _spotify_tracks(url):
    """For a Spotify track URL, return a list with one pending track dict whose query
    is an 'artist title' YouTube search built from the public page's Open Graph tags.

    Returns None if the URL isn't a Spotify link, or a string error message for
    album/playlist links (multi-track scraping isn't reliable) or failed lookups.

    Note: we scrape the public page rather than the Web API because the API now
    rejects catalog reads unless the app owner has Spotify Premium."""
    m = _SPOTIFY_RE.search(url)
    if not m:
        return None
    kind, sid = m.group(1), m.group(2)
    if kind in ("album", "playlist"):
        return (f"I can't read a whole Spotify {kind} (Spotify hides the track list). "
                "Send a single Spotify **track** link, a song name, or a YouTube link.")
    import aiohttp
    page = f"https://open.spotify.com/track/{sid}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(page, headers={"User-Agent": "Mozilla/5.0"},
                             timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    return "Couldn't open that Spotify link (it may be private or region-locked)."
                html = await r.text()
    except Exception:
        return "Couldn't reach Spotify to read that track."
    title = _meta(html, "og:title")
    desc = _meta(html, "og:description") or ""
    if not title:
        return "Couldn't read that Spotify track."
    # og:description looks like "Artist · Album · Song · Year" — first part is the artist.
    artist = desc.split(" · ")[0].strip() if " · " in desc else ""
    query = f"{artist} {title}".strip()
    display = f"{artist} - {title}" if artist else title
    return [{"query": query, "title": display, "lock_title": True,
             "url": None, "webpage": None, "duration": None}]


def _after(ctx, error):
    """Called from the voice player thread when a track ends. Must NOT block the
    audio thread — schedule the next track on the bot loop and return immediately."""
    ctx.bot.loop.call_soon_threadsafe(
        lambda: ctx.bot.loop.create_task(_play_next(ctx))
    )


async def _play_next(ctx):
    """Advance the queue. Iterative (not recursive) so a run of unplayable tracks
    skips cleanly instead of growing the stack or looping forever in loop mode."""
    st = _gs(ctx.guild.id)
    vc = ctx.guild.voice_client
    if not vc:
        return
    while True:
        # Loop only re-plays a track that already resolved successfully.
        if st["loop"] and st["current"] and st["current"].get("url"):
            track = st["current"]
        elif st["queue"]:
            track = st["queue"].popleft()
        else:
            st["current"] = None
            return
        st["current"] = track
        # Resolve lazily so stream URLs are fresh and spotify/search queue entries
        # only hit yt-dlp when they're about to play.
        if not track.get("url"):
            try:
                info = await _resolve(track["query"])
            except Exception as exc:
                _log.exception("resolve failed for %r", track.get("query"))
                await ctx.send(embed=H.error(
                    f"Couldn't play **{track['title']}**: {type(exc).__name__}: {exc}"))
                st["current"] = None
                continue  # skip to the next queued track
            track["url"] = info["url"]
            track["webpage"] = info.get("webpage")
            track["duration"] = info.get("duration")
            if not track.get("lock_title"):
                track["title"] = info.get("title", track["title"])
        if not vc.is_connected():
            await ctx.send(embed=H.error("Lost the voice connection. Try `$join` then `$play` again."))
            st["current"] = None
            return
        try:
            src = discord.FFmpegPCMAudio(track["url"], **_FFMPEG_OPTS)
            src = discord.PCMVolumeTransformer(src, volume=st["volume"])
            vc.play(src, after=lambda e: _after(ctx, e))
            await ctx.send(embed=H.info(f"▶ Now playing: **{track['title']}**"))
            return
        except Exception as exc:
            _log.exception("playback failed for %r", track.get("title"))
            detail = f"{type(exc).__name__}: {exc}".strip().rstrip(":")
            await ctx.send(embed=H.error(f"Failed to play **{track['title']}**: {detail}"))
            st["current"] = None
            continue


async def _ensure_voice(ctx):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send(embed=H.error("Join a voice channel first."))
        return None
    ch = ctx.author.voice.channel
    vc = ctx.guild.voice_client
    if vc is None:
        try:
            return await ch.connect()
        except Exception as exc:
            await ctx.send(embed=H.error(f"Couldn't connect: {exc}"))
            return None
    if vc.channel != ch:
        await vc.move_to(ch)
    return vc


@c("join", "join", "Join your voice channel", ["connect"])
@commands.guild_only()
async def join(ctx):
    vc = await _ensure_voice(ctx)
    if vc:
        await ctx.send(embed=H.success(f"Joined **{vc.channel.name}**."))


@c("leave", "leave", "Leave the voice channel", ["disconnect", "dc"])
@commands.guild_only()
async def leave(ctx):
    vc = ctx.guild.voice_client
    if not vc:
        return await ctx.send(embed=H.error("I'm not in a voice channel."))
    _STATE.pop(ctx.guild.id, None)
    await vc.disconnect()
    await ctx.send(embed=H.success("Disconnected."))


@c("play", "play <song|url>", "Play or queue a song", ["p"])
@commands.guild_only()
async def play(ctx, *, query: str = None):
    if not _YTDLP:
        return await ctx.send(embed=H.error("Music isn't available — yt-dlp isn't installed."))
    if not query:
        return await ctx.send(embed=H.error("Usage: `$play <song name or url>`"))
    vc = await _ensure_voice(ctx)
    if not vc:
        return
    st = _gs(ctx.guild.id)
    async with ctx.typing():
        spotify = await _spotify_tracks(query)
        if isinstance(spotify, str):  # spotify URL but lookup failed
            return await ctx.send(embed=H.error(spotify))
        if spotify is not None:  # spotify track(s) resolved to search queries
            tracks = spotify
        else:  # plain song name or direct (YouTube/etc) URL — resolve lazily
            tracks = [{"query": query, "title": query, "lock_title": False,
                       "url": None, "webpage": None, "duration": None}]
    for t in tracks:
        st["queue"].append(t)
    if not vc.is_playing() and not vc.is_paused():
        await _play_next(ctx)
        if len(tracks) > 1:
            await ctx.send(embed=H.success(f"Added **{len(tracks)}** tracks to the queue."))
    else:
        if len(tracks) > 1:
            await ctx.send(embed=H.success(f"Queued **{len(tracks)}** tracks."))
        else:
            await ctx.send(embed=H.success(
                f"Queued **{tracks[0]['title']}** (position {len(st['queue'])})."))


@c("pause", "pause", "Pause playback")
@commands.guild_only()
async def pause(ctx):
    vc = ctx.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        return await ctx.send(embed=H.success("Paused."))
    await ctx.send(embed=H.error("Nothing is playing."))


@c("resume", "resume", "Resume playback", ["unpause"])
@commands.guild_only()
async def resume(ctx):
    vc = ctx.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        return await ctx.send(embed=H.success("Resumed."))
    await ctx.send(embed=H.error("Nothing is paused."))


@c("skip", "skip", "Skip the current song", ["s", "next"])
@commands.guild_only()
async def skip(ctx):
    vc = ctx.guild.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()  # triggers _after -> _play_next
        return await ctx.send(embed=H.success("Skipped."))
    await ctx.send(embed=H.error("Nothing is playing."))


@c("stop", "stop", "Stop and clear the queue")
@commands.guild_only()
async def stop(ctx):
    vc = ctx.guild.voice_client
    if not vc:
        return await ctx.send(embed=H.error("I'm not in a voice channel."))
    st = _gs(ctx.guild.id)
    st["queue"].clear()
    st["current"] = None
    st["loop"] = False
    if vc.is_playing() or vc.is_paused():
        vc.stop()
    await ctx.send(embed=H.success("Stopped and cleared the queue."))


@c("queue", "queue", "Show the song queue", ["q"])
@commands.guild_only()
async def queue(ctx):
    st = _gs(ctx.guild.id)
    if not st["current"] and not st["queue"]:
        return await ctx.send(embed=H.error("The queue is empty."))
    lines = []
    if st["current"]:
        lines.append(f"**Now:** {st['current']['title']}")
    for n, t in enumerate(list(st["queue"])[:15], 1):
        lines.append(f"`{n}.` {t['title']}")
    if len(st["queue"]) > 15:
        lines.append(f"…and {len(st['queue']) - 15} more")
    await ctx.send(embed=discord.Embed(title="Queue", description="\n".join(lines)[:4096], color=0x5865F2))


@c("nowplaying", "nowplaying", "Show the current song", ["np2", "playing"])
@commands.guild_only()
async def nowplaying(ctx):
    st = _gs(ctx.guild.id)
    if not st["current"]:
        return await ctx.send(embed=H.error("Nothing is playing."))
    t = st["current"]
    e = discord.Embed(title="Now playing", description=f"**{t['title']}**",
                      url=t.get("webpage"), color=0x5865F2)
    if t.get("duration"):
        e.add_field(name="Duration", value=f"{t['duration'] // 60}:{t['duration'] % 60:02d}")
    e.add_field(name="Loop", value="on" if st["loop"] else "off")
    await ctx.send(embed=e)


@c("volume", "volume <0-100>", "Set playback volume", ["vol"])
@commands.guild_only()
async def volume(ctx, level: int = None):
    vc = ctx.guild.voice_client
    if not vc:
        return await ctx.send(embed=H.error("I'm not in a voice channel."))
    st = _gs(ctx.guild.id)
    if level is None:
        return await ctx.send(embed=H.info(f"Volume is **{int(st['volume'] * 100)}%**."))
    level = max(0, min(100, level))
    st["volume"] = level / 100
    if vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
        vc.source.volume = st["volume"]
    await ctx.send(embed=H.success(f"Volume set to **{level}%**."))


@c("loop", "loop", "Toggle looping the current song", ["repeat"])
@commands.guild_only()
async def loop(ctx):
    st = _gs(ctx.guild.id)
    st["loop"] = not st["loop"]
    await ctx.send(embed=H.success(f"Loop **{'enabled' if st['loop'] else 'disabled'}**."))


@c("shuffle", "shuffle", "Shuffle the queue")
@commands.guild_only()
async def shuffle(ctx):
    st = _gs(ctx.guild.id)
    if len(st["queue"]) < 2:
        return await ctx.send(embed=H.error("Not enough songs to shuffle."))
    items = list(st["queue"])
    random.shuffle(items)
    st["queue"] = deque(items)
    await ctx.send(embed=H.success("Queue shuffled."))


@c("remove", "remove <position>", "Remove a song from the queue")
@commands.guild_only()
async def remove(ctx, position: int = None):
    st = _gs(ctx.guild.id)
    if position is None or position < 1 or position > len(st["queue"]):
        return await ctx.send(embed=H.error(f"Pick a position between 1 and {len(st['queue'])}."))
    items = list(st["queue"])
    removed = items.pop(position - 1)
    st["queue"] = deque(items)
    await ctx.send(embed=H.success(f"Removed **{removed['title']}**."))


@c("clearqueue", "clearqueue", "Clear the queue (keep playing)", ["cq"])
@commands.guild_only()
async def clearqueue(ctx):
    st = _gs(ctx.guild.id)
    st["queue"].clear()
    await ctx.send(embed=H.success("Queue cleared."))


def _ensure_opus():
    """discord.py needs libopus to encode voice audio. On NixOS the library isn't
    on the default loader path, so auto-load fails — load it explicitly by soname."""
    if discord.opus.is_loaded():
        return True
    for name in ("libopus.so.0", "libopus.so", "opus"):
        try:
            discord.opus.load_opus(name)
            if discord.opus.is_loaded():
                _log.info("loaded libopus via %s", name)
                return True
        except Exception:
            continue
    _log.warning("libopus could not be loaded — voice playback will fail")
    return False


def register(bot, CATEGORIES, helpers):
    global H
    H = helpers
    _ensure_opus()
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
        CATEGORIES["music"] = {"emoji": "🎵", "commands": added}
    return len(added)
