import discord
from discord.ext import commands
import boto3
from botocore.config import Config
import os
from dotenv import load_dotenv

from datetime import datetime, timezone
import logging

####### CONFIGURATIONS ######
# 加载环境变量
load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

# 智能读取代理配置：
# 如果 .env 中有 GCP_PROXY，它会读取到 "socks5h://127.0.0.1:40000"
# 如果 .env 中没有这个变量（比如在你本地 Mac 上），它会获取到 None
proxy_url = os.getenv('GCP_PROXY')

# 初始化 Discord Bot
bot = commands.Bot(
    command_prefix='!', 
    intents=intents,
    proxy=proxy_url  # 当 proxy=None 时，discord.py 会自动选择直连
)

# 为AWS配置代理
boto_config = Config()
if proxy_url:
    boto_config = Config(
        proxies={
            'http': proxy_url,
            'https': proxy_url
        }
    )

# 初始化 AWS DynamoDB 客户端
dynamodb = boto3.resource(
    'dynamodb',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION'),
    config=boto_config
)
table = dynamodb.Table(os.getenv('DYNAMODB_TABLE_NAME'))

# 配置日志格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s UTC | %(levelname)s | %(message)s'
)
# 强制 logging 使用 UTC 时间
logging.Formatter.converter = lambda *args: datetime.now(timezone.utc).timetuple()


###### BOT FUNCTIONS ######

@bot.event
async def on_command(ctx):
    logging.info(f"收到指令: {ctx.command.name} | 发送者: {ctx.author}")

@bot.event
async def on_ready():
    logging.info(f'登录成功！机器人: {bot.user}')

# 用于测试的hello指令 !hello
@bot.command(name='hello')
async def hello_command(ctx):
    # 1. 获取发起命令的 Discord 用户 ID
    discord_user_id = ctx.author.id
    
    # 2. 获取当前时间 (格式化为 年-月-日 时:分:秒)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 发送提示信息，防止查询时间过长导致用户以为机器人卡死了
    status_msg = await ctx.send("正在统计 DynamoDB 数据，请稍候...")
    
    try:
        # 3. 使用 Plan B 获取数据库行数
        # 先 reload() 一下，让 boto3 从 AWS 拉取最新的表元数据缓存
        table.reload()
        # 直接读取 item_count 属性（完全不消耗读写容量配额）
        total_rows = table.item_count
        
        # 构建最终的回复信息
        reply_message = (
            f"Hello! 👋 `{discord_user_id}`\n"
            f"🕒 当前系统时间: `{current_time}`\n"
            f"📊 数据库大约的总行数: `{total_rows}`"
        )
        
        # 编辑刚才的提示信息，展示最终结果
        await status_msg.edit(content=reply_message)
        
    except Exception as e:
        logging.error(e)
        await status_msg.edit(content=f"⚠️ 查询数据库时发生错误: {str(e)}")

# 运行机器人
if __name__ == '__main__':
    bot.run(os.getenv('DISCORD_TOKEN'))