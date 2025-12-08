from langchain.agents import create_agent
from langchain_groq import ChatGroq
from langchain_core.tools import BaseTool, tool
from typing import List 
from dotenv import load_dotenv
load_dotenv()


def Agent(tools: List[BaseTool], system_prompt: str):
    """
    Create a LangChain agent with specified tools.
    
    Args:
        tools: List of LangChain tool objects (BaseTool instances)
        system_prompt: System prompt for the agent
    
    Returns:
        LangChain agent executor
    """
    llm = ChatGroq(model="openai/gpt-oss-120b")
    
    return create_agent(model=llm, tools=tools, system_prompt=system_prompt)
