"""Server management commands (greed-equivalent "Server" category).

Real, working discord.py guild-management commands: roles, channels, threads,
emojis, stickers, server settings, invites, webhooks and more. Registered via a
collector list so bot registration and the CATEGORIES/website source stay in sync.

Permission and hierarchy checks use discord.py's own check decorators and a few
helpers; Forbidden/HTTP failures are reported by the bot's global error handler.
"""
import asyncio
import io
import ipaddress
import socket
from urllib.parse import urlparse

import aiohttp
import discord
from discord.ext import commands

# Set by register(); namespace exposing .error/.success/.info embed builders.
H = None
CMDS = []  # (name, aliases, syntax, desc, callback)

_MAX_FETCH_BYTES = 8 * 1024 * 1024  # 8 MiB cap on fetched media


def c(name, syntax, desc, aliases=None):
    def deco(fn):
        CMDS.append((name, aliases or [], syntax, desc, fn))
        return fn
    return deco


def _hex(s):
    return int(s.strip().lstrip("#"), 16)


def _url_is_safe(url):
    """Block non-http(s) schemes and any URL resolving to a private/internal IP
    (SSRF guard). All resolved addresses must be public."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return False
    return True


async def _read_url(url):
    if not _url_is_safe(url):
        return None
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    return None
                cl = r.headers.get("Content-Length")
                if cl and cl.isdigit() and int(cl) > _MAX_FETCH_BYTES:
                    return None
                data = await r.content.read(_MAX_FETCH_BYTES + 1)
                if len(data) > _MAX_FETCH_BYTES:
                    return None
                return data
    except Exception:
        return None


async def _role_ok(ctx, role):
    if role >= ctx.guild.me.top_role:
        await ctx.send(embed=H.error(f"I can't manage {role.mention} — it sits above my highest role."))
        return False
    if ctx.author != ctx.guild.owner and role >= ctx.author.top_role:
        await ctx.send(embed=H.error(f"You can't manage {role.mention} — it sits above your highest role."))
        return False
    if role.managed:
        await ctx.send(embed=H.error(f"{role.mention} is managed by an integration and can't be edited."))
        return False
    return True


async def _img_data(ctx, url):
    if ctx.message.attachments:
        return await ctx.message.attachments[0].read()
    if url:
        return await _read_url(url)
    return None


# ════════════════════════════ ROLES ════════════════════════════
@c("role", "role <user> <role>", "Toggle a role on a member", ["r"])
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, member: discord.Member, *, role: discord.Role):
    if not await _role_ok(ctx, role):
        return
    if role in member.roles:
        await member.remove_roles(role)
        await ctx.send(embed=H.success(f"Removed {role.mention} from **{member}**."))
    else:
        await member.add_roles(role)
        await ctx.send(embed=H.success(f"Added {role.mention} to **{member}**."))


@c("rolecreate", "rolecreate <name>", "Create a new role", ["createrole", "addrole"])
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, *, name):
    role = await ctx.guild.create_role(name=name[:100], reason=f"By {ctx.author}")
    await ctx.send(embed=H.success(f"Created role {role.mention}."))


@c("roledelete", "roledelete <role>", "Delete a role", ["delrole", "deleterole"])
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, *, role: discord.Role):
    if not await _role_ok(ctx, role):
        return
    name = role.name
    await role.delete(reason=f"By {ctx.author}")
    await ctx.send(embed=H.success(f"Deleted role **{name}**."))


@c("rolerename", "rolerename <role> <name>", "Rename a role")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, role: discord.Role, *, name):
    if not await _role_ok(ctx, role):
        return
    old = role.name
    await role.edit(name=name[:100])
    await ctx.send(embed=H.success(f"Renamed **{old}** to **{name}**."))


@c("rolecolor", "rolecolor <role> <hex>", "Change a role's color", ["rolecolour"])
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, role: discord.Role, color):
    if not await _role_ok(ctx, role):
        return
    try:
        col = discord.Color(_hex(color))
    except ValueError:
        return await ctx.send(embed=H.error("Give a valid hex color, e.g. `#ff0000`."))
    await role.edit(color=col)
    await ctx.send(embed=H.success(f"Set {role.mention}'s color to `#{col.value:06x}`."))


@c("rolehoist", "rolehoist <role>", "Toggle whether a role is displayed separately")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, *, role: discord.Role):
    if not await _role_ok(ctx, role):
        return
    await role.edit(hoist=not role.hoist)
    await ctx.send(embed=H.success(f"{role.mention} is now {'hoisted' if not role.hoist else 'unhoisted'}."))


@c("rolemention", "rolemention <role>", "Toggle whether a role is mentionable")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, *, role: discord.Role):
    if not await _role_ok(ctx, role):
        return
    await role.edit(mentionable=not role.mentionable)
    await ctx.send(embed=H.success(f"{role.mention} is now {'mentionable' if not role.mentionable else 'unmentionable'}."))


@c("roleadd", "roleadd <user> <role>", "Add a role to a member")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, member: discord.Member, *, role: discord.Role):
    if not await _role_ok(ctx, role):
        return
    await member.add_roles(role)
    await ctx.send(embed=H.success(f"Added {role.mention} to **{member}**."))


@c("roleremove", "roleremove <user> <role>", "Remove a role from a member")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, member: discord.Member, *, role: discord.Role):
    if not await _role_ok(ctx, role):
        return
    await member.remove_roles(role)
    await ctx.send(embed=H.success(f"Removed {role.mention} from **{member}**."))


@c("roleall", "roleall <role>", "Add a role to every member", ["roleeveryone"])
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, *, role: discord.Role):
    if not await _role_ok(ctx, role):
        return
    m = await ctx.send(embed=H.info(f"Adding {role.mention} to everyone…"))
    n = 0
    for member in ctx.guild.members:
        if role not in member.roles:
            try:
                await member.add_roles(role)
                n += 1
            except Exception:
                pass
    await m.edit(embed=H.success(f"Added {role.mention} to **{n}** members."))


@c("rolehumans", "rolehumans <role>", "Add a role to all non-bot members")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, *, role: discord.Role):
    if not await _role_ok(ctx, role):
        return
    n = 0
    for member in ctx.guild.members:
        if not member.bot and role not in member.roles:
            try:
                await member.add_roles(role)
                n += 1
            except Exception:
                pass
    await ctx.send(embed=H.success(f"Added {role.mention} to **{n}** humans."))


@c("rolebots", "rolebots <role>", "Add a role to all bots")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, *, role: discord.Role):
    if not await _role_ok(ctx, role):
        return
    n = 0
    for member in ctx.guild.members:
        if member.bot and role not in member.roles:
            try:
                await member.add_roles(role)
                n += 1
            except Exception:
                pass
    await ctx.send(embed=H.success(f"Added {role.mention} to **{n}** bots."))


@c("roleremoveall", "roleremoveall <role>", "Remove a role from every member")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, *, role: discord.Role):
    if not await _role_ok(ctx, role):
        return
    members = list(role.members)
    for member in members:
        try:
            await member.remove_roles(role)
        except Exception:
            pass
    await ctx.send(embed=H.success(f"Removed {role.mention} from **{len(members)}** members."))


@c("rolepos", "rolepos <role> <position>", "Move a role to a position", ["roleposition"])
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, role: discord.Role, position: int):
    if not await _role_ok(ctx, role):
        return
    await role.edit(position=max(1, position))
    await ctx.send(embed=H.success(f"Moved {role.mention} to position **{role.position}**."))


@c("roleicon", "roleicon <role> <emoji>", "Set a role's icon to an emoji (boost perk)")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, role: discord.Role, emoji):
    if not await _role_ok(ctx, role):
        return
    if "ROLE_ICONS" not in ctx.guild.features:
        return await ctx.send(embed=H.error("This server needs more boosts for role icons."))
    await role.edit(unicode_emoji=emoji)
    await ctx.send(embed=H.success(f"Set {role.mention}'s icon."))


@c("derank", "derank <user>", "Remove all manageable roles from a member", ["striproles"])
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, *, member: discord.Member):
    removable = [r for r in member.roles[1:] if r < ctx.guild.me.top_role and not r.managed]
    if not removable:
        return await ctx.send(embed=H.error("No removable roles on that member."))
    await member.remove_roles(*removable)
    await ctx.send(embed=H.success(f"Removed **{len(removable)}** roles from **{member}**."))


@c("temprole", "temprole <user> <role> <minutes>", "Give a role for a set number of minutes")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx, member: discord.Member, role: discord.Role, minutes: int):
    if not await _role_ok(ctx, role):
        return
    minutes = max(1, min(minutes, 10080))
    await member.add_roles(role)
    await ctx.send(embed=H.success(f"Gave {role.mention} to **{member}** for **{minutes}m**."))

    async def _expire():
        await asyncio.sleep(minutes * 60)
        try:
            await member.remove_roles(role)
        except Exception:
            pass
    asyncio.create_task(_expire())


@c("inrole", "inrole <role>", "List members who have a role", ["rolemembers"])
@commands.guild_only()
async def _f(ctx, *, role: discord.Role):
    members = role.members
    if not members:
        return await ctx.send(embed=H.info(f"No members have {role.mention}."))
    names = ", ".join(m.name for m in members[:50])
    extra = f"\n…and {len(members) - 50} more" if len(members) > 50 else ""
    e = H.info(f"**{len(members)}** members have {role.mention}:\n{names}{extra}")
    await ctx.send(embed=e)


@c("rolecount", "rolecount", "Show how many roles the server has")
@commands.guild_only()
async def _f(ctx):
    await ctx.send(embed=H.info(f"This server has **{len(ctx.guild.roles) - 1}** roles."))


@c("roleinfo2", "roleinfo2 <role>", "Show detailed info about a role", ["ri"])
@commands.guild_only()
async def _f(ctx, *, role: discord.Role):
    e = discord.Embed(title=role.name, color=role.color)
    e.add_field(name="ID", value=role.id)
    e.add_field(name="Members", value=len(role.members))
    e.add_field(name="Color", value=f"#{role.color.value:06x}")
    e.add_field(name="Position", value=role.position)
    e.add_field(name="Hoisted", value=role.hoist)
    e.add_field(name="Mentionable", value=role.mentionable)
    await ctx.send(embed=e)


@c("rolecleanup", "rolecleanup", "Delete all empty roles with no permissions")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def _f(ctx):
    deleted = 0
    for role in list(ctx.guild.roles):
        if role.is_default() or role.managed:
            continue
        if not role.members and role.permissions.value == 0 and role < ctx.guild.me.top_role:
            try:
                await role.delete(reason="rolecleanup")
                deleted += 1
            except Exception:
                pass
    await ctx.send(embed=H.success(f"Deleted **{deleted}** empty roles."))


# ════════════════════════════ CHANNELS ════════════════════════════
@c("channelcreate", "channelcreate <name>", "Create a text channel", ["textcreate", "createchannel"])
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, *, name):
    ch = await ctx.guild.create_text_channel(name[:100])
    await ctx.send(embed=H.success(f"Created {ch.mention}."))


@c("voicecreate", "voicecreate <name>", "Create a voice channel", ["vccreate"])
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, *, name):
    ch = await ctx.guild.create_voice_channel(name[:100])
    await ctx.send(embed=H.success(f"Created voice channel **{ch.name}**."))


@c("categorycreate", "categorycreate <name>", "Create a category", ["catcreate"])
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, *, name):
    ch = await ctx.guild.create_category(name[:100])
    await ctx.send(embed=H.success(f"Created category **{ch.name}**."))


@c("stagecreate", "stagecreate <name>", "Create a stage channel")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, *, name):
    ch = await ctx.guild.create_stage_channel(name[:100])
    await ctx.send(embed=H.success(f"Created stage channel **{ch.name}**."))


@c("channeldelete", "channeldelete [channel]", "Delete a channel", ["delchannel"])
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.abc.GuildChannel = None):
    channel = channel or ctx.channel
    name = channel.name
    await channel.delete(reason=f"By {ctx.author}")
    if channel != ctx.channel:
        await ctx.send(embed=H.success(f"Deleted **#{name}**."))


@c("channelrename", "channelrename <channel> <name>", "Rename a channel")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.abc.GuildChannel, *, name):
    old = channel.name
    await channel.edit(name=name[:100])
    await ctx.send(embed=H.success(f"Renamed **{old}** to **{name}**."))


@c("channeltopic", "channeltopic <channel> <topic>", "Set a channel's topic", ["settopic"])
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.TextChannel, *, topic):
    await channel.edit(topic=topic[:1024])
    await ctx.send(embed=H.success(f"Updated the topic of {channel.mention}."))


@c("slowmode", "slowmode <seconds> [channel]", "Set a channel's slowmode", ["sm"])
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, seconds: int, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    seconds = max(0, min(seconds, 21600))
    await channel.edit(slowmode_delay=seconds)
    await ctx.send(embed=H.success(f"Set slowmode in {channel.mention} to **{seconds}s**."))


@c("nsfw", "nsfw [channel]", "Toggle a channel's NSFW flag")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.edit(nsfw=not channel.is_nsfw())
    await ctx.send(embed=H.success(f"{channel.mention} NSFW is now **{not channel.is_nsfw()}**."))


@c("lock", "lock [channel]", "Lock a channel (deny send messages)")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    ow = channel.overwrites_for(ctx.guild.default_role)
    ow.send_messages = False
    await channel.set_permissions(ctx.guild.default_role, overwrite=ow)
    await ctx.send(embed=H.success(f"🔒 Locked {channel.mention}."))


@c("unlock", "unlock [channel]", "Unlock a channel")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    ow = channel.overwrites_for(ctx.guild.default_role)
    ow.send_messages = None
    await channel.set_permissions(ctx.guild.default_role, overwrite=ow)
    await ctx.send(embed=H.success(f"🔓 Unlocked {channel.mention}."))


@c("lockall", "lockall", "Lock every text channel")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx):
    n = 0
    for channel in ctx.guild.text_channels:
        ow = channel.overwrites_for(ctx.guild.default_role)
        ow.send_messages = False
        try:
            await channel.set_permissions(ctx.guild.default_role, overwrite=ow)
            n += 1
        except Exception:
            pass
    await ctx.send(embed=H.success(f"🔒 Locked **{n}** channels."))


@c("unlockall", "unlockall", "Unlock every text channel")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx):
    n = 0
    for channel in ctx.guild.text_channels:
        ow = channel.overwrites_for(ctx.guild.default_role)
        ow.send_messages = None
        try:
            await channel.set_permissions(ctx.guild.default_role, overwrite=ow)
            n += 1
        except Exception:
            pass
    await ctx.send(embed=H.success(f"🔓 Unlocked **{n}** channels."))


@c("hide", "hide [channel]", "Hide a channel from @everyone")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.abc.GuildChannel = None):
    channel = channel or ctx.channel
    ow = channel.overwrites_for(ctx.guild.default_role)
    ow.view_channel = False
    await channel.set_permissions(ctx.guild.default_role, overwrite=ow)
    await ctx.send(embed=H.success(f"Hid **{channel.name}**."))


@c("unhide", "unhide [channel]", "Reveal a hidden channel")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.abc.GuildChannel = None):
    channel = channel or ctx.channel
    ow = channel.overwrites_for(ctx.guild.default_role)
    ow.view_channel = None
    await channel.set_permissions(ctx.guild.default_role, overwrite=ow)
    await ctx.send(embed=H.success(f"Revealed **{channel.name}**."))


@c("clone", "clone [channel]", "Clone a channel", ["copychannel"])
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    new = await channel.clone(reason=f"By {ctx.author}")
    await ctx.send(embed=H.success(f"Cloned into {new.mention}."))


@c("nuke", "nuke [channel]", "Clone and delete a channel to wipe it", ["nukechannel"])
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    pos = channel.position
    new = await channel.clone(reason=f"Nuked by {ctx.author}")
    await channel.delete()
    await new.edit(position=pos)
    await new.send(embed=H.success(f"💥 Channel nuked by {ctx.author.mention}."))


@c("channelpos", "channelpos <channel> <position>", "Move a channel to a position")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.abc.GuildChannel, position: int):
    await channel.edit(position=max(0, position))
    await ctx.send(embed=H.success(f"Moved **{channel.name}** to position **{channel.position}**."))


@c("movechannel", "movechannel <channel> <category>", "Move a channel into a category")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.abc.GuildChannel, *, category: discord.CategoryChannel):
    await channel.edit(category=category)
    await ctx.send(embed=H.success(f"Moved **{channel.name}** into **{category.name}**."))


@c("syncperms", "syncperms <channel>", "Sync a channel's permissions with its category")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.abc.GuildChannel):
    if not channel.category:
        return await ctx.send(embed=H.error("That channel isn't in a category."))
    await channel.edit(sync_permissions=True)
    await ctx.send(embed=H.success(f"Synced **{channel.name}** with **{channel.category.name}**."))


@c("setbitrate", "setbitrate <voice> <kbps>", "Set a voice channel's bitrate")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.VoiceChannel, kbps: int):
    await channel.edit(bitrate=max(8, min(kbps, 384)) * 1000)
    await ctx.send(embed=H.success(f"Set **{channel.name}** bitrate to **{kbps}kbps**."))


@c("setuserlimit", "setuserlimit <voice> <limit>", "Set a voice channel's user limit")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def _f(ctx, channel: discord.VoiceChannel, limit: int):
    await channel.edit(user_limit=max(0, min(limit, 99)))
    await ctx.send(embed=H.success(f"Set **{channel.name}** user limit to **{limit}**."))


@c("channelcount", "channelcount", "Show channel counts", ["channels2"])
@commands.guild_only()
async def _f(ctx):
    g = ctx.guild
    await ctx.send(embed=H.info(
        f"**Channels**\nText: {len(g.text_channels)}\nVoice: {len(g.voice_channels)}\n"
        f"Categories: {len(g.categories)}\nTotal: {len(g.channels)}"))


# ════════════════════════════ THREADS ════════════════════════════
@c("threadcreate", "threadcreate <name>", "Create a thread in this channel")
@commands.guild_only()
@commands.has_permissions(create_public_threads=True)
async def _f(ctx, *, name):
    th = await ctx.channel.create_thread(name=name[:100], type=discord.ChannelType.public_thread)
    await ctx.send(embed=H.success(f"Created thread {th.mention}."))


@c("threaddelete", "threaddelete", "Delete the current thread")
@commands.guild_only()
@commands.has_permissions(manage_threads=True)
async def _f(ctx):
    if not isinstance(ctx.channel, discord.Thread):
        return await ctx.send(embed=H.error("This isn't a thread."))
    await ctx.channel.delete()


@c("threadarchive", "threadarchive", "Archive the current thread")
@commands.guild_only()
@commands.has_permissions(manage_threads=True)
async def _f(ctx):
    if not isinstance(ctx.channel, discord.Thread):
        return await ctx.send(embed=H.error("This isn't a thread."))
    await ctx.channel.edit(archived=True)
    await ctx.send(embed=H.success("Thread archived."))


@c("threadlock", "threadlock", "Lock the current thread")
@commands.guild_only()
@commands.has_permissions(manage_threads=True)
async def _f(ctx):
    if not isinstance(ctx.channel, discord.Thread):
        return await ctx.send(embed=H.error("This isn't a thread."))
    await ctx.channel.edit(locked=True)
    await ctx.send(embed=H.success("🔒 Thread locked."))


@c("threadunlock", "threadunlock", "Unlock the current thread")
@commands.guild_only()
@commands.has_permissions(manage_threads=True)
async def _f(ctx):
    if not isinstance(ctx.channel, discord.Thread):
        return await ctx.send(embed=H.error("This isn't a thread."))
    await ctx.channel.edit(locked=False)
    await ctx.send(embed=H.success("🔓 Thread unlocked."))


@c("threadrename", "threadrename <name>", "Rename the current thread")
@commands.guild_only()
@commands.has_permissions(manage_threads=True)
async def _f(ctx, *, name):
    if not isinstance(ctx.channel, discord.Thread):
        return await ctx.send(embed=H.error("This isn't a thread."))
    await ctx.channel.edit(name=name[:100])
    await ctx.send(embed=H.success(f"Renamed thread to **{name}**."))


# ════════════════════════════ EMOJIS ════════════════════════════
@c("emojicreate", "emojicreate <name> [url]", "Add an emoji from a URL or attachment", ["addemoji", "emojiadd"])
@commands.guild_only()
@commands.has_permissions(manage_emojis=True)
async def _f(ctx, name, url=None):
    data = await _img_data(ctx, url)
    if not data:
        return await ctx.send(embed=H.error("Attach an image or give a URL."))
    e = await ctx.guild.create_custom_emoji(name=name[:32], image=data)
    await ctx.send(embed=H.success(f"Added emoji {e} `:{e.name}:`."))


@c("emojidelete", "emojidelete <emoji>", "Delete a custom emoji", ["delemoji", "emojiremove"])
@commands.guild_only()
@commands.has_permissions(manage_emojis=True)
async def _f(ctx, emoji: discord.Emoji):
    name = emoji.name
    await emoji.delete()
    await ctx.send(embed=H.success(f"Deleted emoji `:{name}:`."))


@c("emojirename", "emojirename <emoji> <name>", "Rename a custom emoji")
@commands.guild_only()
@commands.has_permissions(manage_emojis=True)
async def _f(ctx, emoji: discord.Emoji, *, name):
    old = emoji.name
    await emoji.edit(name=name[:32])
    await ctx.send(embed=H.success(f"Renamed `:{old}:` to `:{name}:`."))


@c("steal", "steal <emoji> [name]", "Steal a custom emoji into this server", ["emojisteal", "addemojifrom"])
@commands.guild_only()
@commands.has_permissions(manage_emojis=True)
async def _f(ctx, emoji: discord.PartialEmoji, name=None):
    data = await _read_url(emoji.url)
    if not data:
        return await ctx.send(embed=H.error("Couldn't download that emoji."))
    e = await ctx.guild.create_custom_emoji(name=(name or emoji.name)[:32], image=data)
    await ctx.send(embed=H.success(f"Stolen emoji {e} `:{e.name}:`."))


@c("emojicount", "emojicount", "Show the server's emoji count")
@commands.guild_only()
async def _f(ctx):
    anim = sum(1 for e in ctx.guild.emojis if e.animated)
    static = len(ctx.guild.emojis) - anim
    await ctx.send(embed=H.info(f"**Emojis:** {len(ctx.guild.emojis)}/{ctx.guild.emoji_limit*2}\nStatic: {static} · Animated: {anim}"))


@c("emojilist", "emojilist", "List the server's custom emojis", ["listemojis"])
@commands.guild_only()
async def _f(ctx):
    if not ctx.guild.emojis:
        return await ctx.send(embed=H.info("This server has no custom emojis."))
    text = " ".join(str(e) for e in ctx.guild.emojis[:80])
    await ctx.send(embed=H.info(text[:4000]))


# ════════════════════════════ STICKERS ════════════════════════════
@c("stickeradd", "stickeradd <name> [url]", "Add a sticker from a URL or attachment", ["addsticker"])
@commands.guild_only()
@commands.has_permissions(manage_emojis_and_stickers=True)
async def _f(ctx, name, url=None):
    data = await _img_data(ctx, url)
    if not data:
        return await ctx.send(embed=H.error("Attach a PNG/APNG or give a URL."))
    file = discord.File(io.BytesIO(data), filename="sticker.png")
    s = await ctx.guild.create_sticker(name=name[:30], description=name[:100], emoji="⭐", file=file)
    await ctx.send(embed=H.success(f"Added sticker **{s.name}**."))


@c("stickerdelete", "stickerdelete <name>", "Delete a sticker by name", ["delsticker"])
@commands.guild_only()
@commands.has_permissions(manage_emojis_and_stickers=True)
async def _f(ctx, *, name):
    s = discord.utils.get(ctx.guild.stickers, name=name)
    if not s:
        return await ctx.send(embed=H.error("No sticker with that name."))
    await s.delete()
    await ctx.send(embed=H.success(f"Deleted sticker **{name}**."))


@c("stickerrename", "stickerrename <old> <new>", "Rename a sticker")
@commands.guild_only()
@commands.has_permissions(manage_emojis_and_stickers=True)
async def _f(ctx, old, *, new):
    s = discord.utils.get(ctx.guild.stickers, name=old)
    if not s:
        return await ctx.send(embed=H.error("No sticker with that name."))
    await s.edit(name=new[:30])
    await ctx.send(embed=H.success(f"Renamed sticker to **{new}**."))


@c("stickerlist", "stickerlist", "List the server's stickers")
@commands.guild_only()
async def _f(ctx):
    if not ctx.guild.stickers:
        return await ctx.send(embed=H.info("This server has no stickers."))
    names = ", ".join(s.name for s in ctx.guild.stickers)
    await ctx.send(embed=H.info(f"**{len(ctx.guild.stickers)} stickers:** {names}"[:4000]))


@c("stickercount", "stickercount", "Show the server's sticker count")
@commands.guild_only()
async def _f(ctx):
    await ctx.send(embed=H.info(f"This server has **{len(ctx.guild.stickers)}/{ctx.guild.sticker_limit}** stickers."))


# ════════════════════════════ SERVER SETTINGS ════════════════════════════
@c("setname", "setname <name>", "Change the server's name", ["servername", "setservername"])
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx, *, name):
    await ctx.guild.edit(name=name[:100])
    await ctx.send(embed=H.success(f"Renamed the server to **{name}**."))


@c("seticon", "seticon [url]", "Change the server's icon", ["setservericon"])
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx, url=None):
    data = await _img_data(ctx, url)
    if not data:
        return await ctx.send(embed=H.error("Attach an image or give a URL."))
    await ctx.guild.edit(icon=data)
    await ctx.send(embed=H.success("Updated the server icon."))


@c("setbanner", "setbanner [url]", "Change the server's banner (boost perk)")
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx, url=None):
    if "BANNER" not in ctx.guild.features:
        return await ctx.send(embed=H.error("This server needs more boosts for a banner."))
    data = await _img_data(ctx, url)
    if not data:
        return await ctx.send(embed=H.error("Attach an image or give a URL."))
    await ctx.guild.edit(banner=data)
    await ctx.send(embed=H.success("Updated the server banner."))


@c("setsplash", "setsplash [url]", "Change the invite splash (boost perk)")
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx, url=None):
    if "INVITE_SPLASH" not in ctx.guild.features:
        return await ctx.send(embed=H.error("This server needs more boosts for an invite splash."))
    data = await _img_data(ctx, url)
    if not data:
        return await ctx.send(embed=H.error("Attach an image or give a URL."))
    await ctx.guild.edit(splash=data)
    await ctx.send(embed=H.success("Updated the invite splash."))


@c("setdescription", "setdescription <text>", "Set the server description", ["setdesc"])
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx, *, text):
    await ctx.guild.edit(description=text[:300])
    await ctx.send(embed=H.success("Updated the server description."))


@c("setafkchannel", "setafkchannel <voice>", "Set the AFK voice channel")
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx, *, channel: discord.VoiceChannel):
    await ctx.guild.edit(afk_channel=channel)
    await ctx.send(embed=H.success(f"AFK channel set to **{channel.name}**."))


@c("setafktimeout", "setafktimeout <seconds>", "Set the AFK timeout (60/300/900/1800/3600)")
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx, seconds: int):
    if seconds not in (60, 300, 900, 1800, 3600):
        return await ctx.send(embed=H.error("Timeout must be 60, 300, 900, 1800 or 3600."))
    await ctx.guild.edit(afk_timeout=seconds)
    await ctx.send(embed=H.success(f"AFK timeout set to **{seconds}s**."))


@c("setsystemchannel", "setsystemchannel <channel>", "Set the system message channel")
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx, *, channel: discord.TextChannel):
    await ctx.guild.edit(system_channel=channel)
    await ctx.send(embed=H.success(f"System channel set to {channel.mention}."))


@c("setverification", "setverification <none|low|medium|high|highest>", "Set the verification level")
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx, level):
    levels = {
        "none": discord.VerificationLevel.none,
        "low": discord.VerificationLevel.low,
        "medium": discord.VerificationLevel.medium,
        "high": discord.VerificationLevel.high,
        "highest": discord.VerificationLevel.highest,
    }
    if level.lower() not in levels:
        return await ctx.send(embed=H.error("Choose: none, low, medium, high, highest."))
    await ctx.guild.edit(verification_level=levels[level.lower()])
    await ctx.send(embed=H.success(f"Verification level set to **{level.lower()}**."))


@c("setnotifications", "setnotifications <all|mentions>", "Set default notification level")
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx, level):
    m = {"all": discord.NotificationLevel.all_messages, "mentions": discord.NotificationLevel.only_mentions}
    if level.lower() not in m:
        return await ctx.send(embed=H.error("Choose: all or mentions."))
    await ctx.guild.edit(default_notifications=m[level.lower()])
    await ctx.send(embed=H.success(f"Default notifications set to **{level.lower()}**."))


@c("seticonremove", "seticonremove", "Remove the server icon", ["removeicon"])
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx):
    await ctx.guild.edit(icon=None)
    await ctx.send(embed=H.success("Removed the server icon."))


@c("setboostbar", "setboostbar", "Toggle the boost progress bar")
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx):
    new = not ctx.guild.premium_progress_bar_enabled
    await ctx.guild.edit(premium_progress_bar_enabled=new)
    await ctx.send(embed=H.success(f"Boost progress bar **{'enabled' if new else 'disabled'}**."))


# ════════════════════════════ INVITES & WEBHOOKS ════════════════════════════
@c("invites", "invites", "List active invites", ["invitelist"])
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx):
    invs = await ctx.guild.invites()
    if not invs:
        return await ctx.send(embed=H.info("No active invites."))
    lines = [f"`{i.code}` — {i.uses} uses by {i.inviter}" for i in invs[:20]]
    await ctx.send(embed=H.info("\n".join(lines)[:4000]))


@c("createinvite", "createinvite [channel]", "Create an invite link", ["makeinvite", "geninvite"])
@commands.guild_only()
@commands.has_permissions(create_instant_invite=True)
async def _f(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    inv = await channel.create_invite(max_age=0, reason=f"By {ctx.author}")
    await ctx.send(embed=H.success(f"Invite: {inv.url}"))


@c("deleteinvite", "deleteinvite <code>", "Delete an invite by code", ["delinvite", "revokeinvite"])
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx, code):
    for inv in await ctx.guild.invites():
        if inv.code == code:
            await inv.delete()
            return await ctx.send(embed=H.success(f"Deleted invite `{code}`."))
    await ctx.send(embed=H.error("No invite with that code."))


@c("invitecount", "invitecount", "Show how many active invites exist")
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def _f(ctx):
    invs = await ctx.guild.invites()
    await ctx.send(embed=H.info(f"There are **{len(invs)}** active invites."))


@c("vanity", "vanity", "Show the server's vanity invite", ["vanityurl"])
@commands.guild_only()
async def _f(ctx):
    if "VANITY_URL" not in ctx.guild.features:
        return await ctx.send(embed=H.info("This server has no vanity URL."))
    try:
        inv = await ctx.guild.vanity_invite()
        await ctx.send(embed=H.info(f"Vanity: {inv.url} ({inv.uses} uses)"))
    except Exception:
        await ctx.send(embed=H.info("This server has no vanity URL set."))


@c("webhookcreate", "webhookcreate <name> [channel]", "Create a webhook")
@commands.guild_only()
@commands.has_permissions(manage_webhooks=True)
async def _f(ctx, name, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    wh = await channel.create_webhook(name=name[:80])
    try:
        await ctx.author.send(embed=H.success(f"Webhook **{name}** in #{channel.name}:\n{wh.url}"))
        await ctx.send(embed=H.success("Webhook created — URL sent to your DMs."))
    except discord.Forbidden:
        await ctx.send(embed=H.success(f"Webhook **{name}** created (enable DMs to receive the URL)."))


@c("webhooklist", "webhooklist", "List webhooks in this server")
@commands.guild_only()
@commands.has_permissions(manage_webhooks=True)
async def _f(ctx):
    whs = await ctx.guild.webhooks()
    if not whs:
        return await ctx.send(embed=H.info("No webhooks."))
    lines = [f"**{w.name}** in #{w.channel}" for w in whs[:25]]
    await ctx.send(embed=H.info("\n".join(lines)[:4000]))


@c("webhookdelete", "webhookdelete <name>", "Delete webhooks by name")
@commands.guild_only()
@commands.has_permissions(manage_webhooks=True)
async def _f(ctx, *, name):
    deleted = 0
    for w in await ctx.guild.webhooks():
        if w.name == name:
            await w.delete()
            deleted += 1
    await ctx.send(embed=H.success(f"Deleted **{deleted}** webhook(s) named **{name}**."))


# ════════════════════════════ MISC SERVER ════════════════════════════
@c("boosters", "boosters", "List members boosting the server", ["boosterlist"])
@commands.guild_only()
async def _f(ctx):
    boosters = ctx.guild.premium_subscribers
    if not boosters:
        return await ctx.send(embed=H.info("Nobody is boosting this server. 😢"))
    names = ", ".join(b.name for b in boosters[:60])
    await ctx.send(embed=H.info(f"**{len(boosters)} boosters:** {names}"[:4000]))


@c("boostcount", "boostcount", "Show boost level and count", ["boosts"])
@commands.guild_only()
async def _f(ctx):
    g = ctx.guild
    await ctx.send(embed=H.info(f"**Boost level:** {g.premium_tier}\n**Boosts:** {g.premium_subscription_count}"))


@c("listbots", "listbots", "List bots in the server", ["bots"])
@commands.guild_only()
async def _f(ctx):
    bots = [m for m in ctx.guild.members if m.bot]
    if not bots:
        return await ctx.send(embed=H.info("No bots here."))
    names = ", ".join(b.name for b in bots[:60])
    await ctx.send(embed=H.info(f"**{len(bots)} bots:** {names}"[:4000]))


@c("prune", "prune <days>", "Kick members inactive for N days with no roles", ["pruneinactive"])
@commands.guild_only()
@commands.has_permissions(kick_members=True)
async def _f(ctx, days: int):
    days = max(1, min(days, 30))
    pruned = await ctx.guild.prune_members(days=days, reason=f"By {ctx.author}")
    await ctx.send(embed=H.success(f"Pruned **{pruned}** inactive members ({days}d)."))


@c("pruneestimate", "pruneestimate <days>", "Estimate how many members a prune would remove")
@commands.guild_only()
@commands.has_permissions(kick_members=True)
async def _f(ctx, days: int):
    days = max(1, min(days, 30))
    est = await ctx.guild.estimate_pruned_members(days=days)
    await ctx.send(embed=H.info(f"A {days}-day prune would remove about **{est}** members."))


@c("audit", "audit [count]", "Show recent audit log entries")
@commands.guild_only()
@commands.has_permissions(view_audit_log=True)
async def _f(ctx, count: int = 10):
    count = max(1, min(count, 20))
    lines = []
    async for entry in ctx.guild.audit_logs(limit=count):
        who = entry.user.name if entry.user else "?"
        lines.append(f"**{entry.action.name}** by {who}")
    await ctx.send(embed=H.info("\n".join(lines) or "No entries."))


def register(bot, CATEGORIES, helpers):
    """Register all server commands on the bot and mirror them into CATEGORIES.

    Skips any command whose primary name already exists elsewhere (avoids
    duplicate functionality) and drops only the individual aliases that clash.
    """
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
        live_aliases = [a for a in aliases if a not in taken]
        bot.add_command(commands.Command(fn, name=name, aliases=live_aliases))
        taken.add(name)
        taken.update(live_aliases)
        added.append((syntax, desc))
    if added:
        CATEGORIES["server"] = {"emoji": "🛠️", "commands": added}
    return len(added)
