import os
import logging
import random
import requests
import discord
import yfinance as yf
from dotenv import load_dotenv
from discord.ext import commands, tasks
from datetime import datetime, date, timezone
import webserver
import json

# --- ENVIRONMENT ---
load_dotenv()
token = os.getenv("DISCORD_TOKEN")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

# --- LOGGING ---
handler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")

# --- DISCORD INTENTS ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- CONSTANTS ---
s_role = "shut-in"
WATCHLIST_FILE = "watchlist.json"
ALERT_CHANNEL_ID = 1414833850777075722
SUMMARY_CHANNEL_ID = 1414833850777075722
ALERT_THRESHOLD = 2.0  # % move

# --- WATCHLIST STORAGE ---
def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    return ["AAPL", "TSLA", "MSFT"]  # default list

def save_watchlist():
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(WATCHLIST, f)

WATCHLIST = load_watchlist()

# --- UTILITIES ---
def to_date(ed):
    """Convert various yfinance earnings date formats to datetime.date"""
    if isinstance(ed, list):
        ed = ed[0]
    if isinstance(ed, datetime):
        return ed.date()
    if isinstance(ed, date):
        return ed
    if hasattr(ed, "to_pydatetime"):
        return ed.to_pydatetime().date()
    return None

def get_stock_info(symbol):
    try:
        stock = yf.Ticker(symbol)
        data = stock.history(period="5d", interval="1d")

        if data.empty:
            return None, None, None

        price = data["Close"].iloc[-1]
        prev_close = data["Close"].iloc[-2] if len(data) > 1 else price
        change = price - prev_close
        pct_change = (change / prev_close) * 100 if prev_close else 0

        return price, change, pct_change
    except Exception as e:
        print(f"Error fetching stock info for {symbol}: {e}")
        return None, None, None

def get_stock_news(symbol):
    try:
        url = f"https://newsapi.org/v2/everything?q={symbol}&sortBy=publishedAt&apiKey={NEWS_API_KEY}"
        res = requests.get(url).json()
        articles = res.get("articles", [])[:3]
        if not articles:
            return ["No major recent news found."]
        return [f"• {a['title']} ({a['source']['name']})" for a in articles]
    except Exception as e:
        print(f"Error fetching news: {e}")
        return ["Error fetching news."]

# --- TASKS ---
@tasks.loop(minutes=5)
async def stock_alerts():
    channel = bot.get_channel(ALERT_CHANNEL_ID)
    if not channel:
        print("❌ ALERT CHANNEL NOT FOUND.")
        return

    embed = discord.Embed(
        title="📈 Stock Updates",
        color=0xf1c40f,
        timestamp=datetime.now(timezone.utc)
    )

    for symbol in WATCHLIST:
        price, change, pct = get_stock_info(symbol)
        if not price:
            continue

        direction = "🔺" if change > 0 else "🔻"
        value = f"${price:.2f} ({pct:+.2f}%)"

        if abs(pct) >= ALERT_THRESHOLD:
            value += f" ⚡ ALERT: {direction} {pct:.2f}%"

        embed.add_field(name=symbol, value=value, inline=False)

    await channel.send(embed=embed)

@tasks.loop(hours=24)
async def daily_summary():
    channel = bot.get_channel(SUMMARY_CHANNEL_ID)
    gainers, losers = [], []

    for symbol in WATCHLIST:
        price, change, pct = get_stock_info(symbol)
        if price:
            if pct > 0:
                gainers.append((symbol, pct))
            else:
                losers.append((symbol, pct))

    gainers = sorted(gainers, key=lambda x: x[1], reverse=True)[:3]
    losers = sorted(losers, key=lambda x: x[1])[:3]

    embed = discord.Embed(
        title="📊 Daily Market Summary",
        color=0x1abc9c,
        timestamp=datetime.now(timezone.utc)
    )

    if gainers:
        embed.add_field(
            name="📈 Top Gainers",
            value="\n".join([f"**{s}**: +{p:.2f}%" for s, p in gainers]),
            inline=False
        )
    if losers:
        embed.add_field(
            name="📉 Top Losers",
            value="\n".join([f"**{s}**: {p:.2f}%" for s, p in losers]),
            inline=False
        )

    embed.set_footer(text="Market data via Yahoo Finance")
    await channel.send(embed=embed)

@tasks.loop(hours=24)
async def earnings_reminder():
    channel = bot.get_channel(SUMMARY_CHANNEL_ID)
    for symbol in WATCHLIST:
        try:
            stock = yf.Ticker(symbol)
            cal = stock.calendar
            earnings_date = None

            if isinstance(cal, dict):
                earnings_date = to_date(cal.get("Earnings Date"))
            elif hasattr(cal, "empty") and not cal.empty:
                if "Earnings Date" in cal.index:
                    earnings_date = to_date(cal.loc["Earnings Date"][0])

            if earnings_date:
                today = datetime.now().date()
                if (earnings_date - today).days == 1:
                    await channel.send(f"📢 Reminder: **{symbol}** reports earnings tomorrow!")
        except Exception as e:
            print(f"Earnings check failed for {symbol}: {e}")

# --- COMMANDS ---
@bot.command()
async def stock(ctx, symbol: str):
    price, change, pct = get_stock_info(symbol.upper())
    if price is None:
        await ctx.send(f"Could not fetch data for {symbol.upper()}.")
        return

    direction = "🔺 UP" if change > 0 else "🔻 DOWN"
    color = 0x00ff00 if change > 0 else 0xff0000

    embed = discord.Embed(
        title=f"{symbol.upper()} Stock Update",
        description=f"{direction} {pct:.2f}%",
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="Price", value=f"${price:.2f}", inline=True)
    embed.add_field(name="Change", value=f"{change:.2f}", inline=True)
    embed.set_footer(text="Powered by Yahoo Finance 📊")

    await ctx.send(embed=embed)

@bot.command()
async def why(ctx, symbol: str):
    news = get_stock_news(symbol.upper())
    embed = discord.Embed(
        title=f"📰 Why is {symbol.upper()} moving?",
        color=0x7289da,
        timestamp=datetime.now(timezone.utc)
    )
    for n in news:
        embed.add_field(name="•", value=n, inline=False)

    await ctx.send(embed=embed)

# --- WATCHLIST COMMANDS ---
@bot.command()
async def addstock(ctx, symbol: str):
    symbol = symbol.upper()
    price, _, _ = get_stock_info(symbol)

    if price is None:
        await ctx.send(f"❌ Invalid ticker: `{symbol}`")
        return

    if symbol in WATCHLIST:
        await ctx.send(f"⚠️ `{symbol}` is already in the watchlist.")
        return

    WATCHLIST.append(symbol)
    save_watchlist()
    await ctx.send(f"✅ Added `{symbol}` to the watchlist!")

@bot.command()
async def removestock(ctx, symbol: str):
    symbol = symbol.upper()
    if symbol not in WATCHLIST:
        await ctx.send(f"❌ `{symbol}` is not in the watchlist.")
        return

    WATCHLIST.remove(symbol)
    save_watchlist()
    await ctx.send(f"🗑 Removed `{symbol}` from the watchlist.")

@bot.command()
async def liststocks(ctx):
    if not WATCHLIST:
        await ctx.send("📭 No stocks are currently being tracked.")
        return

    embed = discord.Embed(
        title="📈 Current Watchlist",
        description="\n".join([f"• {s}" for s in WATCHLIST]),
        color=0x3498db,
        timestamp=datetime.now(timezone.utc)
    )
    await ctx.send(embed=embed)

# --- FUN COMMANDS ---
@bot.command()
async def hello(ctx):
    await ctx.send(f"Hello {ctx.author.mention}!")

@bot.command()
async def assign(ctx):
    role = discord.utils.get(ctx.guild.roles, name=s_role)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"{ctx.author.mention} is now assigned to {role}")
    else:
        await ctx.send("Role not found!")

@bot.command()
async def remove(ctx):
    role = discord.utils.get(ctx.guild.roles, name=s_role)
    if role:
        await ctx.author.remove_roles(role)
        await ctx.send(f"{ctx.author.mention} had the {role} removed")
    else:
        await ctx.send("Role not found!")

@bot.command()
async def dm(ctx, *, msg):
    await ctx.author.send(f"You said: {msg}")

@bot.command()
async def reply(ctx):
    await ctx.reply("This is a reply to your message")

@bot.command()
async def poll(ctx, *, question):
    embed = discord.Embed(title="📊 New Poll", description=question)
    poll_message = await ctx.send(embed=embed)
    await poll_message.add_reaction("👍")
    await poll_message.add_reaction("👎")

@bot.command()
@commands.has_role(s_role)
async def secret(ctx):
    await ctx.send("Welcome to the secret club!")

@secret.error
async def secret_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        await ctx.send("You don’t have permission to do that!")

# --- EVENTS ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user.name}")
    if not stock_alerts.is_running():
        stock_alerts.start()
    if not daily_summary.is_running():
        daily_summary.start()
    if not earnings_reminder.is_running():
        earnings_reminder.start()

@bot.event
async def on_member_join(member):
    await member.send(f"Welcome to the server {member.name}!")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if "shit" in message.content.lower():
        await message.delete()
        await message.channel.send(f"{message.author.mention} please don’t use that word!")
    await bot.process_commands(message)

# --- KEEP ALIVE + RUN ---
webserver.keep_alive()
bot.run(token, log_handler=handler, log_level=logging.DEBUG)
