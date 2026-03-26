import json
import asyncio
import os
import sys
import random
import time
from typing import Optional
from contextlib import AsyncExitStack

from openai import OpenAI
from dotenv import load_dotenv

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv("dotenv.env")

class EnhancedMCPClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        
        # 反爬虫保护设置
        # Anti-bot protection settings
        self.last_tool_call_time = 0
        self.min_call_interval = 3  # 最小调用间隔（秒）
        self.max_call_interval = 8  # 最大调用间隔（秒）
        
        # Initialize OpenAI client with environment variables
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable must be set")
        
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        
    async def connect_to_server(self):
        server_params = StdioServerParameters(
            command=sys.executable,
            args=['-m', 'mcp_integration.server'], # 修正了启动命令  # Fixed startup command
            env=None
        )

        # 使用与 client.py 相同的方式
        # Use same stdio client setup as client.py
        self.stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params))
        
        # 确保正确解包返回值
        if hasattr(self.stdio_transport, '__iter__') and not isinstance(self.stdio_transport, str):
            try:
                stdio, write = self.stdio_transport
            except ValueError as e:
                print(f"解包stdio_transport失败: {e}")
                print(f"stdio_transport类型: {type(self.stdio_transport)}")
                print(f"stdio_transport内容: {self.stdio_transport}")
                raise
        else:
            raise ValueError(f"意外的stdio_transport类型: {type(self.stdio_transport)}")
            
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(stdio, write))

        await self.session.initialize()
        print("✅ 已连接到Google搜索MCP服务器 / Connected to Google Search MCP Server")
        
    async def anti_bot_protection(self):
        """反爬虫保护：在工具调用之间添加随机延迟
        Anti-bot protection: add randomized delay between tool calls
        """
        current_time = time.time()
        time_since_last_call = current_time - self.last_tool_call_time
        
        if time_since_last_call < self.min_call_interval:
            # 如果距离上次调用时间太短，等待随机时间
            # If last call was too recent, wait a randomized interval
            wait_time = random.uniform(self.min_call_interval, self.max_call_interval)
            print(f"🛡️ 反爬虫保护：等待 {wait_time:.1f} 秒... / Anti-bot protection: Waiting {wait_time:.1f} seconds...")
            await asyncio.sleep(wait_time)
        
        self.last_tool_call_time = time.time()
        
    async def process_query(self, query: str) -> str:
        # 增强的系统提示，明确允许使用搜索工具
        # Enhanced system prompt that explicitly allows using the search tool
        system_prompt = (
            "You are an AI assistant with access to a real-time web search tool. "
            "When a user asks a question that may require up-to-date, current, or web-based information, "
            "you MUST use the google-search tool to get accurate results. "
            "The google-search tool requires a 'query' parameter, which must contain the user's search keywords or question. "
            "Always place the user's full question or main keywords in the 'query' field when calling the tool. "
            "Do not answer questions about current events, news, or potentially outdated topics using only your training data—"
            "always use the google-search tool first. "
            "After searching, provide a comprehensive answer based on the search results. "
            "For date-related or time-sensitive questions, use the search tool to get the latest information and avoid giving outdated dates or facts."
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]

        # 获取所有 mcp 服务器 工具列表信息
        # List available tools from the MCP server
        response = await self.session.list_tools()
        print(f"🔧 可用工具: {[tool.name for tool in response.tools]} / Available tools: {[tool.name for tool in response.tools]}")
        
        # 生成 function call 的描述信息
        available_tools = [{
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema
            }
        } for tool in response.tools]

        # 请求 OpenAI，function call 的描述信息通过 tools 参数传入
        response = self.client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL"),
            messages=messages,
            tools=available_tools,
            tool_choice="auto"  # 让模型自动决定是否使用工具
        )

        # 处理返回的内容
        content = response.choices[0]
        if content.finish_reason == "tool_calls":
            # 如果需要使用工具，就解析工具
            tool_call = content.message.tool_calls[0]
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)

            # 反爬虫保护
            # await self.anti_bot_protection()

            # 执行工具
            print(f"\n🔍 正在执行工具: {tool_name} / Executing tool: {tool_name}")
            print(f"📝 Parameters: {json.dumps(tool_args, ensure_ascii=False, indent=2)}")
            
            try:
                # 添加工具调用超时保护
                result = await asyncio.wait_for(
                    self.session.call_tool(tool_name, tool_args),
                    timeout=300.0  # 300秒超时
                )
            except asyncio.TimeoutError:
                print("⏰ 工具调用超时，返回错误信息 / Tool call timeout, returning error message")
                return "抱歉，搜索请求超时。这可能是由于网络问题或Google的反爬虫机制。请稍后重试。"
            except Exception as e:
                print(f"❌ 工具调用失败: {e} / Tool call failed: {e}")
                return f"搜索失败: {str(e)}"
			
            # 将 OpenAI 返回的调用哪个工具数据和工具执行完成后的数据都存入messages中
            messages.append(content.message.model_dump())
            
            # 正确处理 call_tool 的返回值
            if hasattr(result, 'content') and result.content:
                # 获取第一个内容项
                first_content = result.content[0]
                if hasattr(first_content, 'text'):
                    # 如果是 TextContent，直接获取 text 字段
                    tool_content = first_content.text
                else:
                    # 其他类型的内容，转换为字符串
                    tool_content = str(first_content)
            else:
                # 如果没有 content，直接转换为字符串
                tool_content = str(result)
            
            print(f"📊 工具执行结果长度: {len(tool_content)} 字符 / Tool execution result length: {len(tool_content)} characters")
            
            messages.append({
                "role": "tool",
                "content": tool_content,
                "tool_call_id": tool_call.id,
            })

            # 再次反爬虫保护，在生成最终答案前等待
            # await self.anti_bot_protection()

            # 将上面的结果再返回给 OpenAI 用于生成最终的结果
            print("🤖 正在生成最终回答... / Generating final answer...")
            response = self.client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL"),
                messages=messages,
                max_tokens=20000,
            )
            return response.choices[0].message.content

        return content.message.content
        
    async def chat_loop(self):
        print("\n🚀 Google搜索增强版MCP客户端已启动! / Google Search Enhanced MCP Client Started!")
        print("💡 现在你可以询问任何需要实时信息的问题 / You can now ask any questions that require real-time information")
        print("🔍 系统会自动使用Google搜索来获取最新信息 / The system will automatically use Google Search to get the latest information")
        print("🛡️ 已启用反爬虫保护机制 / Anti-bot protection mechanism enabled")
        print("❓ 输入 'quit' 退出程序 / Type 'quit' to exit the program\n")
        
        while True:
            try:
                query = input("\n🤔 请输入你的问题 / Please enter your question: ").strip()

                if query.lower() == 'quit':
                    break

                if not query:
                    continue

                print("\n⏳ 正在处理你的问题... / Processing your question...")
                response = await self.process_query(query)
                print(f"\n🤖 AI回答 / AI Answer:\n{response}")

            except Exception as e:
                import traceback
                print(f"\n❌ 发生错误 / Error occurred: {e}")
                traceback.print_exc()

    async def cleanup(self):
        """Clean up resources
        清理资源
        """
        await self.exit_stack.aclose()

async def main():
    client = EnhancedMCPClient()
    try:
        await client.connect_to_server()
        await client.chat_loop()
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())