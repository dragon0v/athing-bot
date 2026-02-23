import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import boto3
from moto import mock_aws

# 1. 伪造环境变量（防止导入 bot.py 时报错或连接真实的 AWS）
os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
os.environ['AWS_REGION'] = 'us-east-1'
os.environ['DYNAMODB_TABLE_NAME'] = 'MockTable'
os.environ['DISCORD_TOKEN'] = 'fake_token'

# 在设置好假环境变量后，再导入我们的机器人代码
import bot

# 2. 准备一个假的 AWS DynamoDB 环境 (使用 moto)
@pytest.fixture
def mock_dynamodb():
    # mock_aws() 会拦截所有 boto3 的真实网络请求
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='eu-north-1')
        
        # 在本地内存中创建一个假表
        table = dynamodb.create_table(
            TableName='MockTable',
            KeySchema=[{'AttributeName': 'userId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'userId', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST'
        )
        # 往假表里塞一条测试数据，这样 item_count 就会是 1
        table.put_item(Item={'userId': '12345'})
        
        yield table

# 3. 准备一个假的 Discord Context (上下文)
@pytest.fixture
def mock_ctx():
    # MagicMock 用于伪造普通属性
    ctx = MagicMock()
    ctx.author.id = 9876543210 # 伪造一个 Discord 用户 ID
    
    # AsyncMock 用于伪造异步函数 (因为我们需要 await ctx.send)
    ctx.send = AsyncMock()
    return ctx

# 4. 编写实际的测试用例
@pytest.mark.asyncio
async def test_hello_command(mock_ctx, mock_dynamodb):
    # 使用 patch 把 bot.py 里的 table 替换成我们的 mock_dynamodb
    with patch('bot.table', mock_dynamodb):
        
        # 在 discord.py 中，获取混合指令内部真实函数的方法是 .callback
        await bot.hello_command.callback(mock_ctx)
        
        # 断言 1: 确保 ctx.send 被调用了一次
        mock_ctx.send.assert_called_once()
        
        # 获取机器人准备发送出来的文字内容
        # call_args[0][0] 获取的是 send 函数的第一个位置参数 (也就是文本内容)
        reply_message = mock_ctx.send.call_args[0][0]
        print(reply_message)
        
        # 断言 2: 验证回复内容中是否包含假用户的 ID
        assert "9876543210" in reply_message
        
        # 断言 3: 验证回复内容中是否包含正确的数据库行数 (我们在 mock 里塞了 1 条)
        assert "总行数: `1`" in reply_message

        print("\n✅ 测试通过！机器人成功生成了以下回复：")
        print(reply_message)