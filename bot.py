import discord
from discord.ext import commands
import asyncio
import json
import os
import re
import random
import datetime
import html as html_mod
import aiohttp
from collections import defaultdict

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DEFAULT_PREFIX = "$"
TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")

# ─── DATA STORAGE (flat JSON files) ───────────────────────────────────────────
def load_data(path, default):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default

def save_data(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

DATA_DIR = "data"
economy     = load_data(f"{DATA_DIR}/economy.json", {})
warnings_data = load_data(f"{DATA_DIR}/warnings.json", {})
autoroles   = load_data(f"{DATA_DIR}/autoroles.json", {})
welcomecfg  = load_data(f"{DATA_DIR}/welcome.json", {})
antinuke    = load_data(f"{DATA_DIR}/antinuke.json", {})
levels_data = load_data(f"{DATA_DIR}/levels.json", {})
inv_data    = load_data(f"{DATA_DIR}/inventory.json", {})
marriages   = load_data(f"{DATA_DIR}/marriages.json", {})
prefixes    = load_data(f"{DATA_DIR}/prefixes.json", {})   # guild_id -> prefix string
proposals   = {}  # in-memory only: "guild:user" -> "guild:target"
snipe_cache = {}  # channel_id -> {author, content, attachment, time}
esnipe_cache = {} # channel_id -> {author, before, after, time}
afk_data    = {}  # "guild:user" -> {reason, time}
sticky_data   = load_data("data/sticky.json",   {})  # channel_id -> {content, message_id}
vanity_cfg    = load_data("data/vanity.json",   {})  # guild_id -> {role_id, code}
profile_data  = load_data("data/profiles.json", {})  # guild:user -> {bio, rep, birthday}
sticky_lock   = set()  # channel IDs currently posting a sticky (prevent race)
bot_start     = datetime.datetime.utcnow()

def get_prefix(bot, message):
    if message.guild:
        return prefixes.get(str(message.guild.id), DEFAULT_PREFIX)
    return DEFAULT_PREFIX

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)

# ─── COMMAND CATEGORIES (shared by $help and $cmds) ───────────────────────────
CATEGORIES = {
    "moderation": {
        "emoji": "🛡️",
        "commands": [
            ("ban <user> [reason]",    "Ban a member"),
            ("kick <user> [reason]",   "Kick a member"),
            ("mute <user> [minutes]",  "Timeout a member"),
            ("unmute <user>",          "Remove timeout"),
            ("warn <user> [reason]",   "Warn a member"),
            ("warnings <user>",        "View warnings"),
            ("clearwarn <user>",       "Clear all warnings"),
            ("purge <amount>",         "Delete messages (alias: p)"),
            ("c",                      "Clear last 50 messages (alias: clear)"),
            ("lock",                   "Lock channel"),
            ("unlock",                 "Unlock channel"),
            ("slowmode <seconds>",     "Set slowmode"),
        ]
    },
    "welcome": {
        "emoji": "👋",
        "commands": [
            ("setwelcome <#ch> <msg>", "Set welcome message — vars: {user} {server} {count}"),
            ("setleave <#channel>",    "Set leave channel"),
            ("testwelcome",            "Preview welcome message"),
        ]
    },
    "tickets": {
        "emoji": "🎫",
        "commands": [
            ("ticketsetup <#channel>", "Create ticket panel"),
            ("ticketclose",            "Close current ticket"),
            ("addmember <user>",       "Add user to ticket"),
            ("removemember <user>",    "Remove user from ticket"),
        ]
    },
    "antinuke": {
        "emoji": "🔒",
        "commands": [
            ("antinuke enable",         "Enable anti-nuke"),
            ("antinuke disable",        "Disable anti-nuke"),
            ("antinuke log <#channel>", "Set log channel"),
            ("antinuke status",         "View current status"),
            ("antiraid enable",         "Enable anti-raid"),
            ("antiraid disable",        "Disable anti-raid"),
        ]
    },
    "autorole": {
        "emoji": "🎭",
        "commands": [
            ("autorole add <@role>",    "Add auto-role on join"),
            ("autorole remove <@role>", "Remove auto-role"),
            ("autorole list",           "List auto-roles"),
        ]
    },
    "economy": {
        "emoji": "💰",
        "commands": [
            ("balance [@user]",           "View wallet & bank"),
            ("daily",                     "Claim daily reward"),
            ("work",                      "Earn some coins"),
            ("deposit <amount|all>",      "Deposit to bank"),
            ("withdraw <amount|all>",     "Withdraw from bank"),
            ("pay <@user> <amount>",      "Pay another user"),
            ("leaderboard",              "Top richest users"),
            ("slots <bet>",              "Play slots"),
            ("coinflip <bet> <h/t>",     "Flip a coin"),
            ("blackjack <bet>",          "Play blackjack"),
            ("rob <@user>",              "Rob someone's wallet"),
            ("addmoney <@user> <amt>",   "🔒 Add money to user"),
            ("removemoney <@user> <amt>","🔒 Remove money from user"),
            ("setmoney <@user> <amt>",   "🔒 Set user's wallet"),
        ]
    },
    "fun": {
        "emoji": "🎉",
        "commands": [
            ("8ball <question>",         "Ask the magic 8-ball"),
            ("roll [sides]",             "Roll a dice"),
            ("choose <a|b|...>",         "Choose between options"),
            ("ship <@u1> <@u2>",         "Check compatibility"),
            ("rps <rock/paper/scissors>","Rock paper scissors"),
            ("joke",                     "Random joke"),
            ("meme",                     "Random meme category"),
        ]
    },
    "levels": {
        "emoji": "⭐",
        "commands": [
            ("rank [@user]",          "View your level, XP & progress bar"),
            ("ranktop",               "Top 10 members by level"),
            ("addxp @user <amount>",  "🔒 Add XP to a member"),
            ("removexp @user <amt>",  "🔒 Remove XP from a member"),
            ("setlevel @user <lvl>",  "🔒 Set a member's level"),
            ("setxp @user <amount>",  "🔒 Set a member's total XP"),
        ]
    },
    "shop": {
        "emoji": "🛍️",
        "commands": [
            ("shop [category]",   "Browse the shop (Watches, Food, Jewelry, Valuables, Fun)"),
            ("buy <item>",        "Buy an item from the shop"),
            ("inventory [@user]", "View your or someone's items"),
            ("give @user <item>", "Give an item to someone"),
        ]
    },
    "marriage": {
        "emoji": "💍",
        "commands": [
            ("propose @user",  "Propose to someone"),
            ("accept",         "Accept a marriage proposal"),
            ("decline",        "Decline a marriage proposal"),
            ("divorce",        "End your marriage"),
            ("spouse [@user]", "Check who someone is married to"),
        ]
    },
    "settings": {
        "emoji": "⚙️",
        "commands": [
            ("prefix <new>", "🔒 Change this server's bot prefix (max 5 chars)"),
            ("resetprefix",  "🔒 Reset prefix back to the default `$`"),
            ("getprefix",    "Show the current prefix for this server"),
        ]
    },
    "info": {
        "emoji": "📊",
        "commands": [
            ("ping",             "Bot latency"),
            ("botinfo",          "Bot stats (servers, members, commands)"),
            ("serverinfo",       "Server stats and details"),
            ("userinfo [@user]", "User profile (level, balance, roles, dates)"),
            ("avatar [@user]",   "Display someone's avatar with download links"),
            ("roleinfo <@role>", "Role details and member count"),
        ]
    },
    "utility": {
        "emoji": "🔧",
        "commands": [
            ("snipe [#]",        "See deleted messages — $s, $s 2, $s 3… (up to 10)"),
            ("editsnipe",        "See the last edited message (alias: es)"),
            ("clearsnipe",       "Clear snipe data for this channel (alias: cs)"),
            ("say <text>",       "🔒 Make the bot say something"),
            ("embed <t> | <d>",  "🔒 Post a custom embed (title | description)"),
            ("poll <question>",  "Create a ✅/❌/🤷 poll"),
            ("afk [reason]",     "Set yourself as AFK — auto-clears when you chat"),
            ("nuke",             "🔒 Nuke the channel (delete & recreate it)"),
        ]
    },
    "text": {
        "emoji": "✏️",
        "commands": [
            ("clap <text>",    "Add 👏 claps 👏 between words"),
            ("mock <text>",    "mOcK tExT"),
            ("reverse <text>", "Reverse text"),
            ("emojify <text>", "🇹 🇽 🇹  to emoji letters"),
            ("upper <text>",   "UPPERCASE text"),
            ("lower <text>",   "lowercase text"),
        ]
    },
    "sticky": {
        "emoji": "📌",
        "commands": [
            ("sticky <message>", "🔒 Pin a message that stays at the bottom of the channel"),
            ("unsticky",         "🔒 Remove the sticky message from this channel"),
            ("stickies",         "List all sticky messages in this server"),
        ]
    },
    "vanity": {
        "emoji": "🔗",
        "commands": [
            ("vanity",                    "Show vanity tracking stats & current advertisers"),
            ("vanity setup <code> @role", "🔒 Set vanity code and reward role"),
            ("vanity list",               "List members currently advertising the vanity"),
            ("vanity remove",             "🔒 Disable vanity tracking for this server"),
        ]
    },
    "social": {
        "emoji": "🤝",
        "commands": [
            ("hug @user",       "Hug someone"),
            ("pat @user",       "Pat someone"),
            ("slap @user",      "Slap someone"),
            ("poke @user",      "Poke someone"),
            ("kiss @user",      "Kiss someone"),
            ("wave @user",      "Wave at someone"),
            ("cuddle @user",    "Cuddle someone"),
            ("highfive @user",  "High-five someone"),
            ("bonk @user",      "Bonk someone"),
            ("bite @user",      "Bite someone"),
            ("dance [@user]",   "Dance (alone or with someone)"),
            ("cry",             "Cry 😢"),
            ("feed @user",      "Feed someone"),
            ("tickle @user",    "Tickle someone"),
            ("wink [@user]",    "Wink at someone (or just wink)"),
            ("nom @user",       "Nom someone"),
            ("glomp @user",     "Glomp someone"),
            ("handhold @user",  "Hold hands with someone"),
            ("blush",           "Blush 😊"),
            ("smug",            "Smug mode 😏"),
        ]
    },
    "nsfw": {
        "emoji": "🔞",
        "commands": [
            ("fuck @user",    "🔞 NSFW channels only"),
            ("spank @user",   "🔞 NSFW channels only"),
            ("lick @user",    "🔞 NSFW channels only"),
            ("suck @user",    "🔞 NSFW channels only"),
            ("nsfwneko",      "🔞 Random neko image"),
            ("nsfwwaifu",     "🔞 Random waifu image"),
            ("ahegao",        "🔞 You know what this is"),
        ]
    },
    "animals": {
        "emoji": "🐾",
        "commands": [
            ("cat",   "Random cat image"),
            ("dog",   "Random dog image"),
            ("fox",   "Random fox image"),
            ("duck",  "Random duck image"),
            ("panda", "Random panda image"),
            ("bird",  "Random bird image"),
        ]
    },
    "profile": {
        "emoji": "🪪",
        "commands": [
            ("profile [@user]",        "View someone's full profile card"),
            ("bio [text]",             "Set your bio (omit to clear)"),
            ("rep @user",              "Give someone a reputation point (once per day)"),
            ("birthday set <MM/DD>",   "Save your birthday"),
            ("birthday check [@user]", "See someone's birthday"),
        ]
    },
    "extra_mod": {
        "emoji": "⚔️",
        "commands": [
            ("unban <user_id>",         "🔒 Unban a user by ID"),
            ("softban @user [reason]",  "🔒 Ban+unban to clear messages, no perm ban"),
            ("nick @user <nickname>",   "🔒 Change a member's nickname"),
            ("deafen @user",            "🔒 Server-deafen a member"),
            ("undeafen @user",          "🔒 Remove server-deafen"),
            ("hide",                    "🔒 Hide channel from @everyone"),
            ("unhide",                  "🔒 Reveal channel to @everyone"),
            ("vcmove @user <#vc>",      "🔒 Move a member to another voice channel"),
        ]
    },
    "trivia": {
        "emoji": "❓",
        "commands": [
            ("trivia",       "Answer a random trivia question (15s timer)"),
            ("wyr",          "Would you rather…"),
            ("truth",        "Random truth question"),
            ("dare",         "Random dare prompt"),
            ("nhie",         "Never have I ever…"),
            ("roast @user",  "Roast someone"),
            ("compliment @user", "Compliment someone"),
            ("fortune",      "Get a fortune cookie"),
            ("fact",         "Random interesting fact"),
        ]
    },
    "extra_economy": {
        "emoji": "🎣",
        "commands": [
            ("fish",  "Go fishing for coins"),
            ("hunt",  "Go hunting for coins"),
            ("crime", "Commit a crime for coins (risky)"),
            ("beg",   "Beg for some loose change"),
        ]
    },
    "extra_text": {
        "emoji": "🔠",
        "commands": [
            ("binary encode <text>", "Convert text to binary"),
            ("binary decode <text>", "Convert binary to text"),
            ("caesar <shift> <text>","Caesar-cipher a message"),
            ("count <text>",         "Count characters and words"),
            ("spoiler <text>",       "Wrap text in a spoiler tag"),
            ("zalgo <text>",         "Z̷a̸l̵g̷o̶ text"),
            ("repeat <n> <text>",    "Repeat text N times (max 10)"),
            ("scramble <text>",      "Scramble the words"),
        ]
    },
    "extra_utility": {
        "emoji": "🛠️",
        "commands": [
            ("uptime",            "How long the bot has been running"),
            ("invite",            "Get the bot's invite link"),
            ("membercount",       "Server member count breakdown"),
            ("boosters",          "List server boosters"),
            ("channelinfo [#ch]", "Info about a channel"),
            ("color <hex>",       "Preview a hex color"),
            ("vote",              "Voting links for the bot"),
        ]
    },
    "games": {
        "emoji": "🎮",
        "commands": [
            ("roblox <user>",        "Show a Roblox user's profile info"),
            ("roblox avatar <user>", "Show a Roblox user's avatar"),
        ]
    },
}

# Build command usage lookup: cmd_name → (full_syntax, description)
_CMD_USAGE: dict[str, tuple[str, str]] = {}
for _cat_data in CATEGORIES.values():
    for _syntax, _desc in _cat_data["commands"]:
        _cmd_name = _syntax.split()[0]
        if _cmd_name not in _CMD_USAGE:
            _CMD_USAGE[_cmd_name] = (_syntax, _desc)

def _make_example(prefix: str, syntax: str) -> str:
    """Turn a syntax string into a plausible example invocation."""
    ex = syntax
    for old, new in [
        ("<user>",    "@rpjq"),       ("[@user]", "@rpjq"),
        ("[reason]",  "spam"),       ("[minutes]", "10"),
        ("<amount>",  "10"),         ("<seconds>", "5"),
        ("<#ch>",     "#general"),   ("<channel>", "#general"),
        ("<msg>",     "Welcome!"),   ("<text>",    "hello world"),
        ("<hex>",     "#ff0000"),    ("<item>",    "sword"),
        ("<price>",   "500"),        ("[amount]",  "100"),
        ("<role>",    "@Member"),    ("<n>",       "3"),
        ("<shift>",   "3"),          ("<new>",     "!"),
        ("<minutes>", "10"),         ("<color>",   "#5865f2"),
    ]:
        ex = ex.replace(old, new)
    ex = re.sub(r'<[^>]+>', 'value', ex)
    ex = re.sub(r'\[[^\]]+\]', '', ex).strip()
    return f"{prefix}{ex}"

# ─── SHOP CATALOG ─────────────────────────────────────────────────────────────
SHOP_ITEMS = {
    # Watches
    "casio":        {"emoji": "⌚", "category": "Watches",      "price": 250,    "desc": "Classic digital watch"},
    "rolex":        {"emoji": "🕰️", "category": "Watches",      "price": 15000,  "desc": "Luxury Swiss timepiece"},
    "apple_watch":  {"emoji": "⌚", "category": "Watches",      "price": 4500,   "desc": "Smartwatch with all the features"},
    "pocket_watch": {"emoji": "🕰️", "category": "Watches",      "price": 800,    "desc": "Vintage gold pocket watch"},
    # Food
    "burger":       {"emoji": "🍔", "category": "Food",         "price": 50,     "desc": "Juicy double cheeseburger"},
    "pizza":        {"emoji": "🍕", "category": "Food",         "price": 80,     "desc": "Whole pepperoni pizza"},
    "sushi":        {"emoji": "🍱", "category": "Food",         "price": 120,    "desc": "Premium sushi platter"},
    "lobster":      {"emoji": "🦞", "category": "Food",         "price": 500,    "desc": "Whole steamed lobster"},
    "cake":         {"emoji": "🎂", "category": "Food",         "price": 200,    "desc": "Fancy celebration cake"},
    "coffee":       {"emoji": "☕", "category": "Food",         "price": 20,     "desc": "Fresh brewed coffee"},
    # Jewelry
    "ring":         {"emoji": "💍", "category": "Jewelry",      "price": 3000,   "desc": "Diamond engagement ring"},
    "necklace":     {"emoji": "📿", "category": "Jewelry",      "price": 1500,   "desc": "Gold chain necklace"},
    "earrings":     {"emoji": "💎", "category": "Jewelry",      "price": 900,    "desc": "Crystal drop earrings"},
    "bracelet":     {"emoji": "✨", "category": "Jewelry",      "price": 600,    "desc": "Silver charm bracelet"},
    # Valuables
    "laptop":       {"emoji": "💻", "category": "Valuables",    "price": 8000,   "desc": "High-end gaming laptop"},
    "car":          {"emoji": "🚗", "category": "Valuables",    "price": 50000,  "desc": "Brand new sports car"},
    "house":        {"emoji": "🏠", "category": "Valuables",    "price": 200000, "desc": "3-bedroom house"},
    "yacht":        {"emoji": "🛥️", "category": "Valuables",    "price": 500000, "desc": "Private luxury yacht"},
    "painting":     {"emoji": "🖼️", "category": "Valuables",    "price": 25000,  "desc": "Rare original painting"},
    "gem":          {"emoji": "💎", "category": "Valuables",    "price": 10000,  "desc": "Rare precious gemstone"},
    # Fun
    "trophy":       {"emoji": "🏆", "category": "Fun",          "price": 5000,   "desc": "Gold championship trophy"},
    "ticket":       {"emoji": "🎟️", "category": "Fun",          "price": 300,    "desc": "VIP event ticket"},
    "balloon":      {"emoji": "🎈", "category": "Fun",          "price": 10,     "desc": "A colorful balloon"},
    "rose":         {"emoji": "🌹", "category": "Fun",          "price": 50,     "desc": "Fresh red rose"},
    "fireworks":    {"emoji": "🎆", "category": "Fun",          "price": 150,    "desc": "Box of fireworks"},
}

# ─── ANTI-NUKE TRACKING ───────────────────────────────────────────────────────
nuke_tracker = defaultdict(lambda: defaultdict(list))  # guild -> user -> [timestamps]
NUKE_THRESHOLD = 3      # actions
NUKE_WINDOW    = 10     # seconds

# ─── XP / LEVELING ────────────────────────────────────────────────────────────
XP_PER_MESSAGE  = (15, 25)   # random range awarded per eligible message
XP_COOLDOWN     = 60         # seconds between XP awards per user
xp_cooldowns: dict = {}      # key: "guild_id:user_id" -> last awarded timestamp

def xp_key(guild_id, user_id):
    return f"{guild_id}:{user_id}"

def get_level_data(guild_id, user_id):
    key = xp_key(guild_id, user_id)
    if key not in levels_data:
        levels_data[key] = {"xp": 0, "level": 0}
    return levels_data[key]

def save_levels():
    save_data(f"{DATA_DIR}/levels.json", levels_data)

def xp_for_level(level: int) -> int:
    """Total XP required to reach this level."""
    return 5 * (level ** 2) + 50 * level + 100

def compute_level(xp: int) -> int:
    level = 0
    while xp >= xp_for_level(level):
        xp -= xp_for_level(level)
        level += 1
    return level

def xp_progress(total_xp: int):
    """Returns (current_level, xp_into_level, xp_needed_for_next)."""
    level = 0
    remaining = total_xp
    while remaining >= xp_for_level(level):
        remaining -= xp_for_level(level)
        level += 1
    return level, remaining, xp_for_level(level)

def progress_bar(current, total, length=10):
    filled = int(length * current / total) if total else 0
    return "█" * filled + "░" * (length - filled)

# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_balance(guild_id, user_id):
    key = f"{guild_id}:{user_id}"
    if key not in economy:
        economy[key] = {"wallet": 0, "bank": 0}
    return economy[key]

def save_economy():
    save_data(f"{DATA_DIR}/economy.json", economy)

def embed(title, description, color=0x2b2d31):
    e = discord.Embed(title=title, description=description, color=color)
    e.timestamp = datetime.datetime.utcnow()
    return e

def success(desc):  return embed("✅ Success", desc, 0x57f287)
def error(desc):    return embed("❌ Error",   desc, 0xed4245)
def info(desc):     return embed("ℹ️ Info",    desc, 0x5865f2)

# ─────────────────────────────────────────────────────────────────────────────
#  EVENTS
# ─────────────────────────────────────────────────────────────────────────────

_STATS_FILE = os.path.join(os.path.dirname(__file__), "data", "stats.json")

def _write_stats():
    """Write live guild/member stats to data/stats.json for the web API."""
    try:
        guilds = sorted(bot.guilds, key=lambda g: g.member_count or 0, reverse=True)
        top = [
            {
                "name": g.name,
                "member_count": g.member_count or 0,
                "icon_url": g.icon.url if g.icon else None,
            }
            for g in guilds[:4]
        ]
        total_members = sum(g.member_count or 0 for g in guilds)
        payload = {
            "guild_count": len(guilds),
            "member_count": total_members,
            "top_servers": top,
        }
        os.makedirs(os.path.dirname(_STATS_FILE), exist_ok=True)
        with open(_STATS_FILE, "w") as f:
            json.dump(payload, f)
    except Exception as e:
        print(f"⚠️  Failed to write stats.json: {e}")

@bot.event
async def on_ready():
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name=f"{DEFAULT_PREFIX}help | your server")
    )
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    _write_stats()

@bot.event
async def on_guild_join(guild):
    _write_stats()

@bot.event
async def on_guild_remove(guild):
    _write_stats()

# ── Welcome ──
@bot.event
async def on_member_join(member):
    guild_id = str(member.guild.id)

    # Auto-role
    if guild_id in autoroles:
        for role_id in autoroles[guild_id]:
            role = member.guild.get_role(int(role_id))
            if role:
                try: await member.add_roles(role, reason="Auto-role")
                except: pass

    # Welcome message
    if guild_id in welcomecfg:
        cfg = welcomecfg[guild_id]
        channel = member.guild.get_channel(int(cfg["channel"]))
        if channel:
            msg = cfg["message"].replace("{user}", member.mention) \
                                .replace("{server}", member.guild.name) \
                                .replace("{count}", str(member.guild.member_count))
            e = discord.Embed(description=msg, color=0x5865f2)
            e.set_author(name=str(member), icon_url=member.display_avatar.url)
            e.set_footer(text=f"Member #{member.guild.member_count}")
            await channel.send(embed=e)
    _write_stats()

@bot.event
async def on_member_remove(member):
    guild_id = str(member.guild.id)
    if guild_id in welcomecfg and "leave_channel" in welcomecfg[guild_id]:
        cfg = welcomecfg[guild_id]
        channel = member.guild.get_channel(int(cfg["leave_channel"]))
        if channel:
            e = discord.Embed(description=f"**{member}** has left the server.", color=0xed4245)
            e.set_author(name=str(member), icon_url=member.display_avatar.url)
            await channel.send(embed=e)
    _write_stats()

# ── Anti-Nuke: track dangerous actions ──
async def check_nuke(guild, user, action):
    guild_id = str(guild.id)
    if guild_id not in antinuke or not antinuke[guild_id].get("enabled"):
        return
    if user.id == guild.owner_id:
        return

    now = datetime.datetime.utcnow().timestamp()
    nuke_tracker[guild.id][user.id].append(now)
    # remove old entries
    nuke_tracker[guild.id][user.id] = [
        t for t in nuke_tracker[guild.id][user.id] if now - t < NUKE_WINDOW
    ]

    if len(nuke_tracker[guild.id][user.id]) >= NUKE_THRESHOLD:
        # Ban the user
        try:
            member = guild.get_member(user.id)
            if member:
                await member.ban(reason=f"[Anti-Nuke] Detected mass {action}")
            log_ch_id = antinuke[guild_id].get("log_channel")
            if log_ch_id:
                ch = guild.get_channel(int(log_ch_id))
                if ch:
                    await ch.send(embed=embed(
                        "🛡️ Anti-Nuke Triggered",
                        f"**{user}** was banned for mass `{action}` ({NUKE_THRESHOLD}+ in {NUKE_WINDOW}s)",
                        0xfee75c
                    ))
        except: pass

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    guild_id = str(message.guild.id)
    user_id  = str(message.author.id)

    # Determine if this message is a command invocation before processing
    ctx = await bot.get_context(message)
    is_command = ctx.valid
    await bot.invoke(ctx)

    # ── AFK: clear AFK if author was AFK (runs even on commands) ──
    afk_key = f"{guild_id}:{user_id}"
    if afk_key in afk_data:
        afk_data.pop(afk_key)
        try:
            await message.channel.send(
                embed=discord.Embed(description=f"👋 Welcome back {message.author.mention}! Your AFK has been removed.", color=0x57f287),
                delete_after=5
            )
        except: pass

    # ── AFK: notify if someone mentions an AFK user (runs even on commands) ──
    for mentioned in message.mentions:
        mk = f"{guild_id}:{mentioned.id}"
        if mk in afk_data:
            entry = afk_data[mk]
            reason = entry["reason"]
            ts = entry["time"]
            ago = int(datetime.datetime.utcnow().timestamp() - ts)
            m, s = divmod(ago, 60)
            h, m = divmod(m, 60)
            time_str = f"{h}h {m}m {s}s ago" if h else f"{m}m {s}s ago"
            await message.channel.send(
                embed=discord.Embed(
                    description=f"💤 **{mentioned.display_name}** is AFK: {reason}\n*Set {time_str}*",
                    color=0xfee75c
                ),
                delete_after=8
            )

    # Commands don't earn XP and don't trigger the sticky relay
    if is_command:
        return

    # ── XP ──
    key = xp_key(guild_id, user_id)
    now = datetime.datetime.utcnow().timestamp()
    last = xp_cooldowns.get(key, 0)
    if now - last < XP_COOLDOWN:
        return

    xp_cooldowns[key] = now
    data = get_level_data(guild_id, user_id)
    old_level = xp_progress(data["xp"])[0]

    gained = random.randint(*XP_PER_MESSAGE)
    data["xp"] += gained

    new_level, xp_in, xp_needed = xp_progress(data["xp"])
    data["level"] = new_level
    save_levels()

    if new_level > old_level:
        e = discord.Embed(
            title="⬆️ Level Up!",
            description=f"🎉 {message.author.mention} reached **Level {new_level}**!",
            color=0x57f287
        )
        e.set_thumbnail(url=message.author.display_avatar.url)
        await message.channel.send(embed=e)

    # ── Sticky message relay (only for real chat messages, not commands) ──
    cid = str(message.channel.id)
    if cid in sticky_data and message.channel.id not in sticky_lock:
        sticky_lock.add(message.channel.id)
        try:
            old_id = sticky_data[cid].get("message_id")
            if old_id:
                try:
                    old_msg = await message.channel.fetch_message(int(old_id))
                    await old_msg.delete()
                except: pass
            content = sticky_data[cid]["content"]
            e = discord.Embed(description=content, color=0xfee75c)
            e.set_footer(text="📌 Sticky Message")
            new_msg = await message.channel.send(embed=e)
            sticky_data[cid]["message_id"] = str(new_msg.id)
            save_data(f"data/sticky.json", sticky_data)
        finally:
            sticky_lock.discard(message.channel.id)

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return
    attachment = message.attachments[0].url if message.attachments else None
    entry = {
        "author":     message.author,
        "content":    message.content or "*[no text]*",
        "attachment": attachment,
        "time":       datetime.datetime.utcnow()
    }
    ch = message.channel.id
    if ch not in snipe_cache:
        snipe_cache[ch] = []
    snipe_cache[ch].insert(0, entry)   # newest first
    snipe_cache[ch] = snipe_cache[ch][:10]  # keep last 10

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content:
        return
    esnipe_cache[before.channel.id] = {
        "author": before.author,
        "before": before.content or "*[empty]*",
        "after":  after.content or "*[empty]*",
        "time":   datetime.datetime.utcnow()
    }

@bot.event
async def on_presence_update(before, after):
    if after.bot or not after.guild:
        return
    guild_id = str(after.guild.id)
    if guild_id not in vanity_cfg:
        return
    cfg = vanity_cfg[guild_id]
    code = cfg.get("code", "").lower().strip()
    role_id = cfg.get("role_id")
    if not code or not role_id:
        return
    role = after.guild.get_role(int(role_id))
    if not role:
        return

    def has_vanity(member):
        for act in member.activities:
            if isinstance(act, discord.CustomActivity):
                if act.name and code in act.name.lower():
                    return True
            if hasattr(act, "state") and act.state and code in act.state.lower():
                return True
        return False

    had = has_vanity(before)
    has = has_vanity(after)
    try:
        if has and not had and role not in after.roles:
            await after.add_roles(role, reason="Vanity advertiser")
        elif not has and had and role in after.roles:
            await after.remove_roles(role, reason="Removed vanity from status")
    except: pass

@bot.event
async def on_guild_channel_delete(channel):
    async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
        await check_nuke(channel.guild, entry.user, "channel delete")

@bot.event
async def on_guild_role_delete(role):
    async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
        await check_nuke(role.guild, entry.user, "role delete")

@bot.event
async def on_member_ban(guild, user):
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
        await check_nuke(guild, entry.user, "ban")

# ─────────────────────────────────────────────────────────────────────────────
#  PREFIX
# ─────────────────────────────────────────────────────────────────────────────

@bot.command(name="prefix")
@commands.has_permissions(administrator=True)
async def change_prefix(ctx, new_prefix: str):
    if len(new_prefix) > 5:
        return await ctx.send(embed=error("Prefix must be 5 characters or fewer."))
    prefixes[str(ctx.guild.id)] = new_prefix
    save_data(f"{DATA_DIR}/prefixes.json", prefixes)
    await ctx.send(embed=success(f"Prefix changed to **`{new_prefix}`**\nAll commands now start with `{new_prefix}help`, `{new_prefix}rank`, etc."))

@bot.command(name="resetprefix")
@commands.has_permissions(administrator=True)
async def reset_prefix(ctx):
    prefixes.pop(str(ctx.guild.id), None)
    save_data(f"{DATA_DIR}/prefixes.json", prefixes)
    await ctx.send(embed=success(f"Prefix reset to the default **`{DEFAULT_PREFIX}`**."))

@bot.command(name="getprefix")
async def get_prefix_cmd(ctx):
    p = prefixes.get(str(ctx.guild.id), DEFAULT_PREFIX)
    await ctx.send(embed=info(f"Current prefix for this server: **`{p}`**"))

# ─────────────────────────────────────────────────────────────────────────────
#  HELP
# ─────────────────────────────────────────────────────────────────────────────

def _category_embed(cat_key, p):
    """Compact, limit-safe embed listing a category's commands (works for big cats)."""
    cat = CATEGORIES[cat_key]
    cmds = cat["commands"]
    e = discord.Embed(
        title=f"{cat['emoji']} {cat_key.title()} Commands",
        description=f"**{len(cmds)} commands** • prefix `{p}` • 🔒 = needs permissions",
        color=0x5865f2,
    )
    lines = []
    for syntax, desc in cmds:
        d = desc if len(desc) <= 60 else desc[:59] + "…"
        lines.append(f"`{p}{syntax}` — {d}")
    budget, used, cur, truncated = 5200, 0, "", 0
    chunks = []
    for idx, ln in enumerate(lines):
        if used + len(ln) + 1 > budget:
            truncated = len(lines) - idx
            break
        if len(cur) + len(ln) + 1 > 1024:
            chunks.append(cur)
            cur = ln
        else:
            cur = (cur + "\n" + ln) if cur else ln
        used += len(ln) + 1
    if cur:
        chunks.append(cur)
    for c in chunks:
        e.add_field(name="\u200b", value=c, inline=False)
    if truncated:
        e.add_field(name="\u200b",
                    value=f"…and **{truncated}** more — see the full list on the website.",
                    inline=False)
    e.set_footer(text=f"{p}help {cat_key}  •  {len(cmds)} commands")
    return e


class _CategorySelect(discord.ui.Select):
    def __init__(self, author_id, options):
        super().__init__(placeholder="📂 Choose a category…", options=options,
                         min_values=1, max_values=1)
        self.author_id = author_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message(
                "This menu isn't yours — run the command yourself.", ephemeral=True)
        p = prefixes.get(str(interaction.guild.id), DEFAULT_PREFIX) if interaction.guild else DEFAULT_PREFIX
        await interaction.response.edit_message(embed=_category_embed(self.values[0], p), view=self.view)


class _CommandsView(discord.ui.View):
    def __init__(self, author_id):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.message = None
        items = list(CATEGORIES.items())
        for i in range(0, len(items), 25):  # Discord caps a select at 25 options
            opts = [
                discord.SelectOption(
                    label=key.title()[:100], value=key,
                    emoji=(cat.get("emoji") or None),
                    description=f"{len(cat['commands'])} commands",
                )
                for key, cat in items[i:i + 25]
            ]
            self.add_item(_CategorySelect(author_id, opts))

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


@bot.command()
async def help(ctx, category: str = None):
    p = prefixes.get(str(ctx.guild.id), DEFAULT_PREFIX) if ctx.guild else DEFAULT_PREFIX
    if category and category.lower() in CATEGORIES:
        await ctx.send(embed=_category_embed(category.lower(), p))
    else:
        # Build a compact text grid — avoids the 25-field Discord embed limit
        lines = []
        for name, cat in CATEGORIES.items():
            count = len(cat["commands"])
            lines.append(f"{cat['emoji']} **{name.title()}** ({count}) — `{p}help {name}`")
        half = (len(lines) + 1) // 2
        col_a = "\n".join(lines[:half])
        col_b = "\n".join(lines[half:])
        e = discord.Embed(
            title="📖 Help Menu",
            description=f"Use `{p}help <category>` for detailed commands.\nUse `{p}cmds` to see every command at a glance.\n\u200b",
            color=0x5865f2
        )
        e.add_field(name="\u200b", value=col_a, inline=True)
        e.add_field(name="\u200b", value=col_b, inline=True)
        e.set_footer(text=f"Prefix: {p}  •  {len(bot.commands)} commands loaded")
        await ctx.send(embed=e)

@bot.command(name="cmds", aliases=["commands"])
async def cmd_list(ctx):
    p = prefixes.get(str(ctx.guild.id), DEFAULT_PREFIX) if ctx.guild else DEFAULT_PREFIX
    total = sum(len(v["commands"]) for v in CATEGORIES.values())
    e = discord.Embed(
        title="📋 All Commands",
        description=(f"**{total} commands** across **{len(CATEGORIES)} categories** • prefix `{p}`\n"
                     f"Pick a category from the menu below 👇\n🔒 = requires permissions"),
        color=0x5865f2,
    )
    lines = [f"{cat['emoji']} **{k.title()}** ({len(cat['commands'])})" for k, cat in CATEGORIES.items()]
    half = (len(lines) + 1) // 2
    e.add_field(name="\u200b", value="\n".join(lines[:half]), inline=True)
    e.add_field(name="\u200b", value="\n".join(lines[half:]), inline=True)
    e.set_footer(text=f"Menu expires in 3 min  •  or use {p}help <category>")
    view = _CommandsView(ctx.author.id)
    view.message = await ctx.send(embed=e, view=view)

# ─────────────────────────────────────────────────────────────────────────────
#  MODERATION
# ─────────────────────────────────────────────────────────────────────────────

def mod_check():
    async def predicate(ctx):
        return ctx.author.guild_permissions.moderate_members or ctx.author.guild_permissions.administrator
    return commands.check(predicate)

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    if member.top_role >= ctx.author.top_role:
        return await ctx.send(embed=error("You cannot ban someone with a higher or equal role."))
    await member.ban(reason=f"{ctx.author}: {reason}")
    await ctx.send(embed=success(f"**{member}** has been banned.\n**Reason:** {reason}"))

@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    if member.top_role >= ctx.author.top_role:
        return await ctx.send(embed=error("You cannot kick someone with a higher or equal role."))
    await member.kick(reason=f"{ctx.author}: {reason}")
    await ctx.send(embed=success(f"**{member}** has been kicked.\n**Reason:** {reason}"))

@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int = 10, *, reason="No reason provided"):
    duration = datetime.timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    await ctx.send(embed=success(f"**{member}** has been muted for **{minutes} minutes**."))

@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    await member.timeout(None)
    await ctx.send(embed=success(f"**{member}**'s timeout has been removed."))

@bot.command()
@commands.has_permissions(moderate_members=True)
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    guild_id = str(ctx.guild.id)
    user_id  = str(member.id)
    if guild_id not in warnings_data: warnings_data[guild_id] = {}
    if user_id  not in warnings_data[guild_id]: warnings_data[guild_id][user_id] = []
    warnings_data[guild_id][user_id].append({
        "reason": reason,
        "moderator": str(ctx.author),
        "time": str(datetime.datetime.utcnow())
    })
    save_data(f"{DATA_DIR}/warnings.json", warnings_data)
    count = len(warnings_data[guild_id][user_id])
    await ctx.send(embed=success(f"**{member}** has been warned. ({count} total)\n**Reason:** {reason}"))

@bot.command()
async def warnings(ctx, member: discord.Member):
    guild_id = str(ctx.guild.id)
    user_id  = str(member.id)
    warns = warnings_data.get(guild_id, {}).get(user_id, [])
    if not warns:
        return await ctx.send(embed=info(f"**{member}** has no warnings."))
    e = discord.Embed(title=f"⚠️ Warnings for {member}", color=0xfee75c)
    for i, w in enumerate(warns, 1):
        e.add_field(name=f"Warning #{i}", value=f"**Reason:** {w['reason']}\n**By:** {w['moderator']}", inline=False)
    await ctx.send(embed=e)

@bot.command()
@commands.has_permissions(moderate_members=True)
async def clearwarn(ctx, member: discord.Member):
    guild_id = str(ctx.guild.id)
    user_id  = str(member.id)
    if guild_id in warnings_data: warnings_data[guild_id][user_id] = []
    save_data(f"{DATA_DIR}/warnings.json", warnings_data)
    await ctx.send(embed=success(f"Cleared all warnings for **{member}**."))

@bot.command(aliases=["p"])
@commands.has_permissions(manage_messages=True)
async def purge(ctx, amount: int):
    if amount < 1 or amount > 500:
        return await ctx.send(embed=error("Amount must be between 1 and 500."))
    await ctx.channel.purge(limit=amount + 1)
    m = await ctx.send(embed=success(f"Deleted **{amount}** messages."))
    await asyncio.sleep(3)
    await m.delete()

@bot.command(name="c", aliases=["clear"])
@commands.has_permissions(manage_messages=True)
async def quick_clear(ctx):
    """Quickly clear the last 50 messages."""
    await ctx.channel.purge(limit=51)
    m = await ctx.send(embed=success("Cleared the last **50** messages."))
    await asyncio.sleep(3)
    await m.delete()

@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send(embed=success(f"🔒 **{ctx.channel.mention}** has been locked."))

@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send(embed=success(f"🔓 **{ctx.channel.mention}** has been unlocked."))

@bot.command()
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):
    await ctx.channel.edit(slowmode_delay=seconds)
    await ctx.send(embed=success(f"Slowmode set to **{seconds}s** in {ctx.channel.mention}."))

# ─────────────────────────────────────────────────────────────────────────────
#  WELCOME
# ─────────────────────────────────────────────────────────────────────────────

@bot.command()
@commands.has_permissions(manage_guild=True)
async def setwelcome(ctx, channel: discord.TextChannel, *, message: str):
    guild_id = str(ctx.guild.id)
    if guild_id not in welcomecfg: welcomecfg[guild_id] = {}
    welcomecfg[guild_id]["channel"] = str(channel.id)
    welcomecfg[guild_id]["message"] = message
    save_data(f"{DATA_DIR}/welcome.json", welcomecfg)
    await ctx.send(embed=success(f"Welcome channel set to {channel.mention}.\nMessage: {message}"))

@bot.command()
@commands.has_permissions(manage_guild=True)
async def setleave(ctx, channel: discord.TextChannel):
    guild_id = str(ctx.guild.id)
    if guild_id not in welcomecfg: welcomecfg[guild_id] = {}
    welcomecfg[guild_id]["leave_channel"] = str(channel.id)
    save_data(f"{DATA_DIR}/welcome.json", welcomecfg)
    await ctx.send(embed=success(f"Leave channel set to {channel.mention}."))

@bot.command()
async def testwelcome(ctx):
    await on_member_join(ctx.author)

# ─────────────────────────────────────────────────────────────────────────────
#  TICKETS
# ─────────────────────────────────────────────────────────────────────────────

class TicketButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", emoji="🎫", style=discord.ButtonStyle.blurple, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        existing = discord.utils.get(guild.text_channels, name=f"ticket-{interaction.user.name.lower()}")
        if existing:
            return await interaction.response.send_message(f"You already have a ticket: {existing.mention}", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user:   discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        for role in guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        category = discord.utils.get(guild.categories, name="Tickets")
        if not category:
            category = await guild.create_category("Tickets")

        channel = await category.create_text_channel(
            f"ticket-{interaction.user.name.lower()}",
            overwrites=overwrites,
            topic=f"Ticket opened by {interaction.user}"
        )

        close_view = CloseTicketView()
        e = discord.Embed(
            title="🎫 Support Ticket",
            description=f"Welcome {interaction.user.mention}!\nDescribe your issue and a staff member will assist you shortly.\n\nClick **Close Ticket** when resolved.",
            color=0x5865f2
        )
        await channel.send(embed=e, view=close_view)
        await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", emoji="🔒", style=discord.ButtonStyle.red, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Closing ticket in 5 seconds...")
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def ticketsetup(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    e = discord.Embed(
        title="🎫 Support Tickets",
        description="Click the button below to open a support ticket.\nA private channel will be created just for you.",
        color=0x5865f2
    )
    view = TicketButton()
    await channel.send(embed=e, view=view)
    await ctx.send(embed=success(f"Ticket panel created in {channel.mention}."), delete_after=5)

@bot.command()
@commands.has_permissions(manage_channels=True)
async def addmember(ctx, member: discord.Member):
    await ctx.channel.set_permissions(member, read_messages=True, send_messages=True)
    await ctx.send(embed=success(f"{member.mention} added to this ticket."))

@bot.command()
@commands.has_permissions(manage_channels=True)
async def removemember(ctx, member: discord.Member):
    await ctx.channel.set_permissions(member, read_messages=False)
    await ctx.send(embed=success(f"{member.mention} removed from this ticket."))

# ─────────────────────────────────────────────────────────────────────────────
#  ANTI-NUKE / ANTI-RAID
# ─────────────────────────────────────────────────────────────────────────────

@bot.group(invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def antinuke(ctx):
    await ctx.send(embed=info("Usage: `$antinuke <enable|disable|log|status>`"))

@antinuke.command(name="enable")
@commands.has_permissions(administrator=True)
async def antinuke_enable(ctx):
    guild_id = str(ctx.guild.id)
    if guild_id not in antinuke: antinuke[guild_id] = {}
    antinuke[guild_id]["enabled"] = True
    save_data(f"{DATA_DIR}/antinuke.json", antinuke)
    await ctx.send(embed=success("Anti-nuke is now **enabled**. Users who mass-delete channels/roles or mass-ban will be banned."))

@antinuke.command(name="disable")
@commands.has_permissions(administrator=True)
async def antinuke_disable(ctx):
    guild_id = str(ctx.guild.id)
    if guild_id in antinuke: antinuke[guild_id]["enabled"] = False
    save_data(f"{DATA_DIR}/antinuke.json", antinuke)
    await ctx.send(embed=success("Anti-nuke has been **disabled**."))

@antinuke.command(name="log")
@commands.has_permissions(administrator=True)
async def antinuke_log(ctx, channel: discord.TextChannel):
    guild_id = str(ctx.guild.id)
    if guild_id not in antinuke: antinuke[guild_id] = {}
    antinuke[guild_id]["log_channel"] = str(channel.id)
    save_data(f"{DATA_DIR}/antinuke.json", antinuke)
    await ctx.send(embed=success(f"Anti-nuke logs will be sent to {channel.mention}."))

@antinuke.command(name="status")
async def antinuke_status(ctx):
    guild_id = str(ctx.guild.id)
    cfg = antinuke.get(guild_id, {})
    status = "✅ Enabled" if cfg.get("enabled") else "❌ Disabled"
    log_ch = f"<#{cfg['log_channel']}>" if cfg.get("log_channel") else "Not set"
    e = discord.Embed(title="🔒 Anti-Nuke Status", color=0x5865f2)
    e.add_field(name="Status", value=status)
    e.add_field(name="Log Channel", value=log_ch)
    e.add_field(name="Threshold", value=f"{NUKE_THRESHOLD} actions in {NUKE_WINDOW}s")
    await ctx.send(embed=e)

# Anti-raid (basic: kick new accounts joining rapidly)
join_timestamps = defaultdict(list)

@bot.group(invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def antiraid(ctx):
    await ctx.send(embed=info("Usage: `$antiraid <enable|disable>`"))

@antiraid.command(name="enable")
@commands.has_permissions(administrator=True)
async def antiraid_enable(ctx):
    guild_id = str(ctx.guild.id)
    if guild_id not in antinuke: antinuke[guild_id] = {}
    antinuke[guild_id]["antiraid"] = True
    save_data(f"{DATA_DIR}/antinuke.json", antinuke)
    await ctx.send(embed=success("Anti-raid is now **enabled**. New accounts joining during raids will be kicked."))

@antiraid.command(name="disable")
@commands.has_permissions(administrator=True)
async def antiraid_disable(ctx):
    guild_id = str(ctx.guild.id)
    if guild_id in antinuke: antinuke[guild_id]["antiraid"] = False
    save_data(f"{DATA_DIR}/antinuke.json", antinuke)
    await ctx.send(embed=success("Anti-raid has been **disabled**."))

# ─────────────────────────────────────────────────────────────────────────────
#  AUTO-ROLE
# ─────────────────────────────────────────────────────────────────────────────

@bot.group(invoke_without_command=True)
@commands.has_permissions(manage_roles=True)
async def autorole(ctx):
    await ctx.send(embed=info("Usage: `$autorole <add|remove|list>`"))

@autorole.command(name="add")
@commands.has_permissions(manage_roles=True)
async def autorole_add(ctx, role: discord.Role):
    guild_id = str(ctx.guild.id)
    if guild_id not in autoroles: autoroles[guild_id] = []
    if str(role.id) in autoroles[guild_id]:
        return await ctx.send(embed=error("This role is already an auto-role."))
    autoroles[guild_id].append(str(role.id))
    save_data(f"{DATA_DIR}/autoroles.json", autoroles)
    await ctx.send(embed=success(f"{role.mention} will now be given to new members."))

@autorole.command(name="remove")
@commands.has_permissions(manage_roles=True)
async def autorole_remove(ctx, role: discord.Role):
    guild_id = str(ctx.guild.id)
    if guild_id in autoroles and str(role.id) in autoroles[guild_id]:
        autoroles[guild_id].remove(str(role.id))
        save_data(f"{DATA_DIR}/autoroles.json", autoroles)
        await ctx.send(embed=success(f"{role.mention} removed from auto-roles."))
    else:
        await ctx.send(embed=error("That role is not an auto-role."))

@autorole.command(name="list")
async def autorole_list(ctx):
    guild_id = str(ctx.guild.id)
    roles = autoroles.get(guild_id, [])
    if not roles:
        return await ctx.send(embed=info("No auto-roles set."))
    mentions = [f"<@&{r}>" for r in roles]
    await ctx.send(embed=info("**Auto-Roles:**\n" + "\n".join(mentions)))

# ─────────────────────────────────────────────────────────────────────────────
#  ECONOMY
# ─────────────────────────────────────────────────────────────────────────────

DAILY_AMOUNT  = 500
WORK_MIN, WORK_MAX = 50, 300
DAILY_COOLDOWNS = {}
WORK_COOLDOWNS  = {}

@bot.command(aliases=["bal"])
async def balance(ctx, member: discord.Member = None):
    member = member or ctx.author
    b = get_balance(str(ctx.guild.id), str(member.id))
    e = discord.Embed(title=f"💰 {member.display_name}'s Balance", color=0xfee75c)
    e.add_field(name="👛 Wallet", value=f"${b['wallet']:,}")
    e.add_field(name="🏦 Bank",   value=f"${b['bank']:,}")
    e.add_field(name="💎 Total",  value=f"${b['wallet'] + b['bank']:,}", inline=False)
    await ctx.send(embed=e)

@bot.command()
async def daily(ctx):
    key = f"{ctx.guild.id}:{ctx.author.id}"
    now = datetime.datetime.utcnow()
    if key in DAILY_COOLDOWNS:
        diff = (now - DAILY_COOLDOWNS[key]).total_seconds()
        if diff < 86400:
            remaining = 86400 - diff
            h, m = divmod(int(remaining), 3600)
            m, s = divmod(m, 60)
            return await ctx.send(embed=error(f"You already claimed your daily! Come back in **{h}h {m}m {s}s**."))
    DAILY_COOLDOWNS[key] = now
    bal = get_balance(str(ctx.guild.id), str(ctx.author.id))
    bal["wallet"] += DAILY_AMOUNT
    save_economy()
    await ctx.send(embed=success(f"You claimed your daily **${DAILY_AMOUNT:,}**!\nWallet: **${bal['wallet']:,}**"))

@bot.command()
async def work(ctx):
    key = f"{ctx.guild.id}:{ctx.author.id}"
    now = datetime.datetime.utcnow()
    if key in WORK_COOLDOWNS:
        diff = (now - WORK_COOLDOWNS[key]).total_seconds()
        if diff < 3600:
            remaining = 3600 - diff
            m, s = divmod(int(remaining), 60)
            return await ctx.send(embed=error(f"You're tired! Rest for **{m}m {s}s**."))
    WORK_COOLDOWNS[key] = now
    jobs = ["programmer", "chef", "driver", "streamer", "artist", "teacher", "doctor"]
    earned = random.randint(WORK_MIN, WORK_MAX)
    job = random.choice(jobs)
    bal = get_balance(str(ctx.guild.id), str(ctx.author.id))
    bal["wallet"] += earned
    save_economy()
    await ctx.send(embed=success(f"You worked as a **{job}** and earned **${earned:,}**!\nWallet: **${bal['wallet']:,}**"))

@bot.command()
async def deposit(ctx, amount: str):
    bal = get_balance(str(ctx.guild.id), str(ctx.author.id))
    if amount.lower() == "all":
        amount = bal["wallet"]
    else:
        amount = int(amount)
    if amount <= 0 or amount > bal["wallet"]:
        return await ctx.send(embed=error("Invalid amount."))
    bal["wallet"] -= amount
    bal["bank"]   += amount
    save_economy()
    await ctx.send(embed=success(f"Deposited **${amount:,}** to your bank.\nBank: **${bal['bank']:,}**"))

@bot.command()
async def withdraw(ctx, amount: str):
    bal = get_balance(str(ctx.guild.id), str(ctx.author.id))
    if amount.lower() == "all":
        amount = bal["bank"]
    else:
        amount = int(amount)
    if amount <= 0 or amount > bal["bank"]:
        return await ctx.send(embed=error("Invalid amount."))
    bal["bank"]   -= amount
    bal["wallet"] += amount
    save_economy()
    await ctx.send(embed=success(f"Withdrew **${amount:,}** from your bank.\nWallet: **${bal['wallet']:,}**"))

@bot.command()
async def pay(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        return await ctx.send(embed=error("Amount must be positive."))
    if member.id == ctx.author.id:
        return await ctx.send(embed=error("You can't pay yourself."))
    src = get_balance(str(ctx.guild.id), str(ctx.author.id))
    if src["wallet"] < amount:
        return await ctx.send(embed=error("Insufficient funds in your wallet."))
    dst = get_balance(str(ctx.guild.id), str(member.id))
    src["wallet"] -= amount
    dst["wallet"] += amount
    save_economy()
    await ctx.send(embed=success(f"Sent **${amount:,}** to {member.mention}."))

@bot.command()
async def leaderboard(ctx):
    guild_id = str(ctx.guild.id)
    lb = [(k.split(":")[1], v["wallet"] + v["bank"])
          for k, v in economy.items() if k.startswith(f"{guild_id}:")]
    lb.sort(key=lambda x: x[1], reverse=True)
    e = discord.Embed(title="🏆 Richest Members", color=0xfee75c)
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, total) in enumerate(lb[:10]):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"Unknown ({uid})"
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        e.add_field(name=f"{medal} {name}", value=f"${total:,}", inline=False)
    await ctx.send(embed=e)

@bot.command()
@commands.has_permissions(administrator=True)
async def addmoney(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        return await ctx.send(embed=error("Amount must be positive."))
    bal = get_balance(str(ctx.guild.id), str(member.id))
    bal["wallet"] += amount
    save_economy()
    await ctx.send(embed=success(f"Added **${amount:,}** to {member.mention}'s wallet.\nNew wallet: **${bal['wallet']:,}**"))

@bot.command()
@commands.has_permissions(administrator=True)
async def removemoney(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        return await ctx.send(embed=error("Amount must be positive."))
    bal = get_balance(str(ctx.guild.id), str(member.id))
    bal["wallet"] = max(0, bal["wallet"] - amount)
    save_economy()
    await ctx.send(embed=success(f"Removed **${amount:,}** from {member.mention}'s wallet.\nNew wallet: **${bal['wallet']:,}**"))

@bot.command()
@commands.has_permissions(administrator=True)
async def setmoney(ctx, member: discord.Member, amount: int):
    if amount < 0:
        return await ctx.send(embed=error("Amount cannot be negative."))
    bal = get_balance(str(ctx.guild.id), str(member.id))
    bal["wallet"] = amount
    save_economy()
    await ctx.send(embed=success(f"Set {member.mention}'s wallet to **${amount:,}**."))

@bot.command()
async def rob(ctx, target: discord.Member):
    if target.id == ctx.author.id:
        return await ctx.send(embed=error("You can't rob yourself."))
    src  = get_balance(str(ctx.guild.id), str(ctx.author.id))
    dest = get_balance(str(ctx.guild.id), str(target.id))
    if dest["wallet"] < 50:
        return await ctx.send(embed=error(f"{target.display_name} is too broke to rob!"))
    if random.random() < 0.4:  # 40% success
        stolen = random.randint(1, min(dest["wallet"] // 2, 500))
        dest["wallet"] -= stolen
        src["wallet"]  += stolen
        save_economy()
        await ctx.send(embed=success(f"You robbed **${stolen:,}** from {target.mention}! 🦹"))
    else:
        fine = random.randint(50, 200)
        src["wallet"] = max(0, src["wallet"] - fine)
        save_economy()
        await ctx.send(embed=error(f"You got caught robbing {target.mention} and fined **${fine:,}**! 👮"))

# ── Gambling ──
SLOT_SYMBOLS = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎"]
SLOT_MULT = {"🍒": 2, "🍋": 2, "🍊": 3, "🍇": 3, "⭐": 5, "💎": 10}

@bot.command()
async def slots(ctx, bet: int):
    bal = get_balance(str(ctx.guild.id), str(ctx.author.id))
    if bet <= 0 or bet > bal["wallet"]:
        return await ctx.send(embed=error("Invalid bet amount."))
    reels = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
    display = " | ".join(reels)
    if reels[0] == reels[1] == reels[2]:
        mult = SLOT_MULT[reels[0]]
        winnings = bet * mult
        bal["wallet"] += winnings - bet
        save_economy()
        result = f"**JACKPOT! {display}**\nYou won **${winnings:,}** (x{mult})! 🎉"
        await ctx.send(embed=success(result))
    elif reels[0] == reels[1] or reels[1] == reels[2]:
        winnings = int(bet * 1.5)
        bal["wallet"] += winnings - bet
        save_economy()
        result = f"{display}\nSmall win! You got **${winnings:,}**."
        await ctx.send(embed=embed("🎰 Slots", result, 0xfee75c))
    else:
        bal["wallet"] -= bet
        save_economy()
        await ctx.send(embed=embed("🎰 Slots", f"{display}\nYou lost **${bet:,}**. Better luck next time!", 0xed4245))

@bot.command()
async def coinflip(ctx, bet: int, choice: str):
    bal = get_balance(str(ctx.guild.id), str(ctx.author.id))
    if bet <= 0 or bet > bal["wallet"]:
        return await ctx.send(embed=error("Invalid bet amount."))
    choice = choice.lower()
    if choice not in ("h", "t", "heads", "tails"):
        return await ctx.send(embed=error("Choose `h` (heads) or `t` (tails)."))
    result = random.choice(["h", "t"])
    result_name = "Heads 🪙" if result == "h" else "Tails 🪙"
    won = choice[0] == result
    if won:
        bal["wallet"] += bet
        save_economy()
        await ctx.send(embed=success(f"It's **{result_name}**! You won **${bet:,}**!"))
    else:
        bal["wallet"] -= bet
        save_economy()
        await ctx.send(embed=error(f"It's **{result_name}**! You lost **${bet:,}**."))

@bot.command()
async def blackjack(ctx, bet: int):
    bal = get_balance(str(ctx.guild.id), str(ctx.author.id))
    if bet <= 0 or bet > bal["wallet"]:
        return await ctx.send(embed=error("Invalid bet amount."))

    def card_val(c): return min(c, 10) if c != 1 else 11
    def hand_val(hand):
        total = sum(card_val(c) for c in hand)
        if total > 21 and 1 in hand: total -= 10
        return total
    def draw(): return random.randint(1, 13)
    def fmt(hand): return f"{hand_val(hand)} (cards: {', '.join(str(c) for c in hand)})"

    player = [draw(), draw()]
    dealer = [draw(), draw()]

    if hand_val(player) == 21:
        winnings = int(bet * 1.5)
        bal["wallet"] += winnings
        save_economy()
        return await ctx.send(embed=success(f"**Blackjack!** 🎉 You win **${winnings:,}**!\nYour hand: {fmt(player)}"))

    e = discord.Embed(title="🃏 Blackjack", color=0x5865f2)
    e.add_field(name="Your Hand", value=fmt(player))
    e.add_field(name="Dealer Shows", value=str(dealer[0]))
    e.add_field(name="Actions", value="Reply with `hit` or `stand`", inline=False)
    msg = await ctx.send(embed=e)

    def check(m): return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ("hit", "stand")

    while hand_val(player) < 21:
        try:
            reply = await bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            return await ctx.send(embed=error("Blackjack timed out."))
        if reply.content.lower() == "hit":
            player.append(draw())
            if hand_val(player) > 21:
                bal["wallet"] -= bet
                save_economy()
                return await ctx.send(embed=error(f"Bust! Your hand: {fmt(player)}\nYou lost **${bet:,}**."))
        else:
            break

    while hand_val(dealer) < 17:
        dealer.append(draw())

    pv, dv = hand_val(player), hand_val(dealer)
    if dv > 21 or pv > dv:
        bal["wallet"] += bet
        save_economy()
        await ctx.send(embed=success(f"You win! **${bet:,}**\nYou: {fmt(player)} | Dealer: {fmt(dealer)}"))
    elif pv == dv:
        await ctx.send(embed=embed("🃏 Blackjack", f"Push! Bet returned.\nYou: {fmt(player)} | Dealer: {fmt(dealer)}", 0xfee75c))
    else:
        bal["wallet"] -= bet
        save_economy()
        await ctx.send(embed=error(f"Dealer wins. You lost **${bet:,}**.\nYou: {fmt(player)} | Dealer: {fmt(dealer)}"))

# ─────────────────────────────────────────────────────────────────────────────
#  FUN
# ─────────────────────────────────────────────────────────────────────────────

@bot.command(name="8ball")
async def eightball(ctx, *, question: str):
    responses = [
        "It is certain.", "It is decidedly so.", "Without a doubt.", "Yes, definitely.",
        "You may rely on it.", "As I see it, yes.", "Most likely.", "Outlook good.",
        "Yes.", "Signs point to yes.", "Reply hazy, try again.", "Ask again later.",
        "Better not tell you now.", "Cannot predict now.", "Concentrate and ask again.",
        "Don't count on it.", "My reply is no.", "My sources say no.",
        "Outlook not so good.", "Very doubtful."
    ]
    e = discord.Embed(title="🎱 Magic 8-Ball", color=0x5865f2)
    e.add_field(name="Question", value=question)
    e.add_field(name="Answer",   value=random.choice(responses))
    await ctx.send(embed=e)

@bot.command()
async def roll(ctx, sides: int = 6):
    result = random.randint(1, sides)
    await ctx.send(embed=embed("🎲 Dice Roll", f"You rolled a **{result}** (d{sides})"))

@bot.command()
async def choose(ctx, *, options: str):
    choices = [o.strip() for o in options.split("|")]
    if len(choices) < 2:
        return await ctx.send(embed=error("Separate choices with `|`. Example: `$choose pizza | tacos | sushi`"))
    chosen = random.choice(choices)
    await ctx.send(embed=embed("🤔 Choose", f"I choose: **{chosen}**"))

@bot.command()
async def ship(ctx, user1: discord.Member, user2: discord.Member):
    score = random.randint(0, 100)
    bar = "💗" * (score // 10) + "🤍" * (10 - score // 10)
    await ctx.send(embed=embed("💘 Ship", f"**{user1.display_name}** x **{user2.display_name}**\n\n{bar}\n**{score}% compatible!**", 0xff73fa))

@bot.command()
async def rps(ctx, choice: str):
    options = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
    choice = choice.lower()
    if choice not in options:
        return await ctx.send(embed=error("Choose `rock`, `paper`, or `scissors`."))
    bot_choice = random.choice(list(options.keys()))
    wins = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
    if choice == bot_choice:
        result = "It's a tie!"
    elif wins[choice] == bot_choice:
        result = "You win! 🎉"
    else:
        result = "I win! 😈"
    await ctx.send(embed=embed("✂️ Rock Paper Scissors",
        f"You: {options[choice]}  vs  Me: {options[bot_choice]}\n\n**{result}**"))

@bot.command()
async def joke(ctx):
    jokes = [
        ("Why don't scientists trust atoms?", "Because they make up everything!"),
        ("Why did the scarecrow win an award?", "Because he was outstanding in his field!"),
        ("I told my wife she was drawing her eyebrows too high.", "She looked surprised."),
        ("Why can't you give Elsa a balloon?", "Because she'll let it go!"),
        ("What do you call a fake noodle?", "An impasta!"),
        ("Why did the bicycle fall over?", "Because it was two-tired!"),
    ]
    setup, punchline = random.choice(jokes)
    e = discord.Embed(title="😂 Joke", color=0xfee75c)
    e.add_field(name="Setup",     value=setup,     inline=False)
    e.add_field(name="Punchline", value=punchline, inline=False)
    await ctx.send(embed=e)

async def _reddit_img(subreddit: str) -> str | None:
    """Fetch a random image URL from a subreddit (no auth required)."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://www.reddit.com/r/{subreddit}/random.json?limit=1",
                headers={"User-Agent": "FraudBot/1.0"},
                timeout=aiohttp.ClientTimeout(total=8),
                allow_redirects=True,
            ) as r:
                data = await r.json(content_type=None)
        post = data[0]["data"]["children"][0]["data"]
        url = post.get("url", "")
        if url.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            return url
        images = post.get("preview", {}).get("images", [])
        if images:
            return images[0]["source"]["url"].replace("&amp;", "&")
    except Exception:
        pass
    return None

@bot.command()
async def meme(ctx):
    img = await _reddit_img("memes") or await _reddit_img("dankmemes")
    e = discord.Embed(title="😂 Random Meme", color=0x5865f2)
    if img:
        e.set_image(url=img)
    else:
        e.description = "Couldn't fetch a meme right now. Try again!"
    await ctx.send(embed=e)

# ─────────────────────────────────────────────────────────────────────────────
#  SHOP & INVENTORY
# ─────────────────────────────────────────────────────────────────────────────

def inv_key(guild_id, user_id):
    return f"{guild_id}:{user_id}"

def get_inventory(guild_id, user_id):
    key = inv_key(guild_id, user_id)
    if key not in inv_data:
        inv_data[key] = {}
    return inv_data[key]

def save_inventory():
    save_data(f"{DATA_DIR}/inventory.json", inv_data)

@bot.command(aliases=["store"])
async def shop(ctx, category: str = None):
    categories = {}
    for item_id, item in SHOP_ITEMS.items():
        cat = item["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append((item_id, item))

    if category:
        # show specific category
        matched = {k: v for k, v in categories.items() if k.lower() == category.lower()}
        if not matched:
            return await ctx.send(embed=error(f"Category not found. Try: {', '.join(categories.keys())}"))
        cat_name, items = list(matched.items())[0]
        e = discord.Embed(title=f"🛍️ Shop — {cat_name}", color=0x5865f2)
        for item_id, item in items:
            e.add_field(
                name=f"{item['emoji']} {item_id.replace('_', ' ').title()}",
                value=f"{item['desc']}\n**${item['price']:,}** • `$buy {item_id}`",
                inline=True
            )
        await ctx.send(embed=e)
    else:
        # show category overview
        e = discord.Embed(
            title="🛍️ Shop",
            description="Use `$shop <category>` to browse, then `$buy <item>` to purchase.",
            color=0x5865f2
        )
        cat_emojis = {"Watches": "⌚", "Food": "🍔", "Jewelry": "💍", "Valuables": "💎", "Fun": "🎉"}
        for cat_name, items in categories.items():
            emoji = cat_emojis.get(cat_name, "🛒")
            names = ", ".join(i[0].replace("_", " ").title() for i in items[:4])
            e.add_field(name=f"{emoji} {cat_name}", value=f"`$shop {cat_name.lower()}`\n{names}…", inline=True)
        await ctx.send(embed=e)

@bot.command()
async def buy(ctx, *, item_name: str):
    item_id = item_name.lower().replace(" ", "_")
    if item_id not in SHOP_ITEMS:
        close = [k for k in SHOP_ITEMS if item_name.lower() in k]
        hint = f" Did you mean: `{'`, `'.join(close)}`?" if close else ""
        return await ctx.send(embed=error(f"Item `{item_name}` not found.{hint}\nUse `$shop` to browse."))

    item  = SHOP_ITEMS[item_id]
    price = item["price"]
    bal   = get_balance(str(ctx.guild.id), str(ctx.author.id))

    if bal["wallet"] < price:
        short = price - bal["wallet"]
        return await ctx.send(embed=error(f"You need **${short:,}** more to buy this!\nWallet: **${bal['wallet']:,}** / **${price:,}**"))

    bal["wallet"] -= price
    save_economy()

    inv = get_inventory(str(ctx.guild.id), str(ctx.author.id))
    inv[item_id] = inv.get(item_id, 0) + 1
    save_inventory()

    await ctx.send(embed=success(
        f"You bought {item['emoji']} **{item_id.replace('_', ' ').title()}** for **${price:,}**!\n"
        f"Remaining wallet: **${bal['wallet']:,}**"
    ))

@bot.command(aliases=["inv", "bag"])
async def inventory(ctx, member: discord.Member = None):
    member = member or ctx.author
    inv = get_inventory(str(ctx.guild.id), str(member.id))

    if not inv:
        subject = "Your" if member == ctx.author else f"{member.display_name}'s"
        return await ctx.send(embed=info(f"{subject} inventory is empty."))

    e = discord.Embed(title=f"🎒 {member.display_name}'s Inventory", color=0x5865f2)
    total_value = 0
    for item_id, qty in inv.items():
        if qty <= 0:
            continue
        item = SHOP_ITEMS.get(item_id, {"emoji": "❓", "desc": "Unknown item", "price": 0})
        value = item["price"] * qty
        total_value += value
        e.add_field(
            name=f"{item['emoji']} {item_id.replace('_', ' ').title()} ×{qty}",
            value=f"${item['price']:,} each • **${value:,}** total",
            inline=True
        )
    e.set_footer(text=f"Total inventory value: ${total_value:,}")
    await ctx.send(embed=e)

@bot.command(name="give")
async def give_item(ctx, member: discord.Member, *, item_name: str):
    if member.id == ctx.author.id:
        return await ctx.send(embed=error("You can't give items to yourself."))

    item_id = item_name.lower().replace(" ", "_")
    if item_id not in SHOP_ITEMS:
        return await ctx.send(embed=error(f"Item `{item_name}` not found. Use `$shop` to see item names."))

    src_inv = get_inventory(str(ctx.guild.id), str(ctx.author.id))
    if src_inv.get(item_id, 0) < 1:
        return await ctx.send(embed=error(f"You don't have a **{item_id.replace('_', ' ').title()}** to give!"))

    src_inv[item_id] -= 1
    dst_inv = get_inventory(str(ctx.guild.id), str(member.id))
    dst_inv[item_id] = dst_inv.get(item_id, 0) + 1
    save_inventory()

    item = SHOP_ITEMS[item_id]
    await ctx.send(embed=success(
        f"{ctx.author.mention} gave {item['emoji']} **{item_id.replace('_', ' ').title()}** to {member.mention}! 🎁"
    ))

# ─────────────────────────────────────────────────────────────────────────────
#  MARRIAGE
# ─────────────────────────────────────────────────────────────────────────────

def marriage_key(guild_id, user_id):
    return f"{guild_id}:{user_id}"

def save_marriages():
    save_data(f"{DATA_DIR}/marriages.json", marriages)

@bot.command()
async def propose(ctx, member: discord.Member):
    if member.id == ctx.author.id:
        return await ctx.send(embed=error("You can't propose to yourself."))
    if member.bot:
        return await ctx.send(embed=error("You can't propose to a bot!"))

    a_key = marriage_key(str(ctx.guild.id), str(ctx.author.id))
    b_key = marriage_key(str(ctx.guild.id), str(member.id))

    if a_key in marriages:
        spouse_id = marriages[a_key].split(":")[1]
        spouse = ctx.guild.get_member(int(spouse_id))
        name = spouse.display_name if spouse else "someone"
        return await ctx.send(embed=error(f"You're already married to **{name}**! Use `$divorce` first."))
    if b_key in marriages:
        return await ctx.send(embed=error(f"**{member.display_name}** is already married to someone else!"))

    proposals[a_key] = b_key

    e = discord.Embed(
        title="💍 Marriage Proposal",
        description=f"{ctx.author.mention} is proposing to {member.mention}! 💕\n\n"
                    f"{member.mention}, type `$accept` to say yes or `$decline` to say no.",
        color=0xff73fa
    )
    await ctx.send(embed=e)

@bot.command()
async def accept(ctx):
    b_key = marriage_key(str(ctx.guild.id), str(ctx.author.id))
    # find who proposed to this user
    proposer_key = next((k for k, v in proposals.items() if v == b_key), None)

    if not proposer_key:
        return await ctx.send(embed=error("You don't have any pending proposals!"))

    proposer_id = proposer_key.split(":")[1]
    proposer = ctx.guild.get_member(int(proposer_id))

    marriages[proposer_key] = b_key
    marriages[b_key] = proposer_key
    save_marriages()
    proposals.pop(proposer_key, None)

    e = discord.Embed(
        title="💒 Just Married!",
        description=f"🎉 Congratulations! {proposer.mention if proposer else 'Your partner'} and {ctx.author.mention} are now **married**! 💍",
        color=0xff73fa
    )
    await ctx.send(embed=e)

@bot.command()
async def decline(ctx):
    b_key = marriage_key(str(ctx.guild.id), str(ctx.author.id))
    proposer_key = next((k for k, v in proposals.items() if v == b_key), None)
    if not proposer_key:
        return await ctx.send(embed=error("You don't have any pending proposals!"))

    proposer_id = proposer_key.split(":")[1]
    proposer = ctx.guild.get_member(int(proposer_id))
    proposals.pop(proposer_key, None)
    await ctx.send(embed=embed("💔 Proposal Declined",
        f"{ctx.author.mention} declined {proposer.mention if proposer else 'the proposal'}. 💔", 0xed4245))

@bot.command()
async def divorce(ctx):
    a_key = marriage_key(str(ctx.guild.id), str(ctx.author.id))
    if a_key not in marriages:
        return await ctx.send(embed=error("You're not married to anyone!"))

    b_key = marriages[a_key]
    b_id  = b_key.split(":")[1]
    spouse = ctx.guild.get_member(int(b_id))

    marriages.pop(a_key, None)
    marriages.pop(b_key, None)
    save_marriages()

    await ctx.send(embed=embed("💔 Divorced",
        f"{ctx.author.mention} and {spouse.mention if spouse else 'their spouse'} are now divorced. 💔", 0xed4245))

@bot.command()
async def spouse(ctx, member: discord.Member = None):
    member = member or ctx.author
    key = marriage_key(str(ctx.guild.id), str(member.id))
    if key not in marriages:
        subject = "You are" if member == ctx.author else f"**{member.display_name}** is"
        return await ctx.send(embed=info(f"{subject} not currently married."))

    partner_id = marriages[key].split(":")[1]
    partner = ctx.guild.get_member(int(partner_id))
    name = partner.mention if partner else f"<@{partner_id}>"
    subject = "You are" if member == ctx.author else f"**{member.display_name}** is"
    await ctx.send(embed=embed("💍 Marriage Status", f"{subject} married to {name}! 💕", 0xff73fa))

# ─────────────────────────────────────────────────────────────────────────────
#  LEVELING
# ─────────────────────────────────────────────────────────────────────────────

@bot.command(aliases=["level"])
async def rank(ctx, member: discord.Member = None):
    member = member or ctx.author
    guild_id = str(ctx.guild.id)
    user_id  = str(member.id)

    data = get_level_data(guild_id, user_id)
    level, xp_in, xp_needed = xp_progress(data["xp"])

    # Compute server rank
    guild_entries = [
        (k.split(":")[1], v["xp"])
        for k, v in levels_data.items()
        if k.startswith(f"{guild_id}:")
    ]
    guild_entries.sort(key=lambda x: x[1], reverse=True)
    rank_pos = next((i + 1 for i, (uid, _) in enumerate(guild_entries) if uid == user_id), len(guild_entries))

    bar = progress_bar(xp_in, xp_needed, length=12)

    e = discord.Embed(color=0x5865f2)
    e.set_author(name=f"{member.display_name}'s Rank", icon_url=member.display_avatar.url)
    e.add_field(name="🏅 Rank",   value=f"#{rank_pos}", inline=True)
    e.add_field(name="⭐ Level",  value=str(level),     inline=True)
    e.add_field(name="✨ Total XP", value=f"{data['xp']:,}", inline=True)
    e.add_field(
        name="📊 Progress",
        value=f"`{bar}` {xp_in}/{xp_needed} XP",
        inline=False
    )
    await ctx.send(embed=e)

@bot.command(aliases=["lvltop", "levels"])
async def ranktop(ctx):
    guild_id = str(ctx.guild.id)
    guild_entries = [
        (k.split(":")[1], v["xp"])
        for k, v in levels_data.items()
        if k.startswith(f"{guild_id}:")
    ]
    guild_entries.sort(key=lambda x: x[1], reverse=True)

    e = discord.Embed(title="⭐ Level Leaderboard", color=0x5865f2)
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, total_xp) in enumerate(guild_entries[:10]):
        member = ctx.guild.get_member(int(uid))
        name   = member.display_name if member else f"Unknown ({uid})"
        lvl, _, _ = xp_progress(total_xp)
        medal  = medals[i] if i < 3 else f"`#{i+1}`"
        e.add_field(name=f"{medal} {name}", value=f"Level {lvl} • {total_xp:,} XP", inline=False)

    if not guild_entries:
        e.description = "No one has earned XP yet — start chatting!"
    await ctx.send(embed=e)

@bot.command()
@commands.has_permissions(administrator=True)
async def addxp(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        return await ctx.send(embed=error("Amount must be positive."))
    data = get_level_data(str(ctx.guild.id), str(member.id))
    old_level = xp_progress(data["xp"])[0]
    data["xp"] += amount
    new_level, xp_in, xp_needed = xp_progress(data["xp"])
    data["level"] = new_level
    save_levels()
    msg = f"Added **{amount:,} XP** to {member.mention}.\nTotal XP: **{data['xp']:,}** • Level **{new_level}**"
    if new_level > old_level:
        msg += f"\n🎉 They leveled up to **Level {new_level}**!"
    await ctx.send(embed=success(msg))

@bot.command()
@commands.has_permissions(administrator=True)
async def removexp(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        return await ctx.send(embed=error("Amount must be positive."))
    data = get_level_data(str(ctx.guild.id), str(member.id))
    data["xp"] = max(0, data["xp"] - amount)
    new_level, _, _ = xp_progress(data["xp"])
    data["level"] = new_level
    save_levels()
    await ctx.send(embed=success(f"Removed **{amount:,} XP** from {member.mention}.\nTotal XP: **{data['xp']:,}** • Level **{new_level}**"))

@bot.command()
@commands.has_permissions(administrator=True)
async def setlevel(ctx, member: discord.Member, level: int):
    if level < 0:
        return await ctx.send(embed=error("Level cannot be negative."))
    # Calculate total XP required to reach this level exactly
    total_xp = sum(xp_for_level(i) for i in range(level))
    data = get_level_data(str(ctx.guild.id), str(member.id))
    data["xp"] = total_xp
    data["level"] = level
    save_levels()
    await ctx.send(embed=success(f"Set {member.mention}'s level to **Level {level}** ({total_xp:,} XP)."))

@bot.command()
@commands.has_permissions(administrator=True)
async def setxp(ctx, member: discord.Member, amount: int):
    if amount < 0:
        return await ctx.send(embed=error("XP cannot be negative."))
    data = get_level_data(str(ctx.guild.id), str(member.id))
    data["xp"] = amount
    new_level, _, _ = xp_progress(amount)
    data["level"] = new_level
    save_levels()
    await ctx.send(embed=success(f"Set {member.mention}'s XP to **{amount:,}** (Level **{new_level}**)."))

@bot.group(invoke_without_command=True)
@commands.has_permissions(manage_guild=True)
async def levelcfg(ctx):
    await ctx.send(embed=info("Usage: `$levelcfg channel <#channel>` — set where level-up messages are sent (default: same channel)"))

# ─────────────────────────────────────────────────────────────────────────────
#  INFO COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

@bot.command()
async def ping(ctx):
    latency = round(bot.latency * 1000)
    color = 0x57f287 if latency < 100 else 0xfee75c if latency < 200 else 0xed4245
    await ctx.send(embed=discord.Embed(description=f"🏓 Pong! **{latency}ms**", color=color))

@bot.command()
async def botinfo(ctx):
    guilds   = len(bot.guilds)
    members  = sum(g.member_count for g in bot.guilds)
    commands = len(bot.commands)
    latency  = round(bot.latency * 1000)
    e = discord.Embed(title="🤖 Bot Info", color=0x5865f2)
    e.set_thumbnail(url=bot.user.display_avatar.url)
    e.add_field(name="Servers",   value=str(guilds),    inline=True)
    e.add_field(name="Members",   value=f"{members:,}", inline=True)
    e.add_field(name="Commands",  value=str(commands),  inline=True)
    e.add_field(name="Ping",      value=f"{latency}ms", inline=True)
    e.add_field(name="Prefix",    value=prefixes.get(str(ctx.guild.id), DEFAULT_PREFIX), inline=True)
    e.set_footer(text=f"Bot ID: {bot.user.id}")
    await ctx.send(embed=e)

@bot.command(aliases=["si", "server"])
async def serverinfo(ctx):
    g = ctx.guild
    e = discord.Embed(title=f"📊 {g.name}", color=0x5865f2)
    if g.icon:
        e.set_thumbnail(url=g.icon.url)
    e.add_field(name="Owner",        value=g.owner.mention if g.owner else "Unknown", inline=True)
    e.add_field(name="Members",      value=f"{g.member_count:,}", inline=True)
    e.add_field(name="Channels",     value=str(len(g.channels)), inline=True)
    e.add_field(name="Roles",        value=str(len(g.roles)),    inline=True)
    e.add_field(name="Emojis",       value=str(len(g.emojis)),   inline=True)
    e.add_field(name="Boosts",       value=str(g.premium_subscription_count), inline=True)
    e.add_field(name="Boost Level",  value=str(g.premium_tier),  inline=True)
    e.add_field(name="Verification", value=str(g.verification_level).title(), inline=True)
    e.add_field(name="Created",      value=discord.utils.format_dt(g.created_at, "R"), inline=True)
    e.set_footer(text=f"Server ID: {g.id}")
    await ctx.send(embed=e)

@bot.command(aliases=["ui", "whois"])
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    roles  = [r.mention for r in reversed(member.roles) if r != ctx.guild.default_role]
    lvl_data = get_level_data(str(ctx.guild.id), str(member.id))
    level, _, _ = xp_progress(lvl_data["xp"])
    bal = get_balance(str(ctx.guild.id), str(member.id))

    e = discord.Embed(color=member.color if member.color.value else 0x5865f2)
    e.set_author(name=str(member), icon_url=member.display_avatar.url)
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="ID",        value=str(member.id), inline=True)
    e.add_field(name="Nickname",  value=member.nick or "None", inline=True)
    e.add_field(name="Bot",       value="Yes" if member.bot else "No", inline=True)
    e.add_field(name="Joined",    value=discord.utils.format_dt(member.joined_at, "R"), inline=True)
    e.add_field(name="Created",   value=discord.utils.format_dt(member.created_at, "R"), inline=True)
    e.add_field(name="Level",     value=str(level), inline=True)
    e.add_field(name="Balance",   value=f"${bal['wallet'] + bal['bank']:,}", inline=True)
    if roles:
        e.add_field(name=f"Roles [{len(roles)}]", value=" ".join(roles[:10]) + ("…" if len(roles) > 10 else ""), inline=False)
    e.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=e)

@bot.command(aliases=["av", "pfp"])
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    e = discord.Embed(title=f"{member.display_name}'s Avatar", color=0x5865f2)
    e.set_image(url=member.display_avatar.url)
    e.description = f"[PNG]({member.display_avatar.with_format('png').url}) | [JPG]({member.display_avatar.with_format('jpg').url}) | [WEBP]({member.display_avatar.with_format('webp').url})"
    await ctx.send(embed=e)

@bot.command(aliases=["ri"])
async def roleinfo(ctx, *, role: discord.Role):
    members_with = len(role.members)
    e = discord.Embed(title=f"Role: {role.name}", color=role.color)
    e.add_field(name="ID",          value=str(role.id),       inline=True)
    e.add_field(name="Color",       value=str(role.color),    inline=True)
    e.add_field(name="Members",     value=str(members_with),  inline=True)
    e.add_field(name="Mentionable", value=str(role.mentionable), inline=True)
    e.add_field(name="Hoisted",     value=str(role.hoist),    inline=True)
    e.add_field(name="Position",    value=str(role.position), inline=True)
    e.add_field(name="Created",     value=discord.utils.format_dt(role.created_at, "R"), inline=True)
    e.set_footer(text=f"Role ID: {role.id}")
    await ctx.send(embed=e)

# ─────────────────────────────────────────────────────────────────────────────
#  UTILITY COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

@bot.command(aliases=["s"])
async def snipe(ctx, index: int = 1):
    history = snipe_cache.get(ctx.channel.id, [])
    if not history:
        return await ctx.send(embed=info("Nothing to snipe in this channel!"))
    idx = max(1, min(index, len(history))) - 1   # clamp, convert to 0-based
    s = history[idx]
    total = len(history)
    e = discord.Embed(description=s["content"], color=0xed4245)
    e.set_author(name=str(s["author"]), icon_url=s["author"].display_avatar.url)
    e.set_footer(text=f"Snipe {idx+1}/{total} · Deleted {discord.utils.format_dt(s['time'], 'R')}")
    if s["attachment"]:
        e.set_image(url=s["attachment"])
    await ctx.send(embed=e)

@bot.command(aliases=["es"])
async def editsnipe(ctx):
    s = esnipe_cache.get(ctx.channel.id)
    if not s:
        return await ctx.send(embed=info("Nothing to edit-snipe in this channel!"))
    e = discord.Embed(color=0xfee75c)
    e.set_author(name=str(s["author"]), icon_url=s["author"].display_avatar.url)
    e.add_field(name="Before", value=s["before"][:1024], inline=False)
    e.add_field(name="After",  value=s["after"][:1024],  inline=False)
    e.set_footer(text=f"Edited {discord.utils.format_dt(s['time'], 'R')}")
    await ctx.send(embed=e)

@bot.command(name="clearsnipe", aliases=["cs"])
@commands.has_permissions(manage_messages=True)
async def clearsnipe(ctx):
    """Clear all snipe data for this channel."""
    snipe_cache.pop(ctx.channel.id, None)
    esnipe_cache.pop(ctx.channel.id, None)
    await ctx.send(embed=success("Cleared snipe data for this channel."))

@bot.command()
@commands.has_permissions(administrator=True)
async def say(ctx, *, message: str):
    await ctx.message.delete()
    await ctx.send(message)

@bot.command(name="embed")
@commands.has_permissions(administrator=True)
async def make_embed(ctx, *, text: str):
    if "|" in text:
        parts = text.split("|", 1)
        title, desc = parts[0].strip(), parts[1].strip()
    else:
        title, desc = "Announcement", text.strip()
    e = discord.Embed(title=title, description=desc, color=0x5865f2)
    e.set_footer(text=f"Posted by {ctx.author.display_name}")
    await ctx.message.delete()
    await ctx.send(embed=e)

@bot.command()
async def poll(ctx, *, question: str):
    e = discord.Embed(title="📊 Poll", description=question, color=0x5865f2)
    e.set_footer(text=f"Poll by {ctx.author.display_name}")
    msg = await ctx.send(embed=e)
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")
    await msg.add_reaction("🤷")
    await ctx.message.delete()

@bot.command()
async def afk(ctx, *, reason: str = "AFK"):
    key = f"{str(ctx.guild.id)}:{str(ctx.author.id)}"
    afk_data[key] = {"reason": reason, "time": datetime.datetime.utcnow().timestamp()}
    await ctx.send(embed=success(f"💤 {ctx.author.mention} is now AFK: **{reason}**"), delete_after=5)

@bot.command()
@commands.has_permissions(manage_channels=True)
async def nuke(ctx):
    channel   = ctx.channel
    position  = channel.position
    overwrites = channel.overwrites
    topic     = channel.topic
    slowmode  = channel.slowmode_delay
    new = await channel.clone(reason=f"Nuked by {ctx.author}")
    await new.edit(position=position, topic=topic, slowmode_delay=slowmode)
    await channel.delete()
    await new.send(embed=discord.Embed(
        title="💥 Channel Nuked",
        description=f"This channel was nuked by {ctx.author.mention}.",
        color=0xed4245
    ))

# ─────────────────────────────────────────────────────────────────────────────
#  STICKY MESSAGES
# ─────────────────────────────────────────────────────────────────────────────

@bot.command(name="sticky")
@commands.has_permissions(manage_messages=True)
async def sticky_set(ctx, *, content: str):
    cid = str(ctx.channel.id)
    old_id = sticky_data.get(cid, {}).get("message_id")
    if old_id:
        try:
            old_msg = await ctx.channel.fetch_message(int(old_id))
            await old_msg.delete()
        except: pass
    e = discord.Embed(description=content, color=0xfee75c)
    e.set_footer(text="📌 Sticky Message")
    msg = await ctx.channel.send(embed=e)
    sticky_data[cid] = {"content": content, "message_id": str(msg.id)}
    save_data("data/sticky.json", sticky_data)
    await ctx.message.delete()

@bot.command(name="unsticky")
@commands.has_permissions(manage_messages=True)
async def sticky_remove(ctx):
    cid = str(ctx.channel.id)
    if cid not in sticky_data:
        return await ctx.send(embed=info("No sticky message in this channel."))
    old_id = sticky_data[cid].get("message_id")
    if old_id:
        try:
            old_msg = await ctx.channel.fetch_message(int(old_id))
            await old_msg.delete()
        except: pass
    del sticky_data[cid]
    save_data("data/sticky.json", sticky_data)
    await ctx.send(embed=success("📌 Sticky message removed."), delete_after=5)
    await ctx.message.delete()

@bot.command(name="stickies")
async def stickies_list(ctx):
    guild_stickies = [
        (bot.get_channel(int(cid)), v["content"])
        for cid, v in sticky_data.items()
        if bot.get_channel(int(cid)) and bot.get_channel(int(cid)).guild == ctx.guild
    ]
    if not guild_stickies:
        return await ctx.send(embed=info("No sticky messages set in this server."))
    e = discord.Embed(title="📌 Sticky Messages", color=0xfee75c)
    for ch, content in guild_stickies[:10]:
        e.add_field(name=f"#{ch.name}", value=content[:200], inline=False)
    await ctx.send(embed=e)

# ─────────────────────────────────────────────────────────────────────────────
#  VANITY TRACKING
# ─────────────────────────────────────────────────────────────────────────────

@bot.group(name="vanity", invoke_without_command=True)
async def vanity_group(ctx):
    guild_id = str(ctx.guild.id)
    cfg = vanity_cfg.get(guild_id)
    if not cfg:
        return await ctx.send(embed=info("Vanity tracking is not set up. Use `$vanity setup <code> @role`."))
    code    = cfg.get("code", "N/A")
    role_id = cfg.get("role_id")
    role    = ctx.guild.get_role(int(role_id)) if role_id else None

    # Count members who currently have the vanity in their status
    count = 0
    advertisers = []
    for member in ctx.guild.members:
        for act in member.activities:
            hit = False
            if isinstance(act, discord.CustomActivity) and act.name and code.lower() in act.name.lower():
                hit = True
            if not hit and hasattr(act, "state") and act.state and code.lower() in act.state.lower():
                hit = True
            if hit:
                count += 1
                advertisers.append(member)
                break

    e = discord.Embed(title="🔗 Vanity Tracking", color=0x5865f2)
    e.add_field(name="Vanity Code", value=f"`discord.gg/{code}`", inline=True)
    e.add_field(name="Reward Role", value=role.mention if role else "None", inline=True)
    e.add_field(name="Current Advertisers", value=str(count), inline=True)
    if advertisers:
        names = ", ".join(m.display_name for m in advertisers[:15])
        if count > 15: names += f" …+{count-15} more"
        e.add_field(name="Who", value=names, inline=False)
    await ctx.send(embed=e)

@vanity_group.command(name="setup")
@commands.has_permissions(administrator=True)
async def vanity_setup(ctx, code: str, role: discord.Role):
    guild_id = str(ctx.guild.id)
    code = code.replace("discord.gg/", "").strip()
    vanity_cfg[guild_id] = {"code": code, "role_id": str(role.id)}
    save_data("data/vanity.json", vanity_cfg)
    await ctx.send(embed=success(f"✅ Vanity tracking set up! Code: `discord.gg/{code}` → {role.mention}"))

@vanity_group.command(name="remove")
@commands.has_permissions(administrator=True)
async def vanity_remove(ctx):
    guild_id = str(ctx.guild.id)
    if guild_id not in vanity_cfg:
        return await ctx.send(embed=info("Vanity tracking is not configured."))
    del vanity_cfg[guild_id]
    save_data("data/vanity.json", vanity_cfg)
    await ctx.send(embed=success("Vanity tracking disabled."))

@vanity_group.command(name="list")
async def vanity_list(ctx):
    guild_id = str(ctx.guild.id)
    cfg = vanity_cfg.get(guild_id)
    if not cfg:
        return await ctx.send(embed=info("Vanity tracking is not set up."))
    code = cfg.get("code", "").lower()
    advertisers = []
    for member in ctx.guild.members:
        for act in member.activities:
            hit = False
            if isinstance(act, discord.CustomActivity) and act.name and code in act.name.lower():
                hit = True
            if not hit and hasattr(act, "state") and act.state and code in act.state.lower():
                hit = True
            if hit:
                advertisers.append(member)
                break
    if not advertisers:
        return await ctx.send(embed=info("Nobody currently has the vanity in their status."))
    e = discord.Embed(
        title=f"🔗 Vanity Advertisers — discord.gg/{code}",
        description="\n".join(f"{m.mention} — {m.display_name}" for m in advertisers[:25]),
        color=0x5865f2
    )
    if len(advertisers) > 25:
        e.set_footer(text=f"…and {len(advertisers)-25} more")
    await ctx.send(embed=e)

# ─────────────────────────────────────────────────────────────────────────────
#  TEXT FUN
# ─────────────────────────────────────────────────────────────────────────────

@bot.command()
async def clap(ctx, *, text: str):
    await ctx.send(" 👏 ".join(text.split()))

@bot.command()
async def mock(ctx, *, text: str):
    result = "".join(c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(text))
    await ctx.send(result)

@bot.command()
async def reverse(ctx, *, text: str):
    await ctx.send(text[::-1])

@bot.command()
async def emojify(ctx, *, text: str):
    mapping = {c: f":regional_indicator_{c}:" for c in "abcdefghijklmnopqrstuvwxyz"}
    mapping.update({str(i): f"{i}\u20e3" for i in range(10)})
    mapping[" "] = "  "
    result = "".join(mapping.get(c.lower(), c) for c in text)
    if len(result) > 2000:
        return await ctx.send(embed=error("Text too long to emojify!"))
    await ctx.send(result)

@bot.command()
async def upper(ctx, *, text: str):
    await ctx.send(text.upper())

@bot.command()
async def lower(ctx, *, text: str):
    await ctx.send(text.lower())

# ─────────────────────────────────────────────────────────────────────────────
#  SOCIAL / INTERACTION
# ─────────────────────────────────────────────────────────────────────────────

# otakugifs.xyz reaction names (primary GIF source)
_OTAKU_TYPES = {
    "airkiss", "angrystare", "bite", "bleh", "blush", "brofist", "celebrate",
    "cheers", "clap", "confused", "cool", "cry", "cuddle", "dance", "drool",
    "evillaugh", "facepalm", "handhold", "happy", "headbang", "hug", "huh",
    "kiss", "laugh", "lick", "love", "mad", "nervous", "no", "nom", "nosebleed",
    "nuzzle", "nyah", "pat", "peek", "pinch", "poke", "pout", "punch", "roll",
    "run", "sad", "scared", "shout", "shrug", "shy", "sigh", "sing", "sip",
    "slap", "sleep", "slowclap", "smack", "smile", "smug", "sneeze", "sorry",
    "stare", "stop", "surprised", "sweat", "thumbsup", "tickle", "tired",
    "wave", "wink", "woah", "yawn", "yay", "yes",
}
# Map internal names → nearest available otakugifs reaction
_OTAKU_FALLBACK = {
    "bonk":     "slap",
    "highfive": "wave",
    "happy":    "blush",
    "smile":    "blush",
    "think":    "poke",
    "feed":     "nom",
    "glomp":    "hug",
}
# nekos.life SFW types that actually work
_NEKOS_TYPES = {"hug", "pat", "slap", "kiss", "cuddle", "smug"}

async def _get_gif_url(gif_type: str) -> str | None:
    """Fetch a SFW GIF URL — otakugifs.xyz primary, nekos.life fallback."""
    reaction = gif_type if gif_type in _OTAKU_TYPES else _OTAKU_FALLBACK.get(gif_type)
    async with aiohttp.ClientSession() as s:
        # 1. Try otakugifs.xyz
        if reaction:
            try:
                async with s.get(
                    f"https://api.otakugifs.xyz/gif?reaction={reaction}",
                    timeout=aiohttp.ClientTimeout(total=6)
                ) as r:
                    data = await r.json(content_type=None)
                url = data.get("url")
                if url:
                    return url
            except Exception:
                pass
        # 2. Fallback to nekos.life
        nekos_type = gif_type if gif_type in _NEKOS_TYPES else None
        if nekos_type:
            try:
                async with s.get(
                    f"https://nekos.life/api/v2/img/{nekos_type}",
                    timeout=aiohttp.ClientTimeout(total=6)
                ) as r:
                    data = await r.json(content_type=None)
                url = data.get("url")
                if url:
                    return url
            except Exception:
                pass
    return None

async def _social_gif(ctx, member: discord.Member, waifu_type: str,
                      verb: str, emoji: str, color: int):
    """Fetch a SFW GIF and send it as a social action embed."""
    gif_url = await _get_gif_url(waifu_type)
    e = discord.Embed(
        description=f"{emoji} **{ctx.author.display_name}** {verb} **{member.display_name}**!",
        color=color
    )
    if gif_url:
        e.set_image(url=gif_url)
    await ctx.send(embed=e)

@bot.command()
async def hug(ctx, member: discord.Member):
    await _social_gif(ctx, member, "hug", "hugged", "🤗", 0xffb3c6)

@bot.command()
async def pat(ctx, member: discord.Member):
    await _social_gif(ctx, member, "pat", "patted", "🥹", 0xffd6a5)

@bot.command()
async def slap(ctx, member: discord.Member):
    await _social_gif(ctx, member, "slap", "slapped", "👋", 0xed4245)

@bot.command()
async def poke(ctx, member: discord.Member):
    await _social_gif(ctx, member, "poke", "poked", "👉", 0xfee75c)

@bot.command()
async def kiss(ctx, member: discord.Member):
    await _social_gif(ctx, member, "kiss", "kissed", "💋", 0xff79c6)

@bot.command()
async def wave(ctx, member: discord.Member):
    await _social_gif(ctx, member, "wave", "waved at", "👋", 0x57f287)

@bot.command()
async def cuddle(ctx, member: discord.Member):
    await _social_gif(ctx, member, "cuddle", "cuddled with", "🫂", 0xffb3c6)

@bot.command()
async def highfive(ctx, member: discord.Member):
    await _social_gif(ctx, member, "highfive", "high-fived", "🙌", 0x57f287)

@bot.command()
async def bonk(ctx, member: discord.Member):
    await _social_gif(ctx, member, "bonk", "bonked", "🔨", 0xffa500)

@bot.command()
async def bite(ctx, member: discord.Member):
    await _social_gif(ctx, member, "bite", "bit", "😈", 0xed4245)

@bot.command()
async def dance(ctx, member: discord.Member = None):
    if member:
        await _social_gif(ctx, member, "dance", "danced with", "💃", 0xff79c6)
    else:
        gif = await _fetch_gif("dance")
        e = discord.Embed(description=f"💃 **{ctx.author.display_name}** is dancing!", color=0xff79c6)
        if gif: e.set_image(url=gif)
        await ctx.send(embed=e)

@bot.command()
async def cry(ctx):
    gif = await _fetch_gif("cry")
    e = discord.Embed(description=f"😢 **{ctx.author.display_name}** is crying…", color=0x5865f2)
    if gif: e.set_image(url=gif)
    await ctx.send(embed=e)

@bot.command()
async def feed(ctx, member: discord.Member):
    await _social_gif(ctx, member, "nom", "fed", "🍱", 0xffd6a5)

@bot.command()
async def tickle(ctx, member: discord.Member):
    await _social_gif(ctx, member, "cuddle", "tickled", "😹", 0xfee75c)

@bot.command()
async def wink(ctx, member: discord.Member = None):
    gif = await _fetch_gif("wink")
    if member:
        e = discord.Embed(description=f"😉 **{ctx.author.display_name}** winked at **{member.display_name}**!", color=0xfee75c)
    else:
        e = discord.Embed(description=f"😉 **{ctx.author.display_name}** winked!", color=0xfee75c)
    if gif: e.set_image(url=gif)
    await ctx.send(embed=e)

@bot.command()
async def nom(ctx, member: discord.Member):
    await _social_gif(ctx, member, "nom", "nommed", "😋", 0xffd6a5)

@bot.command()
async def glomp(ctx, member: discord.Member):
    await _social_gif(ctx, member, "glomp", "glomped", "💨", 0xffb3c6)

@bot.command()
async def handhold(ctx, member: discord.Member):
    await _social_gif(ctx, member, "handhold", "held hands with", "🤝", 0xff79c6)

@bot.command()
async def blush(ctx):
    gif = await _fetch_gif("blush")
    e = discord.Embed(description=f"😊 **{ctx.author.display_name}** is blushing!", color=0xffb3c6)
    if gif: e.set_image(url=gif)
    await ctx.send(embed=e)

@bot.command()
async def smug(ctx):
    gif = await _fetch_gif("smug")
    e = discord.Embed(description=f"😏 **{ctx.author.display_name}** is feeling smug.", color=0xfee75c)
    if gif: e.set_image(url=gif)
    await ctx.send(embed=e)

# ─────────────────────────────────────────────────────────────────────────────
#  ANIMALS
# ─────────────────────────────────────────────────────────────────────────────

async def _animal_embed(ctx, url: str, label: str, color: int):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=6)) as r:
                data = await r.json(content_type=None)
        if isinstance(data, list):
            img = data[0].get("url")
        elif isinstance(data, dict):
            img = data.get("url") or data.get("image") or data.get("link") or data.get("message")
        else:
            img = None
        if not img:
            raise ValueError("no image url")
        e = discord.Embed(color=color)
        e.set_image(url=img)
        e.set_footer(text=label)
        await ctx.send(embed=e)
    except Exception:
        await ctx.send(embed=error(f"Couldn't fetch a {label} right now. Try again!"))

@bot.command()
async def cat(ctx):
    await _animal_embed(ctx, "https://api.thecatapi.com/v1/images/search", "🐱 Random Cat", 0xffa500)

@bot.command()
async def dog(ctx):
    await _animal_embed(ctx, "https://dog.ceo/api/breeds/image/random", "🐶 Random Dog", 0x8b4513)

@bot.command()
async def fox(ctx):
    await _animal_embed(ctx, "https://randomfox.ca/floof/", "🦊 Random Fox", 0xff6b35)

@bot.command()
async def duck(ctx):
    await _animal_embed(ctx, "https://random-d.uk/api/random", "🦆 Random Duck", 0x57f287)

@bot.command()
async def panda(ctx):
    img = await _reddit_img("panda") or await _reddit_img("pandas")
    if not img:
        return await ctx.send(embed=error("Couldn't fetch a panda right now. Try again!"))
    e = discord.Embed(color=0x2f3136)
    e.set_image(url=img)
    e.set_footer(text="🐼 Random Panda")
    await ctx.send(embed=e)

@bot.command()
async def bird(ctx):
    img = await _reddit_img("birding") or await _reddit_img("birds")
    if not img:
        return await ctx.send(embed=error("Couldn't fetch a bird right now. Try again!"))
    e = discord.Embed(color=0x5865f2)
    e.set_image(url=img)
    e.set_footer(text="🐦 Random Bird")
    await ctx.send(embed=e)

# ─────────────────────────────────────────────────────────────────────────────
#  PROFILE
# ─────────────────────────────────────────────────────────────────────────────

def get_profile(guild_id, user_id):
    k = f"{guild_id}:{user_id}"
    if k not in profile_data:
        profile_data[k] = {"bio": "", "rep": 0, "birthday": "", "last_rep": 0}
    return profile_data[k]

@bot.command()
async def profile(ctx, member: discord.Member = None):
    member = member or ctx.author
    p  = get_profile(str(ctx.guild.id), str(member.id))
    lv = get_level_data(str(ctx.guild.id), str(member.id))
    level, _, _ = xp_progress(lv["xp"])
    bal = get_balance(str(ctx.guild.id), str(member.id))
    married_to = marriages.get(str(ctx.guild.id), {}).get(str(member.id), {}).get("partner")
    partner_str = f"<@{married_to}>" if married_to else "Single"
    e = discord.Embed(color=member.color if member.color.value else 0x5865f2)
    e.set_author(name=f"{member.display_name}'s Profile", icon_url=member.display_avatar.url)
    e.set_thumbnail(url=member.display_avatar.url)
    if p["bio"]:
        e.description = f"*{p['bio']}*"
    e.add_field(name="Level",     value=str(level),                         inline=True)
    e.add_field(name="Balance",   value=f"${bal['wallet']+bal['bank']:,}",   inline=True)
    e.add_field(name="Rep",       value=str(p["rep"]),                       inline=True)
    e.add_field(name="Birthday",  value=p["birthday"] or "Not set",          inline=True)
    e.add_field(name="Partner",   value=partner_str,                         inline=True)
    e.set_footer(text=f"Joined {discord.utils.format_dt(member.joined_at, 'D')}")
    await ctx.send(embed=e)

@bot.command()
async def bio(ctx, *, text: str = ""):
    p = get_profile(str(ctx.guild.id), str(ctx.author.id))
    if len(text) > 150:
        return await ctx.send(embed=error("Bio must be 150 characters or fewer."))
    p["bio"] = text
    save_data("data/profiles.json", profile_data)
    if text:
        await ctx.send(embed=success(f"✅ Bio set to: *{text}*"))
    else:
        await ctx.send(embed=success("Bio cleared."))

@bot.command()
async def rep(ctx, member: discord.Member):
    if member == ctx.author:
        return await ctx.send(embed=error("You can't rep yourself!"))
    giver = get_profile(str(ctx.guild.id), str(ctx.author.id))
    now = datetime.datetime.utcnow().timestamp()
    if now - giver.get("last_rep", 0) < 86400:
        remaining = int(86400 - (now - giver["last_rep"]))
        h, r = divmod(remaining, 3600)
        m, _ = divmod(r, 60)
        return await ctx.send(embed=error(f"You can rep someone again in **{h}h {m}m**."))
    giver["last_rep"] = now
    target = get_profile(str(ctx.guild.id), str(member.id))
    target["rep"] += 1
    save_data("data/profiles.json", profile_data)
    await ctx.send(embed=success(f"⭐ Gave **{member.display_name}** a rep! They now have **{target['rep']} rep**."))

@bot.group(name="birthday", invoke_without_command=True)
async def birthday_group(ctx):
    p = prefixes.get(str(ctx.guild.id), DEFAULT_PREFIX)
    await ctx.send(embed=info(f"Use `{p}birthday set MM/DD` or `{p}birthday check [@user]`"))

@birthday_group.command(name="set")
async def birthday_set(ctx, date: str):
    try:
        dt = datetime.datetime.strptime(date, "%m/%d")
    except ValueError:
        return await ctx.send(embed=error("Use the format `MM/DD` e.g. `04/20`"))
    p = get_profile(str(ctx.guild.id), str(ctx.author.id))
    p["birthday"] = date
    save_data("data/profiles.json", profile_data)
    await ctx.send(embed=success(f"🎂 Birthday set to **{dt.strftime('%B %d')}**!"))

@birthday_group.command(name="check")
async def birthday_check(ctx, member: discord.Member = None):
    member = member or ctx.author
    p = get_profile(str(ctx.guild.id), str(member.id))
    bday = p.get("birthday", "")
    if not bday:
        return await ctx.send(embed=info(f"**{member.display_name}** hasn't set their birthday yet."))
    try:
        dt = datetime.datetime.strptime(bday, "%m/%d")
        formatted = dt.strftime("%B %d")
    except: formatted = bday
    await ctx.send(embed=discord.Embed(description=f"🎂 **{member.display_name}**'s birthday is **{formatted}**", color=0xfee75c))

# ─────────────────────────────────────────────────────────────────────────────
#  EXTRA MODERATION
# ─────────────────────────────────────────────────────────────────────────────

@bot.command()
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=f"Unbanned by {ctx.author}")
        await ctx.send(embed=success(f"✅ **{user}** has been unbanned."))
    except discord.NotFound:
        await ctx.send(embed=error("No ban found for that user ID."))
    except Exception as e_:
        await ctx.send(embed=error(str(e_)))

@bot.command()
@commands.has_permissions(ban_members=True)
async def softban(ctx, member: discord.Member, *, reason="No reason provided"):
    if member.top_role >= ctx.author.top_role:
        return await ctx.send(embed=error("You cannot softban someone with a higher or equal role."))
    await member.ban(reason=f"Softban by {ctx.author}: {reason}", delete_message_days=7)
    await ctx.guild.unban(member, reason="Softban: unban after message wipe")
    await ctx.send(embed=success(f"🔨 **{member}** was softbanned (messages cleared, not permanently banned)."))

@bot.command()
@commands.has_permissions(manage_nicknames=True)
async def nick(ctx, member: discord.Member, *, nickname: str = None):
    try:
        await member.edit(nick=nickname, reason=f"Nick changed by {ctx.author}")
        txt = f"**{member}**'s nickname set to **{nickname}**" if nickname else f"**{member}**'s nickname was reset"
        await ctx.send(embed=success(txt))
    except discord.Forbidden:
        await ctx.send(embed=error("I don't have permission to change that user's nickname."))

@bot.command()
@commands.has_permissions(deafen_members=True)
async def deafen(ctx, member: discord.Member):
    await member.edit(deafen=True, reason=f"Deafened by {ctx.author}")
    await ctx.send(embed=success(f"🔇 **{member.display_name}** has been server-deafened."))

@bot.command()
@commands.has_permissions(deafen_members=True)
async def undeafen(ctx, member: discord.Member):
    await member.edit(deafen=False, reason=f"Undeafened by {ctx.author}")
    await ctx.send(embed=success(f"🔊 **{member.display_name}** has been undeafened."))

@bot.command()
@commands.has_permissions(manage_channels=True)
async def hide(ctx):
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.view_channel = False
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Hidden by {ctx.author}")
    await ctx.send(embed=success("🔒 Channel hidden from @everyone."))

@bot.command()
@commands.has_permissions(manage_channels=True)
async def unhide(ctx):
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.view_channel = True
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Unhidden by {ctx.author}")
    await ctx.send(embed=success("🔓 Channel is now visible to @everyone."))

@bot.command()
@commands.has_permissions(move_members=True)
async def vcmove(ctx, member: discord.Member, channel: discord.VoiceChannel):
    if not member.voice:
        return await ctx.send(embed=error(f"**{member.display_name}** is not in a voice channel."))
    await member.move_to(channel, reason=f"Moved by {ctx.author}")
    await ctx.send(embed=success(f"🔀 Moved **{member.display_name}** to **{channel.name}**."))

# ─────────────────────────────────────────────────────────────────────────────
#  TRIVIA & RANDOM FUN
# ─────────────────────────────────────────────────────────────────────────────

WYR_LIST = [
    "Would you rather be invisible or be able to fly?",
    "Would you rather never eat your favorite food again or only eat your favorite food?",
    "Would you rather always be 10 minutes late or 20 minutes early?",
    "Would you rather have unlimited money or unlimited knowledge?",
    "Would you rather lose your memory or lose your ability to dream?",
    "Would you rather be famous but hated or unknown but loved?",
    "Would you rather speak all languages or play all instruments?",
    "Would you rather live in the past or the future?",
    "Would you rather have a rewind button or a pause button for life?",
    "Would you rather be a superhero with one weak power or a villain with a strong one?",
]
TRUTH_LIST = [
    "What's the most embarrassing thing you've done?",
    "Who was your first crush?",
    "What's a secret you've never told anyone?",
    "What's the worst lie you've ever told?",
    "What's one thing you'd change about yourself?",
    "Have you ever pretended to be sick to skip something?",
    "What's the strangest dream you've had?",
    "What's your biggest fear?",
    "Have you ever cheated on a test?",
    "What's the most childish thing you still do?",
]
DARE_LIST = [
    "Send the last photo in your camera roll (no skipping!).",
    "Type a message to someone using only your elbows.",
    "Do your best impression of a famous person.",
    "Speak in an accent for the next 5 minutes.",
    "Post a selfie with a silly face.",
    "Change your nickname to something embarrassing for 10 minutes.",
    "Say something nice to every member online right now.",
    "React to the last 5 messages with the weirdest emoji.",
    "Write a short poem about the person above you.",
    "Admit your browser history search from today.",
]
NHIE_LIST = [
    "Never have I ever stayed up for 48 hours straight.",
    "Never have I ever lied about my age.",
    "Never have I ever cried at a movie.",
    "Never have I ever eaten food off the floor.",
    "Never have I ever sent a text to the wrong person.",
    "Never have I ever broken a bone.",
    "Never have I ever been in a fist fight.",
    "Never have I ever pretended not to see a message.",
    "Never have I ever skipped school.",
    "Never have I ever won a competition.",
]
ROAST_LIST = [
    "I'd roast you, but my mom said I'm not allowed to burn trash.",
    "You're like a cloud — when you disappear, it's a beautiful day.",
    "I'd call you a tool, but even tools are useful.",
    "You're proof that even evolution makes mistakes.",
    "I'd explain it to you, but I don't have crayons with me.",
    "Your wifi password is probably your only secret.",
    "You have the face of someone who was picked last in gym class.",
    "If laughter is the best medicine, your face must be curing diseases.",
    "Light travels faster than sound. That's why you seemed bright until you spoke.",
]
COMPLIMENT_LIST = [
    "You're like sunshine on a rainy day — absolutely welcome!",
    "The world is genuinely a better place with you in it.",
    "Your smile could light up the darkest room.",
    "You're even better than a retweet from your favorite person.",
    "You bring out the best in everyone around you.",
    "You are one of a kind and irreplaceable.",
    "You have the energy that makes everything feel possible.",
    "If kindness were currency, you'd be a billionaire.",
    "You make hard things look easy and easy things look fun.",
    "Your vibe is immaculate, honestly.",
]
FORTUNE_LIST = [
    "A surprise is waiting for you around the next corner.",
    "The best things in life are yet to come.",
    "Your hard work is about to pay off in a big way.",
    "Someone is thinking of you right now — and smiling.",
    "Good luck follows you wherever you go today.",
    "An unexpected opportunity will knock — be ready to answer.",
    "You will soon discover a talent you didn't know you had.",
    "A small act of kindness today will echo for years.",
    "The stars have aligned in your favor this week.",
    "You are on the right path — keep going.",
]
FACT_LIST = [
    "A group of flamingos is called a flamboyance.",
    "Honey never spoils — archaeologists have found 3,000-year-old honey that's still edible.",
    "A day on Venus is longer than a year on Venus.",
    "Bananas are berries, but strawberries are not.",
    "Cleopatra lived closer in time to the Moon landing than to the Great Pyramid's construction.",
    "The Eiffel Tower grows about 15 cm taller in summer due to thermal expansion.",
    "Octopuses have three hearts and blue blood.",
    "There are more possible iterations of a game of chess than atoms in the observable universe.",
    "A bolt of lightning contains enough energy to toast 100,000 slices of bread.",
    "Sharks are older than trees — they've been around for ~450 million years.",
    "The loudest animal on Earth relative to its size is the water boatman bug.",
    "Crows can recognize human faces and hold grudges.",
]

@bot.command()
async def trivia(ctx):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://opentdb.com/api.php?amount=1&type=multiple", timeout=aiohttp.ClientTimeout(total=8)) as r:
                data = await r.json()
        q   = data["results"][0]
        question = html_mod.unescape(q["question"])
        correct  = html_mod.unescape(q["correct_answer"])
        options  = [html_mod.unescape(x) for x in q["incorrect_answers"]] + [correct]
        random.shuffle(options)
        letters  = ["🇦","🇧","🇨","🇩"][:len(options)]
        correct_emoji = letters[options.index(correct)]
        desc = "\n".join(f"{letters[i]} {options[i]}" for i in range(len(options)))
        e = discord.Embed(title=f"❓ Trivia — {html_mod.unescape(q['category'])}",
                          description=f"{question}\n\n{desc}", color=0x5865f2)
        e.set_footer(text=f"Difficulty: {q['difficulty'].title()} • React with your answer within 15s")
        msg = await ctx.send(embed=e)
        for em in letters: await msg.add_reaction(em)
        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in letters and reaction.message.id == msg.id
        try:
            reaction, _ = await bot.wait_for("reaction_add", timeout=15.0, check=check)
            if str(reaction.emoji) == correct_emoji:
                await ctx.send(embed=success(f"✅ Correct! The answer was **{correct}**"))
            else:
                await ctx.send(embed=error(f"❌ Wrong! It was {correct_emoji} **{correct}**"))
        except asyncio.TimeoutError:
            await ctx.send(embed=error(f"⏰ Time's up! The answer was {correct_emoji} **{correct}**"))
    except Exception:
        await ctx.send(embed=error("Couldn't fetch a trivia question. Try again!"))

async def _fetch_gif(gif_type: str, sfw: bool = True) -> str | None:
    """Return a GIF URL using otakugifs.xyz (SFW) or nekos.life fallback."""
    if sfw:
        return await _get_gif_url(gif_type)
    # NSFW: handled via _nsfw_gif_url
    return await _nsfw_gif_url(gif_type)

@bot.command()
async def wyr(ctx):
    gif = await _fetch_gif("think") or await _fetch_gif("smug")
    e = discord.Embed(title="🤔 Would You Rather…", description=random.choice(WYR_LIST), color=0xfee75c)
    if gif: e.set_image(url=gif)
    await ctx.send(embed=e)

@bot.command()
async def truth(ctx):
    gif = await _fetch_gif("blush")
    e = discord.Embed(title="🔮 Truth", description=random.choice(TRUTH_LIST), color=0x5865f2)
    if gif: e.set_image(url=gif)
    await ctx.send(embed=e)

@bot.command()
async def dare(ctx):
    gif = await _fetch_gif("smug")
    e = discord.Embed(title="😈 Dare", description=random.choice(DARE_LIST), color=0xed4245)
    if gif: e.set_image(url=gif)
    await ctx.send(embed=e)

@bot.command()
async def nhie(ctx):
    gif = await _fetch_gif("happy")
    e = discord.Embed(title="🙋 Never Have I Ever…", description=random.choice(NHIE_LIST), color=0x57f287)
    if gif: e.set_image(url=gif)
    await ctx.send(embed=e)

@bot.command()
async def roast(ctx, member: discord.Member):
    gif = await _fetch_gif("smug")
    e = discord.Embed(description=f"🔥 {member.mention} — {random.choice(ROAST_LIST)}", color=0xed4245)
    e.set_footer(text=f"Served by {ctx.author.display_name}")
    if gif: e.set_image(url=gif)
    await ctx.send(embed=e)

@bot.command()
async def compliment(ctx, member: discord.Member):
    gif = await _fetch_gif("pat")
    e = discord.Embed(description=f"💖 {member.mention} — {random.choice(COMPLIMENT_LIST)}", color=0xff79c6)
    e.set_footer(text=f"From {ctx.author.display_name}")
    if gif: e.set_image(url=gif)
    await ctx.send(embed=e)

@bot.command()
async def fortune(ctx):
    gif = await _fetch_gif("smile")
    e = discord.Embed(title="🥠 Fortune Cookie", description=random.choice(FORTUNE_LIST), color=0xfee75c)
    if gif: e.set_image(url=gif)
    await ctx.send(embed=e)

@bot.command()
async def fact(ctx):
    gif = await _fetch_gif("happy")
    e = discord.Embed(title="🧠 Did You Know?", description=random.choice(FACT_LIST), color=0x5865f2)
    if gif: e.set_image(url=gif)
    await ctx.send(embed=e)

# ─────────────────────────────────────────────────────────────────────────────
#  EXTRA ECONOMY
# ─────────────────────────────────────────────────────────────────────────────

FISH_OUTCOMES = [
    (300,  "🐟 You caught a small fish worth **${amt}**!"),
    (600,  "🐠 You caught a tropical fish worth **${amt}**!"),
    (1200, "🦈 You reeled in a shark and sold it for **${amt}**!"),
    (0,    "🎣 You fished all day but caught nothing."),
    (50,   "🥾 You pulled out an old boot… sold it for **${amt}**."),
]
HUNT_OUTCOMES = [
    (400,  "🦌 You bagged a deer worth **${amt}**!"),
    (800,  "🐗 You took down a wild boar worth **${amt}**!"),
    (50,   "🐇 You scared a rabbit and sold its fur for **${amt}**."),
    (0,    "🌲 Nothing in the forest today. Better luck next time."),
    (1500, "🦁 You somehow hunted a lion! Sold for **${amt}**!"),
]
CRIME_OUTCOMES = [
    (500,   "💼 You stole a briefcase full of cash: **+${amt}**"),
    (1000,  "🏦 You robbed a small bank branch: **+${amt}**"),
    (-300,  "🚔 You got caught! Paid a fine of **${amt}**."),
    (200,   "🧤 You pickpocketed a tourist: **+${amt}**"),
    (-500,  "👮 The cops found you. Fine: **${amt}**."),
]
BEG_OUTCOMES = [
    (20,  "🪙 A kind stranger tossed you **${amt}**."),
    (50,  "💵 Someone felt generous: **${amt}**."),
    (5,   "😐 All you got was **${amt}** in loose coins."),
    (100, "🎩 A rich passerby gave you **${amt}**!"),
    (0,   "🙄 Nobody gave you anything. Skill issue."),
]

def _activity_cmd(outcomes, cooldown_secs, emoji_label):
    async def inner(ctx):
        gid, uid = str(ctx.guild.id), str(ctx.author.id)
        bal  = get_balance(gid, uid)
        econ = economy.get(gid, {}).get(uid, {})
        key  = f"last_{emoji_label}"
        now  = datetime.datetime.utcnow().timestamp()
        last = econ.get(key, 0)
        if now - last < cooldown_secs:
            rem = int(cooldown_secs - (now - last))
            m, s = divmod(rem, 60)
            return await ctx.send(embed=error(f"⏰ Come back in **{m}m {s}s**."))
        amt, msg_tmpl = random.choice(outcomes)
        msg = msg_tmpl.replace("${amt}", f"${abs(amt):,}")
        if gid not in economy: economy[gid] = {}
        if uid not in economy[gid]: economy[gid][uid] = {}
        economy[gid][uid][key] = now
        bal["wallet"] = max(0, bal["wallet"] + amt)
        if gid not in economy: economy[gid] = {}
        if uid not in economy[gid]: economy[gid][uid] = {"wallet": 0, "bank": 0}
        economy[gid][uid]["wallet"] = bal["wallet"]
        economy[gid][uid]["bank"]   = bal["bank"]
        save_economy()
        color = 0x57f287 if amt > 0 else 0xed4245 if amt < 0 else 0xadb5bd
        await ctx.send(embed=discord.Embed(description=msg, color=color))
    return inner

@bot.command()
async def fish(ctx):
    await _activity_cmd(FISH_OUTCOMES, 30, "fish")(ctx)

@bot.command()
async def hunt(ctx):
    await _activity_cmd(HUNT_OUTCOMES, 45, "hunt")(ctx)

@bot.command()
async def crime(ctx):
    await _activity_cmd(CRIME_OUTCOMES, 60, "crime")(ctx)

@bot.command()
async def beg(ctx):
    await _activity_cmd(BEG_OUTCOMES, 20, "beg")(ctx)

# ─────────────────────────────────────────────────────────────────────────────
#  EXTRA TEXT MANIPULATION
# ─────────────────────────────────────────────────────────────────────────────

@bot.group(name="binary", invoke_without_command=True)
async def binary_group(ctx):
    p = prefixes.get(str(ctx.guild.id), DEFAULT_PREFIX)
    await ctx.send(embed=info(f"Use `{p}binary encode <text>` or `{p}binary decode <binary>`"))

@binary_group.command(name="encode")
async def binary_encode(ctx, *, text: str):
    result = " ".join(format(ord(c), "08b") for c in text)
    if len(result) > 1900:
        return await ctx.send(embed=error("Text too long to encode!"))
    await ctx.send(f"```{result}```")

@binary_group.command(name="decode")
async def binary_decode(ctx, *, text: str):
    try:
        chars = [chr(int(b, 2)) for b in text.split()]
        await ctx.send(f"```{''.join(chars)}```")
    except Exception:
        await ctx.send(embed=error("Invalid binary string. Make sure it's space-separated 8-bit groups."))

@bot.command()
async def caesar(ctx, shift: int, *, text: str):
    result = []
    for c in text:
        if c.isalpha():
            base = ord('A') if c.isupper() else ord('a')
            result.append(chr((ord(c) - base + shift) % 26 + base))
        else:
            result.append(c)
    await ctx.send(f"🔐 `{''.join(result)}`")

@bot.command()
async def count(ctx, *, text: str):
    words = len(text.split())
    chars = len(text)
    chars_no_space = len(text.replace(" ", ""))
    e = discord.Embed(title="🔢 Character Count", color=0x5865f2)
    e.add_field(name="Characters",            value=str(chars),          inline=True)
    e.add_field(name="Characters (no spaces)",value=str(chars_no_space), inline=True)
    e.add_field(name="Words",                 value=str(words),          inline=True)
    await ctx.send(embed=e)

@bot.command()
async def spoiler(ctx, *, text: str):
    escaped = text.replace("|", "\\|")
    await ctx.send(f"||{escaped}||")
    await ctx.message.delete()

@bot.command()
async def zalgo(ctx, *, text: str):
    combining = [chr(c) for c in range(0x0300, 0x036F)]
    result = ""
    for char in text:
        result += char
        if char != " ":
            for _ in range(random.randint(2, 6)):
                result += random.choice(combining)
    if len(result) > 2000:
        return await ctx.send(embed=error("Text too long!"))
    await ctx.send(result)

@bot.command()
async def repeat(ctx, times: int, *, text: str):
    if times < 1 or times > 10:
        return await ctx.send(embed=error("Repeat count must be between 1 and 10."))
    result = (text + "\n") * times
    if len(result) > 1900:
        return await ctx.send(embed=error("Result is too long!"))
    await ctx.send(result.strip())

@bot.command()
async def scramble(ctx, *, text: str):
    words = text.split()
    scrambled = []
    for w in words:
        lst = list(w)
        random.shuffle(lst)
        scrambled.append("".join(lst))
    await ctx.send(" ".join(scrambled))

# ─────────────────────────────────────────────────────────────────────────────
#  EXTRA UTILITY
# ─────────────────────────────────────────────────────────────────────────────

@bot.command()
async def uptime(ctx):
    delta = datetime.datetime.utcnow() - bot_start
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s   = divmod(rem, 60)
    d, h   = divmod(h, 24)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    parts.append(f"{m}m {s}s")
    await ctx.send(embed=discord.Embed(description=f"⏱️ Bot has been online for **{' '.join(parts)}**", color=0x57f287))

@bot.command()
async def invite(ctx):
    perms = discord.Permissions(administrator=True)
    url   = discord.utils.oauth_url(bot.user.id, permissions=perms)
    e = discord.Embed(title="📨 Invite Me!", color=0x5865f2)
    e.description = f"[Click here to invite the bot]({url})"
    await ctx.send(embed=e)

@bot.command()
async def membercount(ctx):
    g      = ctx.guild
    total  = g.member_count
    bots   = sum(1 for m in g.members if m.bot)
    humans = total - bots
    e = discord.Embed(title=f"👥 {g.name} — Member Count", color=0x5865f2)
    e.add_field(name="Total",  value=f"{total:,}",  inline=True)
    e.add_field(name="Humans", value=f"{humans:,}", inline=True)
    e.add_field(name="Bots",   value=f"{bots:,}",   inline=True)
    await ctx.send(embed=e)

@bot.command()
async def boosters(ctx):
    boosts = sorted(ctx.guild.premium_subscribers, key=lambda m: m.premium_since)
    if not boosts:
        return await ctx.send(embed=info("This server has no boosters yet."))
    desc = "\n".join(f"{m.mention} — boosting since {discord.utils.format_dt(m.premium_since, 'D')}" for m in boosts[:20])
    if len(boosts) > 20: desc += f"\n…and {len(boosts)-20} more"
    e = discord.Embed(title=f"💎 Server Boosters ({len(boosts)})", description=desc, color=0xff73fa)
    await ctx.send(embed=e)

@bot.command()
async def channelinfo(ctx, channel: discord.TextChannel = None):
    ch = channel or ctx.channel
    e  = discord.Embed(title=f"#{ch.name}", color=0x5865f2)
    e.add_field(name="ID",       value=str(ch.id),        inline=True)
    e.add_field(name="Category", value=ch.category.name if ch.category else "None", inline=True)
    e.add_field(name="Position", value=str(ch.position),  inline=True)
    e.add_field(name="NSFW",     value=str(ch.is_nsfw()),  inline=True)
    e.add_field(name="Slowmode", value=f"{ch.slowmode_delay}s", inline=True)
    e.add_field(name="Created",  value=discord.utils.format_dt(ch.created_at, "R"), inline=True)
    if ch.topic:
        e.add_field(name="Topic", value=ch.topic[:200], inline=False)
    e.set_footer(text=f"Channel ID: {ch.id}")
    await ctx.send(embed=e)

@bot.command()
async def color(ctx, hex_code: str):
    hex_code = hex_code.lstrip("#")
    try:
        r, g, b = int(hex_code[0:2], 16), int(hex_code[2:4], 16), int(hex_code[4:6], 16)
        int_val  = (r << 16) + (g << 8) + b
        e = discord.Embed(title=f"🎨 Color #{hex_code.upper()}", color=int_val)
        e.add_field(name="Hex",   value=f"#{hex_code.upper()}", inline=True)
        e.add_field(name="RGB",   value=f"({r}, {g}, {b})",     inline=True)
        e.add_field(name="Int",   value=str(int_val),           inline=True)
        e.set_thumbnail(url=f"https://singlecolorimage.com/get/{hex_code}/100x100")
        await ctx.send(embed=e)
    except Exception:
        await ctx.send(embed=error("Invalid hex code. Use format `#RRGGBB` or `RRGGBB`."))

@bot.command()
async def vote(ctx):
    e = discord.Embed(title="🗳️ Vote for the Bot", color=0x5865f2)
    e.description = "Voting helps the bot grow! Check top.gg or discordbotlist.com."
    await ctx.send(embed=e)

# ─────────────────────────────────────────────────────────────────────────────
#  NSFW COMMANDS (NSFW channels only)
# ─────────────────────────────────────────────────────────────────────────────

def nsfw_only():
    async def predicate(ctx):
        if not ctx.channel.is_nsfw():
            await ctx.send(embed=error("🔞 This command can only be used in NSFW channels."))
            return False
        return True
    return commands.check(predicate)

# NSFW type → (source, actual_type) mapping using what's reachable
_NSFW_SOURCE_MAP = {
    "spank":    ("nekos", "spank"),
    "lick":     ("otaku", "lick"),
    "blowjob":  ("otaku", "lick"),
    "fuck":     ("otaku", "kiss"),
    "neko":     ("nekos", "neko"),
    "waifu":    ("nekos", "waifu"),
    "pgif":     ("otaku", "wink"),
    "ahegao":   ("otaku", "blush"),
}

async def _nsfw_gif_url(gif_type: str) -> str | None:
    """Fetch a GIF/image for NSFW commands using reachable APIs."""
    source, actual = _NSFW_SOURCE_MAP.get(gif_type, ("otaku", "lick"))
    try:
        async with aiohttp.ClientSession() as s:
            if source == "nekos":
                async with s.get(
                    f"https://nekos.life/api/v2/img/{actual}",
                    timeout=aiohttp.ClientTimeout(total=6)
                ) as r:
                    data = await r.json(content_type=None)
            else:
                async with s.get(
                    f"https://api.otakugifs.xyz/gif?reaction={actual}",
                    timeout=aiohttp.ClientTimeout(total=6)
                ) as r:
                    data = await r.json(content_type=None)
        return data.get("url")
    except Exception:
        return None

async def _nsfw_gif(ctx, member: discord.Member, waifu_type: str,
                   verb: str, emoji: str, color: int):
    gif_url = await _nsfw_gif_url(waifu_type)
    desc = f"{emoji} **{ctx.author.display_name}** {verb} **{member.display_name}**!" if member else f"{emoji} **{ctx.author.display_name}** {verb}!"
    e = discord.Embed(description=desc, color=color)
    if gif_url:
        e.set_image(url=gif_url)
    e.set_footer(text="🔞 NSFW")
    await ctx.send(embed=e)

@bot.command(name="fuck")
@nsfw_only()
async def nsfw_fuck(ctx, member: discord.Member):
    await _nsfw_gif(ctx, member, "fuck", "fucked", "🔥", 0xed4245)

@bot.command(name="spank")
@nsfw_only()
async def nsfw_spank(ctx, member: discord.Member):
    await _nsfw_gif(ctx, member, "spank", "spanked", "🍑", 0xff6b6b)

@bot.command(name="lick")
@nsfw_only()
async def nsfw_lick(ctx, member: discord.Member):
    await _nsfw_gif(ctx, member, "lick", "licked", "👅", 0xff79c6)

@bot.command(name="suck")
@nsfw_only()
async def nsfw_suck(ctx, member: discord.Member):
    await _nsfw_gif(ctx, member, "blowjob", "sucked off", "💦", 0xff9f9f)

@bot.command(name="nsfwneko")
@nsfw_only()
async def nsfw_neko(ctx):
    await _nsfw_gif(ctx, None, "neko", "posted a neko", "🐱", 0xff79c6)

@bot.command(name="nsfwwaifu")
@nsfw_only()
async def nsfw_waifu(ctx):
    await _nsfw_gif(ctx, None, "waifu", "posted a waifu", "💜", 0x9b59b6)

@bot.command(name="ahegao")
@nsfw_only()
async def nsfw_ahegao(ctx):
    await _nsfw_gif(ctx, None, "pgif", "posted an ahegao", "😵", 0xed4245)

# ─────────────────────────────────────────────────────────────────────────────
#  GAMES — ROBLOX
# ─────────────────────────────────────────────────────────────────────────────

async def _roblox_resolve(username: str):
    """Return (userId, displayName, canonicalUsername) or raise ValueError."""
    async with aiohttp.ClientSession() as s:
        async with s.post(
            "https://users.roblox.com/v1/usernames/users",
            json={"usernames": [username], "excludeBannedUsers": False},
            timeout=aiohttp.ClientTimeout(total=8),
        ) as r:
            data = await r.json()
    users = data.get("data", [])
    if not users:
        raise ValueError(f"No Roblox user found for **{username}**.")
    u = users[0]
    return u["id"], u.get("displayName", username), u["name"]

async def _roblox_count(session, url: str) -> int:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as r:
            return (await r.json()).get("count", 0)
    except Exception:
        return 0

async def _roblox_thumbnail(session, user_id: int) -> str | None:
    try:
        url = (
            f"https://thumbnails.roblox.com/v1/users/avatar"
            f"?userIds={user_id}&size=420x420&format=Png&isCircular=false"
        )
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as r:
            data = await r.json()
        items = data.get("data", [])
        return items[0].get("imageUrl") if items else None
    except Exception:
        return None

@bot.command(name="roblox")
async def roblox_cmd(ctx, arg1: str = None, arg2: str = None):
    prefix = get_prefix(bot, ctx.message)
    if arg1 is None:
        e = discord.Embed(
            title="roblox",
            description="Look up a Roblox user's profile or avatar.",
            color=0x5865f2,
        )
        e.add_field(name="Profile", value=f"`{prefix}roblox <username>`", inline=False)
        e.add_field(name="Avatar",  value=f"`{prefix}roblox avatar <username>`", inline=False)
        await ctx.send(embed=e)
        return

    # $roblox avatar <username>
    if arg1.lower() == "avatar":
        if not arg2:
            await ctx.send(embed=error(f"Usage: `{prefix}roblox avatar <username>`"))
            return
        try:
            user_id, display_name, username = await _roblox_resolve(arg2)
        except ValueError as exc:
            await ctx.send(embed=error(str(exc)))
            return
        async with aiohttp.ClientSession() as session:
            thumb = await _roblox_thumbnail(session, user_id)
        e = discord.Embed(color=0x00b2ff)
        e.set_author(name=f"{display_name} (@{username})")
        if thumb:
            e.set_image(url=thumb)
        else:
            e.description = "Could not load avatar image."
        await ctx.send(embed=e)
        return

    # $roblox <username>
    username_query = arg1
    try:
        user_id, display_name, username = await _roblox_resolve(username_query)
    except ValueError as exc:
        await ctx.send(embed=error(str(exc)))
        return

    async with aiohttp.ClientSession() as session:
        friends_url   = f"https://friends.roblox.com/v1/users/{user_id}/friends/count"
        followers_url = f"https://friends.roblox.com/v1/users/{user_id}/followers/count"
        following_url = f"https://friends.roblox.com/v1/users/{user_id}/followings/count"

        friends_count, followers_count, following_count, thumb = await asyncio.gather(
            _roblox_count(session, friends_url),
            _roblox_count(session, followers_url),
            _roblox_count(session, following_url),
            _roblox_thumbnail(session, user_id),
        )

        # user info
        try:
            async with session.get(
                f"https://users.roblox.com/v1/users/{user_id}",
                timeout=aiohttp.ClientTimeout(total=6),
            ) as r:
                info = await r.json()
        except Exception:
            info = {}

        # past usernames
        try:
            async with session.get(
                f"https://users.roblox.com/v1/users/{user_id}/username-history?limit=50",
                timeout=aiohttp.ClientTimeout(total=6),
            ) as r:
                hist = await r.json()
            past_names = [h["name"] for h in hist.get("data", [])]
        except Exception:
            past_names = []

        # groups
        try:
            async with session.get(
                f"https://groups.roblox.com/v1/users/{user_id}/groups/roles",
                timeout=aiohttp.ClientTimeout(total=6),
            ) as r:
                gdata = await r.json()
            groups = [g["group"]["name"] for g in gdata.get("data", [])]
        except Exception:
            groups = []

    description = info.get("description", "").strip() or None
    created_raw = info.get("created", "")
    banned = info.get("isBanned", False)

    # parse created date
    created_str = "Unknown"
    if created_raw:
        try:
            import datetime as _dt
            created_dt = _dt.datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            created_str = created_dt.strftime("%B %-d, %Y")
        except Exception:
            created_str = created_raw[:10]

    e = discord.Embed(color=0x00b2ff)
    e.set_author(name=f"{display_name} (@{username})")
    if description:
        e.description = description
    if thumb:
        e.set_thumbnail(url=thumb)

    e.add_field(name="Created", value=created_str, inline=True)
    if banned:
        e.add_field(name="Status", value="🔨 Banned", inline=True)

    social = (
        f"**Friends:** {friends_count:,}\n"
        f"**Following:** {following_count:,}\n"
        f"**Followers:** {followers_count:,}"
    )
    e.add_field(name="Social", value=social, inline=False)

    if past_names:
        shown = ", ".join(f"`{n}`" for n in past_names[:7])
        extra = f" ...+{len(past_names) - 7} more" if len(past_names) > 7 else ""
        e.add_field(name=f"Past Usernames ({len(past_names)})", value=shown + extra, inline=False)

    if groups:
        shown_g = ", ".join(groups[:6])
        extra_g = f" ...+{len(groups) - 6} more" if len(groups) > 6 else ""
        e.add_field(name=f"Groups ({len(groups)})", value=shown_g + extra_g, inline=False)

    e.set_footer(text=f"Roblox ID: {user_id}")
    await ctx.send(embed=e)

# ─────────────────────────────────────────────────────────────────────────────
#  ERROR HANDLER
# ─────────────────────────────────────────────────────────────────────────────

@bot.event
async def on_command_error(ctx, err):
    if isinstance(err, commands.MissingPermissions):
        perms = ", ".join(p.replace("_", " ").title() for p in err.missing_permissions)
        await ctx.send(embed=error(f"You need the **{perms}** permission to use this command."))
    elif isinstance(err, commands.BotMissingPermissions):
        perms = ", ".join(p.replace("_", " ").title() for p in err.missing_permissions)
        await ctx.send(embed=error(f"I'm missing the **{perms}** permission. Check my role position and permissions."))
    elif isinstance(err, commands.NoPrivateMessage):
        await ctx.send(embed=error("This command can only be used in a server."))
    elif isinstance(err, (commands.MissingRequiredArgument,
                          commands.MemberNotFound,
                          commands.RoleNotFound,
                          commands.ChannelNotFound,
                          commands.BadUnionArgument,
                          commands.BadArgument)):
        cmd_name   = ctx.command.name if ctx.command else (ctx.invoked_with or "?")
        prefix     = get_prefix(bot, ctx.message)
        syntax_str, desc = _CMD_USAGE.get(cmd_name, (cmd_name, "No description available."))
        e = discord.Embed(title=cmd_name, description=desc, color=0x5865f2)
        e.add_field(name="Syntax",  value=f"`{prefix}{syntax_str}`",              inline=False)
        e.add_field(name="Example", value=f"`{_make_example(prefix, syntax_str)}`", inline=False)
        await ctx.send(embed=e)
    elif isinstance(err, commands.CommandOnCooldown):
        await ctx.send(embed=error(f"This command is on cooldown. Try again in **{err.retry_after:.1f}s**."))
    elif isinstance(err, commands.CheckFailure):
        await ctx.send(embed=error("You can't use this command here."))
    elif isinstance(err, commands.CommandInvokeError):
        orig = err.original
        if isinstance(orig, discord.Forbidden):
            await ctx.send(embed=error("I don't have permission to do that. Check my role position and permissions."))
        elif isinstance(orig, discord.HTTPException):
            await ctx.send(embed=error(f"Discord rejected that request: {str(orig)[:200]}"))
        else:
            await ctx.send(embed=error(f"Something went wrong: {str(orig)[:200]}"))
    elif isinstance(err, commands.CommandNotFound):
        pass  # silently ignore unknown commands

# ═════════════════════════════════════════════════════════════════════════════
#  INFORMATION COMMANDS  (greed-equivalent) — registered via _INFO_CMDS list so
#  bot registration and CATEGORIES/website stay perfectly in sync.
# ═════════════════════════════════════════════════════════════════════════════
from urllib.parse import quote as _urlq

_INFO_CMDS = []  # (name, aliases, syntax, desc, callback)

def _info_cmd(name, syntax, desc, aliases=None):
    def deco(fn):
        _INFO_CMDS.append((name, aliases or [], syntax, desc, fn))
        return fn
    return deco

async def _http_json(url, headers=None, timeout=8):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers or {"User-Agent": "FraudBot/1.0"},
                             timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status != 200:
                    return None
                return await r.json(content_type=None)
    except Exception:
        return None

async def _http_text(url, timeout=8):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers={"User-Agent": "FraudBot/1.0"},
                             timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status != 200:
                    return None
                return await r.text()
    except Exception:
        return None

async def _http_bytes(url, timeout=10):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers={"User-Agent": "FraudBot/1.0"},
                             timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status != 200:
                    return None
                return await r.read()
    except Exception:
        return None

def _unix(dt):
    try:
        return int(dt.timestamp())
    except Exception:
        return 0

def _trim(s, n):
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"

# ── Server info ──────────────────────────────────────────────────────────────
@_info_cmd("servericon", "servericon", "Show the server's icon", ["sicon", "guildicon"])
async def _c(ctx):
    if not ctx.guild.icon:
        return await ctx.send(embed=error("This server has no icon."))
    e = discord.Embed(title=f"{ctx.guild.name} — Icon", color=0x5865f2)
    e.set_image(url=ctx.guild.icon.url)
    await ctx.send(embed=e)

@_info_cmd("serverbanner", "serverbanner", "Show the server's banner", ["sbanner"])
async def _c(ctx):
    if not ctx.guild.banner:
        return await ctx.send(embed=error("This server has no banner."))
    e = discord.Embed(title=f"{ctx.guild.name} — Banner", color=0x5865f2)
    e.set_image(url=ctx.guild.banner.url)
    await ctx.send(embed=e)

@_info_cmd("serversplash", "serversplash", "Show the server's invite splash")
async def _c(ctx):
    if not ctx.guild.splash:
        return await ctx.send(embed=error("This server has no invite splash."))
    e = discord.Embed(title=f"{ctx.guild.name} — Splash", color=0x5865f2)
    e.set_image(url=ctx.guild.splash.url)
    await ctx.send(embed=e)

@_info_cmd("serverid", "serverid", "Show the server's ID", ["guildid", "gid"])
async def _c(ctx):
    await ctx.send(embed=info(f"**{ctx.guild.name}** ID: `{ctx.guild.id}`"))

@_info_cmd("servercreated", "servercreated", "When the server was created", ["serverage"])
async def _c(ctx):
    u = _unix(ctx.guild.created_at)
    await ctx.send(embed=info(f"**{ctx.guild.name}** was created <t:{u}:F> (<t:{u}:R>)."))

@_info_cmd("serverowner", "serverowner", "Show the server owner", ["owner"])
async def _c(ctx):
    owner = ctx.guild.owner or await ctx.guild.fetch_member(ctx.guild.owner_id)
    e = discord.Embed(title="👑 Server Owner", color=0xfee75c,
                      description=f"{owner.mention} (`{owner}`)\nID: `{owner.id}`")
    e.set_thumbnail(url=owner.display_avatar.url)
    await ctx.send(embed=e)

@_info_cmd("boosts", "boosts", "Show server boost stats", ["boostcount", "boost"])
async def _c(ctx):
    g = ctx.guild
    e = discord.Embed(title=f"🚀 {g.name} — Boosts", color=0xf47fff)
    e.add_field(name="Boosts", value=str(g.premium_subscription_count))
    e.add_field(name="Tier", value=f"Level {g.premium_tier}")
    e.add_field(name="Boosters", value=str(len(g.premium_subscribers)))
    await ctx.send(embed=e)

@_info_cmd("boostrole", "boostrole", "Show the server's booster role")
async def _c(ctx):
    r = ctx.guild.premium_subscriber_role
    if not r:
        return await ctx.send(embed=info("This server has no booster role."))
    await ctx.send(embed=info(f"Booster role: {r.mention} ({len(r.members)} members)"))

@_info_cmd("roles", "roles", "List all server roles", ["rolelist"])
async def _c(ctx):
    rs = [r.mention for r in reversed(ctx.guild.roles) if r.name != "@everyone"]
    if not rs:
        return await ctx.send(embed=info("No roles."))
    await ctx.send(embed=info(f"**{len(rs)} Roles**\n" + _trim(" ".join(rs), 3900)))

@_info_cmd("rolecount", "rolecount", "Number of roles in the server")
async def _c(ctx):
    await ctx.send(embed=info(f"This server has **{len(ctx.guild.roles) - 1}** roles."))

@_info_cmd("emojis", "emojis", "List the server's custom emojis", ["emojilist"])
async def _c(ctx):
    es = ctx.guild.emojis
    if not es:
        return await ctx.send(embed=info("This server has no custom emojis."))
    await ctx.send(embed=info(f"**{len(es)} Emojis**\n" + _trim(" ".join(str(e) for e in es), 3900)))

@_info_cmd("emojicount", "emojicount", "Number of custom emojis")
async def _c(ctx):
    await ctx.send(embed=info(f"This server has **{len(ctx.guild.emojis)}** custom emojis."))

@_info_cmd("stickers", "stickers", "List the server's stickers")
async def _c(ctx):
    ss = ctx.guild.stickers
    if not ss:
        return await ctx.send(embed=info("This server has no stickers."))
    await ctx.send(embed=info(f"**{len(ss)} Stickers**\n" + _trim(", ".join(s.name for s in ss), 3900)))

@_info_cmd("stickercount", "stickercount", "Number of stickers")
async def _c(ctx):
    await ctx.send(embed=info(f"This server has **{len(ctx.guild.stickers)}** stickers."))

@_info_cmd("channelcount", "channelcount", "Channel count breakdown")
async def _c(ctx):
    g = ctx.guild
    e = discord.Embed(title=f"📚 {g.name} — Channels", color=0x5865f2)
    e.add_field(name="💬 Text", value=str(len(g.text_channels)))
    e.add_field(name="🔊 Voice", value=str(len(g.voice_channels)))
    e.add_field(name="📁 Categories", value=str(len(g.categories)))
    await ctx.send(embed=e)

@_info_cmd("categories", "categories", "List channel categories")
async def _c(ctx):
    cs = ctx.guild.categories
    if not cs:
        return await ctx.send(embed=info("No categories."))
    await ctx.send(embed=info("**Categories**\n" + _trim("\n".join(c.name for c in cs), 3900)))

@_info_cmd("voicechannels", "voicechannels", "List voice channels", ["vcs"])
async def _c(ctx):
    vs = ctx.guild.voice_channels
    if not vs:
        return await ctx.send(embed=info("No voice channels."))
    await ctx.send(embed=info("**Voice Channels**\n" + _trim("\n".join(v.name for v in vs), 3900)))

@_info_cmd("textchannels", "textchannels", "List text channels")
async def _c(ctx):
    ts = ctx.guild.text_channels
    await ctx.send(embed=info("**Text Channels**\n" + _trim("\n".join(t.mention for t in ts), 3900)))

@_info_cmd("verificationlevel", "verificationlevel", "Server verification level", ["verification"])
async def _c(ctx):
    await ctx.send(embed=info(f"Verification level: **{str(ctx.guild.verification_level).title()}**"))

@_info_cmd("serverfeatures", "serverfeatures", "List the server's feature flags")
async def _c(ctx):
    f = ctx.guild.features
    if not f:
        return await ctx.send(embed=info("This server has no special features."))
    await ctx.send(embed=info("**Features**\n" + ", ".join(x.replace("_", " ").title() for x in f)))

@_info_cmd("vanityurl", "vanityurl", "Show the server's vanity invite", ["vanitycode"])
async def _c(ctx):
    code = ctx.guild.vanity_url_code
    if not code:
        return await ctx.send(embed=info("This server has no vanity URL."))
    await ctx.send(embed=info(f"Vanity URL: `discord.gg/{code}`"))

@_info_cmd("afkinfo", "afkinfo", "Show the server's AFK channel & timeout")
async def _c(ctx):
    ch = ctx.guild.afk_channel
    if not ch:
        return await ctx.send(embed=info("This server has no AFK channel set."))
    await ctx.send(embed=info(f"AFK channel: **{ch.name}** — timeout: {ctx.guild.afk_timeout // 60} min"))

@_info_cmd("bots", "bots", "List bots in the server")
async def _c(ctx):
    bs = [m.mention for m in ctx.guild.members if m.bot]
    if not bs:
        return await ctx.send(embed=info("No bots found (members may not be cached)."))
    await ctx.send(embed=info(f"**{len(bs)} Bots**\n" + _trim(" ".join(bs), 3900)))

@_info_cmd("humancount", "humancount", "Number of human members", ["humans"])
async def _c(ctx):
    n = sum(1 for m in ctx.guild.members if not m.bot)
    await ctx.send(embed=info(f"**{n}** humans in this server."))

@_info_cmd("botcount", "botcount", "Number of bot members")
async def _c(ctx):
    n = sum(1 for m in ctx.guild.members if m.bot)
    await ctx.send(embed=info(f"**{n}** bots in this server."))

@_info_cmd("newmembers", "newmembers", "10 most recently joined members")
async def _c(ctx):
    ms = sorted([m for m in ctx.guild.members if m.joined_at], key=lambda m: m.joined_at, reverse=True)[:10]
    lines = [f"{i+1}. {m} — joined <t:{_unix(m.joined_at)}:R>" for i, m in enumerate(ms)]
    await ctx.send(embed=info("**🆕 Newest Members**\n" + "\n".join(lines)))

@_info_cmd("oldmembers", "oldmembers", "10 earliest members to join")
async def _c(ctx):
    ms = sorted([m for m in ctx.guild.members if m.joined_at], key=lambda m: m.joined_at)[:10]
    lines = [f"{i+1}. {m} — joined <t:{_unix(m.joined_at)}:R>" for i, m in enumerate(ms)]
    await ctx.send(embed=info("**🏛️ Oldest Members**\n" + "\n".join(lines)))

@_info_cmd("admins", "admins", "List server administrators")
async def _c(ctx):
    a = [m.mention for m in ctx.guild.members if not m.bot and m.guild_permissions.administrator]
    if not a:
        return await ctx.send(embed=info("No administrators found."))
    await ctx.send(embed=info(f"**{len(a)} Administrators**\n" + _trim(" ".join(a), 3900)))

@_info_cmd("members", "members", "Total member count")
async def _c(ctx):
    await ctx.send(embed=info(f"**{ctx.guild.name}** has **{ctx.guild.member_count:,}** members."))

@_info_cmd("serverstats", "serverstats", "Quick server stats overview", ["sstats"])
async def _c(ctx):
    g = ctx.guild
    e = discord.Embed(title=f"📊 {g.name} — Stats", color=0x5865f2)
    e.add_field(name="Members", value=f"{g.member_count:,}")
    e.add_field(name="Roles", value=str(len(g.roles) - 1))
    e.add_field(name="Channels", value=str(len(g.channels)))
    e.add_field(name="Emojis", value=str(len(g.emojis)))
    e.add_field(name="Boosts", value=str(g.premium_subscription_count))
    e.add_field(name="Created", value=f"<t:{_unix(g.created_at)}:R>")
    if g.icon:
        e.set_thumbnail(url=g.icon.url)
    await ctx.send(embed=e)

# ── User info ────────────────────────────────────────────────────────────────
@_info_cmd("banner", "banner [@user]", "Show a user's profile banner")
async def _c(ctx, member: discord.Member = None):
    member = member or ctx.author
    u = await bot.fetch_user(member.id)
    if not u.banner:
        return await ctx.send(embed=error(f"{member.display_name} has no banner."))
    e = discord.Embed(title=f"{member.display_name} — Banner", color=member.color)
    e.set_image(url=u.banner.url)
    await ctx.send(embed=e)

@_info_cmd("serveravatar", "serveravatar [@user]", "Show a user's server-specific avatar", ["guildavatar"])
async def _c(ctx, member: discord.Member = None):
    member = member or ctx.author
    if not member.guild_avatar:
        return await ctx.send(embed=error(f"{member.display_name} has no server avatar."))
    e = discord.Embed(title=f"{member.display_name} — Server Avatar", color=member.color)
    e.set_image(url=member.guild_avatar.url)
    await ctx.send(embed=e)

@_info_cmd("userid", "userid [@user]", "Show a user's ID", ["uid"])
async def _c(ctx, member: discord.Member = None):
    member = member or ctx.author
    await ctx.send(embed=info(f"{member.mention} ID: `{member.id}`"))

@_info_cmd("accountage", "accountage [@user]", "When a user's account was created", ["created"])
async def _c(ctx, member: discord.Member = None):
    member = member or ctx.author
    u = _unix(member.created_at)
    await ctx.send(embed=info(f"{member.mention}'s account was created <t:{u}:F> (<t:{u}:R>)."))

@_info_cmd("joindate", "joindate [@user]", "When a user joined this server", ["joined"])
async def _c(ctx, member: discord.Member = None):
    member = member or ctx.author
    u = _unix(member.joined_at)
    await ctx.send(embed=info(f"{member.mention} joined <t:{u}:F> (<t:{u}:R>)."))

@_info_cmd("joinposition", "joinposition [@user]", "A user's join position in the server", ["joinpos"])
async def _c(ctx, member: discord.Member = None):
    member = member or ctx.author
    ordered = sorted([m for m in ctx.guild.members if m.joined_at], key=lambda m: m.joined_at)
    pos = ordered.index(member) + 1
    await ctx.send(embed=info(f"{member.mention} was member **#{pos}** to join."))

@_info_cmd("nickname", "nickname [@user]", "Show a user's nickname")
async def _c(ctx, member: discord.Member = None):
    member = member or ctx.author
    await ctx.send(embed=info(f"{member.mention}'s nickname: **{member.nick or 'None'}**"))

@_info_cmd("userroles", "userroles [@user]", "List a user's roles")
async def _c(ctx, member: discord.Member = None):
    member = member or ctx.author
    rs = [r.mention for r in reversed(member.roles) if r.name != "@everyone"]
    await ctx.send(embed=info(f"**{member.display_name} — {len(rs)} Roles**\n" + (_trim(" ".join(rs), 3900) or "None")))

@_info_cmd("toprole", "toprole [@user]", "Show a user's highest role")
async def _c(ctx, member: discord.Member = None):
    member = member or ctx.author
    await ctx.send(embed=info(f"{member.mention}'s top role: {member.top_role.mention}"))

@_info_cmd("permissions", "permissions [@user]", "List a user's permissions", ["perms"])
async def _c(ctx, member: discord.Member = None):
    member = member or ctx.author
    ps = [p.replace("_", " ").title() for p, v in member.guild_permissions if v]
    await ctx.send(embed=info(f"**{member.display_name} — Permissions**\n" + _trim(", ".join(ps), 3900)))

@_info_cmd("usercolor", "usercolor [@user]", "Show a user's display color")
async def _c(ctx, member: discord.Member = None):
    member = member or ctx.author
    await ctx.send(embed=info(f"{member.mention}'s color: `{str(member.color)}`"))

@_info_cmd("badges", "badges [@user]", "Show a user's Discord badges")
async def _c(ctx, member: discord.Member = None):
    member = member or ctx.author
    flags = [f.name.replace("_", " ").title() for f in member.public_flags.all()]
    await ctx.send(embed=info(f"{member.mention}'s badges: " + (", ".join(flags) if flags else "None")))

@_info_cmd("isbot", "isbot [@user]", "Check whether a user is a bot")
async def _c(ctx, member: discord.Member = None):
    member = member or ctx.author
    await ctx.send(embed=info(f"{member.mention} is **{'a bot 🤖' if member.bot else 'a human 👤'}**."))

@_info_cmd("boostsince", "boostsince [@user]", "When a user started boosting")
async def _c(ctx, member: discord.Member = None):
    member = member or ctx.author
    if not member.premium_since:
        return await ctx.send(embed=info(f"{member.mention} is not boosting this server."))
    await ctx.send(embed=info(f"{member.mention} has boosted since <t:{_unix(member.premium_since)}:R>."))

# ── Role info ────────────────────────────────────────────────────────────────
@_info_cmd("rolemembers", "rolemembers <@role>", "List members with a role", ["inrole"])
async def _c(ctx, role: discord.Role):
    ms = [m.mention for m in role.members]
    if not ms:
        return await ctx.send(embed=info(f"No members have {role.mention}."))
    await ctx.send(embed=info(f"**{role.name} — {len(ms)} Members**\n" + _trim(" ".join(ms), 3900)))

@_info_cmd("rolecolor", "rolecolor <@role>", "Show a role's color")
async def _c(ctx, role: discord.Role):
    await ctx.send(embed=info(f"{role.mention}'s color: `{str(role.color)}`"))

@_info_cmd("roleid", "roleid <@role>", "Show a role's ID")
async def _c(ctx, role: discord.Role):
    await ctx.send(embed=info(f"{role.mention} ID: `{role.id}`"))

@_info_cmd("rolecreated", "rolecreated <@role>", "When a role was created")
async def _c(ctx, role: discord.Role):
    await ctx.send(embed=info(f"{role.mention} was created <t:{_unix(role.created_at)}:R>."))

@_info_cmd("roleperms", "roleperms <@role>", "List a role's permissions")
async def _c(ctx, role: discord.Role):
    ps = [p.replace("_", " ").title() for p, v in role.permissions if v]
    await ctx.send(embed=info(f"**{role.name} — Permissions**\n" + (_trim(", ".join(ps), 3900) or "None")))

@_info_cmd("roleposition", "roleposition <@role>", "Show a role's position")
async def _c(ctx, role: discord.Role):
    await ctx.send(embed=info(f"{role.mention} is at position **{role.position}**."))

# ── Channel info ─────────────────────────────────────────────────────────────
@_info_cmd("channelid", "channelid [#channel]", "Show a channel's ID")
async def _c(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await ctx.send(embed=info(f"{channel.mention} ID: `{channel.id}`"))

@_info_cmd("channeltopic", "channeltopic [#channel]", "Show a channel's topic")
async def _c(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await ctx.send(embed=info(f"**{channel.name} — Topic**\n{channel.topic or 'No topic set.'}"))

@_info_cmd("channelcreated", "channelcreated [#channel]", "When a channel was created")
async def _c(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await ctx.send(embed=info(f"{channel.mention} was created <t:{_unix(channel.created_at)}:R>."))

@_info_cmd("slowmodeinfo", "slowmodeinfo [#channel]", "Show a channel's slowmode delay")
async def _c(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    d = channel.slowmode_delay
    await ctx.send(embed=info(f"{channel.mention} slowmode: **{d}s**" if d else f"{channel.mention} has no slowmode."))

# ── Bot / meta info ──────────────────────────────────────────────────────────
@_info_cmd("shards", "shards", "Show the bot's shard count")
async def _c(ctx):
    await ctx.send(embed=info(f"Shard count: **{bot.shard_count or 1}**"))

@_info_cmd("latency", "latency", "Show the bot's gateway latency")
async def _c(ctx):
    await ctx.send(embed=info(f"🏓 Gateway latency: **{round(bot.latency * 1000)}ms**"))

@_info_cmd("commandcount", "commandcount", "How many commands the bot has", ["cmdcount"])
async def _c(ctx):
    await ctx.send(embed=info(f"I have **{len(bot.commands)}** commands."))

@_info_cmd("servercount", "servercount", "How many servers the bot is in", ["guildcount"])
async def _c(ctx):
    await ctx.send(embed=info(f"I'm in **{len(bot.guilds)}** servers."))

@_info_cmd("usercount", "usercount", "Total users the bot can see")
async def _c(ctx):
    await ctx.send(embed=info(f"I can see **{sum(g.member_count for g in bot.guilds):,}** users."))

@_info_cmd("support", "support", "Get the bot's support info")
async def _c(ctx):
    await ctx.send(embed=info("Need help? Use `$help` to browse commands, or visit the website for the full command list."))

@_info_cmd("botperms", "botperms", "Show the bot's permissions here")
async def _c(ctx):
    ps = [p.replace("_", " ").title() for p, v in ctx.guild.me.guild_permissions if v]
    await ctx.send(embed=info("**My Permissions**\n" + _trim(", ".join(ps), 3900)))

# ── External info APIs (no key required) ─────────────────────────────────────
@_info_cmd("weather", "weather <city>", "Current weather for a city")
async def _c(ctx, *, city: str):
    d = await _http_json(f"https://wttr.in/{_urlq(city)}?format=j1")
    if not d or "current_condition" not in d:
        return await ctx.send(embed=error("Couldn't fetch weather for that location."))
    cc = d["current_condition"][0]
    area = d["nearest_area"][0]
    loc = f"{area['areaName'][0]['value']}, {area['country'][0]['value']}"
    e = discord.Embed(title=f"🌤️ Weather — {loc}", color=0x5865f2,
                      description=cc["weatherDesc"][0]["value"])
    e.add_field(name="Temp", value=f"{cc['temp_C']}°C / {cc['temp_F']}°F")
    e.add_field(name="Feels Like", value=f"{cc['FeelsLikeC']}°C")
    e.add_field(name="Humidity", value=f"{cc['humidity']}%")
    e.add_field(name="Wind", value=f"{cc['windspeedKmph']} km/h")
    await ctx.send(embed=e)

@_info_cmd("github", "github <user>", "Show a GitHub user's profile", ["gh"])
async def _c(ctx, user: str):
    d = await _http_json(f"https://api.github.com/users/{_urlq(user)}")
    if not d or d.get("message") == "Not Found":
        return await ctx.send(embed=error("GitHub user not found."))
    e = discord.Embed(title=d.get("login"), url=d.get("html_url"),
                      description=d.get("bio") or "", color=0x24292e)
    e.set_thumbnail(url=d.get("avatar_url"))
    e.add_field(name="Repos", value=str(d.get("public_repos", 0)))
    e.add_field(name="Followers", value=str(d.get("followers", 0)))
    e.add_field(name="Following", value=str(d.get("following", 0)))
    await ctx.send(embed=e)

@_info_cmd("urban", "urban <term>", "Look up a term on Urban Dictionary", ["ud"])
async def _c(ctx, *, term: str):
    d = await _http_json(f"https://api.urbandictionary.com/v0/define?term={_urlq(term)}")
    if not d or not d.get("list"):
        return await ctx.send(embed=error("No definition found."))
    top = d["list"][0]
    e = discord.Embed(title=f"📖 {top['word']}", url=top.get("permalink"), color=0x1d2439,
                      description=_trim(top["definition"].replace("[", "").replace("]", ""), 1500))
    if top.get("example"):
        e.add_field(name="Example", value=_trim(top["example"].replace("[", "").replace("]", ""), 1000), inline=False)
    e.add_field(name="👍", value=str(top.get("thumbs_up", 0)))
    e.add_field(name="👎", value=str(top.get("thumbs_down", 0)))
    await ctx.send(embed=e)

@_info_cmd("define", "define <word>", "Dictionary definition of a word", ["dict"])
async def _c(ctx, word: str):
    d = await _http_json(f"https://api.dictionaryapi.dev/api/v2/entries/en/{_urlq(word)}")
    if not d or not isinstance(d, list):
        return await ctx.send(embed=error("Word not found."))
    entry = d[0]
    e = discord.Embed(title=f"📚 {entry['word']}", color=0x5865f2)
    for meaning in entry.get("meanings", [])[:3]:
        defs = meaning.get("definitions", [])
        if defs:
            e.add_field(name=meaning.get("partOfSpeech", "—"),
                        value=_trim(defs[0]["definition"], 1000), inline=False)
    await ctx.send(embed=e)

@_info_cmd("wikipedia", "wikipedia <query>", "Search Wikipedia", ["wiki"])
async def _c(ctx, *, query: str):
    d = await _http_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{_urlq(query)}")
    if not d or d.get("type") == "https://mediawiki.org/wiki/HyperSwitch/errors/not_found":
        return await ctx.send(embed=error("No Wikipedia article found."))
    e = discord.Embed(title=d.get("title"),
                      url=d.get("content_urls", {}).get("desktop", {}).get("page"),
                      description=_trim(d.get("extract", ""), 2000), color=0xffffff)
    if d.get("thumbnail"):
        e.set_thumbnail(url=d["thumbnail"]["source"])
    await ctx.send(embed=e)

@_info_cmd("crypto", "crypto <coin>", "Current price of a cryptocurrency", ["coinprice"])
async def _c(ctx, coin: str):
    cid = coin.lower()
    d = await _http_json(f"https://api.coingecko.com/api/v3/simple/price?ids={_urlq(cid)}&vs_currencies=usd&include_24hr_change=true")
    if not d or cid not in d:
        return await ctx.send(embed=error("Coin not found. Use the full id, e.g. `bitcoin`, `ethereum`."))
    price = d[cid]["usd"]
    chg = d[cid].get("usd_24h_change", 0)
    arrow = "📈" if chg >= 0 else "📉"
    await ctx.send(embed=info(f"**{coin.title()}**: ${price:,} {arrow} {chg:+.2f}% (24h)"))

@_info_cmd("time", "time <timezone>", "Current time in a timezone (e.g. Europe/London)")
async def _c(ctx, *, tz: str):
    d = await _http_json(f"https://worldtimeapi.org/api/timezone/{_urlq(tz.strip())}")
    if not d or "datetime" not in d:
        return await ctx.send(embed=error("Unknown timezone. Example: `Europe/London`, `America/New_York`."))
    dt = d["datetime"][:19].replace("T", " ")
    await ctx.send(embed=info(f"🕐 **{d['timezone']}**\n{dt} (UTC{d['utc_offset']})"))

@_info_cmd("country", "country <name>", "Info about a country")
async def _c(ctx, *, name: str):
    d = await _http_json(f"https://restcountries.com/v3.1/name/{_urlq(name)}")
    if not d or not isinstance(d, list):
        return await ctx.send(embed=error("Country not found."))
    c = d[0]
    e = discord.Embed(title=f"{c['flag']} {c['name']['common']}", color=0x57f287)
    e.add_field(name="Capital", value=", ".join(c.get("capital", ["—"])))
    e.add_field(name="Region", value=c.get("region", "—"))
    e.add_field(name="Population", value=f"{c.get('population', 0):,}")
    await ctx.send(embed=e)

@_info_cmd("npm", "npm <package>", "Look up an npm package")
async def _c(ctx, pkg: str):
    d = await _http_json(f"https://registry.npmjs.org/{_urlq(pkg)}")
    if not d or "dist-tags" not in d:
        return await ctx.send(embed=error("npm package not found."))
    latest = d["dist-tags"]["latest"]
    e = discord.Embed(title=f"📦 {pkg}", url=f"https://www.npmjs.com/package/{pkg}",
                      description=_trim(d.get("description", ""), 1000), color=0xcb3837)
    e.add_field(name="Latest", value=latest)
    await ctx.send(embed=e)

@_info_cmd("pypi", "pypi <package>", "Look up a PyPI package")
async def _c(ctx, pkg: str):
    d = await _http_json(f"https://pypi.org/pypi/{_urlq(pkg)}/json")
    if not d or "info" not in d:
        return await ctx.send(embed=error("PyPI package not found."))
    inf = d["info"]
    e = discord.Embed(title=f"🐍 {inf['name']} {inf['version']}", url=inf.get("project_url"),
                      description=_trim(inf.get("summary", ""), 1000), color=0x3776ab)
    if inf.get("author"):
        e.add_field(name="Author", value=inf["author"])
    await ctx.send(embed=e)

@_info_cmd("quote", "quote", "Get a random inspirational quote")
async def _c(ctx):
    d = await _http_json("https://api.quotable.io/random")
    if not d or "content" not in d:
        return await ctx.send(embed=error("Couldn't fetch a quote right now."))
    await ctx.send(embed=info(f"*\"{d['content']}\"*\n— **{d['author']}**"))

@_info_cmd("advice", "advice", "Get a random piece of advice")
async def _c(ctx):
    d = await _http_json("https://api.adviceslip.com/advice")
    if not d or "slip" not in d:
        return await ctx.send(embed=error("Couldn't fetch advice right now."))
    await ctx.send(embed=info(f"💡 {d['slip']['advice']}"))

@_info_cmd("catfact", "catfact", "Get a random cat fact")
async def _c(ctx):
    d = await _http_json("https://catfact.ninja/fact")
    if not d or "fact" not in d:
        return await ctx.send(embed=error("Couldn't fetch a cat fact right now."))
    await ctx.send(embed=info(f"🐱 {d['fact']}"))

@_info_cmd("dogfact", "dogfact", "Get a random dog fact")
async def _c(ctx):
    d = await _http_json("https://dog-api.kinduff.com/api/facts")
    if not d or not d.get("facts"):
        return await ctx.send(embed=error("Couldn't fetch a dog fact right now."))
    await ctx.send(embed=info(f"🐶 {d['facts'][0]}"))

@_info_cmd("numberfact", "numberfact <number>", "Get a fact about a number", ["numfact"])
async def _c(ctx, number: int):
    t = await _http_text(f"http://numbersapi.com/{number}")
    if not t:
        return await ctx.send(embed=error("Couldn't fetch a number fact right now."))
    await ctx.send(embed=info(f"🔢 {t}"))

@_info_cmd("chucknorris", "chucknorris", "Random Chuck Norris fact", ["chuck"])
async def _c(ctx):
    d = await _http_json("https://api.chucknorris.io/jokes/random")
    if not d or "value" not in d:
        return await ctx.send(embed=error("Couldn't fetch a fact right now."))
    await ctx.send(embed=info(f"🥋 {d['value']}"))

@_info_cmd("pokemon", "pokemon <name>", "Look up a Pokémon", ["pokedex"])
async def _c(ctx, name: str):
    d = await _http_json(f"https://pokeapi.co/api/v2/pokemon/{_urlq(name.lower())}")
    if not d or "id" not in d:
        return await ctx.send(embed=error("Pokémon not found."))
    types = ", ".join(t["type"]["name"].title() for t in d["types"])
    e = discord.Embed(title=f"#{d['id']} {d['name'].title()}", color=0xffcb05)
    e.add_field(name="Type", value=types)
    e.add_field(name="Height", value=f"{d['height'] / 10} m")
    e.add_field(name="Weight", value=f"{d['weight'] / 10} kg")
    sprite = d.get("sprites", {}).get("front_default")
    if sprite:
        e.set_thumbnail(url=sprite)
    await ctx.send(embed=e)

@_info_cmd("randomuser", "randomuser", "Generate a random fake user")
async def _c(ctx):
    d = await _http_json("https://randomuser.me/api/")
    if not d or not d.get("results"):
        return await ctx.send(embed=error("Couldn't generate a user right now."))
    u = d["results"][0]
    nm = u["name"]
    e = discord.Embed(title=f"{nm['title']} {nm['first']} {nm['last']}", color=0x5865f2)
    e.add_field(name="Email", value=u["email"], inline=False)
    e.add_field(name="Location", value=f"{u['location']['city']}, {u['location']['country']}")
    e.set_thumbnail(url=u["picture"]["large"])
    await ctx.send(embed=e)

@_info_cmd("ipinfo", "ipinfo <ip>", "Look up info for a public IP address", ["iplookup"])
async def _c(ctx, ip: str):
    d = await _http_json(f"http://ip-api.com/json/{_urlq(ip)}")
    if not d or d.get("status") != "success":
        return await ctx.send(embed=error("Couldn't look up that IP."))
    e = discord.Embed(title=f"🌐 {d['query']}", color=0x5865f2)
    e.add_field(name="Country", value=d.get("country", "—"))
    e.add_field(name="City", value=d.get("city", "—"))
    e.add_field(name="ISP", value=d.get("isp", "—"), inline=False)
    await ctx.send(embed=e)

# Register all Information commands and mirror into CATEGORIES (website source).
for _n, _al, _sx, _ds, _fn in _INFO_CMDS:
    if bot.get_command(_n):
        continue
    bot.add_command(commands.Command(_fn, name=_n, aliases=_al))
    CATEGORIES["info"]["commands"].append((_sx, _ds))

# ═════════════════════════════════════════════════════════════════════════════
#  UTILITY COMMANDS  (greed-equivalent) — registered via _UTIL_CMDS list.
# ═════════════════════════════════════════════════════════════════════════════
import hashlib as _hashlib
import base64 as _b64
import uuid as _uuid
import secrets as _secrets
import string as _string
import ast as _ast
import operator as _op

_UTIL_CMDS = []

def _util_cmd(name, syntax, desc, aliases=None):
    def deco(fn):
        _UTIL_CMDS.append((name, aliases or [], syntax, desc, fn))
        return fn
    return deco

_MATH_OPS = {
    _ast.Add: _op.add, _ast.Sub: _op.sub, _ast.Mult: _op.mul, _ast.Div: _op.truediv,
    _ast.Pow: _op.pow, _ast.Mod: _op.mod, _ast.FloorDiv: _op.floordiv,
    _ast.USub: _op.neg, _ast.UAdd: _op.pos,
}

def _safe_math(expr):
    if len(expr) > 100:
        raise ValueError("expression too long")
    def ev(node):
        if isinstance(node, _ast.Constant) and isinstance(node.value, (int, float)):
            if abs(node.value) > 1e15:
                raise ValueError("number too large")
            return node.value
        if isinstance(node, _ast.BinOp):
            if type(node.op) not in _MATH_OPS:
                raise ValueError("unsupported operator")
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, _ast.Pow):
                if abs(left) > 1000 or abs(right) > 100:
                    raise ValueError("exponent out of range")
            return _MATH_OPS[type(node.op)](left, right)
        if isinstance(node, _ast.UnaryOp):
            if type(node.op) not in _MATH_OPS:
                raise ValueError("unsupported operator")
            return _MATH_OPS[type(node.op)](ev(node.operand))
        raise ValueError("unsupported")
    return ev(_ast.parse(expr, mode="eval").body)

_MORSE = {
    'a': '.-', 'b': '-...', 'c': '-.-.', 'd': '-..', 'e': '.', 'f': '..-.', 'g': '--.',
    'h': '....', 'i': '..', 'j': '.---', 'k': '-.-', 'l': '.-..', 'm': '--', 'n': '-.',
    'o': '---', 'p': '.--.', 'q': '--.-', 'r': '.-.', 's': '...', 't': '-', 'u': '..-',
    'v': '...-', 'w': '.--', 'x': '-..-', 'y': '-.--', 'z': '--..', '0': '-----',
    '1': '.----', '2': '..---', '3': '...--', '4': '....-', '5': '.....', '6': '-....',
    '7': '--...', '8': '---..', '9': '----.', ' ': '/',
}
_UNMORSE = {v: k for k, v in _MORSE.items()}

_FLIP = str.maketrans(
    "abcdefghijklmnopqrstuvwxyz0123456789",
    "ɐqɔpǝɟƃɥᴉɾʞlɯuodbɹsʇnʌʍxʎz0ƖᄅƐㄣϛ9ㄥ86",
)
_LEET = str.maketrans("aeiotsbgl", "43107$69|")
_FW = {c: chr(ord(c) + 0xFEE0) for c in _string.ascii_letters + _string.digits}

def _roman(n):
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
            (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out

def _unroman(s):
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for ch in reversed(s.upper()):
        v = vals.get(ch, 0)
        total += -v if v < prev else v
        prev = max(prev, v)
    return total

def _words(text):
    return text.split()

def _parse_seconds(s):
    m = re.fullmatch(r"(\d+)\s*([smhd])", s.strip().lower())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]

def _emoji_parts(text):
    m = re.match(r"<(a?):(\w+):(\d+)>", text.strip())
    if not m:
        return None
    animated, name, eid = m.group(1) == "a", m.group(2), m.group(3)
    ext = "gif" if animated else "png"
    return name, eid, f"https://cdn.discordapp.com/emojis/{eid}.{ext}"

# ── Encoding / hashing ───────────────────────────────────────────────────────
@_util_cmd("base64encode", "base64encode <text>", "Encode text to Base64", ["b64encode", "b64e"])
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(f"```{_b64.b64encode(text.encode()).decode()}```"))

@_util_cmd("base64decode", "base64decode <text>", "Decode Base64 text", ["b64decode", "b64d"])
async def _c(ctx, *, text: str):
    try:
        out = _b64.b64decode(text.encode()).decode("utf-8", "replace")
    except Exception:
        return await ctx.send(embed=error("Invalid Base64."))
    await ctx.send(embed=info(f"```{_trim(out, 1900)}```"))

@_util_cmd("base32encode", "base32encode <text>", "Encode text to Base32", ["b32encode"])
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(f"```{_b64.b32encode(text.encode()).decode()}```"))

@_util_cmd("base32decode", "base32decode <text>", "Decode Base32 text", ["b32decode"])
async def _c(ctx, *, text: str):
    try:
        out = _b64.b32decode(text.strip().encode()).decode("utf-8", "replace")
    except Exception:
        return await ctx.send(embed=error("Invalid Base32."))
    await ctx.send(embed=info(f"```{_trim(out, 1900)}```"))

@_util_cmd("hexencode", "hexencode <text>", "Encode text to hexadecimal", ["tohexstr"])
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(f"```{text.encode().hex()}```"))

@_util_cmd("hexdecode", "hexdecode <hex>", "Decode hexadecimal to text")
async def _c(ctx, *, hexstr: str):
    try:
        out = bytes.fromhex(hexstr.replace(" ", "")).decode("utf-8", "replace")
    except Exception:
        return await ctx.send(embed=error("Invalid hex."))
    await ctx.send(embed=info(f"```{_trim(out, 1900)}```"))

@_util_cmd("urlencode", "urlencode <text>", "URL-encode text")
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(f"```{_urlq(text)}```"))

@_util_cmd("urldecode", "urldecode <text>", "URL-decode text")
async def _c(ctx, *, text: str):
    from urllib.parse import unquote as _uq
    await ctx.send(embed=info(f"```{_trim(_uq(text), 1900)}```"))

@_util_cmd("rot13", "rot13 <text>", "ROT13-cipher text")
async def _c(ctx, *, text: str):
    import codecs
    await ctx.send(embed=info(f"```{codecs.encode(text, 'rot_13')}```"))

@_util_cmd("atbash", "atbash <text>", "Atbash-cipher text")
async def _c(ctx, *, text: str):
    tbl = str.maketrans(_string.ascii_lowercase + _string.ascii_uppercase,
                        _string.ascii_lowercase[::-1] + _string.ascii_uppercase[::-1])
    await ctx.send(embed=info(f"```{text.translate(tbl)}```"))

@_util_cmd("md5", "md5 <text>", "MD5 hash of text")
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(f"```{_hashlib.md5(text.encode()).hexdigest()}```"))

@_util_cmd("sha1", "sha1 <text>", "SHA-1 hash of text")
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(f"```{_hashlib.sha1(text.encode()).hexdigest()}```"))

@_util_cmd("sha256", "sha256 <text>", "SHA-256 hash of text")
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(f"```{_hashlib.sha256(text.encode()).hexdigest()}```"))

@_util_cmd("hash", "hash <text>", "SHA-256 hash of text (alias of sha256)")
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(f"```{_hashlib.sha256(text.encode()).hexdigest()}```"))

# ── Text transforms ──────────────────────────────────────────────────────────
@_util_cmd("morse", "morse <text>", "Encode text to Morse code")
async def _c(ctx, *, text: str):
    out = " ".join(_MORSE.get(c, "?") for c in text.lower())
    await ctx.send(embed=info(f"```{_trim(out, 1900)}```"))

@_util_cmd("unmorse", "unmorse <code>", "Decode Morse code to text")
async def _c(ctx, *, code: str):
    out = "".join(_UNMORSE.get(tok, "?") for tok in code.split(" "))
    await ctx.send(embed=info(f"```{_trim(out, 1900)}```"))

@_util_cmd("upsidedown", "upsidedown <text>", "Flip text upside-down")
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(text.lower().translate(_FLIP)[::-1]))

@_util_cmd("fullwidth", "fullwidth <text>", "Convert text to ｆｕｌｌｗｉｄｔｈ", ["vaporwavetext"])
async def _c(ctx, *, text: str):
    await ctx.send(embed=info("".join(_FW.get(c, c) for c in text)))

@_util_cmd("leetspeak", "leetspeak <text>", "Convert text to l33t5p34k", ["leet"])
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(text.lower().translate(_LEET)))

@_util_cmd("owoify", "owoify <text>", "OwO-ify text", ["owo", "uwu"])
async def _c(ctx, *, text: str):
    out = re.sub(r"[rl]", "w", re.sub(r"[RL]", "W", text))
    out = out.replace("na", "nya").replace("Na", "Nya")
    await ctx.send(embed=info(out + " owo"))

@_util_cmd("aesthetic", "aesthetic <text>", "Spaced-out ａ ｅ ｓ ｔ ｈ ｅ ｔ ｉ ｃ text")
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(" ".join(_FW.get(c, c) for c in text)))

@_util_cmd("slugify", "slugify <text>", "Turn text into a url-slug")
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(f"`{re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')}`"))

@_util_cmd("titlecase", "titlecase <text>", "Convert text To Title Case")
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(text.title()))

@_util_cmd("snakecase", "snakecase <text>", "convert_text_to_snake_case", ["snake"])
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(f"`{'_'.join(_words(text.lower()))}`"))

@_util_cmd("camelcase", "camelcase <text>", "convertTextToCamelCase", ["camel"])
async def _c(ctx, *, text: str):
    w = _words(text.lower())
    out = (w[0] + "".join(x.capitalize() for x in w[1:])) if w else ""
    await ctx.send(embed=info(f"`{out}`"))

@_util_cmd("kebabcase", "kebabcase <text>", "convert-text-to-kebab-case", ["kebab"])
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(f"`{'-'.join(_words(text.lower()))}`"))

@_util_cmd("wc", "wc <text>", "Count words, characters and lines", ["wordcount"])
async def _c(ctx, *, text: str):
    e = discord.Embed(title="🔢 Count", color=0x5865f2)
    e.add_field(name="Characters", value=str(len(text)))
    e.add_field(name="Words", value=str(len(_words(text))))
    e.add_field(name="Lines", value=str(len(text.splitlines()) or 1))
    await ctx.send(embed=e)

@_util_cmd("ascii", "ascii <text>", "Show character codes for text")
async def _c(ctx, *, text: str):
    await ctx.send(embed=info(f"```{_trim(' '.join(str(ord(c)) for c in text), 1900)}```"))

# ── Numbers / math ───────────────────────────────────────────────────────────
@_util_cmd("math", "math <expression>", "Evaluate a math expression", ["calc", "calculate"])
async def _c(ctx, *, expression: str):
    try:
        await ctx.send(embed=info(f"`{expression}` = **{_safe_math(expression)}**"))
    except Exception:
        await ctx.send(embed=error("Invalid expression. Use + - * / ** % //."))

@_util_cmd("roman", "roman <number>", "Convert a number to Roman numerals")
async def _c(ctx, number: int):
    if not (0 < number < 4000):
        return await ctx.send(embed=error("Number must be 1–3999."))
    await ctx.send(embed=info(f"**{number}** = `{_roman(number)}`"))

@_util_cmd("unroman", "unroman <roman>", "Convert Roman numerals to a number")
async def _c(ctx, roman: str):
    await ctx.send(embed=info(f"`{roman.upper()}` = **{_unroman(roman)}**"))

@_util_cmd("tobinary", "tobinary <number>", "Convert a number to binary", ["bin"])
async def _c(ctx, number: int):
    await ctx.send(embed=info(f"**{number}** = `{bin(number)[2:]}`"))

@_util_cmd("frombinary", "frombinary <bits>", "Convert binary to a number")
async def _c(ctx, bits: str):
    try:
        await ctx.send(embed=info(f"`{bits}` = **{int(bits, 2)}**"))
    except ValueError:
        await ctx.send(embed=error("Invalid binary."))

@_util_cmd("tohex", "tohex <number>", "Convert a number to hexadecimal")
async def _c(ctx, number: int):
    await ctx.send(embed=info(f"**{number}** = `{hex(number)[2:]}`"))

@_util_cmd("fromhex", "fromhex <hex>", "Convert hexadecimal to a number")
async def _c(ctx, hexstr: str):
    try:
        await ctx.send(embed=info(f"`{hexstr}` = **{int(hexstr, 16)}**"))
    except ValueError:
        await ctx.send(embed=error("Invalid hex."))

@_util_cmd("tooctal", "tooctal <number>", "Convert a number to octal")
async def _c(ctx, number: int):
    await ctx.send(embed=info(f"**{number}** = `{oct(number)[2:]}`"))

@_util_cmd("factorial", "factorial <n>", "Calculate n!")
async def _c(ctx, n: int):
    if not (0 <= n <= 1000):
        return await ctx.send(embed=error("n must be 0–1000."))
    import math as _m
    await ctx.send(embed=info(f"**{n}!** = {_trim(str(_m.factorial(n)), 1900)}"))

@_util_cmd("fibonacci", "fibonacci <n>", "Show the first n Fibonacci numbers", ["fib"])
async def _c(ctx, n: int):
    if not (1 <= n <= 50):
        return await ctx.send(embed=error("n must be 1–50."))
    a, b, seq = 0, 1, []
    for _ in range(n):
        seq.append(a)
        a, b = b, a + b
    await ctx.send(embed=info(", ".join(map(str, seq))))

@_util_cmd("isprime", "isprime <n>", "Check whether a number is prime")
async def _c(ctx, n: int):
    prime = n > 1 and all(n % i for i in range(2, int(n ** 0.5) + 1))
    await ctx.send(embed=info(f"**{n}** is {'a prime ✅' if prime else 'not prime ❌'}."))

@_util_cmd("gcd", "gcd <a> <b>", "Greatest common divisor of two numbers")
async def _c(ctx, a: int, b: int):
    import math as _m
    await ctx.send(embed=info(f"gcd({a}, {b}) = **{_m.gcd(a, b)}**"))

@_util_cmd("lcm", "lcm <a> <b>", "Least common multiple of two numbers")
async def _c(ctx, a: int, b: int):
    import math as _m
    await ctx.send(embed=info(f"lcm({a}, {b}) = **{abs(a * b) // _m.gcd(a, b) if a and b else 0}**"))

@_util_cmd("average", "average <numbers...>", "Average of a list of numbers", ["mean", "avg"])
async def _c(ctx, *numbers: float):
    if not numbers:
        return await ctx.send(embed=error("Give me some numbers."))
    await ctx.send(embed=info(f"Average = **{sum(numbers) / len(numbers):.4g}**"))

@_util_cmd("sumof", "sumof <numbers...>", "Sum of a list of numbers", ["total"])
async def _c(ctx, *numbers: float):
    await ctx.send(embed=info(f"Sum = **{sum(numbers):.4g}**"))

@_util_cmd("temp", "temp <value> <c/f>", "Convert temperature between °C and °F")
async def _c(ctx, value: float, unit: str):
    u = unit.lower().lstrip("°")
    if u == "c":
        await ctx.send(embed=info(f"{value}°C = **{value * 9 / 5 + 32:.1f}°F**"))
    elif u == "f":
        await ctx.send(embed=info(f"{value}°F = **{(value - 32) * 5 / 9:.1f}°C**"))
    else:
        await ctx.send(embed=error("Unit must be `c` or `f`."))

# ── Colors ───────────────────────────────────────────────────────────────────
@_util_cmd("hextorgb", "hextorgb <hex>", "Convert a hex color to RGB")
async def _c(ctx, hexcode: str):
    h = hexcode.lstrip("#")
    if len(h) != 6:
        return await ctx.send(embed=error("Use a 6-digit hex like `#5865f2`."))
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return await ctx.send(embed=error("Invalid hex."))
    await ctx.send(embed=info(f"`#{h}` → `rgb({r}, {g}, {b})`"))

@_util_cmd("rgbtohex", "rgbtohex <r> <g> <b>", "Convert RGB to a hex color")
async def _c(ctx, r: int, g: int, b: int):
    if not all(0 <= v <= 255 for v in (r, g, b)):
        return await ctx.send(embed=error("Each value must be 0–255."))
    await ctx.send(embed=info(f"`rgb({r}, {g}, {b})` → `#{r:02x}{g:02x}{b:02x}`"))

@_util_cmd("randomcolor", "randomcolor", "Generate a random color", ["randcolor"])
async def _c(ctx):
    val = random.randint(0, 0xFFFFFF)
    e = discord.Embed(title=f"#{val:06x}", color=val,
                      description=f"`rgb({val >> 16 & 255}, {val >> 8 & 255}, {val & 255})`")
    await ctx.send(embed=e)

# ── Generators ───────────────────────────────────────────────────────────────
@_util_cmd("password", "password [length]", "Generate a secure random password", ["pass", "genpass"])
async def _c(ctx, length: int = 16):
    length = max(6, min(64, length))
    alphabet = _string.ascii_letters + _string.digits + "!@#$%^&*"
    pw = "".join(_secrets.choice(alphabet) for _ in range(length))
    try:
        await ctx.author.send(embed=info(f"🔐 Your password:\n```{pw}```"))
        await ctx.send(embed=success("Sent your new password in DMs."))
    except discord.Forbidden:
        await ctx.send(embed=error("I couldn't DM you — enable DMs and try again."))

@_util_cmd("uuid", "uuid", "Generate a random UUID")
async def _c(ctx):
    await ctx.send(embed=info(f"`{_uuid.uuid4()}`"))

@_util_cmd("token", "token [length]", "Generate a random secure token")
async def _c(ctx, length: int = 24):
    length = max(8, min(128, length))
    await ctx.send(embed=info(f"```{_secrets.token_urlsafe(length)[:length]}```"))

@_util_cmd("rng", "rng <min> <max>", "Random number in a range", ["random"])
async def _c(ctx, low: int, high: int):
    if low > high:
        low, high = high, low
    await ctx.send(embed=info(f"🎲 **{random.randint(low, high)}** ({low}–{high})"))

@_util_cmd("dice", "dice <NdM>", "Roll dice, e.g. 2d6", ["diceroll"])
async def _c(ctx, notation: str = "1d6"):
    m = re.fullmatch(r"(\d{1,3})d(\d{1,4})", notation.lower())
    if not m:
        return await ctx.send(embed=error("Use NdM format, e.g. `2d6`."))
    n, sides = int(m.group(1)), int(m.group(2))
    if not (1 <= n <= 100 and 2 <= sides <= 1000):
        return await ctx.send(embed=error("Up to 100 dice, 2–1000 sides."))
    rolls = [random.randint(1, sides) for _ in range(n)]
    await ctx.send(embed=info(f"🎲 {notation}: {', '.join(map(str, rolls))}\n**Total: {sum(rolls)}**"))

@_util_cmd("coin", "coin", "Flip a coin", ["flipcoin"])
async def _c(ctx):
    await ctx.send(embed=info(f"🪙 **{random.choice(['Heads', 'Tails'])}**"))

@_util_cmd("lorem", "lorem [paragraphs]", "Generate placeholder text")
async def _c(ctx, paragraphs: int = 1):
    base = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod "
            "tempor incididunt ut labore et dolore magna aliqua ut enim ad minim veniam").split()
    paragraphs = max(1, min(5, paragraphs))
    out = "\n\n".join(" ".join(random.choice(base) for _ in range(40)).capitalize() + "."
                      for _ in range(paragraphs))
    await ctx.send(embed=info(_trim(out, 3900)))

@_util_cmd("randomemoji", "randomemoji", "Get a random emoji")
async def _c(ctx):
    emojis = "😀😎🤖👻🔥💎🚀🎉🌈🦄🍕🎮⚡🌙☄️🐉🎲🧩🎯🪄"
    await ctx.send(embed=info(random.choice(emojis)))

@_util_cmd("randomname", "randomname", "Generate a random name")
async def _c(ctx):
    first = ["Alex", "Sam", "Jordan", "Casey", "Riley", "Max", "Skylar", "Quinn", "Avery", "Rowan"]
    last = ["Stone", "Frost", "Vale", "Knox", "Reed", "Hale", "Cross", "Bishop", "Wolfe", "Kane"]
    await ctx.send(embed=info(f"🪪 **{random.choice(first)} {random.choice(last)}**"))

# ── Discord / time ───────────────────────────────────────────────────────────
@_util_cmd("timestamp", "timestamp [unix]", "Show Discord timestamp formats")
async def _c(ctx, unix: int = None):
    u = unix if unix is not None else int(datetime.datetime.utcnow().timestamp())
    fmts = "\n".join(f"`<t:{u}:{f}>` → <t:{u}:{f}>" for f in "tTdDfFR")
    await ctx.send(embed=info(fmts))

@_util_cmd("snowflake", "snowflake <id>", "Decode a Discord ID's creation date", ["snowstamp"])
async def _c(ctx, snowflake_id: int):
    ms = (snowflake_id >> 22) + 1420070400000
    await ctx.send(embed=info(f"`{snowflake_id}` was created <t:{ms // 1000}:F> (<t:{ms // 1000}:R>)."))

@_util_cmd("unixtime", "unixtime", "Show the current Unix timestamp", ["epoch"])
async def _c(ctx):
    await ctx.send(embed=info(f"Current Unix time: `{int(datetime.datetime.utcnow().timestamp())}`"))

@_util_cmd("now", "now", "Show the current UTC time")
async def _c(ctx):
    u = int(datetime.datetime.utcnow().timestamp())
    await ctx.send(embed=info(f"🕐 <t:{u}:F>"))

# ── Emoji / channel tools ────────────────────────────────────────────────────
@_util_cmd("enlarge", "enlarge <emoji>", "Show a custom emoji at full size", ["jumbo", "bigemoji"])
async def _c(ctx, emoji: str):
    parts = _emoji_parts(emoji)
    if not parts:
        return await ctx.send(embed=error("Give me a custom emoji."))
    name, _eid, url = parts
    e = discord.Embed(title=name, color=0x5865f2)
    e.set_image(url=url)
    await ctx.send(embed=e)

@_util_cmd("emojiurl", "emojiurl <emoji>", "Get the image URL of a custom emoji")
async def _c(ctx, emoji: str):
    parts = _emoji_parts(emoji)
    if not parts:
        return await ctx.send(embed=error("Give me a custom emoji."))
    await ctx.send(embed=info(parts[2]))

@_util_cmd("steal", "steal <emoji> [name]", "🔒 Add a custom emoji to this server")
async def _c(ctx, emoji: str, name: str = None):
    if not ctx.author.guild_permissions.manage_emojis:
        return await ctx.send(embed=error("You need **Manage Emojis** permission."))
    parts = _emoji_parts(emoji)
    if not parts:
        return await ctx.send(embed=error("Give me a custom emoji to steal."))
    ename, _eid, url = parts
    data = await _http_bytes(url)
    if not data:
        return await ctx.send(embed=error("Couldn't download that emoji."))
    try:
        new = await ctx.guild.create_custom_emoji(name=name or ename, image=data)
    except discord.HTTPException:
        return await ctx.send(embed=error("Failed to add the emoji (maybe the server is full)."))
    await ctx.send(embed=success(f"Added {new} as `:{new.name}:`"))

@_util_cmd("firstmessage", "firstmessage", "Link to the first message in this channel", ["firstmsg"])
async def _c(ctx):
    async for msg in ctx.channel.history(limit=1, oldest_first=True):
        return await ctx.send(embed=info(f"[Jump to the first message]({msg.jump_url}) by {msg.author.mention}"))
    await ctx.send(embed=error("No messages found."))

@_util_cmd("cleanup", "cleanup [amount]", "🔒 Delete the bot's recent messages")
async def _c(ctx, amount: int = 20):
    if not ctx.author.guild_permissions.manage_messages:
        return await ctx.send(embed=error("You need **Manage Messages** permission."))
    amount = max(1, min(100, amount))
    deleted = await ctx.channel.purge(limit=amount, check=lambda m: m.author == ctx.me)
    await ctx.send(embed=success(f"Cleaned up {len(deleted)} of my messages."), delete_after=4)

# ── Reminders ────────────────────────────────────────────────────────────────
_REMINDERS = defaultdict(list)

_MAX_REMINDERS_PER_USER = 10

@_util_cmd("remind", "remind <time> <text>", "Set a reminder, e.g. 10m take a break", ["remindme"])
async def _c(ctx, when: str, *, text: str):
    secs = _parse_seconds(when)
    if not secs or secs > 86400:
        return await ctx.send(embed=error("Use a time like `30s`, `10m`, `2h`, `1d` (max 1 day)."))
    if len(_REMINDERS[ctx.author.id]) >= _MAX_REMINDERS_PER_USER:
        return await ctx.send(embed=error(f"You already have {_MAX_REMINDERS_PER_USER} pending reminders."))
    text = _trim(text, 500)
    _REMINDERS[ctx.author.id].append(text)
    await ctx.send(embed=success(f"Okay! I'll remind you in {when}."))

    async def _fire():
        await asyncio.sleep(secs)
        try:
            await ctx.reply(embed=info(f"⏰ Reminder: {text}"))
        except Exception:
            pass
        if text in _REMINDERS[ctx.author.id]:
            _REMINDERS[ctx.author.id].remove(text)
    asyncio.create_task(_fire())

@_util_cmd("reminders", "reminders", "List your pending reminders")
async def _c(ctx):
    rs = _REMINDERS.get(ctx.author.id, [])
    if not rs:
        return await ctx.send(embed=info("You have no pending reminders."))
    await ctx.send(embed=info(_trim("**Your reminders:**\n" + "\n".join(f"• {r}" for r in rs), 3900)))

# ── Network utilities (no key required) ──────────────────────────────────────
@_util_cmd("qr", "qr <text>", "Generate a QR code", ["qrcode"])
async def _c(ctx, *, text: str):
    url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={_urlq(text)}"
    e = discord.Embed(title="QR Code", color=0x5865f2)
    e.set_image(url=url)
    await ctx.send(embed=e)

@_util_cmd("shorten", "shorten <url>", "Shorten a URL", ["shorturl"])
async def _c(ctx, url: str):
    if not url.startswith(("http://", "https://")):
        return await ctx.send(embed=error("Give me a full URL starting with http(s)://"))
    out = await _http_text(f"https://is.gd/create.php?format=simple&url={_urlq(url)}")
    if not out or not out.startswith("http"):
        return await ctx.send(embed=error("Couldn't shorten that URL."))
    await ctx.send(embed=info(f"🔗 {out}"))

@_util_cmd("dadjoke", "dadjoke", "Get a random dad joke")
async def _c(ctx):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://icanhazdadjoke.com/",
                             headers={"Accept": "application/json", "User-Agent": "FraudBot"},
                             timeout=aiohttp.ClientTimeout(total=8)) as r:
                d = await r.json(content_type=None)
    except Exception:
        d = None
    if not d or "joke" not in d:
        return await ctx.send(embed=error("Couldn't fetch a joke right now."))
    await ctx.send(embed=info(f"😄 {d['joke']}"))

@_util_cmd("yesno", "yesno [question]", "Let fate decide yes or no")
async def _c(ctx, *, question: str = None):
    d = await _http_json("https://yesno.wtf/api")
    if not d or "answer" not in d:
        return await ctx.send(embed=info(f"🎱 **{random.choice(['Yes', 'No', 'Maybe'])}**"))
    e = discord.Embed(title=d["answer"].upper(), color=0x5865f2)
    e.set_image(url=d["image"])
    await ctx.send(embed=e)

@_util_cmd("vigenere", "vigenere <key> <text>", "Vigenère-cipher text with a key")
async def _c(ctx, key: str, *, text: str):
    key = "".join(c for c in key.lower() if c.isalpha())
    if not key:
        return await ctx.send(embed=error("Key must contain letters."))
    out, ki = [], 0
    for ch in text:
        if ch.isalpha():
            base = ord("A") if ch.isupper() else ord("a")
            shift = ord(key[ki % len(key)]) - ord("a")
            out.append(chr((ord(ch) - base + shift) % 26 + base))
            ki += 1
        else:
            out.append(ch)
    await ctx.send(embed=info(f"```{_trim(''.join(out), 1900)}```"))

# Register all Utility commands and mirror into CATEGORIES (website source).
for _n, _al, _sx, _ds, _fn in _UTIL_CMDS:
    if bot.get_command(_n):
        continue
    bot.add_command(commands.Command(_fn, name=_n, aliases=_al))
    CATEGORIES["utility"]["commands"].append((_sx, _ds))

# ═════════════════════════════════════════════════════════════════════════════
#  MASS-GENERATED COMMANDS  —  Manipulation (avatar filters) + Reactions (GIFs)
# ═════════════════════════════════════════════════════════════════════════════
import io as _io
from PIL import Image as _PImage, ImageOps as _POps, ImageFilter as _PFilter, ImageEnhance as _PEnh

_AVATAR_SIZE = 512


async def _fetch_avatar_bytes(target) -> bytes | None:
    try:
        asset = target.display_avatar.replace(size=_AVATAR_SIZE, format="png", static_format="png")
        return await asset.read()
    except Exception:
        try:
            return await target.display_avatar.read()
        except Exception:
            return None


def _colorize(im, black, white):
    g = _POps.grayscale(im)
    return _POps.colorize(g, black=black, white=white).convert("RGBA")


def _tint(im, rf, gf, bf):
    rgb = im.convert("RGB")
    r, g, b = rgb.split()
    r = r.point(lambda v: min(255, int(v * rf)))
    g = g.point(lambda v: min(255, int(v * gf)))
    b = b.point(lambda v: min(255, int(v * bf)))
    return _PImage.merge("RGB", (r, g, b)).convert("RGBA")


def _pixelate(im, blocks):
    small = im.resize((blocks, blocks), _PImage.NEAREST)
    return small.resize(im.size, _PImage.NEAREST)


def _enh(im, kind, factor):
    rgb = im.convert("RGB")
    enhancer = {
        "color": _PEnh.Color, "contrast": _PEnh.Contrast,
        "bright": _PEnh.Brightness, "sharp": _PEnh.Sharpness,
    }[kind](rgb)
    return enhancer.enhance(factor).convert("RGBA")


def _deepfry(im):
    rgb = im.convert("RGB")
    rgb = _PEnh.Color(rgb).enhance(4.0)
    rgb = _PEnh.Contrast(rgb).enhance(2.6)
    rgb = _PEnh.Sharpness(rgb).enhance(6.0)
    rgb = _PEnh.Brightness(rgb).enhance(1.1)
    return rgb.convert("RGBA")


def _sketch(im):
    g = _POps.grayscale(im)
    edges = g.filter(_PFilter.FIND_EDGES)
    return _POps.invert(edges).convert("RGBA")


def _f_rotate(im, deg):
    return im.rotate(deg, expand=True)


# name -> (function, description)
MANIP_FILTERS = {
    "grayscale":   (lambda im: _POps.grayscale(im).convert("RGBA"),            "Grayscale an avatar"),
    "greyscale":   (lambda im: _POps.grayscale(im).convert("RGBA"),            "Grayscale an avatar (alias)"),
    "invert":      (lambda im: _POps.invert(im.convert("RGB")).convert("RGBA"),"Invert avatar colors"),
    "negative":    (lambda im: _POps.invert(im.convert("RGB")).convert("RGBA"),"Negative (inverted) avatar"),
    "sepia":       (lambda im: _colorize(im, "#1a1208", "#ffe8b0"),            "Warm sepia tone"),
    "deepfry":     (_deepfry,                                                  "Deep-fry an avatar"),
    "blur":        (lambda im: im.filter(_PFilter.GaussianBlur(6)),            "Blur an avatar"),
    "gaussian":    (lambda im: im.filter(_PFilter.GaussianBlur(10)),           "Heavy gaussian blur"),
    "boxblur":     (lambda im: im.filter(_PFilter.BoxBlur(6)),                 "Box blur an avatar"),
    "sharpen":     (lambda im: im.filter(_PFilter.SHARPEN),                    "Sharpen an avatar"),
    "smooth":      (lambda im: im.filter(_PFilter.SMOOTH_MORE),                "Smooth an avatar"),
    "detail":      (lambda im: im.filter(_PFilter.DETAIL),                     "Enhance avatar detail"),
    "edges":       (lambda im: im.filter(_PFilter.FIND_EDGES),                 "Find edges in an avatar"),
    "contour":     (lambda im: im.filter(_PFilter.CONTOUR),                    "Contour an avatar"),
    "emboss":      (lambda im: im.filter(_PFilter.EMBOSS),                     "Emboss an avatar"),
    "edgeenhance": (lambda im: im.filter(_PFilter.EDGE_ENHANCE_MORE),          "Enhance avatar edges"),
    "sketch":      (_sketch,                                                   "Pencil-sketch an avatar"),
    "posterize":   (lambda im: _POps.posterize(im.convert("RGB"), 3).convert("RGBA"), "Posterize an avatar"),
    "solarize":    (lambda im: _POps.solarize(im.convert("RGB"), 90).convert("RGBA"), "Solarize an avatar"),
    "flip":        (lambda im: _POps.flip(im),                                 "Flip an avatar vertically"),
    "mirror":      (lambda im: _POps.mirror(im),                               "Mirror an avatar horizontally"),
    "rotate":      (lambda im: _f_rotate(im, 90),                              "Rotate an avatar 90°"),
    "upsidedown":  (lambda im: _f_rotate(im, 180),                             "Flip an avatar upside-down"),
    "pixelate":    (lambda im: _pixelate(im, 32),                              "Pixelate an avatar"),
    "pixel":       (lambda im: _pixelate(im, 16),                              "Heavy pixelate an avatar"),
    "mosaic":      (lambda im: _pixelate(im, 8),                               "Mosaic an avatar"),
    "brighten":    (lambda im: _enh(im, "bright", 1.6),                        "Brighten an avatar"),
    "darken":      (lambda im: _enh(im, "bright", 0.55),                       "Darken an avatar"),
    "contrast":    (lambda im: _enh(im, "contrast", 1.8),                      "Boost avatar contrast"),
    "saturate":    (lambda im: _enh(im, "color", 2.2),                         "Saturate an avatar"),
    "desaturate":  (lambda im: _enh(im, "color", 0.3),                         "Desaturate an avatar"),
    "vibrant":     (lambda im: _enh(im, "color", 1.7),                         "Make an avatar vibrant"),
    "red":         (lambda im: _tint(im, 1.6, 0.5, 0.5),                       "Red-tint an avatar"),
    "green":       (lambda im: _tint(im, 0.5, 1.6, 0.5),                       "Green-tint an avatar"),
    "blue":        (lambda im: _tint(im, 0.5, 0.5, 1.7),                       "Blue-tint an avatar"),
    "cyan":        (lambda im: _tint(im, 0.4, 1.5, 1.5),                       "Cyan-tint an avatar"),
    "magenta":     (lambda im: _tint(im, 1.5, 0.4, 1.5),                       "Magenta-tint an avatar"),
    "yellow":      (lambda im: _tint(im, 1.5, 1.5, 0.4),                       "Yellow-tint an avatar"),
    "neon":        (lambda im: _colorize(im, "#0d001a", "#00ffea"),           "Neon glow filter"),
    "matrix":      (lambda im: _colorize(im, "#001a00", "#00ff00"),           "Matrix green filter"),
    "nightvision": (lambda im: _colorize(im, "#001000", "#43ff64"),           "Night-vision filter"),
    "blueprint":   (lambda im: _colorize(im, "#001b4d", "#cfe3ff"),           "Blueprint filter"),
    "fire":        (lambda im: _colorize(im, "#1a0000", "#ffcc00"),           "Fiery filter"),
    "ice":         (lambda im: _colorize(im, "#001a33", "#cceeff"),           "Icy filter"),
    "sunset":      (lambda im: _colorize(im, "#2d0a4e", "#ffd17a"),           "Sunset filter"),
    "ocean":       (lambda im: _colorize(im, "#001f3f", "#7fdbff"),           "Ocean filter"),
    "gold":        (lambda im: _colorize(im, "#3a2a00", "#ffd700"),           "Golden filter"),
    "crimson":     (lambda im: _colorize(im, "#2a0000", "#ff4d4d"),           "Crimson filter"),
    "amethyst":    (lambda im: _colorize(im, "#1a0033", "#e0b3ff"),           "Amethyst filter"),
    "toxic":       (lambda im: _colorize(im, "#0a2a00", "#c0ff00"),           "Toxic-green filter"),
    "rose":        (lambda im: _colorize(im, "#3a001f", "#ffd6e8"),           "Rose filter"),
    "mint":        (lambda im: _colorize(im, "#00261a", "#b3ffe0"),           "Mint filter"),
    "coffee":      (lambda im: _colorize(im, "#1a0d00", "#d2a679"),           "Coffee filter"),
    "noir":        (lambda im: _enh(_POps.grayscale(im).convert("RGBA"), "contrast", 1.6), "Film-noir filter"),
    "vaporwave":   (lambda im: _tint(im, 1.3, 0.8, 1.5),                      "Vaporwave aesthetic"),
}


async def _apply_manip(ctx, user, fn):
    target = user or ctx.author
    data = await _fetch_avatar_bytes(target)
    if not data:
        return await ctx.send(embed=error("Could not fetch that avatar."))

    def _process():
        im = _PImage.open(_io.BytesIO(data)).convert("RGBA")
        out = fn(im).convert("RGBA")
        buf = _io.BytesIO()
        out.save(buf, "PNG")
        buf.seek(0)
        return buf

    try:
        buf = await asyncio.to_thread(_process)
    except Exception:
        return await ctx.send(embed=error("Failed to process that image."))
    await ctx.send(file=discord.File(buf, filename="manip.png"))


def _make_manip(fn):
    async def _cmd(ctx, user: discord.Member = None):
        await _apply_manip(ctx, user, fn)
    return _cmd


# Reactions: name -> (emoji, "<verb target>", "<verb self>")
REACTIONS = {
    "airkiss":    ("😘", "blows a kiss to",       "blows a kiss"),
    "angrystare": ("😠", "angrily stares at",     "is angrily staring"),
    "bleh":       ("😝", "sticks their tongue at","goes bleh"),
    "brofist":    ("👊", "brofists",              "wants a brofist"),
    "celebrate":  ("🎉", "celebrates with",       "is celebrating"),
    "cheers":     ("🥂", "cheers with",           "raises a toast"),
    "clap":       ("👏", "claps for",             "is clapping"),
    "confused":   ("😕", "is confused by",        "is confused"),
    "cool":       ("😎", "thinks they're cool with","is feeling cool"),
    "drool":      ("🤤", "drools over",           "is drooling"),
    "evillaugh":  ("😈", "laughs evilly at",      "laughs evilly"),
    "facepalm":   ("🤦", "facepalms at",          "facepalms"),
    "happy":      ("😄", "is happy with",         "is happy"),
    "headbang":   ("🤘", "headbangs with",        "is headbanging"),
    "huh":        ("❓", "is puzzled by",         "goes huh?"),
    "laugh":      ("😂", "laughs with",           "bursts out laughing"),
    "lick":       ("👅", "licks",                 "wants to lick someone"),
    "love":       ("❤️", "loves",                 "is in love"),
    "mad":        ("😡", "is mad at",             "is mad"),
    "nervous":    ("😰", "is nervous around",     "is nervous"),
    "no":         ("🙅", "says no to",            "says no"),
    "nosebleed":  ("🩸", "gets a nosebleed over", "has a nosebleed"),
    "nuzzle":     ("🥰", "nuzzles",               "wants to nuzzle"),
    "nyah":       ("😼", "nyahs at",              "goes nyah~"),
    "peek":       ("👀", "peeks at",              "is peeking"),
    "pinch":      ("🤏", "pinches",               "wants to pinch someone"),
    "pout":       ("😤", "pouts at",              "is pouting"),
    "punch":      ("🥊", "punches",               "throws a punch"),
    "roll":       ("🤸", "rolls toward",          "rolls around"),
    "run":        ("🏃", "runs from",             "is running"),
    "sad":        ("😢", "is sad about",          "is sad"),
    "scared":     ("😱", "is scared of",          "is scared"),
    "shout":      ("📢", "shouts at",             "is shouting"),
    "shrug":      ("🤷", "shrugs at",             "shrugs"),
    "shy":        ("☺️", "is shy around",         "is feeling shy"),
    "sigh":       ("😮‍💨", "sighs at",            "sighs"),
    "sing":       ("🎤", "sings to",              "is singing"),
    "sip":        ("🍵", "sips tea at",           "sips their tea"),
    "sleep":      ("😴", "falls asleep on",       "is sleeping"),
    "slowclap":   ("👏", "slow-claps for",        "slow-claps"),
    "smack":      ("✋", "smacks",                "wants to smack someone"),
    "smile":      ("😊", "smiles at",             "is smiling"),
    "sneeze":     ("🤧", "sneezes on",            "sneezes"),
    "sorry":      ("🙇", "apologizes to",         "is sorry"),
    "stare":      ("👁️", "stares at",            "is staring"),
    "stop":       ("✋", "tells off",             "says stop"),
    "surprised":  ("😲", "surprises",             "is surprised"),
    "sweat":      ("😅", "sweats around",         "is sweating"),
    "thumbsup":   ("👍", "gives a thumbs up to",  "gives a thumbs up"),
    "tired":      ("🥱", "is tired of",           "is tired"),
    "woah":       ("😮", "is amazed by",          "goes woah"),
    "yawn":       ("🥱", "yawns at",              "yawns"),
    "yay":        ("🙌", "cheers for",            "goes yay"),
    "yes":        ("🙆", "agrees with",           "says yes"),
}


def _make_reaction(name, emoji, vt, vs):
    async def _cmd(ctx, member: discord.Member = None):
        gif = await _get_gif_url(name)
        a = ctx.author.display_name
        if member and member.id != ctx.author.id:
            desc = f"{emoji} **{a}** {vt} **{member.display_name}**!"
        else:
            desc = f"{emoji} **{a}** {vs}!"
        e = discord.Embed(description=desc, color=0xff79c6)
        if gif:
            e.set_image(url=gif)
        await ctx.send(embed=e)
    return _cmd


# Register generated commands and collect metadata for $help / $cmds / the website
_GEN_MANIP: list[tuple[str, str]] = []
_GEN_REACT: list[tuple[str, str]] = []

for _name, (_fn, _desc) in MANIP_FILTERS.items():
    if bot.get_command(_name):
        continue
    _c = _make_manip(_fn)
    _c.__name__ = f"manip_{_name}"
    bot.add_command(commands.Command(_c, name=_name))
    _GEN_MANIP.append((f"{_name} [user]", _desc))

for _name, (_emoji, _vt, _vs) in REACTIONS.items():
    if bot.get_command(_name):
        continue
    _c = _make_reaction(_name, _emoji, _vt, _vs)
    _c.__name__ = f"reaction_{_name}"
    bot.add_command(commands.Command(_c, name=_name))
    _GEN_REACT.append((f"{_name} [user]", f"{_emoji} {_vs.capitalize()}"))

if _GEN_MANIP:
    CATEGORIES["manipulation"] = {"emoji": "🖼️", "commands": _GEN_MANIP}
if _GEN_REACT:
    CATEGORIES["reactions"] = {"emoji": "🎭", "commands": _GEN_REACT}

# Register external command modules (large hand-built categories live in their
# own files to keep bot.py manageable). Each exposes register(bot, CATEGORIES, helpers).
import types as _types
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_HELPERS = _types.SimpleNamespace(
    error=error, success=success, info=info,
    load_data=load_data, save_data=save_data,
)
import ext_server as _ext_server
_ext_server.register(bot, CATEGORIES, _HELPERS)
import ext_lastfm as _ext_lastfm
_ext_lastfm.register(bot, CATEGORIES, _HELPERS)
import ext_spotify as _ext_spotify
_ext_spotify.register(bot, CATEGORIES, _HELPERS)
import ext_music as _ext_music
_ext_music.register(bot, CATEGORIES, _HELPERS)

# Rebuild the usage lookup so the new categories appear in $help / $cmds
for _cat_data in CATEGORIES.values():
    for _syntax, _desc in _cat_data["commands"]:
        _cn = _syntax.split()[0]
        if _cn not in _CMD_USAGE:
            _CMD_USAGE[_cn] = (_syntax, _desc)


# ─────────────────────────────────────────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: DISCORD_BOT_TOKEN environment variable is not set.")
        print("   Add it as a secret in the Replit Secrets tab.")
        exit(1)
    os.makedirs(DATA_DIR, exist_ok=True)
    bot.run(TOKEN)
