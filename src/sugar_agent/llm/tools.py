"""LLM tool/function definitions for Sugar Agent.

These tools are exposed to the LLM via function calling.
Each tool has a name, description, and JSON Schema parameters.
"""

# All tools available to the LLM
LLM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "record_blood_glucose",
            "description": "记录一次血糖读数。当用户在消息中提到血糖值时，自动调用此工具。"
            "可以同时解析空腹/餐后等背景信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "number",
                        "description": "血糖数值",
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["mmol/L", "mg/dL"],
                        "description": "血糖单位，默认为 mmol/L（中国标准）",
                    },
                    "context": {
                        "type": "string",
                        "enum": ["fasting", "before_meal", "after_meal", "bedtime", "random"],
                        "description": "测量时机：空腹(fasting)、餐前(before_meal)、餐后(after_meal)、睡前(bedtime)、随机(random)",
                    },
                    "notes": {
                        "type": "string",
                        "description": "用户提到的其他背景信息，比如吃了什么、运动了等",
                    },
                    "recorded_at": {
                        "type": "string",
                        "description": "用户提到测量时间时的 ISO 8601 时间戳，如果用户没说明就留空",
                    },
                },
                "required": ["value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_blood_glucose_trend",
            "description": "查询近期的血糖趋势数据，用于分析血糖控制情况。调用此工具来获取历史血糖记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "查询最近几天的数据，默认为7天",
                        "default": 7,
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_memory",
            "description": "保存一条重要的信息到长期记忆中。当用户提到值得记住的事情时调用此工具。"
            "例如：喜好、习惯、重要事件、关系里程碑等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要记住的内容，尽量简洁准确",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["love", "health", "preference", "habit", "fact", "event"],
                        "description": "记忆分类：love(恋爱相关)、health(健康相关)、preference(喜好)、habit(习惯)、fact(事实)、event(事件)",
                    },
                    "importance": {
                        "type": "integer",
                        "description": "重要性 1-5，5为最重要",
                        "minimum": 1,
                        "maximum": 5,
                        "default": 3,
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_memory",
            "description": "搜索存储在长期记忆中的信息。当需要回忆之前的对话或用户提到过的事情时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或问题",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["love", "health", "preference", "habit", "fact", "event"],
                        "description": "限定记忆分类（可选）",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询天气预报。当用户问天气时调用。可以指定城市名或区县名，如'北京'、'昌平'、'上海'。不指定则查询默认城市。",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "查询未来几天，默认1天（今天），最多7天",
                        "default": 1,
                        "minimum": 1,
                        "maximum": 7,
                    },
                    "location": {
                        "type": "string",
                        "description": "城市或区县名，如'北京'、'昌平'、'海淀'、'沙河'",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "为用户设置一个定时提醒。当用户说'提醒我...'、'记得到时候...'等时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_description": {
                        "type": "string",
                        "description": "提醒时间的自然语言描述，如'明天早上8点'、'下午3点'、'1小时后'",
                    },
                    "message": {
                        "type": "string",
                        "description": "提醒的内容",
                    },
                },
                "required": ["time_description", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "获取当前的日期和时间。当需要知道现在几点、今天几号时调用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]
