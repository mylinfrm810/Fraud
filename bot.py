import discord
from discord.ext import commands
import asyncio
import json
import os
import random
import datetime
from collections import defaultdict

# ─── CONFIG ───────────────────────────────────────────────────────────────────
PREFIX = "$"
TOKEN = "DISCORD_TOKEN"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ─── DATA STORAGE ────────────────────────────────────────────────────────────
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
warnings_db = load_data(f"{DATA_DIR}/warnings.json", {})
autoroles   = load_data(f"{DATA_DIR}/autoroles.json", {})
welcomecfg  = load_data(f"{DATA_DIR}/welcome.json", {})
antinuke    = load_data(f"{DATA_DIR}/antinuke.json", {})

# ─── ANTI-NUKE TRACKING ──────────────────────────────────────────────────────
nuke_tracker = defaultdict(lambda: defaultdict(list))
NUKE_THRESHOLD = 3
NUKE_WINDOW = 10

# ─── HELPERS ────────────────────────────────────────────────────────────────
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

def success(d): return embed("✅ Success", d, 0x57f287)
def error(d): return embed("❌ Error", d, 0xed4245)
def info(d): return embed("ℹ️ Info", d, 0x5865f2)

# ─── EVENTS ──────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{PREFIX}help | your server"
        )
    )
    print(f"Logged in as {bot.user}")

# ─── WELCOME EVENTS ──────────────────────────────────────────────────────────
@bot.event
async def on_member_join(member):
    guild_id = str(member.guild.id)

    if guild_id in autoroles:
        for role_id in autoroles[guild_id]:
            role = member.guild.get_role(int(role_id))
            if role:
                try:
                    await member.add_roles(role)
                except:
                    pass

    if guild_id in welcomecfg:
        cfg = welcomecfg[guild_id]
        channel = member.guild.get_channel(int(cfg["channel"]))
        if channel:
            msg = cfg["message"].replace("{user}", member.mention)
            await channel.send(embed=discord.Embed(description=msg, color=0x5865f2))

# ─── HELP COMMAND (unchanged) ────────────────────────────────────────────────
# (KEEP YOUR HELP COMMAND EXACTLY AS YOU HAD IT)

# ─── MODERATION (unchanged) ──────────────────────────────────────────────────
# (ALL YOUR MODERATION COMMANDS STAY SAME)

# ─── WELCOME COMMANDS (unchanged) ────────────────────────────────────────────
# (KEEP SAME)

# ─── TICKETS (unchanged) ──────────────────────────────────────────────────────
# (KEEP SAME)

# ─── ANTI-NUKE / ANTI-RAID (unchanged) ───────────────────────────────────────
# (KEEP SAME)

# ─── ECONOMY ─────────────────────────────────────────────────────────────────
DAILY_AMOUNT = 500
WORK_MIN, WORK_MAX = 50, 300

DAILY_COOLDOWNS = {}
WORK_COOLDOWNS = {}

@bot.command()
async def balance(ctx, member: discord.Member = None):
    member = member or ctx.author
    bal = get_balance(str(ctx.guild.id), str(member.id))

    e = discord.Embed(title=f"{member.display_name}'s Balance", color=0xfee75c)
    e.add_field(name="Wallet", value=f"${bal['wallet']:,}")
    e.add_field(name="Bank", value=f"${bal['bank']:,}")
    e.add_field(name="Total", value=f"${bal['wallet'] + bal['bank']:,}", inline=False)
    await ctx.send(embed=e)

# ─── REMOVE DUPLICATE `bal` COMMAND (FIXED ISSUE) ────────────────────────────
# (intentionally removed to prevent command conflicts)

# ─── KEEP REST OF YOUR COMMANDS AS THEY WERE ────────────────────────────────
# (daily, work, gambling, fun, etc remain unchanged)

# ─── ERROR HANDLER ───────────────────────────────────────────────────────────
@bot.event
async def on_command_error(ctx, err):
    if isinstance(err, commands.MissingPermissions):
        await ctx.send(embed=error("No permission."))
    elif isinstance(err, commands.MissingRequiredArgument):
        await ctx.send(embed=error("Missing argument."))
    elif isinstance(err, commands.CommandNotFound):
        pass

# ─── RUN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    bot.run(TOKEN)
