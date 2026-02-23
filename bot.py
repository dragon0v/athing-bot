import discord
from discord.ext import commands
import boto3
from botocore.config import Config
import os
from dotenv import load_dotenv
import google.generativeai as genai

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

# 初始化 Gemini API
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

# 选择模型，推荐使用 gemini-1.5-flash 或 gemini-2.5-flash，速度快且便宜/免费
model = genai.GenerativeModel('gemini-2.5-flash')

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
        await status_msg.edit(content=f"⚠️ 查询数据库时发生错误: {str(e)}")

# 2. 定义新的 AI 指令
# 使用 *, prompt: str 可以让指令后面的所有文字都被当做 prompt，即使包含空格
@bot.hybrid_command(name='ai', aliases=['!', 'ask', 'chat'], description="基于数据库内容向 AI 提问 (例如: /ai 上次铲屎是什么时候)")
async def ai_command(ctx, *, prompt: str):
    
    # 【极其关键】Discord 要求斜杠指令必须在 3 秒内响应。
    # 因为读取 DB + 调用大模型肯定会超过 3 秒，我们必须先告诉 Discord "机器人在思考中"
    # 这样可以争取到 15 分钟的超时时间。
    await ctx.defer() 
    
    # 【关键新增】开启“正在输入...”状态
    # 在这个 with 语句块内的所有耗时操作执行期间，Discord 频道里都会显示“机器人正在输入...”
    async with ctx.typing():
        try:
            # 1. 扫描整个 DynamoDB 获取全部数据
            # 注意：如果数据量超过 1MB，DynamoDB 一次只能返回一部分，需要循环获取（分页）
            response = table.scan()
            all_items = response.get('Items', [])
            
            # 自动处理 DynamoDB 的分页逻辑，确保拿到真正的“全表数据”
            while 'LastEvaluatedKey' in response:
                response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
                all_items.extend(response.get('Items', []))
                
            # 2. 将数据格式化为文本格式（因为 DynamoDB 返回的数字可能是 Decimal 类型，直接转 string 最安全）
            db_context_text = str(all_items)
            
            # 3. 构造给 Gemini 的终极 Prompt (System Prompt + 数据库内容 + 用户问题)
            full_prompt = (
                "你是一个聪明的私人助理。以下是我的 DynamoDB 数据库中的所有记录数据：\n"
                f"```json\n{db_context_text}\n```\n"
                "请根据上述数据，准确地回答用户的提问。如果数据中找不到答案，请诚实地说明。用户如果用英语提问则用英语回答。\n\n"
                f"用户的提问是：{prompt}"
            )
            
            # 4. 调用 Gemini API 生成回答
            ai_response = model.generate_content(full_prompt)
            reply_text = ai_response.text
            
            # 5. Discord 单条消息最多 2000 个字符的限制处理
            if len(reply_text) > 2000:
                # 如果太长，截断并加上提示（或者你可以写一段逻辑将内容分成多条发送）
                reply_text = reply_text[:1990] + "\n...(内容过长截断)"
                
            # 6. 将 AI 的回答发送到 Discord
            await ctx.send(f"{reply_text}")
            
        except Exception as e:
            # 如果发生错误，也要确保回复用户
            await ctx.send(f"⚠️ AI 处理出错: {str(e)}")

# 运行机器人
bot.run(os.getenv('DISCORD_TOKEN'))