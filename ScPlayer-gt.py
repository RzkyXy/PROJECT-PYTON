import requests, certifi
import discord
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import matplotlib.dates as mdates
from io import BytesIO
import matplotlib.pyplot as plt
import re
import json
import os
from discord.ext import commands, tasks
from discord import app_commands


TOKEN = "YOUR TOKEN"
URL = "https://growtopiagame.com/detail"

proxies = {
    "http": "socks5://user:pw@ip:port",
    "https": "socks5://user:pw@ip:port",
}

STATUS_CHANNEL_ID = 123  # Channel khusus status online
LOG_CHANNEL_ID = 123     # Channel khusus log perubahan
ROLE_ID = 123          # Role yang ditag kalau turun drastis
ALERT_CHANNEL_ID = 123
PRICE_ROLE_IDS = [123, 123, 123, 123]
GUILD_ID = 123  # ID server (guild) kamu


# ID channel yang dipantau
last_active = {}
inactive_settings = {}
removed_logs = {}        # logs remove role {guild_id: [(member_id, datetime_last_chat, datetime_remove)]}
WATCHED_CHANNEL_ID = 123  # ganti dengan ID channel
ROLE_NAME = "Private"  # role yang akan dihapus kalau afk > 3 hari
AFK_LIMIT = timedelta(days=3)

# Variabel global
previous_online_users = None
previous_message = None
total_minus = None
seen_mods_date = None
player_history = []
mod_online_time = {}  # untuk menyimpan durasi online mod hari ini
mod_first_seen = {}   # waktu pertama kali online (per hari)
mod_last_seen = {}    # waktu terakhir terlihat online
mod_first_seen = {}
mod_online_time = {}
mods_seen_today = set()
last_reset_date = None
last_btc_price = None
last_btc_time = 0
# History harga DL
dl_history = []

# Ambil jumlah online player dari API
def get_online_users():
    try:
        r = requests.get(URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return int(data.get("online_user", 0))  # pastikan int
    except Exception as e:
        print("❌ Error get_online_users:", e)
    return None

def get_now_time():
    try:
        tz = ZoneInfo("Asia/Jakarta")
    except ZoneInfoNotFoundError:
        print("⚠️ Timezone Asia/Jakarta tidak ditemukan, fallback ke UTC")
        tz = ZoneInfo("UTC")
    return datetime.now(tz)

def reset_seen_mods():
    global seen_mods_today, seen_mods_date
    seen_mods_today.clear()
    seen_mods_date = datetime.now(ZoneInfo("Asia/Jakarta")).date()

def get_btc_price():
    global last_btc_price, last_btc_time
    now = datetime.now().timestamp()

    # gunakan cache 5 menit
    if last_btc_price and now - last_btc_time < 300:
        return last_btc_price

    urls = [
        ("coingecko", "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"),
        ("binance", "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"),
        ("cryptorates", "https://cryptorates.ai/v1/get/btc"),
    ]

    for source, url in urls:
        try:
            r = requests.get(url, timeout=10, verify=certifi.where())
            if r.status_code == 200:
                data = r.json()
                if source == "coingecko":
                    last_btc_price = data.get("bitcoin", {}).get("usd")
                elif source == "binance":
                    last_btc_price = float(data["price"])
                elif source == "cryptorates":
                    last_btc_price = data.get("price")
                last_btc_time = now
                return last_btc_price
        except Exception as e:
            print(f"⚠️ Gagal ambil dari {source}: {e}")

    # kalau semua gagal, tetap kembalikan cache lama atau N/A
    return last_btc_price if last_btc_price else "N/A"

def get_dl_price():
    try:
        r = requests.get("https://api.noire.my.id/api", timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("diamondLock", {}).get("price")
    except Exception as e:
        print("❌ Error get_dl_price:", e)
    return None    


intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# === Slash command /role add user role ===
@bot.tree.command(name="role", description="Tambah role ke user")
@app_commands.describe(action="add/remove", user="User target", role="Role target")
async def role(interaction: discord.Interaction, action: str, user: discord.Member, role: discord.Role):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("Lu tidak punya izin manage_roles.", ephemeral=True)
        return

    if action.lower() == "add":
        await user.add_roles(role)
        await interaction.response.send_message(f"Role **{role.name}** ditambahkan ke {user.mention}")
    elif action.lower() == "remove":
        await user.remove_roles(role)
        await interaction.response.send_message(f"Role **{role.name}** dihapus dari {user.mention}")
    else:
        await interaction.response.send_message("Format salah. Gunakan `/role add user role` atau `/role remove user role`")

# === Slash Command BAN ===
@bot.tree.command(name="ban", description="Ban user dari server")
@app_commands.describe(user="User yang ingin diban", reason="Alasan ban (opsional)")
async def ban_slash(interaction: discord.Interaction, user: discord.Member, reason: str = "Tidak ada alasan"):
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message("Kamu tidak punya izin untuk ban members.", ephemeral=True)
        return

    try:
        await user.ban(reason=reason)
        await interaction.response.send_message(
            f"✅ {user.mention} berhasil diban.\nAlasan: {reason}"
        )
    except Exception as e:
        await interaction.response.send_message(f" Gagal ban {user.mention}: {e}")

@bot.tree.command(name="unban", description="Unban user dari server")
@app_commands.describe(user_id="ID user yang ingin di-unban")
async def unban_slash(interaction: discord.Interaction, user_id: int):
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message("Lu tidak punya izin untuk unban members.", ephemeral=True)
        return

    try:
        user = await interaction.guild.fetch_ban(discord.Object(id=user_id))
        await interaction.guild.unban(user.user)
        await interaction.response.send_message(f"{user.user} berhasil di-unban.")
    except Exception as e:
        await interaction.response.send_message(f"Gagal unban ID `{user_id}`: {e}")   

# === Prefix Command BAN ===
@bot.command(name="ban")   # <- tetap "!ban"
@commands.has_permissions(ban_members=True)
async def ban_prefix_cmd(ctx, member: discord.Member, *, reason: str = None):
    if reason is None:
        reason = "Tidak ada alasan"
    try:
        await member.ban(reason=reason)
        await ctx.send(f"{member.mention} berhasil diban.\n📄 Alasan: {reason}")
    except Exception as e:
        await ctx.send(f"Gagal ban {member.mention}: {e}")

@ban_prefix_cmd.error
async def ban_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("```!ban <user> <reason>```")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("Lu tidak punya izin untuk ban member.")
    else:
        await ctx.send(f" Error: {error}")
@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban_prefix(ctx, user_id: int):
    try:
        ban_entry = await ctx.guild.fetch_ban(discord.Object(id=user_id))
        await ctx.guild.unban(ban_entry.user)
        await ctx.send(f"{ban_entry.user} berhasil di-unban.")
    except discord.NotFound:
        await ctx.send(f"User dengan ID `{user_id}` tidak ada di ban list.")
    except Exception as e:
        await ctx.send(f"Gagal unban ID `{user_id}`: {e}")

@bot.command(name="mute")
@commands.has_permissions(manage_roles=True)
async def mute_prefix(ctx, member: discord.Member, *, reason="Tidak ada alasan"):
    muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not muted_role:
        muted_role = await ctx.guild.create_role(name="Muted")
        for channel in ctx.guild.channels:
            await channel.set_permissions(muted_role, send_messages=False, speak=False)
    try:
        await member.add_roles(muted_role, reason=reason)
        await ctx.send(f"Mampus {member.mention} telah di-mute.\nAlasan: {reason}")
    except Exception as e:
        await ctx.send(f" Gagal mute {member.mention}: {e}")

@mute_prefix.error
async def mute_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("`!mute <user> [alasan]`")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("Lu tidak punya izin untuk mute member.")
    else:
        await ctx.send(f"Error: {error}")

@bot.command(name="unmute")
@commands.has_permissions(manage_roles=True)
async def unmute_prefix(ctx, member: discord.Member):
    muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not muted_role:
        await ctx.send("Role `Muted` belum dibuat.")
        return
    try:
        await member.remove_roles(muted_role)
        await ctx.send(f"Kamu {member.mention} telah di-unmute.")
    except Exception as e:
        await ctx.send(f"Gagal unmute {member.mention}: {e}")
        return

def parse_duration(duration_str: str):
    """Konversi string durasi ke timedelta"""
    match = re.match(r"^(\d+)([smhd])$", duration_str.lower())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    if unit == "s":  # detik
        return timedelta(seconds=value)
    elif unit == "m":  # menit
        return timedelta(minutes=value)
    elif unit == "h":  # jam
        return timedelta(hours=value)
    elif unit == "d":  # hari
        return timedelta(days=value)
    return None

@bot.command(name="timeout")
@commands.has_permissions(moderate_members=True)
async def mute_prefix(ctx, member: discord.Member = None, duration: str = None, *, reason="Tidak ada alasan"):
    """!timeout <user> <durasi> [alasan]"""
    if not member or not duration:
        await ctx.send("`!timeout @user 10m [alasan]`")
        return

    delta = parse_duration(duration)
    if not delta:
        await ctx.send("Durasi tidak valid. Gunakan format: `10m`, `2h`, `1d`")
        return

    try:
        until = discord.utils.utcnow() + delta
        await member.timeout(until, reason=reason)
        await ctx.send(f"mampus {member.mention} telah dimute selama **{duration}**.\nAlasan: {reason}")
    except Exception as e:
        await ctx.send(f"Gagal mute {member.mention}: {e}")


@bot.command(name="untimeout")
@commands.has_permissions(moderate_members=True)
async def unmute_prefix(ctx, member: discord.Member = None):
    """!untimeout <user>"""
    if not member:
        await ctx.send("Format salah.\nContoh: `!untimeout @user`")
        return

    try:
        await member.timeout(None)
        await ctx.send(f"{member.mention} berhasil diuntimeout.")
    except Exception as e:
        await ctx.send(f"Gagal untimeout {member.mention}: {e}")    

# === Command set inactive ===
@bot.tree.command(name="setinactive", description="Atur sistem cek member tidak aktif.")
@app_commands.describe(
    channel="Channel yang dipantau",
    role="Role yang akan dihapus",
    log_channel="Channel logs",
    days="Jumlah hari tidak aktif sebelum role dihapus"
)
async def set_inactive(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    role: discord.Role,
    log_channel: discord.TextChannel,
    days: int
):
    guild_id = interaction.guild.id
    inactive_settings[guild_id] = {
        "channel_id": channel.id,
        "role_id": role.id,
        "logs_channel": log_channel.id,
        "days": days
    }
    removed_logs[guild_id] = []
    await interaction.response.send_message(
        f"✅ Sistem cek tidak aktif diset!\n"
        f"📌 Channel dipantau: {channel.mention}\n"
        f"🎭 Role target: {role.mention}\n"
        f"📝 Logs: {log_channel.mention}\n"
        f"⏳ Durasi: {days} hari"
    )
# === Command cek log remove ===
@bot.command(name="logremove")
async def logremove(ctx):
    guild_id = ctx.guild.id
    logs = removed_logs.get(guild_id, [])
    if not logs:
        await ctx.send("📭 Belum ada member yang di-remove role.")
        return

    lines = []
    for member_id, last_time, removed_time in logs[-10:]:  # tampilkan max 10 terakhir
        member = ctx.guild.get_member(member_id)
        name = member.name if member else f"UserID {member_id}"
        last_str = last_time.strftime("%Y-%m-%d %H:%M:%S UTC") if last_time else "Tidak ada"
        removed_str = removed_time.strftime("%Y-%m-%d %H:%M:%S UTC")
        lines.append(f"🔹 {name} | Last chat: {last_str} | Removed: {removed_str}")

    msg = "\n".join(lines)
    await ctx.send(f"📜 Log Remove Role:\n{msg}")

DATA_FILE = "inactive_data.json"

def save_data():
    data = {
        "last_active": {str(g): {str(u): t.isoformat() for u, t in users.items()} for g, users in last_active.items()},
        "inactive_settings": inactive_settings,
        "removed_logs": {
            str(g): [(uid, lt.isoformat() if lt else None, rt.isoformat()) for uid, lt, rt in logs]
            for g, logs in removed_logs.items()
        }
    }
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

def load_data():
    global last_active, inactive_settings, removed_logs
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            # restore last_active
            last_active = {
                int(g): {int(u): datetime.fromisoformat(t) for u, t in users.items()}
                for g, users in data.get("last_active", {}).items()
            }
            inactive_settings = {
                int(g): v for g, v in data.get("inactive_settings", {}).items()
            }
            removed_logs = {
                int(g): [(uid, datetime.fromisoformat(lt) if lt else None, datetime.fromisoformat(rt)) for uid, lt, rt in logs]
                for g, logs in data.get("removed_logs", {}).items()
            }

async def send_web_text():
    global previous_online_users, previous_message, total_minus, player_history
    global mod_first_seen, mod_online_time, mods_seen_today, last_reset_date, mod_last_seen

    while True:
        now_time = get_now_time()
        web_data = get_online_users()
        timestamp = now_time.strftime("%H:%M:%S")
        today_str = now_time.strftime("%d %B %Y")

        mods_display = "Tidak ada mod online saat ini"
        seen_display = "No mods were seen today yet."

        # Reset harian
        if last_reset_date is None or last_reset_date != now_time.date():
            mods_seen_today.clear()
            mod_first_seen.clear()
            mod_last_seen.clear()
            last_reset_date = now_time.date()
            
        if web_data is not None:
            player_history.append((now_time, web_data))
            cutoff = now_time - timedelta(hours=24)
            player_history[:] = [(t, v) for t, v in player_history if t >= cutoff]
        #Mod data
        try:
            mod_data = requests.get(
                "https://gist.githubusercontent.com/Galangrs/22b5c1862e275a14dbbd9adef3103250/raw/config.json",
                timeout=10
            ).json()

            mods_list = mod_data.get("mods", [])
            mod_info = []

            for mod in mods_list:
                name = mod.get("name", "Unknown")
                undercover = mod.get("undercover", True)
                updated = mod.get("updated", 0)

                status = "<:online_badge:1133244041576841349> Online" if undercover is False else "<:undercover:1404369826293747834> Undercover"
                is_online = True   # dianggap online kalau ada di list

                prev_status = mod_last_seen.get(name)

                if is_online:
                    # reset timer jika sebelumnya offline
                    if prev_status != "online":
                        mod_first_seen[name] = updated or int(datetime.now().timestamp())

                    mod_last_seen[name] = "online"

                    first_seen_ts = mod_first_seen[name]
                    elapsed_seconds = int(datetime.now().timestamp()) - first_seen_ts
                    start_time_str = datetime.fromtimestamp(first_seen_ts, ZoneInfo("Asia/Jakarta")).strftime("%H:%M")
                    now_time_str = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%H:%M")

                    if elapsed_seconds < 3600:
                        elapsed_str = f"{elapsed_seconds // 60} menit"
                    else:
                        elapsed_str = f"{elapsed_seconds // 3600} jam {(elapsed_seconds % 3600) // 60} menit"

                    mod_info.append(f"{name} ({status}) — {elapsed_str} ({start_time_str}–{now_time_str})")
                    mods_seen_today.add(name)
                else:
                    mod_last_seen[name] = "offline"

            if mod_info:
                mods_display = "\n".join(mod_info)

            if mods_seen_today:
                seen_display = "\n".join(sorted(mods_seen_today))

        except Exception as e:
            mods_display = f"Error mengambil data mods: {e}"

        # embed
        embed = discord.Embed(
            title="Growtopia Status",
            description=f":green_circle: Online count: {int(web_data):,}" if web_data is not None else "No data",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(
            name="<:moderator:1252149658956992564> Moderator/Guardian Currently Online",
            value=mods_display, inline=False
        )
        embed.add_field(
            name=f"📅 Mods Seen Today ({today_str})",
            value=seen_display, inline=False
        )
        embed.set_footer(text=f"Last Update: {now_time.strftime('%H:%M:%S')}")

        status_channel = bot.get_channel(STATUS_CHANNEL_ID)
        if status_channel:
            if previous_message:
                try:
                    await previous_message.edit(embed=embed)
                except:
                    previous_message = await status_channel.send(embed=embed)
            else:
                previous_message = await status_channel.send(embed=embed)

        previous_online_users = web_data

        # ====== Log perubahan & alert ======
        if web_data is not None:
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if previous_online_users is not None:
                diff = web_data - previous_online_users
                if previous_online_users > 0:
                    percent_change = (diff / previous_online_users) * 100
                else:
                    percent_change = 0
                increment = f"(+{diff:,} +{percent_change:.2f}%)" if diff > 0 else f"(-{abs(diff):,} {percent_change:.2f}%)" if diff < 0 else "(no change)"
            else:
                increment = "(first update)"

            if log_channel:
                await log_channel.send(f"[{timestamp}] Online User: {web_data:,} {increment}")

            # Alert kalau turun > 1500
            if previous_online_users is not None and web_data < previous_online_users - 1500:
                total_minus = previous_online_users - web_data
                alert_channel = bot.get_channel(ALERT_CHANNEL_ID)
                if alert_channel:
                    await alert_channel.send(
                        f"[{timestamp}] Online player: {web_data:,} (-{total_minus:,} {percent_change:.2f}%) \n||<@&{ROLE_ID}>||"
                    )
                else:
                    print(f" ALERT_CHANNEL_ID {ALERT_CHANNEL_ID} tidak ditemukan!")
            
            # Update previous_online_users & presence di luar blok alert
            previous_online_users = web_data
            btc_price = get_btc_price()
            if btc_price is not None:
                await bot.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.playing,
                        name=f"BTC: ${btc_price:,.0f} | Online: {web_data:,}"
                    )
                )
            else:
                await bot.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.playing,
                        name="Bitcoin: N/A"
                    )
                )

            dl_price = get_dl_price()
            if dl_price is not None:
                dl_history.append((now_time, dl_price))
                cutoff = now_time - timedelta(hours=24)
                dl_history[:] = [(t, v) for t, v in dl_history if t >= cutoff]

        await asyncio.sleep(30)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    guild_id = message.guild.id
    if guild_id in inactive_settings:
        settings = inactive_settings[guild_id]
        if message.channel.id == settings["channel_id"]:
            last_active.setdefault(guild_id, {})[message.author.id] = datetime.now(timezone.utc)
            # Kirim log tiap kali "yapping"
            log_channel = bot.get_channel(settings["logs_channel"])
            if log_channel:
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                await log_channel.send(f"💬 {message.author.display_name} yapping di {message.channel.mention} (<t:{int(datetime.now().timestamp())}:R>)")

    if message.content.lower() == "!dl":
        if not dl_history:
            await message.reply("📊 Belum ada data DL untuk 24 jam terakhir. Tunggu ±1 menit setelah bot mulai.")
            return

        times, values = zip(*dl_history)

        min_dl = min(values)
        max_dl = max(values)
        current_dl = values[-1]

        max_time = times[values.index(max_dl)].strftime("%H:%M")
        min_time = times[values.index(min_dl)].strftime("%H:%M")

        # Bikin grafik DL
        plt.style.use("dark_background")
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(times, values, color="cyan", linewidth=2)

        ax.set_title("Diamond Lock Price - 24 Jam Terakhir", color="white", fontsize=14)
        ax.set_xlabel("Time (WIB)", color="white")
        ax.set_ylabel("Price (World Locks)", color="white")
        ax.grid(True, linestyle="--", alpha=0.5)

        locator = mdates.AutoDateLocator()
        formatter = mdates.DateFormatter("%H:%M", tz=ZoneInfo("Asia/Jakarta"))
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)

        fig.autofmt_xdate(rotation=45)
        ax.tick_params(colors="white")
        ax.xaxis.label.set_color("white")
        ax.yaxis.label.set_color("white")

        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        plt.close(fig)

        # Embed
        embed = discord.Embed(
            title="📊 Diamond Lock Price - 24 Jam Terakhir",
            description=(
                f"**Max:** RP {max_dl:,} ({max_time} WIB)\n"
                f"**Min:** RP {min_dl:,} ({min_time} WIB)\n"
                f"**Currently:** RP {current_dl:,} <t:{int(datetime.now().timestamp())}:R>"
            ),
            color=discord.Color.blue()
        )
        embed.set_image(url="attachment://dl_graph.png")

        file = discord.File(buf, filename="dl_graph.png")
        await message.reply(embed=embed, file=file)

    await bot.process_commands(message)


    if message.content.lower().startswith("!cv"):
        try:
            parts = message.content.split()
            if len(parts) != 4:
                await message.reply(" Format salah.\nContoh: `!cv 100 usd idr`")
                return
    
            # Banned words list
            bad_words = {"world", "everyone", "here", "@everyone", "@here"}
            if any(word.lower() in bad_words for word in parts[1:]):
                await message.reply(" Format salah.\nContoh: `!cv 100 usd idr`")
                return
    
            amount = float(parts[1])
            from_currency = parts[2].upper()
            to_currency = parts[3].upper()
    
            # Ambil data kurs dari mata uang asal
            url = f"https://open.er-api.com/v6/latest/{from_currency}"
            res = requests.get(url).json()
    
            if res.get("result") != "success":
                await message.reply(f"⚠️ Gagal mengambil data kurs {from_currency}")
                return
    
            rate = res["rates"].get(to_currency)
            if not rate:
                await message.reply(f"⚠️ Mata uang {to_currency} tidak ditemukan.")
                return
    
            result_value = amount * rate
    
            await message.reply(
                f"💱 {amount:,.2f} {from_currency} = **{result_value:,.2f} {to_currency}**\n"
                f"(Kurs 1 {from_currency} = {rate:,.2f} {to_currency})"
            )
    
        except Exception as e:
            await message.reply(f"⚠️ Terjadi error: {e} ")
            return

    if message.content.lower().startswith("!price"):
        # Cek apakah user punya salah satu role
        if not any(role.id in PRICE_ROLE_IDS for role in message.author.roles):
            await message.reply("Booster dulu lah sayang, baru bisa akses fitur ini!")
            return
    
        parts = message.content.split()
    
        # Default values
        amount = 1.0
        symbol = None
        target_currency = "USD"
    
        # Parsing format
        if len(parts) == 2:
            # !price btc
            symbol = parts[1].upper()
        elif len(parts) == 3:
            if parts[1].replace('.', '', 1).isdigit():
                # !price 5 btc
                amount = float(parts[1])
                symbol = parts[2].upper()
            else:
                # !price btc idr
                symbol = parts[1].upper()
                target_currency = parts[2].upper()
        elif len(parts) == 4:
            # !price 5 btc idr
            amount = float(parts[1])
            symbol = parts[2].upper()
            target_currency = parts[3].upper()
        else:
            await message.reply(" Format salah.\nContoh: `!price btc`, `!price btc idr`, `!price 5 btc`, `!price 5 btc idr`")
            return
    
        try:
            # Ambil harga USD dari Cryptorates.ai
            url = f"https://cryptorates.ai/v1/get/{symbol}"
            resp = requests.get(url, timeout=10).json()
    
            price_usd = resp.get("price")
            if price_usd is None:
                await message.reply(f"⚠️ Cryptocurrency `{symbol}` tidak ditemukan.")
                return
    
            if target_currency != "USD":
                # Konversi ke mata uang lain
                rate_url = f"https://open.er-api.com/v6/latest/USD"
                rate_data = requests.get(rate_url).json()
    
                if rate_data.get("result") != "success":
                    await message.reply(f"⚠️ Gagal mengambil kurs USD ke {target_currency}")
                    return
    
                rate = rate_data["rates"].get(target_currency)
                if not rate:
                    await message.reply(f"⚠️ Mata uang {target_currency} tidak ditemukan.")
                    return
    
                price_target = price_usd * rate * amount
                await message.reply(
                    f"💹 Harga **{amount} {symbol}** sekarang: **{price_target:,.2f} {target_currency}**\n"
                    f"💱 (1 {symbol} = {price_usd * rate:,.2f} {target_currency})\n"
                    f"Lu dapat akses! berikut harganya dalam {target_currency}!\n"
                )
            else:
                price_target = price_usd * amount
                await message.reply(
                    f"💹 Harga **{amount} {symbol}** sekarang: **${price_target:,.2f} USD**\n"
                    f"💱 (1 {symbol} = ${price_usd:,.2f} USD)\n"
                    f"Lu dapat akses! berikut harganya dalam {target_currency}!\n"
                )
    
        except Exception as e:
            await message.reply(f"⚠️ Terjadi error: {e}")
            return
    
    if message.content.lower() == "!help":
        help_text = (
            "Hi Sayang Berikut adalah perintah yang tersedia:\n"
            "`!cv <jumlah> <dari> <ke>` - Konversi mata uang\n"
            "`!price <crypto> [<target_currency>]` - Cek harga cryptocurrency\n"
            "`!player` - Lihat grafik pemain online dalam 24 jam terakhir\n"
            "`!help` - Tampilkan daftar perintah ini"
            "`/role add <user> <role>` - Tambah role ke user (admin only)\n"
            "`/role remove <user> <role>` - Hapus role dari user (admin only)\n"
            "`/ban <user> [reason]` - Ban user dari server (admin only)\n"
            "`/unban <user_id>` - Unban user dari server (admin only)\n"
            "`/setinactive <channel> <role> <log_channel> <days>` - Atur sistem cek member tidak aktif (admin only)\n"
            "`!mute <user> [reason]` - Mute user (admin only)\n"
            "`!unmute <user>` - Unmute user (admin only)\n"
            "`!timeout <user> <durasi> [alasan]` - Timeout user (admin only)\n"
            "`!untimeout <user>` - Untimeout user (admin only)\n"
            "`!ban <user> <reason>` (admin only)\n"
            "`!unban <user_id>` - Unban user dari server (admin only)\n"
            "`!logremove` - Cek log remove role (admin only)\n"
            "`!setinactive <channel> <role> <log_channel> <days>` - Atur sistem cek member tidak aktif (admin only)\n"
        )
        await message.reply(help_text)

    if message.content.lower() == "!player":
        if not player_history:
            await message.reply("📊 Belum ada data untuk 24 jam terakhir. Tunggu ±1 menit setelah bot mulai.")
            return
    
        times, values = zip(*player_history)  # times = tuple of datetime objects (Asia/Jakarta)
    
        # Hitung statistik
        min_players = min(values)
        max_players = max(values)
        avg_players = sum(values) / len(values)
        current_players = values[-1]

        max_time = times[values.index(max_players)].strftime("%H:%M")
        min_time = times[values.index(min_players)].strftime("%H:%M")
    
        # Bikin grafik (tanpa titik)
        plt.style.use("dark_background")
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(times, values, color="orange", linewidth=2)  # tanpa marker
    
        ax.set_title("Online Players in last 24 hours", color="white", fontsize=14)
        ax.set_xlabel("Time (WIB)", color="white")
        ax.set_ylabel("Players", color="white")
        ax.grid(True, linestyle="--", alpha=0.5)
    
        locator = mdates.AutoDateLocator()
        formatter = mdates.DateFormatter("%H:%M", tz=ZoneInfo("Asia/Jakarta"))
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)
    
        fig.autofmt_xdate(rotation=45)
        ax.tick_params(colors="white")
        ax.xaxis.label.set_color("white")
        ax.yaxis.label.set_color("white")
    
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        plt.close(fig)
    
        # Embed
        embed = discord.Embed(
            title="📊 Online Players - 24 Jam Terakhir",
            description=(
                f"**Max (ATH):** {max_players:,} ({max_time} WIB)\n"
                f"**Min (ATL):** {min_players:,} ({min_time} WIB)\n"
                f"**Currently:** {current_players:,} <t:{int(datetime.now().timestamp())}:R>"
            ),
            color=discord.Color.orange()
        )
        embed.set_image(url="attachment://player_graph.png")
    
        # Kirim embed + gambar
        file = discord.File(buf, filename="player_graph.png")
        await message.reply(embed=embed, file=file)  
        return
    await bot.process_commands(message)

@tasks.loop(hours=1)
async def check_inactivity():
    now = datetime.now(timezone.utc)
    for guild_id, settings in inactive_settings.items():
        guild = bot.get_guild(guild_id)
        if not guild:
            continue

        role = guild.get_role(settings["role_id"])
        channel = guild.get_channel(settings["channel_id"])
        log_channel = bot.get_channel(settings["logs_channel"])
        days = settings.get("days", 2)
        if not role or not channel:
            continue

        cutoff = now - timedelta(days=days)

        # Ambil semua pesan setelah cutoff
        recent_messages = await channel.history(after=cutoff, limit=None).flatten()
        active_members = {msg.author.id: msg.created_at for msg in recent_messages if not msg.author.bot}

        # 🔹 Log siapa saja yang aktif (yapping)
        if log_channel and active_members:
            lines = []
            for user_id, last_time in active_members.items():
                member = guild.get_member(user_id)
                if member and role in member.roles:
                    lines.append(f"✅ {member.mention} terakhir yapping: `<t:{int(datetime.now().timestamp())}:R>`")
            if lines:
                await log_channel.send("\n".join(lines))

        # 🔹 Hapus role dari yang tidak aktif
        for member in role.members:
            if member.id not in active_members:
                try:
                    await member.remove_roles(role, reason=f"Tidak aktif {days} hari di {channel.name}")
                    removed_logs.setdefault(guild_id, []).append(
                        (member.id, None, now)
                    )
                    if log_channel:
                        await log_channel.send(
                            f"📢 {member.mention} role {role.mention} dicabut (tidak aktif {days} hari di {channel.mention})."
                        )
                except Exception as e:
                    if log_channel:
                        await log_channel.send(f"Gagal hapus role dari {member.mention}: {e}")

async def before_check_inactivity():
    await bot.wait_until_ready()

@bot.event
async def on_ready():
    print("✅ Bot siap!")
    bot.loop.create_task(send_web_text())
    
    try:
        synced = await bot.tree.sync()
        print(f"✅ Slash commands sinkron: {len(synced)}")
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        print("✅ Slash commands disinkronkan")
    except Exception as e:
        print(f" Error sync slash command: {e}")

    check_inactivity.start()    

bot.run(TOKEN)
