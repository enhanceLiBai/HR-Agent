import json
import os
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

# 载入 .env 文件里的环境变量
load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL")
)

class ToolRegistry:
    def __init__(self):
        # 存储结构: {"函数名": 函数对象}
        self.tools = {}
        
    def register(self, func):
        """装饰器: 自动注册工具"""
        self.tools[func.__name__] = func
        return func
        
    def call_tool(self, name, arguments_str):
        """统一的工具执行入口，自带异常处理"""
        try:
            args = json.loads(arguments_str) if arguments_str else {}
            return self.tools[name](**args)
        except Exception as e:
            return f"工具 {name} 执行失败 原因：{e}"
    
# 实例化全局注册中心
registry = ToolRegistry()

# --- 注册我们的工具 ---
@registry.register
def get_current_weather(location):
    """查询地球城市的天气"""
    return f"{location}今天天气晴朗 25°"

# --- 注册 get_cultural_landmarks 工具 ---
@registry.register
def get_cultural_landmarks(location):
    """查询指定城市的著名文化景点"""
    return f"{location}的故宫和颐和园非常美丽"

# 严格修正了拼写的工具定义说明书 📑
tools_definition = [
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "查询指定城市的天气状况",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "城市名称 比如: '北京'，'上海'"}
                },
                "required": ["location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_cultural_landmarks",
            "description": "查询指定城市的著名文化景点",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "城市名称：比如北京"}
                },
                "required": ["location"]
            }
        }
    }
]

class MessageHistory:
    def __init__(self):
        self.messages = []
    
    def append(self, role, content,tool_calls=None,tool_call_id=None,name=None):
        """向后追加普通对话"""
        msg={"role":role,"content":content}
        if tool_calls:
         msg["tool_calls"]=tool_calls
        if tool_call_id:
            msg["tool_call_id"]=tool_call_id
        if name:
            msg["name"]=name
        self.messages.append(msg)
      
            
        
    def insert_system_top(self, content):
        """关键动作，将系统总结置顶插入到索引 0"""
        self.messages.insert(0, {"role": "system", "content": content})
        
    def clear_keep_last(self, n=1):
        """保留最后 n 条温热对话，其余清空"""
        last_messages = self.messages[-n:] if self.messages else []
        self.messages = last_messages
    def auto_summarize(self,client,model_name="deepseek-v4-flash"):
        """当历史记忆超过阈值时，自动触发大模型进行记忆压缩"""
        #设定阈值：当历史信息超过8条时自动压缩
        if len(self.messages)<=8:
            return
        print("\n检测到历史对话过长正在启动记忆压缩")
        
        #1.分离出需要压缩的旧信息，和需要保留的最新2条对话
        old_message=self.messages[:-2]
        #将旧消息转换为字符串格式，方便喂给大模型
        old_messages_str=json.dumps(old_message,ensure_ascii=False,indent=2)
        
        #2.构建给大模型的压缩指令
        summary_prompt=[
            {
                "role":"system",
                "content":"你是一个记忆管理助手，请将用户提供的对话历史压缩成一段100字以内的摘要。必须包含：1.用户的核心需求 2.工具查到的关键数据 3.模型的最终结论。"
            },
            {
                "role":"user",
                "content":f"请压缩以下历史：\n{old_messages_str}"
            }
        ]
        try:
            #3.调用大模型生产摘要
            response=client.chat.completions.create(
                model=model_name,
                messages=summary_prompt,
                stream=False
            )
            
            summary_content=response.choices[0].message.content
            print(f"📝 成功生成记忆摘要: {summary_content}")

            #4.重组记忆库：清洗老记忆->保留最新的对话->置顶新摘要
            self.clear_keep_last(n=2)               #此时self.message只剩下最后2条
            self.insert_system_top(summary_content)#将新摘要插入到最前面
        except Exception as e:
            print(f"记忆压缩失败：{e}保留原有对话记忆继续对话")
            

def start_agent_cli():
    history=MessageHistory()
    print("Agent 完全引擎已启动！输入'exit' 退出.")
    while True:
        user_input=input("\n 用户:")
        if user_input.strip().lower()=="exit":
            print("再见！")
            break
        if not user_input.strip():
            continue
        #1.记录用户输入并触发记忆检查
        history.append("user",user_input)
        history.auto_summarize(client)

        # 第一次调用大模型：让大模型决定是否使用工具
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=history.messages,
            tools=tools_definition,
            tool_choice="auto",
            stream=True
        )
        
        tool_chunks = {}
        finish_reason = None
        assistant_reply=""
        
        
        print("Agent思考中....",end="",flush=True)
        for chunk in response:  # 💡 修正：去掉了 response 后面多余的括号
            choices = chunk.choices
            if not choices:
                continue
                
            delta = choices[0].delta
            
            #如果大模型选择直接文本回复（不用工具)
            if delta.content:
                if not assistant_reply:
                    print("\n Assistant: ",end="")
                assistant_reply+=delta.content
                print(delta.content,end="",flush=True)
            # 💡 修正：改用对象属性点运算符访问（delta.tool_calls）
            if delta.tool_calls:
                for tool_call in delta.tool_calls:
                    index = tool_call.index
                    
                    # 发现新工具: 初始化容器
                    if index not in tool_chunks:
                        tool_chunks[index] = {
                            "id":tool_call.id,
                            "name": tool_call.function.name if tool_call.function.name else None,
                            "arguments": ""
                        }
                        print(f"📦 检测到工具调用需求: 名字 -> {tool_chunks[index]['name']}")
                        
                    # 核心动作：持续累加参数碎片
                    if tool_call.function and tool_call.function.arguments:
                        fragment = tool_call.function.arguments
                        tool_chunks[index]["arguments"] += fragment
                        print(f"  🧩 正在拼接参数碎片: {fragment:10} -> 当前缓冲区：{tool_chunks[index]['arguments']}")
                        
            if choices[0].finish_reason:
                finish_reason = choices[0].finish_reason

        # 流式结束开始触发并发执行 🛠️
        if finish_reason == "tool_calls":
            #构建一个给大模型留档的assistant 消息结构 ,包含它发出的tool_calls原型
            api_tool_calls=[]
            for index,info in tool_chunks.items():
                if info["name"] is not None:
                    api_tool_calls.append({
                        "id":info["id"],
                        "type":"function",
                        "function":{"name":info["name"],"arguments":info["arguments"]}
                    })
            #必须先把大模型的这个"调用意图"记入历史
            history.append("assistant",content=None,tool_calls=api_tool_calls)
            #利用线程池并发执行多个工具任务
            futures = {}
            print("\n🏁 流式传输结束：开始【并发】解析参数并且执行工具")
            
            with ThreadPoolExecutor() as executor:
                for index, info in tool_chunks.items():
                    name = info['name']
                    args_str = info['arguments']
                    if name is not None:
                        print(f"启动后台线程执行工具[{name}]->参数：{args_str}")
                        futures[info["id"]]={
                            "name":name,
                            "future":executor.submit(registry.call_tool,name,args_str)
                        }
            #收集结果，并严格以role="tool" 格式填回记忆库
            for tool_id,task in futures.items():
                result=task["future"].result()
                print(f"工具[{task['name']}] 执行完毕，返回结果")
                history.append(role="tool",content=result,tool_call_id=tool_id,name=task["name"])
            #4.第二次调用大模型:结合刚刚拿到的工具结果,输出最终人话回答
            print("结合数据整理最终回答中...\n Assistant: ",end="")
            final_response=client.chat.completions.create(
                model="deepseek-v4-flash",
                messages=history.messages,
                stream=True
            )             
            final_reply=""
            for chunk in final_response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content=chunk.choices[0].delta.content
                    final_reply+=content
                    print(content,end="",flush=True)
            print()
            
            #将模型的最终人话回答记入历史
            history.append("assistant",final_reply)
        elif assistant_reply:
            #如果一开始就只是文本回复，直接把文本记入历史
            print()
            history.append("assistant",assistant_reply)
        
if __name__ == "__main__":
    start_agent_cli()