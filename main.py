import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
from flask import Flask, jsonify, request
import webserver
import yfinance as yf
import requests
from discord.ext import tasks
import random
from datetime import datetime
from datetime import datetime, date
from mangum import Mangum
from asgiref.wsgi import WsgiToAsgi


NEWS_API_KEY = os.getenv("NEWS_API_KEY")

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

s_role = "shut-in"
WATCHLIST = ["AAPL", "TSLA", "MSFT", "PLTR", "UAL" ]   # you can expand this
ALERT_CHANNEL_ID = 1414833850777075722 # replace with your Discord channel ID
ALERT_THRESHOLD = 2.0  # % move
SUMMARY_CHANNEL_ID = 1414833850777075722

def to_date(ed):
    """Convert various yfinance earnings date formats to datetime.date"""
    if isinstance(ed, list):
        ed = ed[0]  # yfinance sometimes returns a list
    if isinstance(ed, datetime):
        return ed.date()
    if isinstance(ed, date):  # already a date
        return ed
    if hasattr(ed, "to_pydatetime"):  # pandas Timestamp
        return ed.to_pydatetime().date()
    return None


def get_stock_info(symbol):
    try:
        stock = yf.Ticker(symbol)
        # Get last 5 days to ensure data is there
        data = stock.history(period="5d", interval="1d")

        if data.empty:
            return None, None, None

        # Latest price
        price = data['Close'].iloc[-1]

        # Previous close
        prev_close = data['Close'].iloc[-2] if len(data) > 1 else price

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
        articles = res.get("articles", [])[:3]  # top 3 recent news
        if not articles:
            return ["No major recent news found."]
        return [f"• {a['title']} ({a['source']['name']})" for a in articles]
    except Exception as e:
        print(f"Error fetching news: {e}")
        return ["Error fetching news."]


@tasks.loop(minutes=5)
async def stock_alerts():
    channel = bot.get_channel(ALERT_CHANNEL_ID)
    if not channel:
        print("❌ ALERT CHANNEL NOT FOUND. Check ALERT_CHANNEL_ID.")
        return

    msg = "**📈 Stock Updates**\n"
    for symbol in WATCHLIST:
        price, change, pct = get_stock_info(symbol)
        msg += f"{symbol}: ${price:.2f} ({pct:+.2f}%)\n"

        # ⚡ Alert only if threshold is crossed
        if price and abs(pct) >= ALERT_THRESHOLD:
            direction = "🔺 UP" if change > 0 else "🔻 DOWN"
            msg += f"⚡ **ALERT**: {symbol} is {direction} {pct:.2f}%\n"

    await channel.send(msg)


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

    msg = "**📊 Daily Market Summary**\n\n"
    if gainers:
        msg += "**Top Gainers:**\n" + "\n".join([f"{s}: +{p:.2f}%" for s, p in gainers]) + "\n\n"
    if losers:
        msg += "**Top Losers:**\n" + "\n".join([f"{s}: {p:.2f}%" for s, p in losers])
    await channel.send(msg)

@tasks.loop(hours=24)
async def earnings_reminder():
    channel = bot.get_channel(SUMMARY_CHANNEL_ID)
    for symbol in WATCHLIST:
        try:
            stock = yf.Ticker(symbol)
            cal = stock.calendar

            if not cal:
                continue

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
        except Exception as e:
            print(f"Earnings check failed for {symbol}: {e}")

@bot.command()
async def stock(ctx, symbol: str):
    """Get live stock price and % change."""
    price, change, pct = get_stock_info(symbol.upper())
    if price is None:
        await ctx.send(f"Could not fetch data for {symbol.upper()}.")
        return

    direction = "🔺 UP" if change > 0 else "🔻 DOWN"
    await ctx.send(f"**{symbol.upper()}** is {direction}\n"
                   f"Price: ${price:.2f}\nChange: {change:.2f} ({pct:.2f}%)")


@bot.command()
async def why(ctx, symbol: str):
    """Get recent news explaining stock movement."""
    news = get_stock_news(symbol.upper())
    await ctx.send(f"📰 **Why is {symbol.upper()} moving?**\n" + "\n".join(news))

@bot.event
async def on_ready():
    print(f"We are ready to go in, {bot.user.name}")

@bot.event
async def on_member_join(member):
    await member.send(f"Welcome to the server {member.name}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if "shit" in message.content.lower():
        await message.delete()
        await message.channel.send(f"{message.author.mention} dont use that word! ")




    await bot.process_commands(message)

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
        await ctx.send("you messed up gang")
@bot.command()
async def remove(ctx):
    role = discord.utils.get(ctx.guild.roles, name=s_role)
    if role:
        await ctx.author.remove_roles(role)
        await ctx.send(f"{ctx.author.mention} had the {role} removed")
    else:
        await ctx.send("you messed up gang")

@bot.command()
async def dm(ctx, *, msg):
    await ctx.author.send(f"You said {msg}")


@bot.command()
async def reply(ctx):
    await ctx.reply("This is a reply to your message")

@bot.command()
async  def poll(ctx, *, question):
    embed = discord.Embed(title="New Poll", description=question)
    poll_message = await ctx.send(embed=embed)
    await poll_message.add_reaction("👍")
    await poll_message.add_reaction("👎")


@bot.command()
@commands.has_role(s_role)
async def secret(ctx):
    await ctx.send("Welcome to the gay club!")

@secret.error
async def secret_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        await ctx.send("you dont have permission to do that!")

@bot.event
async def on_ready():
    print(f"We are ready to go in, {bot.user.name}")
    if not stock_alerts.is_running():
        stock_alerts.start()
    if not daily_summary.is_running():
        daily_summary.start()
    if not earnings_reminder.is_running():
        earnings_reminder.start()

webserver.keep_alive()



bot.run(token, log_handler=handler, log_level= logging.DEBUG)

