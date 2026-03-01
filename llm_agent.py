from langchain.agents import initialize_agent, AgentType
from langchain_community.llms import HuggingFacePipeline
from transformers import pipeline

from tools.orchestrator_tool import correlation_tool
from tools.search_tool import search_tool
from tools.rag_tool import incident_memory, store_incident


# Load HuggingFace model
hf_pipeline = pipeline(
    "text2text-generation",
    model="./soc_llm_flan_t5",
    tokenizer="./soc_llm_flan_t5",
    max_length=512
)

llm = HuggingFacePipeline(pipeline=hf_pipeline)


tools = [
    correlation_tool,
    incident_memory,
    search_tool,
    store_incident
]


# DO NOT USE SYSTEM_PROMPT HERE
agent = initialize_agent(
    tools=tools,
    llm=llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True,
    handle_parsing_errors=True,
    agent_kwargs={
        "prefix": """You are a SOC AI agent.

You MUST use tools when needed.

Use EXACT format:

Thought: what you think
Action: correlation_tool
Action Input: the JSON string
Observation: tool result
Final Answer: your analysis
"""
    }
)


print("Agent input keys:", agent.input_keys)
